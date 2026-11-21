import asyncio
import os
import time
from contextlib import asynccontextmanager

import jwt
from celery import Celery
from fastapi import Depends, FastAPI, Header, HTTPException
from psycopg2.extras import Json
from psycopg2.pool import ThreadedConnectionPool
from pydantic import BaseModel

SECRET = os.environ["JWT_SECRET"]
DEMO_PASSWORD = os.environ["DEMO_PASSWORD"]
NODE_NAME = os.environ.get("NODE_NAME", "api-unknown")

# Satu objek Celery global dengan connection pool & publisher confirms
celery_app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])
celery_app.conf.update(
    broker_transport_options={"confirm_publish": True},
    broker_pool_limit=10,
    task_default_queue="celery",
    task_default_queue_type="quorum",
    broker_connection_retry_on_startup=True,
)

pool: ThreadedConnectionPool | None = None


def init_db_pool():
    """Inisialisasi pool ke PgBouncer dengan retry agar aman saat startup serentak."""
    global pool
    for _ in range(15):
        try:
            pool = ThreadedConnectionPool(
                1,
                10,
                host=os.environ["PG_HOST"],
                port=int(os.environ.get("PG_PORT", "5432")),
                dbname="cbt",
                user="cbt",
                password=os.environ["PG_PASSWORD"],
            )
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Gagal terhubung ke PgBouncer setelah 15 percobaan.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db_pool()
    yield
    if pool:
        pool.closeall()


app = FastAPI(title="CBT Queue Ingestion API", lifespan=lifespan)


class LoginRequest(BaseModel):
    student_id: str
    password: str


def auth(authorization: str = Header(...)) -> str:
    try:
        token = authorization.replace("Bearer ", "").strip()
        return jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="token tidak valid")


@app.get("/")
async def health():
    return {"status": "ok", "node": NODE_NAME}


@app.post("/login")
async def login(body: LoginRequest):
    if body.password != DEMO_PASSWORD:
        raise HTTPException(status_code=401, detail="login gagal")
    exp = int(time.time()) + 7200
    token = jwt.encode({"sub": body.student_id, "exp": exp}, SECRET, algorithm="HS256")
    return {"token": token, "node": NODE_NAME}


@app.post("/answer")
def save_answer(data: dict, student_id: str = Depends(auth)):
    """Simpan draft jawaban via PgBouncer (Alur 4a -> 5)."""
    exam_id = data.get("exam_id", "UJIAN-01")
    answers = data["answers"]
    conn = pool.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO submissions (student_id, exam_id, answers, status) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (student_id, exam_id) "
                "DO UPDATE SET answers = EXCLUDED.answers, received_at = now()",
                (student_id, exam_id, Json(answers), "draft"),
            )
    finally:
        pool.putconn(conn)
    return {"status": "tersimpan", "node": NODE_NAME}


@app.get("/progress")
def get_progress(exam_id: str = "UJIAN-01", student_id: str = Depends(auth)):
    """Ambil progres & nilai siswa via PgBouncer (Alur 4a -> 5)."""
    conn = pool.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT s.status, s.answers, r.score "
                "FROM submissions s LEFT JOIN results r "
                "ON s.student_id = r.student_id AND s.exam_id = r.exam_id "
                "WHERE s.student_id = %s AND s.exam_id = %s",
                (student_id, exam_id),
            )
            row = cur.fetchone()
            if not row:
                return {"status": "belum_ada_data", "node": NODE_NAME}
            return {
                "student_id": student_id,
                "exam_id": exam_id,
                "status": row[0],
                "answers": row[1],
                "score": float(row[2]) if row[2] is not None else None,
                "node": NODE_NAME,
            }
    finally:
        pool.putconn(conn)


@app.post("/submit", status_code=202)
async def submit(data: dict, student_id: str = Depends(auth)):
    """Pure Async: langsung kirim ke RabbitMQ Cluster tanpa menyentuh PostgreSQL (Alur 4b)."""
    exam_id = data.get("exam_id", "UJIAN-01")
    answers = data["answers"]
    payload = {"student_id": student_id, "exam_id": exam_id, "answers": answers}
    try:
        await asyncio.to_thread(
            celery_app.send_task,
            "tasks.nilai_jawaban",
            args=[payload],
        )
    except Exception:
        raise HTTPException(status_code=503, detail="antrean tidak tersedia, coba lagi")

    return {"status": "diterima", "node": NODE_NAME}
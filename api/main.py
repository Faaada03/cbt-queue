import os
import time
import jwt
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel
from celery import Celery
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import Json

SECRET = os.environ["JWT_SECRET"]
app = FastAPI(title="CBT Queue Ingestion API (5000 VU + PgBouncer)")

# Inisialisasi Celery dengan Publisher Confirms & Quorum Queue
celery_app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])
celery_app.conf.update(
    broker_transport_options={"confirm_publish": True},
    task_default_queue="celery",
    task_default_queue_type="quorum",
    broker_connection_retry_on_startup=True,
)


def init_db_pool(retries: int = 10, delay: float = 2.0):
    """Membuka pool koneksi ke PgBouncer dengan retry otomatis saat startup."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return ThreadedConnectionPool(
                1,
                20,
                host=os.environ["PG_HOST"],
                port=int(os.environ.get("PG_PORT", "5432")),
                dbname="cbt",
                user="cbt",
                password=os.environ["PG_PASSWORD"],
            )
        except Exception as e:
            last_err = e
            print(f"[API] Menunggu PgBouncer siap ({attempt}/{retries}): {e}")
            time.sleep(delay)
    raise RuntimeError(f"Gagal terhubung ke PgBouncer: {last_err}")


pool = init_db_pool()


class LoginRequest(BaseModel):
    student_id: str
    password: str


def auth(authorization: str = Header(...)):
    try:
        token = authorization.replace("Bearer ", "")
        return jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="token tidak valid")


@app.get("/")
def cek():
    return {"status": "ok", "node": os.environ.get("NODE_NAME", "?")}


@app.post("/login")
def login(body: LoginRequest):
    if body.password != os.environ["DEMO_PASSWORD"]:
        raise HTTPException(status_code=401, detail="login gagal")
    exp = int(time.time()) + 7200
    token = jwt.encode({"sub": body.student_id, "exp": exp}, SECRET, algorithm="HS256")
    return {"token": token}


@app.post("/answer")
def save_answer(data: dict, student_id: str = Depends(auth)):
    """Simpan draft jawaban sementara melalui PgBouncer (mode transaction)."""
    exam_id = data.get("exam_id", "UJIAN-01")
    answers = data["answers"]
    conn = pool.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO submissions (student_id, exam_id, answers, status) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (student_id, exam_id) DO UPDATE SET answers=EXCLUDED.answers, received_at=now()",
                (student_id, exam_id, Json(answers), "draft"),
            )
    finally:
        pool.putconn(conn)
    return {"status": "tersimpan", "node": os.environ.get("NODE_NAME", "?")}


@app.get("/progress")
def get_progress(exam_id: str = "UJIAN-01", student_id: str = Depends(auth)):
    """Cek status jawaban dan nilai melalui PgBouncer."""
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
                return {"status": "belum_ada_data"}
            return {
                "student_id": student_id,
                "exam_id": exam_id,
                "status": row[0],
                "answers": row[1],
                "score": float(row[2]) if row[2] is not None else None,
            }
    finally:
        pool.putconn(conn)


@app.post("/submit", status_code=202)
def submit(data: dict, student_id: str = Depends(auth)):
    """Pure Async: Langsung kirim ke RabbitMQ Cluster tanpa menyentuh PostgreSQL."""
    exam_id = data.get("exam_id", "UJIAN-01")
    answers = data["answers"]
    try:
        celery_app.send_task(
            "tasks.nilai_jawaban",
            args=[{"student_id": student_id, "exam_id": exam_id, "answers": answers}],
        )
    except Exception:
        raise HTTPException(status_code=503, detail="antrean tidak tersedia, coba lagi")

    return {"status": "diterima", "node": os.environ.get("NODE_NAME", "?")}
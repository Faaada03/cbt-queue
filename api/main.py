import os
import time
import jwt
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel
from celery import Celery
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import Json

SECRET = os.environ["JWT_SECRET"]
app = FastAPI(title="CBT Queue Ingestion API")

# Inisialisasi Celery dengan Publisher Confirms & Quorum Queue (Alur 5 Draw.io)
celery_app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])
celery_app.conf.update(
    broker_transport_options={"confirm_publish": True},
    task_default_queue="celery",
    task_default_queue_type="quorum",
    broker_connection_retry_on_startup=True,
)

# Connection Pool PostgreSQL (Alur 4 Draw.io)
pool = ThreadedConnectionPool(
    1,
    10,
    host=os.environ["PG_HOST"],
    dbname="cbt",
    user="cbt",
    password=os.environ["PG_PASSWORD"],
)


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
    """Menyimpan progres jawaban sementara (autosave sesuai diagram Draw.io)."""
    exam_id, answers = data["exam_id"], data["answers"]
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
    """Melihat status jawaban dan hasil nilai siswa (sesuai diagram Draw.io)."""
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
    """Menyimpan jawaban final ke PostgreSQL dan mempublikasikan task ke RabbitMQ Cluster."""
    exam_id = data.get("exam_id", "UJIAN-01")
    answers = data["answers"]
    conn = pool.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO submissions (student_id, exam_id, answers, status) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (student_id, exam_id) DO UPDATE SET answers=EXCLUDED.answers, status=%s, received_at=now()",
                (student_id, exam_id, Json(answers), "diterima", "diterima"),
            )
    finally:
        pool.putconn(conn)

    try:
        celery_app.send_task(
            "tasks.nilai_jawaban",
            args=[{"student_id": student_id, "exam_id": exam_id, "answers": answers}],
        )
    except Exception:
        raise HTTPException(status_code=503, detail="antrean tidak tersedia, coba lagi")

    return {"status": "diterima", "node": os.environ.get("NODE_NAME", "?")}
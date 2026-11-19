import os
import time
import threading
from contextlib import contextmanager

import jwt
import psycopg2
from celery import Celery
from fastapi import FastAPI, Depends, Header, HTTPException
from psycopg2.extras import Json
from psycopg2.pool import ThreadedConnectionPool
from pydantic import BaseModel

SECRET = os.environ["JWT_SECRET"]
NODE = os.environ.get("NODE_NAME", "?")
DEFAULT_EXAM = "UJIAN-01"

app = FastAPI(title="CBT Queue Ingestion API")

# Publisher confirms + quorum queue (alur 5 pada diagram)
celery_app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])
celery_app.conf.update(
    broker_transport_options={"confirm_publish": True},
    task_default_queue="celery",
    task_default_queue_type="quorum",
    broker_connection_retry_on_startup=True,
)

# Connection pool PostgreSQL (alur 4 pada diagram).
# ThreadedConnectionPool melempar error jika habis, bukan menunggu.
# Semaphore membuat request mengantre sehingga tidak gagal saat beban tinggi.
POOL_MAX = 20
pool = ThreadedConnectionPool(
    2,
    POOL_MAX,
    host=os.environ["PG_HOST"],
    dbname="cbt",
    user="cbt",
    password=os.environ["PG_PASSWORD"],
)
pool_sem = threading.BoundedSemaphore(POOL_MAX)


@contextmanager
def db():
    pool_sem.acquire()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)
        pool_sem.release()


class LoginRequest(BaseModel):
    student_id: str
    password: str


class AnswerBody(BaseModel):
    exam_id: str = DEFAULT_EXAM
    answers: dict


def auth(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="token tidak ada")
    try:
        token = authorization.replace("Bearer ", "")
        return jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="token tidak valid")


@app.get("/")
def cek():
    return {"status": "ok", "node": NODE}


@app.post("/login")
def login(body: LoginRequest):
    if body.password != os.environ["DEMO_PASSWORD"]:
        raise HTTPException(status_code=401, detail="login gagal")
    exp = int(time.time()) + 7200
    token = jwt.encode({"sub": body.student_id, "exp": exp}, SECRET, algorithm="HS256")
    return {"token": token}


@app.post("/answer")
def save_answer(body: AnswerBody, student_id: str = Depends(auth)):
    """Autosave jawaban sementara. Ditolak (409) jika sudah di-submit final."""
    try:
        with db() as conn, conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO submissions (student_id, exam_id, answers, status) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (student_id, exam_id) DO UPDATE "
                "SET answers=EXCLUDED.answers, received_at=now() "
                "WHERE submissions.status = 'draft'",
                (student_id, body.exam_id, Json(body.answers), "draft"),
            )
            saved = cur.rowcount == 1
    except psycopg2.Error:
        raise HTTPException(status_code=503, detail="database tidak tersedia, coba lagi")
    if not saved:
        raise HTTPException(status_code=409, detail="jawaban sudah di-submit final")
    return {"status": "tersimpan", "node": NODE}


@app.get("/progress")
def get_progress(exam_id: str = DEFAULT_EXAM, student_id: str = Depends(auth)):
    """Status jawaban dan nilai siswa."""
    try:
        with db() as conn, conn, conn.cursor() as cur:
            cur.execute(
                "SELECT s.status, s.answers, r.score "
                "FROM submissions s LEFT JOIN results r "
                "ON s.student_id = r.student_id AND s.exam_id = r.exam_id "
                "WHERE s.student_id = %s AND s.exam_id = %s",
                (student_id, exam_id),
            )
            row = cur.fetchone()
    except psycopg2.Error:
        raise HTTPException(status_code=503, detail="database tidak tersedia, coba lagi")
    if not row:
        return {"status": "belum_ada_data"}
    return {
        "student_id": student_id,
        "exam_id": exam_id,
        "status": row[0],
        "answers": row[1],
        "score": float(row[2]) if row[2] is not None else None,
    }


@app.post("/submit", status_code=202)
def submit(body: AnswerBody, student_id: str = Depends(auth)):
    """Simpan jawaban final ke PostgreSQL, lalu publish task ke RabbitMQ.

    Idempoten: kiriman ulang menimpa baris yang sama, aman untuk retry.
    """
    try:
        with db() as conn, conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO submissions (student_id, exam_id, answers, status) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (student_id, exam_id) DO UPDATE "
                "SET answers=EXCLUDED.answers, status=EXCLUDED.status, received_at=now()",
                (student_id, body.exam_id, Json(body.answers), "diterima"),
            )
    except psycopg2.Error:
        raise HTTPException(status_code=503, detail="database tidak tersedia, coba lagi")

    try:
        celery_app.send_task(
            "tasks.nilai_jawaban",
            args=[{"student_id": student_id, "exam_id": body.exam_id, "answers": body.answers}],
        )
    except Exception:
        raise HTTPException(status_code=503, detail="antrean tidak tersedia, coba lagi")

    return {"status": "diterima", "node": NODE}
import os
import time
import asyncio
import jwt
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from celery import Celery
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import Json

SECRET = os.environ["JWT_SECRET"]
app = FastAPI(title="CBT Queue Ingestion API")

# Batasi maksimal 12 operasi tulis DB+Broker simultan per container API (total 36 untuk 3 API)
# agar PostgreSQL & RabbitMQ Quorum (0.25 CPU) tidak pernah jenuh atau melempar PoolError 500.
submit_sem = asyncio.Semaphore(20)
pool = ThreadedConnectionPool(
    2,
    22,
    host=os.environ["PG_HOST"],
    dbname="cbt",
    user="cbt",
    password=os.environ["PG_PASSWORD"],
)

celery_app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])
celery_app.conf.update(
    broker_transport_options={"confirm_publish": True, "max_retries": 2},
    broker_pool_limit=6,
    task_default_queue="celery",
    task_default_queue_type="quorum",
    broker_connection_retry_on_startup=True,
)

pool = ThreadedConnectionPool(
    2,
    15,
    host=os.environ["PG_HOST"],
    dbname="cbt",
    user="cbt",
    password=os.environ["PG_PASSWORD"],
)


class LoginRequest(BaseModel):
    student_id: str
    password: str


async def auth(authorization: str = Header(...)):
    try:
        token = authorization.replace("Bearer ", "")
        return jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="token tidak valid")


@app.get("/")
async def cek():
    return {"status": "ok", "node": os.environ.get("NODE_NAME", "?")}


@app.post("/login")
async def login(body: LoginRequest):
    if body.password != os.environ["DEMO_PASSWORD"]:
        raise HTTPException(status_code=401, detail="login gagal")
    exp = int(time.time()) + 7200
    token = jwt.encode({"sub": body.student_id, "exp": exp}, SECRET, algorithm="HS256")
    return {"token": token}


def _db_upsert_submission(student_id: str, exam_id: str, answers: dict, status: str):
    conn = pool.getconn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO submissions (student_id, exam_id, answers, status) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (student_id, exam_id) DO UPDATE SET answers=EXCLUDED.answers, status=%s, received_at=now()",
                (student_id, exam_id, Json(answers), status, status),
            )
    finally:
        pool.putconn(conn)


def _db_get_progress(student_id: str, exam_id: str):
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
            return cur.fetchone()
    finally:
        pool.putconn(conn)


def _publish_grading_task(student_id: str, exam_id: str, answers: dict):
    celery_app.send_task(
        "tasks.nilai_jawaban",
        args=[{"student_id": student_id, "exam_id": exam_id, "answers": answers}],
        retry=False,
    )


@app.post("/answer")
async def save_answer(data: dict, student_id: str = Depends(auth)):
    exam_id, answers = data["exam_id"], data["answers"]
    async with submit_sem:
        await run_in_threadpool(_db_upsert_submission, student_id, exam_id, answers, "draft")
    return {"status": "tersimpan", "node": os.environ.get("NODE_NAME", "?")}


@app.get("/progress")
async def get_progress(exam_id: str = "UJIAN-01", student_id: str = Depends(auth)):
    async with submit_sem:
        row = await run_in_threadpool(_db_get_progress, student_id, exam_id)
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
async def submit(data: dict, student_id: str = Depends(auth)):
    exam_id = data.get("exam_id", "UJIAN-01")
    answers = data["answers"]

    async with submit_sem:
        await run_in_threadpool(_db_upsert_submission, student_id, exam_id, answers, "diterima")
        try:
            await run_in_threadpool(_publish_grading_task, student_id, exam_id, answers)
        except Exception:
            raise HTTPException(status_code=503, detail="antrean sibuk, coba lagi")

    return {"status": "diterima", "node": os.environ.get("NODE_NAME", "?")}
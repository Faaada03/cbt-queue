import os
import psycopg2
from celery import Celery

app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_default_queue="celery",
    task_default_queue_type="quorum",
)


def get_conn():
    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        dbname="cbt",
        user="cbt",
        password=os.environ["PG_PASSWORD"],
    )


@app.task(name="tasks.nilai_jawaban")
def nilai_jawaban(data: dict):
    sid, eid, answers = data["student_id"], data["exam_id"], data["answers"]
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT soal_no, jawaban FROM answer_keys WHERE exam_id=%s", (eid,))
            kunci = dict(cur.fetchall())
            benar = sum(1 for no, j in kunci.items() if answers.get(f"soal_{no}") == j)
            skor = 100.0 * benar / max(len(kunci), 1)

            # Alur 8 Draw.io: Tulis hasil (UPSERT results)
            cur.execute(
                "INSERT INTO results (student_id, exam_id, score) VALUES (%s, %s, %s) "
                "ON CONFLICT (student_id, exam_id) DO UPDATE SET score=EXCLUDED.score, graded_at=now()",
                (sid, eid, skor),
            )
            cur.execute(
                "UPDATE submissions SET status=%s WHERE student_id=%s AND exam_id=%s",
                ("selesai", sid, eid),
            )
    finally:
        conn.close()
    return {"student_id": sid, "exam_id": eid, "score": skor}
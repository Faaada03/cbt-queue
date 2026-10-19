import os
from fastapi import FastAPI
from celery import Celery

app = FastAPI()
celery_app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])

@app.get("/")
def cek():
    return {"status": "ok"}

@app.post("/submit")
def submit(data: dict):
    celery_app.send_task("tasks.nilai_jawaban", args=[data])
    return {"status": "diterima"}


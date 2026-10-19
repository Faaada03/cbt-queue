import os
import random
import time
from celery import Celery

app = Celery("tasks", broker=os.environ["CELERY_BROKER_URL"])

@app.task(name="tasks.nilai_jawaban")
def nilai_jawaban(data):
    time.sleep(random.uniform(0.05, 0.1))
    return {"status": "dinilai"}

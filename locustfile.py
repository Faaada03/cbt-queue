import random
from locust import HttpUser, task, between


class SiswaCBT(HttpUser):
    wait_time = between(1.0, 3.0)

    def on_start(self):
        self.sid = f"MHS-{random.randint(1, 10**7)}"
        self.headers = {}
        r = self.client.post(
            "/login",
            json={"student_id": self.sid, "password": "cbt123"},
            name="/login",
        )
        if r.status_code == 200:
            self.headers = {"Authorization": "Bearer " + r.json()["token"]}

    @task(2)
    def save_draft_answer(self):
        """Menguji jalur PgBouncer -> PostgreSQL (autosave draft)."""
        if not self.headers:
            return
        self.client.post(
            "/answer",
            headers=self.headers,
            json={
                "exam_id": "UJIAN-01",
                "answers": {
                    "soal_1": "A",
                    "soal_2": "B",
                    "soal_3": "C",
                    "soal_4": "D",
                    "soal_5": "A",
                },
            },
            name="/answer",
        )

    @task(1)
    def check_progress(self):
        """Menguji pembacaan data lewat PgBouncer."""
        if not self.headers:
            return
        self.client.get(
            "/progress?exam_id=UJIAN-01",
            headers=self.headers,
            name="/progress",
        )

    @task(3)
    def submit_final(self):
        """Menguji jalur Pure Async -> RabbitMQ Quorum Queue -> Celery Worker -> PgBouncer."""
        if not self.headers:
            return
        self.client.post(
            "/submit",
            headers=self.headers,
            json={
                "exam_id": "UJIAN-01",
                "answers": {
                    "soal_1": "A",
                    "soal_2": "B",
                    "soal_3": "C",
                    "soal_4": "D",
                    "soal_5": "A",
                },
            },
            name="/submit",
        )
import random
from locust import HttpUser, task, between


class Siswa(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.sid = f"MHS-{random.randint(1, 10**6)}"
        r = self.client.post(
            "/login",
            json={"student_id": self.sid, "password": "cbt123"},
            name="/login",
        )
        if r.status_code == 200:
            self.headers = {"Authorization": "Bearer " + r.json()["token"]}
        else:
            self.headers = {}

    @task
    def submit(self):
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
import time
import random
from locust import HttpUser, task, between


class Siswa(HttpUser):
    wait_time = between(3, 6)

    def on_start(self):
        self.sid = f"MHS-{random.randint(1, 10**7)}"
        # Bagi beban secara seimbang ke gateway1 (8000) dan gateway2 (8001)
        self.gateway = random.choice(["http://localhost:8000", "http://localhost:8001"])
        self.headers = {}

        while not self.headers:
            try:
                r = self.client.post(
                    f"{self.gateway}/login",
                    json={"student_id": self.sid, "password": "cbt123"},
                    name="/login",
                )
                if r.status_code == 200:
                    self.headers = {"Authorization": "Bearer " + r.json()["token"]}
                else:
                    time.sleep(random.uniform(1.5, 4.0))
            except Exception:
                time.sleep(random.uniform(1.5, 4.0))

    @task
    def submit(self):
        if not self.headers:
            return
        self.client.post(
            f"{self.gateway}/submit",
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
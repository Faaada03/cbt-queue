import random
from locust import FastHttpUser, between, task

GATEWAYS = ["http://localhost:8000", "http://localhost:8001"]


class SiswaCBT(FastHttpUser):
    wait_time = between(25, 40)  # ~100-200 RPS pada 1.000 VU
    connection_timeout = 10.0
    network_timeout = 15.0

    def on_start(self):
        self.gw = random.choice(GATEWAYS)
        self.sid = f"MHS-{random.randint(1, 10**8)}"
        self.headers = {}
        with self.client.post(
            f"{self.gw}/login",
            json={"student_id": self.sid, "password": "cbt123"},
            name="/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self.headers = {"Authorization": "Bearer " + resp.json()["token"]}
                resp.success()
            else:
                resp.failure(f"Login gagal: HTTP {resp.status_code}")

    @task
    def submit_jawaban(self):
        if not self.headers:
            return
        with self.client.post(
            f"{self.gw}/submit",
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
            catch_response=True,
        ) as resp:
            if resp.status_code == 202:
                resp.success()
            else:
                resp.failure(f"Submit gagal: HTTP {resp.status_code}")
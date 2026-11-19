import time
import random
from locust import HttpUser, task, between


class Siswa(HttpUser):
    wait_time = between(60, 90)

    def on_start(self):
        self.sid = f"MHS-{random.randint(1, 10**7)}"
        self.gateways = ["http://localhost:8000", "http://localhost:8001"]
        random.shuffle(self.gateways)
        self.headers = {}

        while not self.headers:
            for gw in self.gateways:
                try:
                    r = self.client.post(
                        f"{gw}/login",
                        json={"student_id": self.sid, "password": "cbt123"},
                        name="/login",
                    )
                    if r.status_code == 200:
                        self.headers = {"Authorization": "Bearer " + r.json()["token"]}
                        break
                except Exception:
                    continue
            if not self.headers:
                time.sleep(random.uniform(1.0, 3.0))

    @task
    def submit(self):
        if not self.headers:
            return
        payload = {
            "exam_id": "UJIAN-01",
            "answers": {
                "soal_1": "A",
                "soal_2": "B",
                "soal_3": "C",
                "soal_4": "D",
                "soal_5": "A",
            },
        }
        # Coba gateway utama; jika mati (port 8000/8001), otomatis failover ke gateway kedua
        for idx, gw in enumerate(self.gateways):
            is_last = idx == len(self.gateways) - 1
            with self.client.post(
                f"{gw}/submit",
                headers=self.headers,
                json=payload,
                name="/submit",
                catch_response=True,
            ) as r:
                if r.status_code == 202:
                    r.success()
                    return
                if not is_last:
                    r.success()  # Abaikan kegagalan hop pertama karena akan langsung failover
                else:
                    r.failure(f"Semua gateway gagal (HTTP {r.status_code})")
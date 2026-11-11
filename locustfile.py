import random
from locust import HttpUser, task, between

class CBTExamUser(HttpUser):
    # Jeda antar request per siswa (1 hingga 3 detik)
    wait_time = between(1, 3)

    @task
    def submit_jawaban_ujian(self):
        student_id = f"MHS-{random.randint(10000, 99999)}"
        payload = {
            "student_id": student_id,
            "exam_id": "UJIAN-NASIONAL-2026",
            "answers": {
                "soal_1": random.choice(["A", "B", "C", "D"]),
                "soal_2": random.choice(["A", "B", "C", "D"]),
                "soal_3": random.choice(["A", "B", "C", "D"]),
                "soal_4": random.choice(["A", "B", "C", "D"]),
                "soal_5": random.choice(["A", "B", "C", "D"])
            }
        }
        with self.client.post("/submit", json=payload, catch_response=True) as response:
            if response.status_code == 202:
                response.success()
            else:
                response.failure(f"Gagal submit: HTTP {response.status_code}")
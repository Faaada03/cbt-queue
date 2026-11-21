import time
import requests

GATEWAYS = ["http://localhost:8000", "http://localhost:8001"]
PASSWORD = "cbt123"


def get_jwt_token() -> str:
    for gw in GATEWAYS:
        try:
            r = requests.post(
                f"{gw}/login",
                json={"student_id": "MONITOR-DR", "password": PASSWORD},
                timeout=3,
            )
            if r.status_code == 200:
                return r.json()["token"]
        except Exception:
            continue
    raise RuntimeError("Gagal login ke semua gateway Nginx.")


def main():
    token = get_jwt_token()
    headers = {"Authorization": f"Bearer {token}"}
    print("JWT siap. Memantau ketersediaan layanan & RTO (Ctrl+C untuk berhenti)...\n")

    in_outage = False
    outage_start = 0.0
    gw_idx = 0

    while True:
        gw = GATEWAYS[gw_idx % len(GATEWAYS)]
        t0 = time.perf_counter()
        try:
            resp = requests.post(
                f"{gw}/submit",
                headers=headers,
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
                timeout=2.0,
            )
            lat_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 202:
                if in_outage:
                    rto = time.perf_counter() - outage_start
                    print(f"\n[PULIH] Layanan kembali normal di {gw} | RTO = {rto:.3f} detik\n")
                    in_outage = False
                node = resp.json().get("node", "?")
                print(f"[202 OK] {gw} -> {node} | Latency: {lat_ms:.1f} ms")
            else:
                raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:
            if not in_outage:
                in_outage = True
                outage_start = time.perf_counter()
                print(f"\n[GANGGUAN] {gw} gagal ({exc}). Failover ke gateway berikutnya...")
            gw_idx += 1

        time.sleep(0.25)


if __name__ == "__main__":
    main()
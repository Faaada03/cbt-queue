import time
import requests

GATEWAYS = ["http://localhost:8000", "http://localhost:8001"]
PASSWORD = "cbt123"


def get_jwt_token():
    for gw in GATEWAYS:
        try:
            r = requests.post(
                f"{gw}/login",
                json={"student_id": "MONITOR-DR", "password": PASSWORD},
                timeout=2,
            )
            if r.status_code == 200:
                return r.json()["token"]
        except Exception:
            continue
    raise RuntimeError("Gagal login ke semua gateway Nginx!")


def main():
    print("Mengambil token JWT...")
    token = get_jwt_token()
    headers = {"Authorization": f"Bearer {token}"}
    print("Token berhasil didapat. Memulai pemantauan RTO (Tekan Ctrl+C untuk berhenti)...\n")

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
                    "answers": {"soal_1": "A", "soal_2": "B", "soal_3": "C", "soal_4": "D", "soal_5": "A"},
                },
                timeout=2.0,
            )
            lat_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 202:
                if in_outage:
                    rto = time.perf_counter() - outage_start
                    print(f"\n[PULIH] Layanan kembali normal di {gw}! RTO Terukur = {rto:.3f} detik\n")
                    in_outage = False
                print(f"[OK 202] {gw} | Node: {resp.json().get('node')} | Latency: {lat_ms:.1f} ms")
            else:
                raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as e:
            if not in_outage:
                in_outage = True
                outage_start = time.perf_counter()
                print(f"\n[GANGGUAN TERDETEKSI] {gw} gagal ({e}). Mencoba failover...")
            gw_idx += 1  # Failover ke gateway berikutnya

        time.sleep(0.25)


if __name__ == "__main__":
    main()
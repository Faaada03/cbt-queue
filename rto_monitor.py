import time
import requests

# Gunakan 127.0.0.1 (bukan localhost) agar deteksi port mati di Windows instan (< 5 ms)
GATEWAYS = ["http://127.0.0.1:8000", "http://127.0.0.1:8001"]
PASSWORD = "cbt123"


def get_jwt_token(session: requests.Session):
    for gw in GATEWAYS:
        try:
            r = session.post(
                f"{gw}/login",
                json={"student_id": "MONITOR-DR", "password": PASSWORD},
                timeout=5.0,
            )
            if r.status_code == 200:
                return r.json()["token"]
        except Exception:
            continue
    raise RuntimeError("Gagal login ke semua gateway Nginx!")


def main():
    session = requests.Session()
    print("Mengambil token JWT...")
    token = get_jwt_token(session)
    headers = {"Authorization": f"Bearer {token}"}
    print("Token berhasil didapat. Memulai pemantauan RTO (Tekan Ctrl+C untuk berhenti)...\n")

    in_outage = False
    outage_start = 0.0
    gw_idx = 0

    while True:
        gw = GATEWAYS[gw_idx % len(GATEWAYS)]
        t0 = time.perf_counter()
        try:
            resp = session.post(
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
                timeout=4.0,
            )
            lat_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 202:
                node = resp.json().get("node")
                if in_outage:
                    rto = time.perf_counter() - outage_start
                    print(f"\n[PULIH] Failover berhasil ke {gw} (Node: {node})! RTO Terukur = {rto:.3f} detik\n")
                    in_outage = False
                elif lat_ms > 900:
                    print(f"[OK 202 - SEAMLESS FAILOVER] {gw} | Dialihkan ke Node: {node} | Latency: {lat_ms:.1f} ms (RTO Klien = 0.000s)")
                else:
                    print(f"[OK 202] {gw} | Node: {node} | Latency: {lat_ms:.1f} ms")
            else:
                raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as e:
            if not in_outage:
                in_outage = True
                outage_start = time.perf_counter()
                print(f"\n[GANGGUAN TERDETEKSI] {gw} gagal ({type(e).__name__}). Mencoba failover...")
            gw_idx += 1

        time.sleep(0.3)


if __name__ == "__main__":
    main()
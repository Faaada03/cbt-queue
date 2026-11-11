import time
import subprocess
import requests
from datetime import datetime

URL = "http://localhost:8000/submit"
PAYLOAD = {
    "student_id": "MHS-DR-001",
    "exam_id": "UJIAN-01",
    "answers": {
        "soal_1": "A",
        "soal_2": "B",
        "soal_3": "C",
        "soal_4": "D",
        "soal_5": "A"
    }
}

def get_container_info(container_name):
    """Mengambil status Running (True/False) dan IP asli langsung dari Docker"""
    try:
        out = subprocess.check_output(
            [
                "docker", "inspect", "-f",
                "{{.State.Running}}|{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                container_name
            ],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        running_str, ip_addr = out.split("|")
        return (running_str == "true"), f"{ip_addr}:8000"
    except Exception:
        return False, "unknown"

print("=== MONITOR FAILOVER & PENGUKUR RTO (CBT-QUEUE) ===")
print(f"Target Endpoint: {URL}\n")

_, primary_ip = get_container_info("cbt_fastapi_primary")
_, backup_ip = get_container_info("cbt_fastapi_backup")
print(f"IP Container Utama    (cbt_fastapi_primary) : {primary_ip}")
print(f"IP Container Cadangan (cbt_fastapi_backup)  : {backup_ip}\n")

last_success_time = time.time()
failure_start_time = None
is_on_backup = False

while True:
    now = time.time()
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    primary_alive, current_primary_ip = get_container_info("cbt_fastapi_primary")
    _, current_backup_ip = get_container_info("cbt_fastapi_backup")

    if current_primary_ip != "unknown":
        primary_ip = current_primary_ip
    if current_backup_ip != "unknown":
        backup_ip = current_backup_ip

    try:
        resp = requests.post(URL, json=PAYLOAD, timeout=5.0)
        if resp.status_code in [200, 201, 202]:
            # 1. DETEKSI FAILOVER: Hanya jika cbt_fastapi_primary benar-benar MATI (di-kill)
            if not primary_alive and not is_on_backup:
                start_ref = failure_start_time if failure_start_time else last_success_time
                rto_sec = now - start_ref
                is_on_backup = True
                failure_start_time = None

                print("\n" + "=" * 65)
                print(f"[{ts}] ALERT: BUKTI FAILOVER TERDETEKSI!")
                print(f"Container Utama Mati   : {primary_ip} [PRIMARY (UTAMA)]")
                print(f"Diambil Alih Cadangan  : {backup_ip} [BACKUP (CADANGAN)]")
                print(f"Nilai RTO Terukur      : {rto_sec:.3f} detik ({rto_sec * 1000:.1f} ms)")
                print("=" * 65 + "\n")

            # 2. DETEKSI FAILBACK: Hanya jika cbt_fastapi_primary sudah HIDUP kembali
            elif primary_alive and is_on_backup:
                is_on_backup = False
                failure_start_time = None

                print("\n" + "-" * 65)
                print(f"[{ts}] INFO: FAILBACK TERDETEKSI (CONTAINER UTAMA PULIH)!")
                print(f"Trafik Kembali Dari    : {backup_ip} [BACKUP (CADANGAN)]")
                print(f"Kembali Dilayani Oleh  : {primary_ip} [PRIMARY (UTAMA)]")
                print("-" * 65 + "\n")

            last_success_time = now

            if is_on_backup:
                print(f"[{ts}] HTTP {resp.status_code} OK | Server: {backup_ip} [BACKUP (CADANGAN)]")
            else:
                print(f"[{ts}] HTTP {resp.status_code} OK | Server: {primary_ip} [PRIMARY (UTAMA)]")
        else:
            if failure_start_time is None:
                failure_start_time = last_success_time
            print(f"[{ts}] HTTP {resp.status_code} - Mengalihkan trafik ke container cadangan...")

    except Exception as e:
        if failure_start_time is None:
            failure_start_time = last_success_time
        print(f"[{ts}] GANGGUAN KONEKSI ({type(e).__name__}) - Mengalihkan ke cadangan...")

    time.sleep(0.2)
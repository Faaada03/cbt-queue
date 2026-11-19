"""Uji beban bertahap untuk CBT Queue.

Pemakaian (dari folder proyek, stack sudah berjalan):
    python loadtest/load_test.py <jumlah_worker>

Tiap tahap: login semua klien (tidak dihitung), kirim /submit serentak,
tunggu antrean kosong, lalu bandingkan jumlah diterima vs dinilai di database.
Hasil ditambahkan ke hasil_loadtest.csv.
"""
import asyncio
import csv
import statistics
import subprocess
import sys
import time

import httpx

GATEWAYS = ["http://localhost:8000", "http://localhost:8001"]
PASSWORD = "cbt123"
EXAM_ID = "UJIAN-01"
ANSWERS = {"soal_1": "A", "soal_2": "B", "soal_3": "C", "soal_4": "D", "soal_5": "A"}

CLIENT_STAGES = [1, 10, 50, 100, 500, 1000]
OUTPUT_CSV = "hasil_loadtest.csv"
DRAIN_TIMEOUT_S = 180


def compose_exec(*args) -> str:
    cmd = ["docker", "compose", "exec", "-T", *args]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout


def get_queue_length() -> int:
    """Jumlah pesan (ready + unacked) di antrean 'celery'."""
    try:
        out = compose_exec("rmq1", "rabbitmqctl", "list_queues", "-q", "name", "messages")
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "celery":
                return int(parts[1])
    except Exception:
        pass
    return 0


def db_count(table: str) -> int:
    try:
        out = compose_exec(
            "postgres", "psql", "-U", "cbt", "-d", "cbt", "-t", "-A",
            "-c", f"SELECT count(*) FROM {table}",
        )
        return int(out.strip())
    except Exception:
        return -1


def reset_tables():
    try:
        compose_exec(
            "postgres", "psql", "-U", "cbt", "-d", "cbt",
            "-c", "TRUNCATE submissions, results",
        )
    except Exception as e:
        print(f"  ! Gagal TRUNCATE tabel: {e}")


async def login(client: httpx.AsyncClient, idx: int):
    base = GATEWAYS[idx % len(GATEWAYS)]
    try:
        r = await client.post(
            f"{base}/login",
            json={"student_id": f"peserta-{idx:04d}", "password": PASSWORD},
            timeout=15.0,
        )
        return r.json()["token"] if r.status_code == 200 else None
    except Exception:
        return None


async def send_request(client: httpx.AsyncClient, idx: int, token):
    if token is None:
        return False, 0.0
    base = GATEWAYS[idx % len(GATEWAYS)]
    start = time.perf_counter()
    try:
        resp = await client.post(
            f"{base}/submit",
            headers={"Authorization": f"Bearer {token}"},
            json={"exam_id": EXAM_ID, "answers": ANSWERS},
            timeout=15.0,
        )
        return resp.status_code == 202, (time.perf_counter() - start) * 1000
    except Exception:
        return False, (time.perf_counter() - start) * 1000


async def run_stage(num_clients: int, worker_count: int):
    print(f"\n[Worker: {worker_count}] Uji beban {num_clients} klien...")
    reset_tables()
    limits = httpx.Limits(max_keepalive_connections=200, max_connections=500)

    async with httpx.AsyncClient(limits=limits) as client:
        tokens = await asyncio.gather(*[login(client, i) for i in range(num_clients)])
        start_burst = time.perf_counter()
        results = await asyncio.gather(
            *[send_request(client, i, tokens[i]) for i in range(num_clients)]
        )
        ingestion_duration = time.perf_counter() - start_burst

    latencies = [r[1] for r in results if r[0]]
    success_count = sum(1 for r in results if r[0])

    # Tunggu antrean kosong (queue drain), dengan batas waktu
    while get_queue_length() > 0 and time.perf_counter() - start_burst < DRAIN_TIMEOUT_S:
        await asyncio.sleep(0.5)
    # Beri waktu task terakhir selesai ditulis ke database
    await asyncio.sleep(2)
    total_drain_duration = time.perf_counter() - start_burst

    diterima = db_count("submissions")
    dinilai = db_count("results")

    ingestion_rps = success_count / ingestion_duration if ingestion_duration > 0 else 0
    worker_rps = dinilai / total_drain_duration if total_drain_duration > 0 and dinilai > 0 else 0
    avg_lat = statistics.mean(latencies) if latencies else 0
    p95_lat = (
        statistics.quantiles(latencies, n=100)[94]
        if len(latencies) >= 20
        else max(latencies, default=0)
    )
    error_rate = 100.0 * (num_clients - success_count) / num_clients

    print(
        f" -> 202: {success_count}/{num_clients} (error {error_rate:.2f}%) | "
        f"RPS: {ingestion_rps:.2f} | Avg: {avg_lat:.1f} ms, P95: {p95_lat:.1f} ms | "
        f"Drain: {total_drain_duration:.1f} s | DB diterima={diterima}, dinilai={dinilai}"
    )

    return {
        "workers": worker_count,
        "clients": num_clients,
        "success_202": success_count,
        "error_rate_pct": round(error_rate, 2),
        "ingestion_time_s": round(ingestion_duration, 4),
        "ingestion_rps": round(ingestion_rps, 2),
        "avg_latency_ms": round(avg_lat, 2),
        "p95_latency_ms": round(p95_lat, 2),
        "drain_time_s": round(total_drain_duration, 4),
        "worker_throughput_tps": round(worker_rps, 2),
        "db_diterima": diterima,
        "db_dinilai": dinilai,
    }


async def main():
    if len(sys.argv) < 2:
        print("Gunakan: python loadtest/load_test.py <jumlah_worker>")
        sys.exit(1)

    worker_count = int(sys.argv[1])
    rows = []
    for clients in CLIENT_STAGES:
        rows.append(await run_stage(clients, worker_count))
        await asyncio.sleep(2)

    try:
        with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
            file_exists = bool(f.readline())
    except FileNotFoundError:
        file_exists = False

    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    print(f"\nData ditambahkan ke {OUTPUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
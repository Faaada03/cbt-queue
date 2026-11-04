import asyncio
import time
import subprocess
import csv
import statistics
import sys
import httpx

# Daftar port Nginx load balancer sesuai konfigurasi sistem Anda
NGINX_URLS = [
    "http://localhost:8001/submit",
    "http://localhost:8002/submit",
]

CLIENT_STAGES = [1, 10, 50, 100, 500, 1000]
OUTPUT_CSV = "hasil_loadtest.csv"


def get_queue_length() -> int:
    """Mengambil jumlah pesan tersisa (ready + unacked) di antrean celery RabbitMQ."""
    try:
        cmd = [
            "docker", "compose", "exec", "-T", "rabbitmq",
            "rabbitmqctl", "list_queues", "-q", "name", "messages"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in res.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "celery":
                return int(parts[1])
    except Exception:
        pass
    return 0


async def send_request(client: httpx.AsyncClient, idx: int):
    url = NGINX_URLS[idx % len(NGINX_URLS)]
    payload = {
        "peserta_id": f"peserta-{idx:04d}",
        "jawaban": ["A", "B", "C", "D", "A"]
    }
    start = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, timeout=15.0)
        latency_ms = (time.perf_counter() - start) * 1000
        return resp.status_code == 202, latency_ms
    except Exception:
        latency_ms = (time.perf_counter() - start) * 1000
        return False, latency_ms


async def run_stage(num_clients: int, worker_count: int):
    print(f"\n[Worker: {worker_count}] Menjalankan uji beban {num_clients} klien...")
    limits = httpx.Limits(max_keepalive_connections=200, max_connections=500)
    
    async with httpx.AsyncClient(limits=limits) as client:
        start_burst = time.perf_counter()
        tasks = [send_request(client, i) for i in range(num_clients)]
        results = await asyncio.gather(*tasks)
        ingestion_duration = time.perf_counter() - start_burst

    successes = [r[0] for r in results]
    latencies = [r[1] for r in results if r[0]]
    success_count = sum(successes)

    # Memantau waktu kuras antrean (Queue Drain Time) pada Celery Worker
    while get_queue_length() > 0:
        await asyncio.sleep(0.2)
    total_drain_duration = time.perf_counter() - start_burst

    ingestion_rps = success_count / ingestion_duration if ingestion_duration > 0 else 0
    worker_rps = success_count / total_drain_duration if total_drain_duration > 0 else 0
    avg_lat = statistics.mean(latencies) if latencies else 0
    p95_lat = (
        statistics.quantiles(latencies, n=100)[94]
        if len(latencies) >= 20
        else max(latencies, default=0)
    )

    print(
        f" -> Sukses 202: {success_count}/{num_clients} | "
        f"Ingestion RPS: {ingestion_rps:.2f} req/s | "
        f"Avg Latency: {avg_lat:.2f} ms (P95: {p95_lat:.2f} ms) | "
        f"Total Drain Time: {total_drain_duration:.2f} s ({worker_rps:.2f} task/s)"
    )

    return {
        "workers": worker_count,
        "clients": num_clients,
        "success_202": success_count,
        "ingestion_time_s": round(ingestion_duration, 4),
        "ingestion_rps": round(ingestion_rps, 2),
        "avg_latency_ms": round(avg_lat, 2),
        "p95_latency_ms": round(p95_lat, 2),
        "drain_time_s": round(total_drain_duration, 4),
        "worker_throughput_tps": round(worker_rps, 2),
    }


async def main():
    if len(sys.argv) < 2:
        print("Gunakan perintah: python load_test.py <jumlah_worker>")
        sys.exit(1)

    worker_count = int(sys.argv[1])
    rows = []

    for clients in CLIENT_STAGES:
        row = await run_stage(clients, worker_count)
        rows.append(row)
        await asyncio.sleep(2)

    file_exists = False
    try:
        with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
            file_exists = bool(f.readline())
    except FileNotFoundError:
        pass

    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
        # Jika file belum ada, tulis header kolom
            writer.writeheader()
        writer.writerows(rows)

    print(f"\nData berhasil ditambahkan ke {OUTPUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
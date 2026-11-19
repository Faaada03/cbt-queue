# CBT Queue – Dynamic Worker Queue (Kelompok 3)

Pemrosesan jawaban ujian masif (Computer Based Test) dengan FastAPI, RabbitMQ,
Celery, dan PostgreSQL, dijalankan dengan Docker Compose. Tanpa Single Point of Failure
pada tiap lapisan (dalam batas satu mesin).

## Anggota
- Muhammad ramadhan
- Muhammad Reza Firmansyah
- Muhammad Fanisam
- Ananda Farid Firdaus
- M Rangga Pratama Putra

## Arsitektur
Client -> Nginx (gateway1:8000 / gateway2:8001) -> API (api1, api2, api3)
-> PostgreSQL (simpan jawaban) dan RabbitMQ cluster 3 node (quorum queue)
-> Celery worker (scale 2 sampai 6) -> PostgreSQL (simpan hasil nilai).

| Komponen | Keterangan |
|---|---|
| gateway1, gateway2 | Nginx identik, `least_conn`, failover dilakukan di sisi client |
| api1 sampai api3 | FastAPI active-active, stateless, JWT |
| postgres | Tabel `submissions`, `results`, `answer_keys` |
| rmq1 sampai rmq3 | Cluster RabbitMQ, quorum queue, volume persisten |
| celery_worker | `acks_late`, `prefetch=1`, penilaian idempoten (UPSERT) |
| cadvisor, prometheus, grafana | Monitoring (opsional, profile `monitoring`) |

Semua container aplikasi dibatasi 0,25 CPU dan 256 MB. PostgreSQL dan RabbitMQ 512 MB.
Diagram ada di folder `docs/`.

## Jaringan
- `frontend-net`: jalur masuk. Dihubungkan ke gateway, RabbitMQ management, dan monitoring.
- `backend-net` (internal): API, PostgreSQL, RabbitMQ, worker. Tidak terbuka ke host.

## Cara menjalankan
```bash
cp .env.example .env        # lalu ganti nilainya
docker compose up -d --build
docker compose ps
```

Skala worker:
```bash
docker compose up -d --scale celery_worker=4
```

Monitoring (opsional, lebih berat):
```bash
docker compose --profile monitoring up -d
```
Grafana: http://localhost:3000 | Prometheus: http://localhost:9090 | RabbitMQ UI: http://localhost:15672

## Endpoint
| Endpoint | Fungsi |
|---|---|
| POST /login | Mendapat token JWT |
| POST /answer | Autosave jawaban (status draft) |
| GET /progress | Status, jawaban tersimpan, dan nilai |
| POST /submit | Jawaban final, masuk antrean, balasan 202 |

## Pengujian
```bash
# Uji fungsi
docker compose exec postgres psql -U cbt -d cbt -c 'SELECT * FROM results'

# Load test bertahap (argumen = jumlah worker saat ini)
python loadtest/load_test.py 2
python loadtest/plot_grafik.py

# Load test dengan Locust
locust -f locustfile.py --headless -u 1000 -r 6 -t 3m --csv hasil

# Pemantau RTO saat failover
python rto_monitor.py
```

Bukti tidak ada data hilang (jalankan setelah antrean kosong):
```bash
docker compose exec postgres psql -U cbt -d cbt -c 'SELECT (SELECT count(*) FROM submissions) AS diterima, (SELECT count(*) FROM results) AS dinilai'
```

## Skenario Disaster Recovery
| Skenario | Perintah |
|---|---|
| Dua worker mati | `docker ps -q -f name=celery_worker \| head -2 \| xargs docker kill` |
| RabbitMQ restart | `docker compose restart rmq2` |
| Satu API mati | `docker compose kill api2` |
| Satu Nginx mati | `docker compose kill gateway1` |

## Batasan yang diketahui
- Semua container berjalan di satu mesin, sehingga host tetap menjadi SPOF.
- PostgreSQL satu node (dengan volume persisten), belum ada replika.
- Failover antar gateway dilakukan di sisi client (dua port), bukan lewat VIP.
- Nginx menyimpan alamat IP API saat start. Jika IP berubah setelah container dibuat ulang,
  jalankan `docker compose restart gateway1 gateway2`.
- Login memakai satu password demo dari `.env`, karena ini simulasi.

## Struktur folder
- `api/`, `worker/`: kode dan Dockerfile
- `nginx/`, `rabbitmq/`, `prometheus/`, `grafana/`, `db/`: konfigurasi
- `loadtest/`: skrip uji beban dan grafik
- `docs/`: diagram, laporan, dan data lama (`docs/lama/`)
# CBT Queue – Dynamic Worker Queue (Kelompok 3)

Pemrosesan jawaban ujian masif menggunakan FastAPI, RabbitMQ, dan Celery
yang dijalankan dengan Docker Compose.

## Anggota
- Rama
- Reza
- Fanisemz
- Farid
- Rangga

## Arsitektur singkat
- api (FastAPI): menerima kiriman jawaban, lalu mengirimnya ke antrean
- rabbitmq: message broker dengan antrean durable dan volume persisten
- worker (Celery): memproses penilaian secara asinkron, di-scale 2 sampai 6

Diagram ada di folder `docs/`.

## Jaringan
- frontend-net (172.20.0.0/24): jalur masuk dari luar, hanya api
- backend-net (172.21.0.0/24, internal): api, rabbitmq, dan worker

## Cara menjalankan
```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

## Struktur folder
- api/ : kode dan Dockerfile layanan FastAPI
- worker/ : kode dan Dockerfile Celery worker
- docs/ : diagram dan laporan

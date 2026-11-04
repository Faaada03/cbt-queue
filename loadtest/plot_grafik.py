import pandas as pd
import matplotlib.pyplot as plt

# Membaca data hasil load testing dari file CSV
OUTPUT_CSV = "hasil_loadtest.csv"

try:
    df = pd.read_csv(OUTPUT_CSV)
except FileNotFoundError:
    print(f"File {OUTPUT_CSV} tidak ditemukan. Jalankan skrip load_test.py terlebih dahulu!")
    exit(1)

workers_list = sorted(df["workers"].unique())

# Membuat kanvas grid 2x2 untuk visualisasi grafik
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle(
    "Evaluasi Skalabilitas & Load Testing Platform CBT (1 - 1.000 Klien)",
    fontsize=14,
    fontweight="bold"
)

# 1. Grafik Ingestion Throughput (RPS)
for w in workers_list:
    sub = df[df["workers"] == w]
    axes[0, 0].plot(sub["clients"], sub["ingestion_rps"], marker="o", label=f"{w} Worker")
axes[0, 0].set_title("HTTP Ingestion Throughput (RPS)")
axes[0, 0].set_xlabel("Jumlah Klien Konkuren")
axes[0, 0].set_ylabel("Throughput (Request / Detik)")
axes[0, 0].grid(True, linestyle="--", alpha=0.6)
axes[0, 0].legend()

# 2. Grafik Waktu Tanggap HTTP (Rata-rata Latency)
for w in workers_list:
    sub = df[df["workers"] == w]
    axes[0, 1].plot(sub["clients"], sub["avg_latency_ms"], marker="s", label=f"{w} Worker")
axes[0, 1].set_title("Waktu Tanggap HTTP Rata-rata (ms)")
axes[0, 1].set_xlabel("Jumlah Klien Konkuren")
axes[0, 1].set_ylabel("Waktu Tanggap (ms)")
axes[0, 1].grid(True, linestyle="--", alpha=0.6)
axes[0, 1].legend()

# 3. Grafik Throughput Pemrosesan Worker (Task/Detik)
for w in workers_list:
    sub = df[df["workers"] == w]
    axes[1, 0].plot(sub["clients"], sub["worker_throughput_tps"], marker="^", label=f"{w} Worker")
axes[1, 0].set_title("Effective Worker Throughput (Task / Detik)")
axes[1, 0].set_xlabel("Jumlah Klien Konkuren")
axes[1, 0].set_ylabel("Kecepatan Penilaian (Task / Detik)")
axes[1, 0].grid(True, linestyle="--", alpha=0.6)
axes[1, 0].legend()

# 4. Grafik Total Waktu Kuras Antrean (Drain Time)
for w in workers_list:
    sub = df[df["workers"] == w]
    axes[1, 1].plot(sub["clients"], sub["drain_time_s"], marker="d", label=f"{w} Worker")
axes[1, 1].set_title("Waktu Penyelesaian Antrean / Queue Drain Time (Detik)")
axes[1, 1].set_xlabel("Jumlah Klien Konkuren")
axes[1, 1].set_ylabel("Total Waktu (Detik)")
axes[1, 1].grid(True, linestyle="--", alpha=0.6)
axes[1, 1].legend()

plt.tight_layout(rect=[0, 0.03, 1, 0.95])
plt.savefig("grafik_pertemuan_3.png", dpi=300)
print("Grafik perbandingan berhasil disimpan sebagai file grafik_pertemuan_3.png")
# SETUP AKIRA — Dari Nol Sampai Jalan

Panduan ini untuk laptop yang **belum pernah** menjalankan AKIRA. Ikuti
berurutan. Perkiraan waktu: 30–45 menit, sebagian besar menunggu unduhan.

Semua perintah dijalankan di **PowerShell**, dari dalam folder `akira`.

---

## 1. Periksa prasyarat dulu

Jangan langsung memasang apa pun. Pastikan tiga hal ini ada:

```powershell
python --version        # harus 3.10, 3.11, atau 3.12
nvidia-smi              # harus menampilkan GPU NVIDIA
ollama --version        # harus menampilkan versi
```

| Kalau gagal | Lakukan |
|---|---|
| `python` tidak dikenal atau versi 3.13 | Pasang Python 3.11 dari python.org — **centang "Add to PATH"** |
| `nvidia-smi` tidak dikenal | Pasang driver NVIDIA terbaru. Tanpa GPU tetap bisa, tapi lambat |
| `ollama` tidak dikenal | Pasang dari ollama.com |

**Kenapa bukan Python 3.13:** beberapa pustaka audio belum menyediakan versi
siap pakai untuk 3.13, dan memasangnya dari kode sumber menuntut Visual C++.

---

## 2. Kalau `activate` diblokir

PowerShell di Windows memblokir skrip secara bawaan. Buka ulang sekali saja:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Jawab `Y`. Cukup sekali per komputer.

---

## 3. Buat lingkungan virtual

```powershell
python -m venv venv
venv\Scripts\activate
```

Tanda berhasil: awal baris berubah jadi `(venv) PS ...`.

Setiap kali membuka terminal baru, jalankan `venv\Scripts\activate` lagi.

---

## 4. Pasang PyTorch versi CUDA — WAJIB DULUAN

```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**Urutan ini penting.** Kalau langkah 5 dijalankan lebih dulu, `pip` akan
memasang PyTorch versi CPU secara otomatis. AKIRA tetap jalan, tapi Whisper
lokal berjalan di prosesor — sekitar 10 detik per kalimat, bukan 1 detik.

Periksa hasilnya:

```powershell
python -c "import torch; print(torch.cuda.is_available())"
```

Harus `True`. Kalau `False`, hapus lalu pasang ulang dengan perintah di atas.

---

## 5. Pasang sisa dependensi

```powershell
pip install -r requirements.txt
```

**Kalau `pyaudio` gagal:** jalankan `pip install pipwin` lalu
`pipwin install pyaudio`.

**Opsional** — pintasan keyboard yang berfungsi di luar jendela AKIRA:

```powershell
pip install keyboard
```

---

## 6. Unduh model pendukung openWakeWord

```powershell
python -c "import openwakeword; openwakeword.utils.download_models()"
```

Ini mengunduh ekstraktor fitur audio yang dibutuhkan model wake word.
Hanya sekali.

---

## 7. Siapkan model bahasa lokal

```powershell
ollama pull qwen3:4b
```

Ukurannya sekitar 2,6 GB. Setelah selesai, uji:

```powershell
ollama run qwen3:4b "halo"
```

Harus menjawab. Tekan `Ctrl+D` untuk keluar.

---

## 8. Buat berkas `.env`

```powershell
Copy-Item .env.example .env
```

Buka `.env` di VS Code, lalu isi `GROQ_API_KEY`:

1. Buka **console.groq.com** → masuk dengan akun Google
2. **API Keys** → **Create API Key** → salin
3. Tempel setelah `GROQ_API_KEY=` — **tanpa spasi, tanpa tanda kutip**

```
GROQ_API_KEY=gsk_abc123...
```

Satu key Groq dipakai untuk transkripsi **dan** penalaran. Tanpa key ini
AKIRA tetap berjalan, hanya dengan Whisper lokal dan qwen3 lokal.

Periksa bahwa terbaca:

```powershell
python scripts\cek_api_key.py
```

---

## 9. Siapkan Google Calendar

### 9a. Buat kredensial (sekali per tim)

1. Buka **console.cloud.google.com** → buat proyek baru
2. **APIs & Services** → **Library** → cari **Google Calendar API** → **Enable**
3. **OAuth consent screen** → pilih **External** → isi nama aplikasi & email
4. Di bagian **Test users**, tambahkan email **setiap anggota tim**
5. **Credentials** → **Create Credentials** → **OAuth client ID** →
   jenis **Desktop app**
6. Unduh berkas JSON-nya → ganti nama jadi `credentials.json` →
   taruh di folder `config/`

### 9b. Terbitkan aplikasinya — JANGAN DILEWATI

Selama status aplikasi masih **"Testing"**, Google mencabut izin setiap
**7 hari**. Gejalanya jahat: AKIRA hidup normal, wake word terdeteksi, suara
keluar — tapi **setiap perintah kalender gagal** dengan pesan `invalid_grant`.

**OAuth consent screen** → tombol **Publish App** → konfirmasi.

### 9c. Login pertama

Saat AKIRA pertama kali dijalankan, browser terbuka meminta izin. Pilih akun
yang sudah terdaftar sebagai Test user, lalu izinkan. Berkas
`config/token.json` akan dibuat otomatis.

**Kalau muncul `invalid_grant` di kemudian hari:**

```powershell
Remove-Item config\token.json
python run.py
```

Lalu login ulang di browser.

---

## 10. Pastikan berkas penting ada

```
config/
├── settings.yaml        ada di ZIP
├── credentials.json     dari langkah 9a — TIDAK ada di ZIP
└── token.json           dibuat otomatis saat login pertama

models/
├── akira_wake_up.onnx               ada di ZIP
├── akira_destroy.onnx               ada di ZIP
├── id_ID-news_tts-medium.onnx       ada di ZIP (lihat catatan di bawah)
└── id_ID-news_tts-medium.onnx.json  ada di ZIP

.env                     dari langkah 8 — TIDAK ada di ZIP
```

`credentials.json`, `token.json`, dan `.env` sengaja tidak disertakan karena
berisi kredensial pribadi.

**Kalau mengambil dari GitHub, bukan dari ZIP:** suara Piper
(`id_ID-news_tts-medium.onnx`, 63 MB) tidak ikut di repositori karena melewati
ambang peringatan ukuran berkas GitHub. Unduh berkas `.onnx` dan `.onnx.json`
suara **id_ID news_tts medium** dari repositori *piper-voices* milik rhasspy di
Hugging Face, lalu taruh di folder `models/`. Tanpa berkas ini AKIRA tetap
berjalan — suara cadangannya memakai suara bawaan Windows.

---

## 11. Uji bertahap

Dari yang paling ringan. Kalau satu gagal, berhenti dan perbaiki dulu:

```powershell
# 1. Semua test otomatis — tanpa mikrofon, GPU, maupun internet
pytest tests/ -q

# 2. Mesin STT mana yang siap
python -m src.stt.backends

# 3. Model LLM Groq mana yang hidup (butuh internet)
python scripts\cek_model_llm.py

# 4. Penguraian perintah — tanpa mikrofon
python -m src.nlp.parser
```

Test pertama harus menunjukkan **898 passed**.

---

## 12. Jalankan

**Sebagai aplikasi** (disarankan):

```powershell
python akira_app.py
```

Atau klik ganda `scripts\buka_aplikasi.bat`.

Di tab **Status**, tekan **Periksa Komponen** — semua baris harus hijau atau
kuning, tidak ada yang merah. Lalu **Jalankan AKIRA** dan ucapkan
**"AKIRA WAKE UP"**.

**Mode terminal:**

```powershell
python run.py
```

---

## 13. (Opsional) Jalan otomatis saat laptop menyala

```powershell
powershell -ExecutionPolicy Bypass -File scripts\pasang_autostart.ps1
```

Mencabutnya:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\hapus_autostart.ps1
```

Tiga hal yang sudah ditangani skripnya:

- **Berjalan sebagai pengguna biasa.** Opsi Task Scheduler "run whether user
  is logged on or not" memutus akses ke mikrofon dan speaker — AKIRA jadi
  tuli dan bisu padahal log-nya terlihat normal.
- **Jendela hitam disembunyikan** lewat `akira_start_hidden.vbs`.
- **Jeda 1 menit setelah login**, supaya wifi dan Ollama sempat siap.

**Untuk demo, jangan pakai auto-start.** Jalankan manual lewat aplikasi
supaya log startup terlihat.

---

## Kalau bermasalah

| Gejala | Penyebab paling mungkin |
|---|---|
| `torch.cuda.is_available()` = `False` | PyTorch versi CPU. Ulangi langkah 4 |
| Transkripsi sangat lambat | Sama dengan di atas |
| `invalid_grant` di log | Token kedaluwarsa. Hapus `config\token.json`, login ulang, lalu kerjakan langkah 9b |
| Log berisi `GROQ_API_KEY KOSONG` | `.env` belum diisi, atau baris masih diawali `#` |
| `.env` tidak terbaca sama sekali | Tersimpan sebagai `.env.txt`. Cek dengan `dir .env*` |
| Wake word tidak pernah terdeteksi | Uji mikrofon di tab Status. RMS harus di atas 320 |
| AKIRA menjawab sendiri tanpa dipanggil | Ruangan berisik. Naikkan "Ambang derau mikrofon" di tab Pengaturan |
| `pyaudio` gagal dipasang | `pip install pipwin` lalu `pipwin install pyaudio` |
| `Ollama tidak siap` | Buka aplikasi Ollama dulu, atau jalankan `ollama serve` |

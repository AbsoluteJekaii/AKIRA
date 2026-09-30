"""
Perintah rahasia: AKIRA menghapus dirinya sendiri.
Tanggung jawab: Person 1 (Integrator utama) — Sprint 3.14

PERINGATAN: modul ini menghapus file secara permanen. Baca sampai habis
sebelum mengubah apa pun di sini.

--- Kenapa desainnya berlapis ---

Menghapus seluruh proyek dengan satu kalimat terdengar keren, tapi berbahaya
untuk hal yang paling mahal di proyek ini: `models/akira_wake_up.onnx`.
File itu hasil training Colab berjam-jam dan TIDAK bisa dibuat ulang dalam
hitungan menit. Kalau terhapus karena salah dengar sehari sebelum final,
AKIRA tidak bisa dipanggil sama sekali.

Karena itu ada tiga lapis pengaman:

1. **Cadangan otomatis.** Sebelum menghapus apa pun, seluruh isi proyek
   di-zip ke folder induk. Bisa dimatikan, tapi jangan.
2. **Kode ucap acak.** User harus mengucapkan kata yang AKIRA sebutkan saat
   itu juga. Salah dengar tidak mungkin menghasilkan kata yang tepat.
3. **Bertingkat.** Default hanya menghapus DATA (token, log, pengaturan),
   bukan model dan kode. Penghapusan total harus diminta eksplisit.

--- Kenapa penghapusan ditunda ---

Proses Python tidak bisa menghapus folder tempat dirinya sendiri berjalan
di Windows — file .pyd dan DLL di dalam venv sedang terkunci. Jadi untuk
mode total, AKIRA menulis skrip kecil yang menunggu prosesnya mati, baru
menghapus foldernya. Skrip itu menghapus dirinya sendiri di baris terakhir.
"""
import os
import secrets
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from loguru import logger

# Kata sandi ucap — dipilih yang bunyinya jauh berbeda satu sama lain,
# supaya Whisper tidak mungkin tertukar antar pilihan.
KATA_KODE = ["MERAK", "GARUDA", "KOMODO", "RAJAWALI", "CENDRAWASIH"]

# Yang dihapus di tiap tingkat.
TINGKAT = {
    "data": [
        "config/token.json",           # akses ke Google Calendar
        "config/session_state.json",
        "config/user_settings.json",   # nama panggilan
        "config/pintasan.json",
        "logs",                        # berisi transkripsi setiap ucapan
        # Rekaman suara terakhir. Sebelumnya tercantum "temp.wav" — nama
        # lama yang sudah tidak dipakai — sehingga rekaman sungguhan justru
        # tertinggal. Padahal itu data paling pribadi di seluruh daftar ini.
        "temp_recording.wav",
    ],
    "model": [
        "models",
    ],
    "total": [],  # ditangani terpisah: seluruh folder proyek
}


def akar_proyek() -> Path:
    """Folder akar proyek (tempat run.py berada)."""
    return Path(__file__).resolve().parents[2]


def pilih_kata_kode() -> str:
    # secrets, bukan random: kata kode ini gerbang terakhir sebelum data
    # dihapus, jadi tidak boleh dapat ditebak dari keadaan generator acak.
    return secrets.choice(KATA_KODE)


def cocok_kata_kode(jawaban: str, kode: str) -> bool:
    """
    Cek apakah user mengucapkan kata kodenya.
    Longgar terhadap tanda baca dan huruf besar-kecil, tapi katanya harus utuh.
    """
    if not jawaban:
        return False
    bersih = "".join(c for c in jawaban.upper() if c.isalpha() or c.isspace())
    return kode.upper() in bersih.split()


def buat_cadangan(tujuan_dir: Path = None) -> Path | None:
    """
    Zip seluruh proyek sebelum penghapusan. venv dan __pycache__ dilewati
    karena besar dan bisa dibuat ulang.

    Return path file cadangan, atau None kalau gagal.
    """
    akar = akar_proyek()
    tujuan_dir = tujuan_dir or akar.parent
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    tujuan = Path(tujuan_dir) / f"akira_backup_{stempel}.zip"

    lewati = {"venv", "__pycache__", ".git", ".pytest_cache"}

    try:
        with zipfile.ZipFile(tujuan, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(akar):
                dirs[:] = [d for d in dirs if d not in lewati]
                for nama in files:
                    penuh = Path(root) / nama
                    if penuh == tujuan:
                        continue
                    z.write(penuh, penuh.relative_to(akar))
        logger.info(f"Cadangan dibuat: {tujuan}")
        return tujuan
    except Exception as e:
        logger.error(f"Gagal membuat cadangan: {e}")
        return None


def daftar_target(tingkat: str) -> list:
    """
    Daftar path yang AKAN dihapus untuk tingkat tertentu.
    Dipakai untuk memberi tahu user sebelum eksekusi — tidak menghapus apa pun.
    """
    akar = akar_proyek()

    if tingkat == "total":
        return [akar]

    target = []
    for tingkat_nama in ("data", "model"):
        if tingkat == "data" and tingkat_nama == "model":
            continue
        for rel in TINGKAT[tingkat_nama]:
            path = akar / rel
            if path.exists():
                target.append(path)
    return target


def hapus_sekarang(tingkat: str) -> list:
    """
    Hapus target untuk tingkat 'data' atau 'model' — langsung, tanpa tunda.
    Return daftar path yang berhasil dihapus.
    """
    if tingkat == "total":
        raise ValueError("Tingkat 'total' harus lewat jadwalkan_hapus_total()")

    terhapus = []
    for path in daftar_target(tingkat):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            terhapus.append(path)
            logger.warning(f"Dihapus: {path}")
        except Exception as e:
            logger.error(f"Gagal menghapus {path}: {e}")
    return terhapus


def jadwalkan_hapus_total() -> Path | None:
    """
    Jadwalkan penghapusan seluruh folder proyek SETELAH proses ini mati.

    Python tidak bisa menghapus folder tempat dirinya berjalan (file di venv
    sedang terkunci Windows), jadi pekerjaannya diserahkan ke skrip kecil yang
    menunggu prosesnya keluar, menghapus foldernya, lalu menghapus dirinya
    sendiri.

    Return path skrip yang dibuat, atau None kalau gagal.
    """
    akar = akar_proyek()
    pid = os.getpid()

    if os.name == "nt":
        skrip = akar.parent / f"akira_hapus_{pid}.bat"
        isi = f"""@echo off
rem Menunggu proses AKIRA (PID {pid}) benar-benar berhenti
:tunggu
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto tunggu
)
timeout /t 2 /nobreak >nul
rmdir /s /q "{akar}"
del "%~f0"
"""
    else:
        skrip = akar.parent / f"akira_hapus_{pid}.sh"
        isi = f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 1; done
sleep 2
rm -rf "{akar}"
rm -- "$0"
"""

    try:
        skrip.write_text(isi, encoding="utf-8")
        if os.name != "nt":
            skrip.chmod(0o755)

        # stdin/stdout/stderr WAJIB diputus. Kalau skrip mewarisi pipe dari
        # proses induk, induknya ikut menunggu skrip selesai — padahal skrip
        # itu justru menunggu induknya mati. Keduanya saling menunggu dan
        # AKIRA menggantung selamanya alih-alih berhenti.
        tanpa_io = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        if os.name == "nt":
            # Jalur lengkap cmd.exe dari COMSPEC. Nama "cmd" saja membuat
            # Windows mencarinya di beberapa folder, sehingga cmd.exe palsu
            # di folder yang salah bisa ikut terjalankan.
            penerjemah = os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
            subprocess.Popen(
                [penerjemah, "/c", str(skrip)],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                **tanpa_io,
            )
        else:
            subprocess.Popen(["/bin/sh", str(skrip)], start_new_session=True, **tanpa_io)

        logger.warning(f"Penghapusan total dijadwalkan lewat {skrip}")
        return skrip
    except Exception as e:
        logger.error(f"Gagal menjadwalkan penghapusan total: {e}")
        return None


def ringkas_target(tingkat: str) -> str:
    """Kalimat untuk dibacakan AKIRA — apa saja yang akan hilang."""
    if tingkat == "total":
        return (
            "seluruh sistem saya, termasuk kode program, model wake word, "
            "dan semua konfigurasi"
        )
    if tingkat == "model":
        return "semua model saya, termasuk model wake word hasil training"
    return (
        "data pribadi saya: token login, rekaman suara terakhir, log percakapan, "
        "nama panggilan, dan pengaturan pintasan"
    )


if __name__ == "__main__":
    # python -m src.dialog.self_destruct
    # HANYA menampilkan apa yang AKAN dihapus. Tidak menghapus apa pun.
    print(f"Akar proyek: {akar_proyek()}\n")
    for tingkat in ("data", "model", "total"):
        print(f"[{tingkat}] {ringkas_target(tingkat)}")
        for path in daftar_target(tingkat):
            print(f"    - {path}")
        print()

    kode = pilih_kata_kode()
    print(f"Contoh kata kode: {kode}")
    for jawaban in [kode, kode.lower(), f"kodenya {kode}.", "MERAK GARUDA", "batal"]:
        print(f"  {jawaban!r:22} -> cocok={cocok_kata_kode(jawaban, kode)}")

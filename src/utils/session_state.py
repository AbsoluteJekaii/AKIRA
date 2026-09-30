"""
Status sesi selama satu kali menjalankan AKIRA.
Tanggung jawab: Person 1 (Integrator utama) — Sprint 3.5

Aturan briefing (sesuai permintaan):
- Sekali per RUN. Panggilan "AKIRA WAKE UP" pertama setelah program dinyalakan
  akan mendapat laporan agenda; panggilan berikutnya tidak.
- Reset otomatis kalau tanggal berganti (lewat 23:59), supaya AKIRA yang
  dibiarkan hidup semalaman tetap melapor di pagi berikutnya.

Versi sebelumnya menyimpan status ke file, sehingga restart program TIDAK
memicu briefing lagi. Itu salah tafsir dari saya — statusnya sekarang murni
di memori proses, jadi setiap kali `python run.py` dijalankan, hitungannya
mulai dari nol.
"""
from datetime import datetime

from loguru import logger

# Tanggal saat briefing terakhir diucapkan DI PROSES INI. None = belum pernah.
_briefing_terakhir: str | None = None


def _hari_ini() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def sudah_briefing_hari_ini() -> bool:
    """
    True kalau briefing sudah diucapkan dalam run ini DAN masih di hari yang sama.
    Begitu tanggal berganti, hasilnya kembali False dengan sendirinya.
    """
    if _briefing_terakhir is None:
        return False
    if _briefing_terakhir != _hari_ini():
        logger.info("Tanggal berganti, briefing akan diucapkan lagi")
        return False
    return True


def tandai_briefing_selesai():
    """Catat bahwa briefing sudah diucapkan di run ini."""
    global _briefing_terakhir
    _briefing_terakhir = _hari_ini()
    logger.info(f"Briefing ditandai selesai untuk {_briefing_terakhir}")


def reset_briefing():
    """Paksa briefing diucapkan lagi (dipakai saat testing / demo ulang)."""
    global _briefing_terakhir
    _briefing_terakhir = None
    logger.info("Status briefing direset")


if __name__ == "__main__":
    # python -m src.utils.session_state
    print("Awal run  :", sudah_briefing_hari_ini())
    tandai_briefing_selesai()
    print("Sesudah   :", sudah_briefing_hari_ini())
    reset_briefing()
    print("Direset   :", sudah_briefing_hari_ini())

"""
Saluran pemicu: membangunkan AKIRA tanpa mengucapkan wake word.
Tanggung jawab: Person 1 (Integrator) — Sprint 4.1

Kenapa modul terpisah, bukan langsung di app.py atau di gui/:
`app.py` tidak boleh mengimpor apa pun dari `gui/`. Kalau ia melakukannya,
menjalankan AKIRA lewat terminal akan ikut memuat Tkinter — dan di mesin
tanpa tampilan grafis, itu gagal total.

Modul ini netral: `gui/` mengisi pemicu, `app.py` memeriksanya. Keduanya
tidak saling mengimpor.
"""
import threading
import time
from dataclasses import dataclass, field

from loguru import logger

# Diset antarmuka, dibaca loop wake word di app.py
_pemicu = threading.Event()
_antrean_perintah: list = []
_kunci = threading.Lock()

# Klik ganda tak sengaja, atau pintasan yang tertekan dua kali, akan
# menumpuk dua pemicu identik — AKIRA lalu menjalankan perintah yang sama
# dua kali berturut-turut. Pemicu yang sama dalam jeda ini diabaikan.
JEDA_DUPLIKAT_DETIK = 2.0

# Pemicu yang tertahan lebih lama dari ini dibuang. Kalau AKIRA sibuk dan
# user menekan beberapa tombol karena mengira tidak berfungsi, menjalankan
# semuanya sekaligus setelah sesi selesai justru membingungkan — bukan itu
# yang dia maksud saat menekannya.
UMUR_MAKS_DETIK = 25.0
_terakhir: tuple = ("", 0.0)


def _duplikat(kunci: str) -> bool:
    """True kalau pemicu yang sama baru saja masuk."""
    global _terakhir
    sekarang = time.time()
    kunci_lama, waktu_lama = _terakhir
    if kunci == kunci_lama and (sekarang - waktu_lama) < JEDA_DUPLIKAT_DETIK:
        return True
    _terakhir = (kunci, sekarang)
    return False


@dataclass
class Pemicu:
    """Satu permintaan dari antarmuka ke mesin AKIRA."""

    jenis: str = "dengar"          # "dengar" | "perintah"
    perintah: str = ""             # diisi kalau jenis == "perintah"
    sumber: str = "antarmuka"      # untuk log: antarmuka / pintasan
    dibuat: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)


def picu_dengar(sumber: str = "antarmuka"):
    """
    Minta AKIRA langsung mendengarkan, melewati wake word.

    Dipakai tombol dan pintasan keyboard. Berguna saat wake word tidak
    terdeteksi karena ruangan bising — jalur cadangan yang tidak bergantung
    pada pengenalan suara sama sekali.
    """
    if _duplikat("dengar"):
        logger.debug("Pemicu 'dengar' ganda diabaikan")
        return
    with _kunci:
        _antrean_perintah.append(Pemicu(jenis="dengar", sumber=sumber))
    _pemicu.set()
    logger.info(f"Pemicu 'dengar' dari {sumber}")


def picu_perintah(teks: str, sumber: str = "antarmuka"):
    """
    Titipkan perintah berupa teks untuk dijalankan AKIRA lewat alur penuh.

    Beda dengan jalur ketik di tab Perintah yang mengeksekusi langsung:
    ini masuk ke sesi percakapan normal, sehingga slot filling dan
    konfirmasi lisan tetap berjalan seperti biasa.
    """
    teks = (teks or "").strip()
    if not teks:
        return
    if _duplikat(f"perintah:{teks}"):
        logger.debug(f"Pemicu ganda diabaikan: '{teks}'")
        return
    with _kunci:
        _antrean_perintah.append(Pemicu(jenis="perintah", perintah=teks, sumber=sumber))
    _pemicu.set()
    logger.info(f"Pemicu 'perintah' dari {sumber}: '{teks}'")


def ada_pemicu() -> bool:
    """Cek tanpa mengambil. Dipanggil loop wake word tiap siklus."""
    return _pemicu.is_set()


def ambil() -> Pemicu | None:
    """
    Ambil satu pemicu dari antrean. Return None kalau kosong.

    Pemicu yang sudah kedaluwarsa dibuang tanpa dijalankan.
    """
    sekarang = time.time()
    with _kunci:
        while _antrean_perintah:
            item = _antrean_perintah.pop(0)
            if sekarang - item.dibuat > UMUR_MAKS_DETIK:
                logger.info(
                    f"Pemicu kedaluwarsa dibuang: "
                    f"{item.perintah or item.jenis} "
                    f"({sekarang - item.dibuat:.0f} detik lalu)"
                )
                continue
            if not _antrean_perintah:
                _pemicu.clear()
            return item

        _pemicu.clear()
        return None


def bersihkan():
    """Kosongkan antrean. Dipakai saat sesi selesai agar tidak menumpuk."""
    global _terakhir
    with _kunci:
        _antrean_perintah.clear()
        _pemicu.clear()
    _terakhir = ("", 0.0)

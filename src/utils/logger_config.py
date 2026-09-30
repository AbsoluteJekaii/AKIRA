"""
Setup logging terpusat untuk AKIRA — semua modul pakai `from loguru import logger` langsung,
file ini cuma konfigurasi tujuan output log (terminal + file).
"""
import sys

from loguru import logger

# Handler yang dipasang modul ini. Hanya ini yang boleh dilepas ulang.
_handler_milik_sendiri: list = []
_default_sudah_dilepas = False


def setup_logger(log_path: str = "logs/akira.log"):
    """
    Pasang tujuan log terminal dan berkas.

    JANGAN memakai `logger.remove()` tanpa argumen di sini. Di loguru, itu
    melepas SEMUA handler — termasuk saluran ke antarmuka grafis yang
    dipasang sebelum AKIRA dijalankan. Akibatnya panel Log di aplikasi
    kosong total begitu AKIRA menyala: bukan rusak, tapi terputus tepat saat
    mulai. Yang dilepas hanya handler bawaan loguru dan milik modul ini.
    """
    global _default_sudah_dilepas

    if not _default_sudah_dilepas:
        try:
            logger.remove(0)        # handler bawaan loguru (stderr)
        except ValueError:
            pass                    # sudah dilepas sebelumnya
        _default_sudah_dilepas = True

    while _handler_milik_sendiri:
        try:
            logger.remove(_handler_milik_sendiri.pop())
        except ValueError:
            pass

    # Tanpa konsol (dijalankan lewat pythonw), sys.stdout bernilai None dan
    # logger.add(None) langsung gagal saat start.
    if sys.stdout is not None:
        _handler_milik_sendiri.append(logger.add(
            sys.stdout, level="INFO",
            format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}",
        ))
    _handler_milik_sendiri.append(logger.add(
        log_path, level="DEBUG", rotation="5 MB", retention="7 days",
    ))
    return logger

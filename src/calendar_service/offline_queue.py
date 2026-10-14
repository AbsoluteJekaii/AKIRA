"""
Antrean offline: jadwal baru yang gagal dikirim karena internet putus.

Masalah yang diselesaikan:
Bagian pendengaran dan pemahaman AKIRA bisa jalan tanpa internet (Whisper
lokal, Qwen lokal, Piper), tapi Google Calendar tidak. Dulu, jadwal yang
diucapkan saat offline langsung hilang: AKIRA minta maaf dan user harus
mengulang semuanya nanti.

Sekarang:
1. Kalau pembuatan event gagal KARENA JARINGAN, jadwalnya disimpan ke
   config/pending_events.json (lokal, tidak ikut ke GitHub).
2. Loop reminder (yang sudah jalan tiap beberapa detik) mencoba mengirim
   isi antrean. Begitu internet kembali, jadwal masuk ke kalender dan AKIRA
   memberi tahu lewat suara.

Cakupan sengaja dibatasi pada MEMBUAT jadwal. Hapus/pindah/ubah butuh ID
event dari Google, yang tidak bisa diketahui saat offline.

Anti-duplikat: tiap jadwal di antrean diberi ID sendiri yang dikirim sebagai
ID event ke Google. Kalau pengiriman sebenarnya sudah sampai tapi balasannya
hilang, percobaan berikutnya ditolak Google dengan 409 (ID sudah ada), dan
itu dihitung berhasil, bukan dibuat dua kali.
"""
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

ANTREAN_PATH = "config/pending_events.json"

_lock = threading.Lock()

# Nama kelas galat yang berarti "tidak bisa menjangkau server". Dicek lewat
# nama supaya modul ini tidak wajib mengimpor httplib2 / google.auth.
_NAMA_GALAT_JARINGAN = {
    "ServerNotFoundError",      # httplib2: DNS gagal, internet putus
    "TransportError",           # google.auth: refresh token gagal karena jaringan
    "NewConnectionError",
    "MaxRetryError",
    "ConnectTimeout",
    "ReadTimeout",
    "Timeout",
    "RelatedServerNotFound",
}

# OSError yang BUKAN masalah jaringan (file hilang, izin ditolak).
_OSERROR_BUKAN_JARINGAN = (FileNotFoundError, PermissionError, IsADirectoryError,
                           NotADirectoryError, FileExistsError)


def _status_http(e) -> int | None:
    resp = getattr(e, "resp", None)
    status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def galat_jaringan(e: BaseException) -> bool:
    """
    True kalau galat ini berarti server tidak terjangkau (layak diantrekan).

    Galat lain (token dicabut, data tidak valid) TIDAK diantrekan: mengirim
    ulang tidak akan pernah berhasil, dan user perlu tahu sekarang.
    """
    dilihat = set()
    while e is not None and id(e) not in dilihat:
        dilihat.add(id(e))

        if type(e).__name__ in _NAMA_GALAT_JARINGAN:
            return True
        if isinstance(e, OSError) and not isinstance(e, _OSERROR_BUKAN_JARINGAN):
            # ConnectionError, TimeoutError, socket.gaierror, dst.
            return True

        status = _status_http(e)
        if status is not None and 500 <= status <= 599:
            return True      # server Google sedang bermasalah, coba lagi nanti

        e = e.__cause__ or e.__context__
    return False


def _path() -> Path:
    return Path(ANTREAN_PATH)


def _baca() -> list:
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        # File rusak jangan sampai menghentikan AKIRA. Simpan salinannya supaya
        # isinya tidak hilang, lalu mulai antrean baru.
        cadangan = path.with_suffix(".rusak.json")
        try:
            os.replace(path, cadangan)
        except OSError:
            pass
        logger.error(f"Antrean offline tidak terbaca ({e}), dipindah ke {cadangan}")
        return []


def _tulis(items: list):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sementara = path.with_suffix(".tmp")
    sementara.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(sementara, path)       # atomik: tidak ada file setengah jadi


def simpan(summary: str, start_datetime: str, end_datetime: str,
           description: str = None) -> dict:
    """Masukkan satu jadwal ke antrean. Return item yang disimpan."""
    item = {
        # Hex huruf kecil termasuk alfabet base32hex yang diterima Google
        # sebagai ID event (a-v, 0-9, panjang 5-1024).
        "id": uuid.uuid4().hex,
        "summary": summary,
        "start": start_datetime,
        "end": end_datetime,
        "description": description,
        "dibuat": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        items = _baca()
        items.append(item)
        _tulis(items)
    logger.warning(f"Offline: '{summary}' ({start_datetime}) disimpan ke antrean, "
                   f"total {len(items)} menunggu")
    return item


def daftar() -> list:
    with _lock:
        return list(_baca())


def jumlah() -> int:
    return len(daftar())


def sebagai_event(item: dict) -> dict:
    """Bentuk mirip event Google, supaya konteks percakapan tetap bisa merujuknya."""
    return {
        "id": item["id"],
        "summary": item["summary"],
        "description": item.get("description"),
        "start": {"dateTime": item["start"]},
        "end": {"dateTime": item["end"]},
        "_offline": True,
    }


def _hapus(item_id: str):
    with _lock:
        items = [i for i in _baca() if i.get("id") != item_id]
        _tulis(items)


def sinkronkan(create_fn=None) -> tuple[list, bool]:
    """
    Kirim isi antrean ke Google Calendar.

    Return (berhasil, masih_offline):
        berhasil      daftar item yang sudah masuk kalender
        masih_offline True kalau berhenti karena jaringan masih putus

    Berhenti di galat jaringan pertama: kalau satu gagal karena offline,
    sisanya pasti gagal juga, jadi tidak perlu dicoba.
    """
    if create_fn is None:
        from src.calendar_service.crud import create_event as create_fn

    berhasil = []
    for item in daftar():
        try:
            try:
                create_fn(item["summary"], item["start"], item["end"],
                          description=item.get("description"), event_id=item["id"])
            except Exception as e:
                status = _status_http(e)
                if status == 409:
                    # ID sudah ada di kalender: kiriman sebelumnya ternyata sampai.
                    logger.info(f"'{item['summary']}' ternyata sudah ada di kalender")
                elif status == 400:
                    # Jaring pengaman: kalau Google menolak ID buatan kita,
                    # kirim tanpa ID daripada antrean macet selamanya.
                    logger.warning(f"ID antrean ditolak Google, kirim ulang tanpa ID: {e}")
                    create_fn(item["summary"], item["start"], item["end"],
                              description=item.get("description"))
                else:
                    raise
        except Exception as e:
            if galat_jaringan(e):
                logger.debug(f"Sinkronisasi ditunda, masih offline: {e}")
                return berhasil, True
            # Galat permanen untuk item ini: jangan menghalangi item lain.
            logger.error(f"Jadwal antrean '{item.get('summary')}' gagal dikirim "
                         f"dan dilewati: {e}")
            continue

        _hapus(item["id"])
        berhasil.append(item)
        logger.info(f"Sinkron: '{item['summary']}' masuk ke Google Calendar")

    return berhasil, False


def ucapkan_hasil_sinkron(berhasil: list) -> str:
    """Kalimat yang diucapkan AKIRA setelah antrean terkirim."""
    if not berhasil:
        return ""
    if len(berhasil) == 1:
        return (f"Internet sudah tersambung lagi, Bos. Jadwal {berhasil[0]['summary']} "
                f"yang tadi saya simpan sudah masuk ke kalender.")
    nama = ", ".join(i["summary"] for i in berhasil[:3])
    sisa = f", dan {len(berhasil) - 3} lainnya" if len(berhasil) > 3 else ""
    return (f"Internet sudah tersambung lagi, Bos. {len(berhasil)} jadwal yang tertunda "
            f"sudah masuk ke kalender: {nama}{sisa}.")

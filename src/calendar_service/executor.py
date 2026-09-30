"""
Jembatan antara skema JSON hasil NLP dan operasi Google Calendar.
Tanggung jawab: Person 1 (Calendar & Backend Integration Lead) — Sprint 3

State machine memanggil execute() dari sini, tidak perlu tahu detail API Google.
Semua konversi format (YYYY-MM-DD + HH:MM -> ISO datetime) terjadi di sini.

Baru di Sprint 3:
- _handle_baca() paham RENTANG tanggal ("tahun 2026", "seminggu ke depan"),
  bukan cuma satu tanggal.
- _handle_waktu() menjawab "sekarang jam berapa" tanpa menyentuh API Google.
- get_briefing(days) menyusun ringkasan beberapa hari ke depan, dipakai
  saat AKIRA baru dinyalakan.
"""
import re
from datetime import datetime, timedelta

from loguru import logger

from src.nlp.date_time_parser import BULAN_NAMA, HARI_NAMA, ucapkan_tanggal

DEFAULT_DURATION_MINUTES = 60
TIMEZONE = "Asia/Jakarta"   # samakan dengan crud.TIMEZONE & config calendar.timezone
MAX_EVENTS_DIBACAKAN = 8  # batas supaya AKIRA tidak membacakan 50 event sekaligus


def to_iso_datetime(tanggal: str, jam: str) -> str:
    """Gabungkan '2026-09-10' + '15:00' jadi '2026-09-10T15:00:00'."""
    return f"{tanggal}T{jam}:00"


def compute_end_time(tanggal: str, jam: str, duration_minutes: int = DEFAULT_DURATION_MINUTES) -> str:
    """Hitung waktu selesai (default +1 jam, karena user jarang menyebut jam selesai lewat suara)."""
    start = datetime.strptime(f"{tanggal} {jam}", "%Y-%m-%d %H:%M")
    end = start + timedelta(minutes=duration_minutes)
    return end.strftime("%Y-%m-%dT%H:%M:%S")


def execute(data: dict) -> dict:
    """
    Eksekusi aksi sesuai skema JSON.
    Return dict: {"success": bool, "message": str (untuk diucapkan TTS), "data": ...}
    """
    aksi = data.get("aksi")
    logger.info(f"Eksekusi aksi '{aksi}' dengan data: {data}")

    try:
        if aksi == "catat":
            return _handle_catat(data)
        if aksi == "baca":
            return _handle_baca(data)
        if aksi == "hapus":
            return _handle_hapus(data)
        if aksi == "reschedule":
            return _handle_reschedule(data)
        if aksi == "waktu":
            return _handle_waktu(data)
        if aksi == "reminder":
            return _handle_reminder(data)

        return {"success": False, "message": "Maaf Bos, saya tidak mengerti perintahnya."}

    except Exception as e:
        logger.error(f"Gagal eksekusi aksi '{aksi}': {e}")
        return {"success": False, "message": f"Maaf Bos, ada kendala saat memproses: {e}"}


# ----------------------------------------------------------------- helpers
def _event_date_str(event: dict) -> str:
    """Tanggal event dalam YYYY-MM-DD (menangani event berjam maupun seharian)."""
    start = event.get("start", {})
    raw = start.get("dateTime") or start.get("date", "")
    return raw[:10]


def _event_time_str(event: dict) -> str | None:
    """Jam event (HH:MM), None kalau event seharian penuh."""
    dt = event.get("start", {}).get("dateTime")
    return dt[11:16] if dt else None


def _ucapkan_tanggal(tanggal: str, sebut_tahun: bool = True) -> str:
    """
    '2026-11-17' -> '17 November 2026'.

    Tahun sekarang DISEBUT secara default. Tanpa tahun, kalimat seperti
    "tidak ada jadwal pada 31 Agustus" ambigu — user tidak bisa tahu apakah
    AKIRA salah menangkap tahunnya (masalah yang berulang di beberapa demo).
    """
    return ucapkan_tanggal(tanggal, sebut_tahun=sebut_tahun)


def _sebut_jadwal(judul: str) -> str:
    """
    Rakit frasa "jadwal X" tanpa kata ganda.
    Event berjudul "Jadwal tanpa nama" dulu diucapkan "Jadwal Jadwal tanpa nama".
    """
    judul = (judul or "tanpa nama").strip()
    if judul.lower().startswith("jadwal"):
        return judul
    return f"jadwal {judul}"


def _ringkas_event(event: dict, sebut_tanggal: bool = True, sebut_tahun: bool = False) -> str:
    """Susun satu baris deskripsi event untuk dibacakan TTS."""
    judul = event.get("summary", "jadwal tanpa nama")
    jam = _event_time_str(event)

    if sebut_tanggal:
        bagian_tanggal = _ucapkan_tanggal(_event_date_str(event), sebut_tahun=True)
        return f"{judul} pada {bagian_tanggal}" + (f" jam {jam}" if jam else "")
    return f"{judul}" + (f" jam {jam}" if jam else " sepanjang hari")


def _batas_hari(tanggal: str, akhir_hari: bool = False) -> str:
    """
    Ubah 'YYYY-MM-DD' jadi batas waktu ISO menurut zona waktu LOKAL.

    Ini bug halus yang belum sempat terlihat karena kalender masih kosong:
    versi sebelumnya memakai akhiran 'Z' (UTC). Karena Jakarta UTC+7, rentang
    "29 Agustus 00:00Z - 23:59Z" sebenarnya berarti
    "29 Agustus jam 07:00 sampai 30 Agustus jam 06:59" waktu Jakarta.
    Akibatnya jadwal pagi sebelum jam 7 tidak akan pernah terbaca, dan jadwal
    dini hari besok ikut terbawa.
    """
    jam = "23:59:59" if akhir_hari else "00:00:00"
    waktu = datetime.strptime(f"{tanggal} {jam}", "%Y-%m-%d %H:%M:%S")
    try:
        from zoneinfo import ZoneInfo

        waktu = waktu.replace(tzinfo=ZoneInfo(TIMEZONE))
    except Exception:
        # Kalau data zona waktu tidak tersedia, pakai offset zona waktu sistem
        waktu = waktu.astimezone()
    return waktu.isoformat()


def _ambil_event_rentang(mulai: str, akhir: str, max_results: int = 100) -> list:
    """
    Ambil event dalam rentang tanggal langsung lewat parameter API
    (timeMin/timeMax), bukan menyaring manual di Python.
    Ini penting untuk permintaan sepanjang tahun — menyaring 100 event
    terdekat saja tidak akan mencakup Desember.
    """
    from src.calendar_service.crud import read_events

    return read_events(
        max_results=max_results,
        time_min=_batas_hari(mulai),
        time_max=_batas_hari(akhir, akhir_hari=True),
    )


# ------------------------------------------------------------------ aksi
def _handle_catat(data: dict) -> dict:
    from src.calendar_service.crud import create_event

    kegiatan = data.get("kegiatan") or "Jadwal tanpa nama"
    start = to_iso_datetime(data["tanggal"], data["jam"])

    # Kalau user menyebut jam selesai, pakai itu. Kalau tidak, tetap +1 jam.
    if data.get("jam_selesai"):
        end = to_iso_datetime(data["tanggal"], data["jam_selesai"])
        if end <= start:  # "jam 23 sampai jam 1" -> selesai di hari berikutnya
            end = compute_end_time(data["tanggal"], data["jam"])
            logger.warning("Jam selesai lebih awal dari jam mulai, dikembalikan ke default +1 jam")
    else:
        end = compute_end_time(data["tanggal"], data["jam"])

    event = create_event(kegiatan, start, end, description=data.get("deskripsi"))

    pesan = (
        f"Sudah saya catat, Bos. {kegiatan} pada "
        f"{_ucapkan_tanggal(data['tanggal'], True)} jam {data['jam']}"
    )
    if data.get("jam_selesai"):
        pesan += f" sampai {data['jam_selesai']}"
    return {"success": True, "message": pesan + ".", "data": event}


def _sebutan(data: dict) -> str:
    """Kata yang dipakai user ('kegiatan'/'acara'/'agenda'), supaya balasan nyambung."""
    from src.nlp.text_normalizer import deteksi_sebutan

    return deteksi_sebutan(data.get("teks_asli", ""))


def _handle_baca(data: dict) -> dict:
    """
    Baca jadwal, tiga mode:
    1. Rentang ("tahun 2026", "seminggu ke depan") -> ambil seluruh rentang
    2. Satu tanggal -> hanya hari itu
    3. Tanpa keduanya -> beberapa jadwal terdekat
    """
    from src.calendar_service.crud import read_events

    mulai = data.get("tanggal_mulai")
    akhir = data.get("tanggal_akhir")
    tanggal = data.get("tanggal")
    sebutan = _sebutan(data)

    # --- Mode 1: rentang
    if mulai and akhir:
        label = data.get("label_rentang") or f"{_ucapkan_tanggal(mulai)} sampai {_ucapkan_tanggal(akhir)}"
        events = _ambil_event_rentang(mulai, akhir)
        if not events:
            return {"success": True, "message": f"Tidak ada {sebutan} pada {label}, Bos.", "data": []}

        total = len(events)
        dipakai = events[:MAX_EVENTS_DIBACAKAN]
        lintas_tahun = mulai[:4] != akhir[:4] or label.startswith("tahun")
        lines = [_ringkas_event(e, sebut_tanggal=True, sebut_tahun=lintas_tahun) for e in dipakai]

        message = f"Pada {label} ada {total} {sebutan}, Bos. " + ". ".join(lines) + "."
        if total > len(dipakai):
            message += f" Dan {total - len(dipakai)} {sebutan} lainnya."
        return {"success": True, "message": message, "data": events}

    # --- Mode 2: satu tanggal
    if tanggal:
        events = _ambil_event_rentang(tanggal, tanggal)
        events = [e for e in events if _event_date_str(e) == tanggal]
        if not events:
            return {
                "success": True,
                "message": f"Tidak ada {sebutan} pada {_ucapkan_tanggal(tanggal)}, Bos.",
                "data": [],
            }
        lines = [_ringkas_event(e, sebut_tanggal=False) for e in events[:MAX_EVENTS_DIBACAKAN]]
        message = (
            f"Pada {ucapkan_tanggal(tanggal, sebut_hari=True)} ada {len(events)} {sebutan}, Bos. "
            + ". ".join(lines) + "."
        )
        return {"success": True, "message": message, "data": events}

    # --- Mode 3: jadwal terdekat
    events = read_events(max_results=3)
    if not events:
        return {"success": True, "message": f"Tidak ada {sebutan} yang akan datang, Bos.", "data": []}

    lines = [_ringkas_event(e, sebut_tanggal=True) for e in events]
    message = f"Ada {len(events)} {sebutan} terdekat, Bos. " + ". ".join(lines) + "."
    return {"success": True, "message": message, "data": events}


def _handle_waktu(data: dict) -> dict:
    """
    Jawab pertanyaan waktu ("sekarang jam berapa", "tanggal berapa hari ini").
    Tidak menyentuh API Google sama sekali — jawabannya instan.
    """
    from src.nlp.date_time_parser import parse_date_id

    now = datetime.now()
    teks_asli = (data.get("teks_asli") or "").lower()

    # "617 hari lagi itu hari apa?" — yang ditanya BUKAN hari ini, tapi tanggal
    # hasil hitungan. Dulu selalu dijawab tanggal hari ini.
    if re.search(r"\b\d{1,4}\s+(?:hari|minggu|bulan)\s+(?:lagi|ke depan|kedepan|kemudian|mendatang|dari sekarang|dari hari ini|dari saat ini|setelah hari ini)\b", teks_asli):
        target = parse_date_id(teks_asli, now)
        if target:
            return {
                "success": True,
                "message": (
                    f"Bos, itu jatuh pada hari {HARI_NAMA[target.weekday()]}, "
                    f"tanggal {target.day} {BULAN_NAMA[target.month - 1]} {target.year}."
                ),
                "data": {"tanggal": target.strftime("%Y-%m-%d")},
            }

    # "15 menit lagi jam berapa", "2 jam lagi pukul berapa"
    m = re.search(r"\b(\d{1,3})\s+(menit|jam)\s+(?:lagi|dari sekarang|kemudian|ke depan)\b", teks_asli)
    if m and re.search(r"\b(?:jam|pukul)\s+berapa\b", teks_asli):
        jumlah = int(m.group(1))
        target = now + (timedelta(minutes=jumlah) if m.group(2) == "menit" else timedelta(hours=jumlah))
        beda_hari = target.date() != now.date()
        keterangan = f", {HARI_NAMA[target.weekday()]}" if beda_hari else ""
        return {
            "success": True,
            "message": f"Bos, {jumlah} {m.group(2)} lagi itu jam {target:%H:%M}{keterangan}.",
            "data": {"waktu": target.isoformat()},
        }

    tanya_jam = "jam berapa" in teks_asli or "pukul berapa" in teks_asli
    tanya_tanggal = any(k in teks_asli for k in ("tanggal berapa", "hari apa", "bulan apa", "tahun berapa"))

    bagian = []
    if tanya_jam or not tanya_tanggal:
        # Format HH:MM supaya diucapkan lewat konversi yang sama dengan
        # semua jam lain: "jam 18:19" -> "jam 6 lewat 19 malam"
        bagian.append(f"sekarang jam {now:%H:%M}")
    if tanya_tanggal or not tanya_jam:
        bagian.append(
            f"hari {HARI_NAMA[now.weekday()]}, tanggal {now.day} {BULAN_NAMA[now.month - 1]} {now.year}"
        )

    message = "Bos, " + " dan ".join(bagian) + "."
    return {"success": True, "message": message, "data": {"waktu": now.isoformat()}}


def cari_bentrok(tanggal: str, jam: str, jam_selesai: str = None,
                 durasi_menit: int = DEFAULT_DURATION_MINUTES) -> list:
    """
    Cari event yang waktunya bertabrakan dengan jadwal baru.

    Dua acara dianggap bentrok kalau rentang waktunya beririsan — bukan hanya
    kalau jam mulainya sama persis. Rapat 09:00-10:00 dan 09:30-10:30 tetap
    bentrok meski jam mulainya berbeda.

    Event seharian penuh (tanpa jam) diabaikan: ulang tahun dan hari libur
    tidak menghalangi apa pun.
    """
    if not tanggal or not jam:
        return []

    mulai_baru = datetime.strptime(f"{tanggal} {jam}", "%Y-%m-%d %H:%M")
    if jam_selesai:
        selesai_baru = datetime.strptime(f"{tanggal} {jam_selesai}", "%Y-%m-%d %H:%M")
        if selesai_baru <= mulai_baru:
            selesai_baru = mulai_baru + timedelta(minutes=durasi_menit)
    else:
        selesai_baru = mulai_baru + timedelta(minutes=durasi_menit)

    try:
        events = _ambil_event_rentang(tanggal, tanggal)
    except Exception as e:
        logger.error(f"Gagal cek bentrok: {e}")
        return []

    bentrok = []
    for e in events:
        if _event_date_str(e) != tanggal:
            continue
        jam_e = _event_time_str(e)
        if not jam_e:
            continue      # event seharian, bukan bentrok

        mulai_e = datetime.strptime(f"{tanggal} {jam_e}", "%Y-%m-%d %H:%M")
        akhir_raw = (e.get("end") or {}).get("dateTime")
        try:
            selesai_e = (
                datetime.strptime(akhir_raw[:16], "%Y-%m-%dT%H:%M")
                if akhir_raw else mulai_e + timedelta(minutes=durasi_menit)
            )
        except ValueError:
            selesai_e = mulai_e + timedelta(minutes=durasi_menit)

        # Beririsan kalau salah satu mulai sebelum yang lain selesai
        if mulai_baru < selesai_e and mulai_e < selesai_baru:
            bentrok.append(e)

    if bentrok:
        judul = [b.get("summary", "?") for b in bentrok]
        logger.info(f"Bentrok pada {tanggal} jam {jam}: {judul}")
    return bentrok


def ucapkan_bentrok(bentrok: list, tanggal: str) -> str:
    """Kalimat peringatan bentrok untuk dibacakan sebelum konfirmasi."""
    if len(bentrok) == 1:
        e = bentrok[0]
        return (
            f"Bos, pada {_ucapkan_tanggal(tanggal)} sudah ada "
            f"{e.get('summary', 'jadwal lain')} jam {_event_time_str(e)}."
        )
    daftar = ", ".join(
        f"{e.get('summary', 'jadwal')} jam {_event_time_str(e)}" for e in bentrok[:3]
    )
    return f"Bos, pada {_ucapkan_tanggal(tanggal)} sudah ada {len(bentrok)} jadwal: {daftar}."


def cari_kandidat(data: dict) -> list:
    """
    Cari event yang cocok untuk aksi hapus / reschedule.

    Tiga cara mencari, digabung:
    1. Nama kegiatan (kalau disebut) -> pencarian kata kunci di judul
    2. Tanggal (kalau disebut)       -> semua event di tanggal itu
    3. Kalau keduanya disebut, hasilnya diiris — hanya event yang cocok DUA-DUANYA

    Ini yang memungkinkan "hapus jadwal saya tanggal 30" tanpa menyebut nama:
    dulu perintah itu ditolak karena nama kegiatan wajib.

    PENTING untuk reschedule: field 'tanggal' berisi tanggal TUJUAN, bukan
    tanggal jadwal yang dicari. Menyaring kandidat dengan tanggal tujuan selalu
    menghasilkan nol — persis bug "Saya tidak menemukan jadwal meeting" padahal
    meeting-nya ada hari ini dan hendak dipindah ke tanggal 31.
    Untuk reschedule, penyaring tanggal diambil dari 'tanggal_asal'
    (hasil pemisahan asal/tujuan di parser), bukan dari 'tanggal'.
    """
    from src.calendar_service.crud import find_event_by_keyword

    keyword = data.get("kegiatan")
    if data.get("aksi") == "reschedule":
        tanggal = data.get("tanggal_asal")
    else:
        # hapus & reminder: 'tanggal' memang tanggal event yang dicari
        tanggal = data.get("tanggal")

    # Hapus massal: semua jadwal, atau semua dalam rentang tertentu
    if data.get("hapus_semua") or (data.get("tanggal_mulai") and data.get("aksi") == "hapus"):
        mulai = data.get("tanggal_mulai")
        akhir = data.get("tanggal_akhir")

        if mulai and akhir:
            hasil = _ambil_event_rentang(mulai, akhir)
        elif tanggal:
            # "hapus seluruh jadwal MALAM INI" — kata "seluruh" menandakan
            # semua jadwal DI HARI ITU, bukan seluruh isi kalender.
            # Tanpa penjagaan ini, satu kalimat bisa menghapus 32 event.
            logger.info(f"Hapus semua dibatasi pada tanggal {tanggal}")
            hasil = _ambil_event_rentang(tanggal, tanggal)
            hasil = [e for e in hasil if _event_date_str(e) == tanggal]
        else:
            from src.calendar_service.crud import read_events

            hasil = read_events(max_results=100)
        if keyword:
            # "hapus semua rapat minggu depan" — masih disaring namanya
            hasil = [e for e in hasil if keyword.lower() in e.get("summary", "").lower()]
        return hasil

    if keyword and tanggal:
        cocok_nama = find_event_by_keyword(keyword)
        return [e for e in cocok_nama if _event_date_str(e) == tanggal]
    if keyword:
        return find_event_by_keyword(keyword)
    if tanggal:
        return _ambil_event_rentang(tanggal, tanggal)
    return []


def hapus_banyak(events: list) -> dict:
    """
    Hapus beberapa event sekaligus. Kegagalan per event dicatat sendiri —
    satu yang gagal tidak menghentikan sisanya.
    """
    from src.calendar_service.crud import delete_event

    berhasil, gagal = [], []
    for e in events:
        try:
            delete_event(e["id"])
            berhasil.append(e)
        except Exception as err:
            logger.error(f"Gagal menghapus {e.get('summary')}: {err}")
            gagal.append(e)

    pesan = f"{len(berhasil)} jadwal sudah dihapus, Bos."
    if gagal:
        pesan += f" {len(gagal)} gagal dihapus."
    return {"success": bool(berhasil), "message": pesan, "data": berhasil}


def ubah_event(event: dict, perubahan: dict) -> dict:
    """
    Ubah isi satu event: nama, deskripsi, tanggal, dan/atau jam.

    `perubahan` memakai nama field yang sama dengan skema NLP
    (kegiatan, deskripsi, tanggal, jam, jam_selesai), jadi hasil
    correction.parse_koreksi() bisa langsung dipakai tanpa penerjemahan.
    """
    from src.calendar_service.crud import update_event

    body = {}
    if perubahan.get("kegiatan"):
        body["summary"] = perubahan["kegiatan"]
    if perubahan.get("deskripsi"):
        body["description"] = perubahan["deskripsi"]

    tanggal = perubahan.get("tanggal") or _event_date_str(event)
    jam = perubahan.get("jam") or _event_time_str(event) or "09:00"

    if perubahan.get("tanggal") or perubahan.get("jam") or perubahan.get("jam_selesai"):
        mulai = to_iso_datetime(tanggal, jam)
        if perubahan.get("jam_selesai"):
            selesai = to_iso_datetime(tanggal, perubahan["jam_selesai"])
            if selesai <= mulai:
                selesai = compute_end_time(tanggal, jam)
        else:
            selesai = compute_end_time(tanggal, jam)
        body["start"] = {"dateTime": mulai, "timeZone": TIMEZONE}
        body["end"] = {"dateTime": selesai, "timeZone": TIMEZONE}

    if not body:
        return {"success": False, "message": "Tidak ada yang diubah, Bos."}

    updated = update_event(event["id"], body)
    nama = body.get("summary") or event.get("summary", "jadwal")
    return {
        "success": True,
        "message": f"{_sebut_jadwal(nama).capitalize()} sudah diperbarui, Bos.",
        "data": updated,
    }


def deskripsi_kandidat(event: dict) -> str:
    """Kalimat pendek untuk membacakan pilihan ke user."""
    return _ringkas_event(event, sebut_tanggal=True)


def hapus_event(event: dict) -> dict:
    """Hapus satu event yang SUDAH dipilih & dikonfirmasi user."""
    from src.calendar_service.crud import delete_event

    delete_event(event["id"])
    return {
        "success": True,
        "message": f"{_sebut_jadwal(event.get('summary')).capitalize()} sudah dihapus, Bos.",
        "data": event,
    }


def atur_pengingat(event: dict, menit: int) -> dict:
    """Pasang pengingat pada event yang SUDAH dipilih & dikonfirmasi user."""
    from src.calendar_service.crud import set_event_reminder
    from src.nlp.date_time_parser import ucapkan_lead_time

    updated = set_event_reminder(event["id"], menit)
    return {
        "success": True,
        "message": (
            f"Siap Bos. Saya akan mengingatkan {ucapkan_lead_time(menit)} sebelum "
            f"{event.get('summary', 'acara')} dimulai."
        ),
        "data": updated,
    }


def _handle_reminder(data: dict) -> dict:
    """
    Dipanggil hanya kalau app.py tidak sempat menjalankan alur pemilihan
    kandidat (mis. dari test). Alur normal lewat _proses_aksi_berisiko().
    """
    kandidat = cari_kandidat(data)
    if not kandidat:
        return {"success": False, "message": "Saya tidak menemukan jadwalnya, Bos."}
    if len(kandidat) > 1:
        return {
            "success": False,
            "message": f"Ada {len(kandidat)} jadwal yang cocok, Bos. Sebutkan lebih spesifik.",
            "data": kandidat,
        }
    return atur_pengingat(kandidat[0], data.get("lead_menit") or 15)


def pindah_event(event: dict, tanggal: str, jam: str = None) -> dict:
    """Pindahkan satu event yang SUDAH dipilih & dikonfirmasi user."""
    from src.calendar_service.crud import reschedule_event

    jam = jam or _event_time_str(event) or "09:00"
    updated = reschedule_event(
        event["id"], to_iso_datetime(tanggal, jam), compute_end_time(tanggal, jam)
    )
    return {
        "success": True,
        "message": (
            f"{_sebut_jadwal(event.get('summary')).capitalize()} sudah dipindah ke "
            f"{_ucapkan_tanggal(tanggal)} jam {jam}, Bos."
        ),
        "data": updated,
    }


def _handle_hapus(data: dict) -> dict:
    from src.calendar_service.crud import delete_event, find_event_by_keyword

    keyword = data.get("kegiatan")
    if not keyword:
        return {"success": False, "message": "Jadwal mana yang mau dihapus, Bos? Sebutkan nama kegiatannya."}

    matches = find_event_by_keyword(keyword)
    if not matches:
        return {"success": False, "message": f"Saya tidak menemukan jadwal '{keyword}', Bos."}
    if len(matches) > 1:
        judul_list = ", ".join(e.get("summary", "") for e in matches[:3])
        return {
            "success": False,
            "message": f"Ada {len(matches)} jadwal yang cocok: {judul_list}. Tolong sebutkan lebih spesifik, Bos.",
            "data": matches,
        }

    event = matches[0]
    delete_event(event["id"])
    return {
        "success": True,
        "message": f"{_sebut_jadwal(event.get('summary')).capitalize()} sudah dihapus, Bos.",
        "data": event,
    }


def _handle_reschedule(data: dict) -> dict:
    from src.calendar_service.crud import find_event_by_keyword, reschedule_event

    keyword = data.get("kegiatan")
    if not keyword:
        return {"success": False, "message": "Jadwal mana yang mau dipindah, Bos? Sebutkan nama kegiatannya."}

    matches = find_event_by_keyword(keyword)
    if not matches:
        return {"success": False, "message": f"Saya tidak menemukan jadwal '{keyword}', Bos."}
    if len(matches) > 1:
        judul_list = ", ".join(e.get("summary", "") for e in matches[:3])
        return {
            "success": False,
            "message": f"Ada {len(matches)} jadwal yang cocok: {judul_list}. Tolong sebutkan lebih spesifik, Bos.",
            "data": matches,
        }

    event = matches[0]

    # Kalau user tidak menyebut jam baru, pertahankan jam aslinya.
    jam = data.get("jam") or _event_time_str(event) or "09:00"
    if not data.get("jam"):
        logger.info(f"Jam tidak disebut, memakai jam asli event: {jam}")

    new_start = to_iso_datetime(data["tanggal"], jam)
    new_end = compute_end_time(data["tanggal"], jam)
    updated = reschedule_event(event["id"], new_start, new_end)
    return {
        "success": True,
        "message": (
            f"{_sebut_jadwal(event.get('summary')).capitalize()} sudah dipindah ke "
            f"{_ucapkan_tanggal(data['tanggal'])} jam {jam}, Bos."
        ),
        "data": updated,
    }


# --------------------------------------------------------------- briefing
def get_briefing(days: int = 7, max_events: int = MAX_EVENTS_DIBACAKAN) -> str:
    """
    Ringkasan jadwal `days` hari ke depan, untuk diucapkan saat AKIRA dinyalakan
    atau setelah sapaan.

    Beda dengan Sprint 2: SELALU mengembalikan kalimat, tidak pernah None.
    Kalau kosong pun AKIRA tetap melapor ("agenda Anda kosong") — user jadi tahu
    sistemnya hidup dan sudah mengecek, bukan diam karena error.
    """
    now = datetime.now()
    mulai = now.strftime("%Y-%m-%d")
    akhir = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        events = _ambil_event_rentang(mulai, akhir)
    except Exception as e:
        logger.error(f"Gagal ambil jadwal untuk briefing: {e}")
        return "Maaf Bos, saya belum bisa mengambil data kalender saat ini."

    hari_ini = now.strftime("%Y-%m-%d")
    jam_sekarang = now.strftime("%H:%M")

    # Buang event hari ini yang jamnya sudah lewat
    relevan = []
    for e in events:
        tgl = _event_date_str(e)
        jam = _event_time_str(e)
        if tgl == hari_ini and jam is not None and jam < jam_sekarang:
            continue
        relevan.append(e)

    if not relevan:
        return f"Bos, agenda Anda {days} hari ke depan masih kosong. Tidak ada yang perlu dikhawatirkan."

    jadwal_hari_ini = [e for e in relevan if _event_date_str(e) == hari_ini]
    sisanya = [e for e in relevan if _event_date_str(e) != hari_ini]

    bagian = []
    if jadwal_hari_ini:
        lines = [_ringkas_event(e, sebut_tanggal=False) for e in jadwal_hari_ini[:max_events]]
        bagian.append(f"Hari ini Anda punya {len(jadwal_hari_ini)} jadwal. " + ". ".join(lines) + ".")
    else:
        bagian.append("Hari ini tidak ada jadwal.")

    if sisanya:
        sisa_dipakai = sisanya[: max(0, max_events - len(jadwal_hari_ini))]
        if sisa_dipakai:
            lines = [_ringkas_event(e, sebut_tanggal=True) for e in sisa_dipakai]
            bagian.append(f"Dalam {days} hari ke depan ada {len(sisanya)} jadwal lagi. " + ". ".join(lines) + ".")
        else:
            bagian.append(f"Masih ada {len(sisanya)} jadwal lagi dalam {days} hari ke depan.")

    return "Bos, ini laporan agenda Anda. " + " ".join(bagian)


if __name__ == "__main__":
    # Test konversi waktu & jawaban waktu (tidak menyentuh API Google):
    #   python -m src.calendar_service.executor
    print("to_iso_datetime:", to_iso_datetime("2026-09-10", "15:00"))
    print("compute_end_time:", compute_end_time("2026-09-10", "15:00"))
    print("compute_end_time (lintas jam):", compute_end_time("2026-09-10", "23:30"))
    print("waktu (jam):", _handle_waktu({"teks_asli": "sekarang jam berapa"})["message"])
    print("waktu (tanggal):", _handle_waktu({"teks_asli": "sekarang tanggal berapa"})["message"])

"""
Parsing tanggal & jam Bahasa Indonesia (rule-based, deterministik).
Tanggung jawab: Person 3 (NLP & Intelligence Lead) — Sprint 3

Perubahan besar dari Sprint 2:
1. Aturan Indonesia dikerjakan SENDIRI dulu (bukan langsung ke dateparser).
   dateparser sering salah: "30 agustus" tanpa tahun bisa jadi 2027, dan
   "tahun 2026" sering diparse jadi tanggal acak. Sekarang dateparser hanya
   dipakai sebagai jaring pengaman terakhir.
2. Ada parse_date_range_id() untuk permintaan RENTANG:
   "tahun 2026", "minggu ini", "seminggu ke depan", "bulan depan".
3. Aturan tahun: kalau user tidak menyebut tahun, pakai tahun berjalan;
   pindah ke tahun depan HANYA kalau tanggalnya sudah lewat.
"""
import calendar
import re
from datetime import date, datetime, timedelta

from dateparser.search import search_dates
from loguru import logger

BULAN = {
    "januari": 1, "jan": 1,
    "februari": 2, "febuari": 2, "feb": 2, "pebruari": 2,
    "maret": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "agustus": 8, "agus": 8, "agt": 8, "ags": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nopember": 11, "nov": 11,
    "desember": 12, "des": 12,
}

HARI = {
    "senin": 0, "selasa": 1, "rabu": 2, "kamis": 3,
    "jumat": 4, "jum'at": 4, "sabtu": 5, "ahad": 6,
}

BULAN_NAMA = ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
              "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
HARI_NAMA = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

BULAN_PATTERN = "|".join(sorted(BULAN.keys(), key=len, reverse=True))
HARI_PATTERN = "|".join(sorted(HARI.keys(), key=len, reverse=True))

# Pola jam — dipakai untuk parsing jam DAN dibuang saat mencari tanggal,
# karena kata "jam" mengacaukan dateparser.
TIME_PATTERN = r"\bjam\s+(?:setengah\s+)?\d{1,2}(?:[:.]\d{2})?\s*(?:pagi|siang|sore|malam)?\b"

DATE_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "TIMEZONE": "Asia/Jakarta",
    "RETURN_AS_TIMEZONE_AWARE": False,
}


# ---------------------------------------------------------------- helpers
def _resolve_year(day: int, month: int, ref: datetime, explicit_year: int | None) -> int:
    """
    Tentukan tahun untuk tanggal tanpa tahun.
    Aturan: pakai tahun berjalan. Pindah ke tahun depan HANYA kalau
    tanggal itu sudah lewat (sebelum hari ini).

    Ini yang memperbaiki bug '30 agustus jadi 2027' — selama tanggalnya
    masih hari ini atau ke depan, tahunnya tetap tahun berjalan.
    """
    if explicit_year is not None:
        # Tahun di masa lalu untuk perintah penjadwalan hampir pasti salah dengar.
        # Whisper rutin menulis 2026 jadi 2006 atau 2020. Orang tidak menjadwalkan
        # rapat di tahun yang sudah lewat, jadi angkanya diabaikan dan tahun
        # disimpulkan seperti biasa.
        if explicit_year < ref.year:
            logger.warning(
                f"Tahun {explicit_year} sudah lewat, kemungkinan salah dengar — "
                f"tahun disimpulkan ulang"
            )
        else:
            return explicit_year

    max_day = calendar.monthrange(ref.year, month)[1]
    candidate = date(ref.year, month, min(day, max_day))
    if candidate < ref.date():
        return ref.year + 1
    return ref.year


# ---------------------------------------------------------------- tanggal
def parse_date_id(text: str, reference_time: datetime = None) -> datetime | None:
    """
    Cari tanggal tunggal di dalam kalimat.
    Urutan: tanggal eksplisit -> hari dalam minggu -> pola relatif -> dateparser.

    Tanggal eksplisit didahulukan supaya kalimat seperti
    "besok saya mau lihat jadwal 17 november" tidak salah ambil "besok".
    """
    now = reference_time or datetime.now()
    t = text.lower()

    # 1. "30 agustus", "17 november 2026", "tanggal 5 september"
    m = re.search(
        rf"\b(?:tanggal\s+)?(\d{{1,2}})\s+({BULAN_PATTERN})\b(?:\s+(?:tahun\s+)?(\d{{4}}))?", t
    )
    if m:
        day = int(m.group(1))
        month = BULAN[m.group(2)]
        year = int(m.group(3)) if m.group(3) else None
        year = _resolve_year(day, month, now, year)
        try:
            result = datetime(year, month, day)
            logger.debug(f"Tanggal eksplisit '{m.group(0)}' -> {result.date()}")
            return result
        except ValueError:
            # Pola "32 januari 2027" — user (atau STT) menyebut angka+bulan
            # tapi harinya mustahil. JANGAN fallback ke dateparser, karena
            # dateparser sering menghasilkan tanggal ngaco dari input rusak.
            # Lebih baik return None agar dialog bertanya ulang.
            logger.warning(
                f"Tanggal tidak valid: {day}/{month}/{year} — "
                f"tidak di-fallback, dialog akan bertanya ulang"
            )
            return None

    # 2. Format angka: "30/8/2026", "30-08"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        if year is not None and year < 100:
            year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            year = _resolve_year(day, month, now, year)
            try:
                result = datetime(year, month, day)
                logger.debug(f"Tanggal numerik '{m.group(0)}' -> {result.date()}")
                return result
            except ValueError:
                pass

    # 3. "tanggal 30" — hanya angka hari, tanpa nama bulan.
    #    Dipakai bulan berjalan; kalau harinya sudah lewat, pindah ke bulan depan.
    m = re.search(r"\btanggal\s+(\d{1,2})\b(?!\s*(?:%s))" % BULAN_PATTERN, t)
    if m:
        day = int(m.group(1))
        year, month = now.year, now.month
        if day < now.day:
            month += 1
            if month > 12:
                month, year = 1, year + 1
        if day <= calendar.monthrange(year, month)[1]:
            result = datetime(year, month, day)
            logger.debug(f"Tanggal tanpa bulan '{m.group(0)}' -> {result.date()}")
            return result
        logger.warning(f"Tanggal {day} tidak ada di bulan {month}")

    # 4. Pola relatif — dicek sebelum nama hari supaya "minggu depan" tidak
    #    salah tertangkap sebagai hari Minggu.
    #
    #    "hari ini" dan "sekarang" TIDAK dihitung kalau didahului "dari":
    #    pada "512 hari dari hari ini", frasa itu cuma titik acuan, bukan
    #    tanggal yang dimaksud. Tanpa penjagaan ini, jawabannya jadi hari ini.
    relatif = [
        (r"(?<!dari )\bhari\s+ini\b", 0),
        (r"(?<!dari )\bnanti\b", 0),
        (r"\b(?:pagi|siang|sore|malam)\s+ini\b", 0),
        (r"\bbesok\s+lusa\b", 2),
        (r"\blusa\b", 2),
        (r"\bbesok\b", 1),
        (r"\bkemarin\b", -1),
    ]
    for pattern, offset in relatif:
        if re.search(pattern, t):
            result = now + timedelta(days=offset)
            logger.debug(f"Pola relatif '{pattern}' -> {result.date()}")
            return datetime(result.year, result.month, result.day)

    if re.search(r"\bminggu\s+depan\b", t):
        result = now + timedelta(weeks=1)
        return datetime(result.year, result.month, result.day)
    if re.search(r"\bbulan\s+depan\b", t):
        result = now + timedelta(days=30)
        return datetime(result.year, result.month, result.day)

    # 5. "hari senin", "senin depan", "kamis"
    m = re.search(rf"\b(?:hari\s+)?({HARI_PATTERN})\b(\s+depan)?", t)
    if m:
        target = HARI[m.group(1)]
        delta = (target - now.weekday()) % 7
        if delta == 0:
            delta = 7  # "hari senin" saat ini hari Senin = Senin depan
        if m.group(2) and delta < 7:
            delta += 7
        result = now + timedelta(days=delta)
        logger.debug(f"Hari '{m.group(0).strip()}' -> {result.date()}")
        return datetime(result.year, result.month, result.day)

    # 6. "3 hari lagi", "2 minggu lagi"
    # "512 hari dari sekarang" sama artinya dengan "512 hari lagi".
    # Bentuk "dari sekarang" sebelumnya jatuh ke dateparser, yang menebak
    # dengan menyertakan jam saat ini — dan untuk pertanyaan "hari apa",
    # hasilnya bisa meleset satu hari.
    m = re.search(r"\b(\d{1,4})\s+(hari|minggu|bulan)\s+(?:lagi|ke depan|kedepan|kemudian|mendatang|dari sekarang|dari hari ini|dari saat ini|setelah hari ini)\b", t)
    if m:
        n = int(m.group(1))
        days = n * {"hari": 1, "minggu": 7, "bulan": 30}[m.group(2)]
        result = now + timedelta(days=days)
        logger.debug(f"Relatif '{m.group(0)}' -> {result.date()}")
        return datetime(result.year, result.month, result.day)

    # 7. Jaring pengaman: dateparser (jarang sampai sini)
    cleaned = re.sub(TIME_PATTERN, " ", t)
    cleaned = re.sub(r"\btahun\s+\d{4}\b", " ", cleaned).strip()
    if not cleaned:
        return None

    settings = dict(DATE_SETTINGS, RELATIVE_BASE=now)
    try:
        found = search_dates(cleaned, languages=["id"], settings=settings)
    except Exception as e:
        logger.warning(f"search_dates error: {e}")
        found = None

    if found:
        matched_text, parsed = found[0]
        # Tolak hasil yang cuma menangkap satu angka telanjang
        if len(matched_text.strip()) > 2:
            logger.debug(f"dateparser '{matched_text}' -> {parsed.date()}")
            return parsed

    logger.info(f"Tidak ada tanggal tunggal di: '{text}'")
    return None


# ---------------------------------------------------------------- rentang
def parse_date_range_id(text: str, reference_time: datetime = None) -> tuple[str, str, str] | None:
    """
    Deteksi permintaan RENTANG tanggal.
    Return (tanggal_mulai, tanggal_akhir, label_ucapan) format YYYY-MM-DD,
    atau None kalau bukan permintaan rentang.

    Ini yang memperbaiki "bacakan jadwal saya untuk tahun 2026":
    dulu diperlakukan sebagai satu tanggal, sekarang jadi rentang 1 Jan - 31 Des.
    """
    now = reference_time or datetime.now()
    t = text.lower()
    today = now.date()

    if re.search(r"\btahun\s+ini\b", t):
        return (today.isoformat(), f"{today.year}-12-31", "sisa tahun ini")

    if re.search(r"\btahun\s+depan\b", t):
        y = today.year + 1
        return (f"{y}-01-01", f"{y}-12-31", f"tahun {y}")

    # "tahun 2026"
    m = re.search(r"\btahun\s+(\d{4})\b", t)
    if m:
        year = int(m.group(1))
        return (f"{year}-01-01", f"{year}-12-31", f"tahun {year}")

    # "bulan november", "bulan november 2026"
    m = re.search(rf"\bbulan\s+({BULAN_PATTERN})\b(?:\s+(\d{{4}}))?", t)
    if m:
        month = BULAN[m.group(1)]
        year = int(m.group(2)) if m.group(2) else now.year
        if m.group(2) is None and month < now.month:
            year += 1
        last = calendar.monthrange(year, month)[1]
        return (f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}",
                f"bulan {BULAN_NAMA[month - 1]} {year}")

    if re.search(r"\bbulan\s+ini\b", t):
        last = calendar.monthrange(today.year, today.month)[1]
        return (today.isoformat(), f"{today.year}-{today.month:02d}-{last:02d}", "bulan ini")

    if re.search(r"\bbulan\s+depan\b", t):
        first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        last = calendar.monthrange(first.year, first.month)[1]
        return (first.isoformat(), f"{first.year}-{first.month:02d}-{last:02d}",
                f"bulan {BULAN_NAMA[first.month - 1]}")

    if re.search(r"\bminggu\s+ini\b", t):
        end = today + timedelta(days=6 - today.weekday())
        return (today.isoformat(), end.isoformat(), "minggu ini")

    if re.search(r"\bminggu\s+depan\b", t):
        start = today + timedelta(days=7 - today.weekday())
        return (start.isoformat(), (start + timedelta(days=6)).isoformat(), "minggu depan")

    if re.search(r"\b(seminggu|satu minggu|1 minggu)\s+(ke depan|kedepan|lagi|mendatang)\b", t):
        return (today.isoformat(), (today + timedelta(days=7)).isoformat(), "seminggu ke depan")
    if re.search(r"\b(sebulan|satu bulan|1 bulan)\s+(ke depan|kedepan|lagi|mendatang)\b", t):
        return (today.isoformat(), (today + timedelta(days=30)).isoformat(), "sebulan ke depan")

    # "3 hari lagi saya ada jadwal ga?" — maksudnya rentang sampai hari itu,
    # bukan cuma hari ke-3 saja. Ini juga menyelamatkan salah dengar seperti
    # "367 hari lagi": jawabannya jadi masuk akal ("tidak ada dalam 367 hari").
    m = re.search(r"\b(\d{1,4})\s+(hari|minggu|bulan)\s+(?:lagi|ke depan|kedepan|kemudian|mendatang|dari sekarang|dari hari ini|dari saat ini|setelah hari ini)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = n * {"hari": 1, "minggu": 7, "bulan": 30}[unit]
        return (today.isoformat(), (today + timedelta(days=days)).isoformat(),
                f"{n} {unit} ke depan")

    return None


# "hari minggu" berarti hari Minggu; "minggu" sendirian bisa berarti pekan
# ("minggu depan"), sehingga tidak ada di tabel HARI. Di dalam DAFTAR hari
# ("sabtu dan minggu"), maknanya jelas hari — dan hanya di situ ia diterima.
_HARI_DALAM_DAFTAR = rf"(?:hari\s+)?(?:{HARI_PATTERN}|minggu(?!\s+(?:depan|ini|lalu|kemarin)))"
# Pemisah boleh berurutan: "senin, rabu, DAN jumat" memakai koma lalu "dan".
# Pola yang hanya menerima satu pemisah memotong daftar tepat sebelum hari
# terakhir — dan hari itu hilang tanpa jejak.
_PEMISAH_DAFTAR = r"\s*(?:,|dan|serta|sama|&)(?:\s*(?:,|dan|serta|sama|&))*\s*(?:juga\s+)?"


def gabung_tanggal(daftar_iso: list, jam_per_tanggal: dict = None,
                   kegiatan_per_tanggal: dict = None) -> str:
    """
    Susun daftar tanggal jadi kalimat yang enak didengar.

    ["2026-10-01", "2026-10-03"] -> "Kamis 1 Oktober dan Sabtu 3 Oktober"

    Nama hari selalu disebut: pengguna sering menyebut jadwal dengan nama
    hari ("sabtu dan kamis"), dan mendengar nama harinya kembali adalah cara
    tercepat memastikan AKIRA memahami hari yang dimaksud.
    """
    bagian = []
    for t in daftar_iso:
        try:
            d = datetime.strptime(t, "%Y-%m-%d")
            # Tanpa koma setelah nama hari: di dalam daftar, koma itu
            # terdengar seperti pemisah antar-tanggal saat dibacakan.
            teks = f"{HARI_NAMA[d.weekday()]} {d.day} {BULAN_NAMA[d.month - 1]}"
        except (ValueError, TypeError):
            teks = str(t)
        if kegiatan_per_tanggal and t in kegiatan_per_tanggal:
            teks += f" {kegiatan_per_tanggal[t]}"
        if jam_per_tanggal and t in jam_per_tanggal:
            teks += f" jam {jam_per_tanggal[t]}"
        bagian.append(teks)

    if len(bagian) <= 1:
        return "".join(bagian)
    return ", ".join(bagian[:-1]) + " dan " + bagian[-1]


def _daftar_hari(t: str, now: datetime) -> list:
    """
    Ambil beberapa NAMA HARI yang disebut sebagai daftar.

    "saya ada jadwal hari sabtu dan kamis" -> [Kamis terdekat, Sabtu terdekat]

    Syarat ketat, karena salah tafsir di sini berarti membuat jadwal ganda:
    - minimal dua hari BERBEDA
    - dirangkai dengan "dan", koma, "serta", atau "sama" — BUKAN "atau".
      "sabtu atau minggu" adalah pilihan, bukan dua jadwal.
    """
    m = re.search(rf"\b{_HARI_DALAM_DAFTAR}(?:{_PEMISAH_DAFTAR}{_HARI_DALAM_DAFTAR})+\b", t)
    if not m:
        return []

    potongan = m.group(0)
    nama_hari = re.findall(rf"\b({HARI_PATTERN}|minggu)(\s+depan)?\b", potongan)

    tanggal = []
    for nama, depan in nama_hari:
        target = 6 if nama == "minggu" else HARI[nama]
        delta = (target - now.weekday()) % 7
        if delta == 0:
            delta = 7
        if depan and delta < 7:
            delta += 7
        hasil = now + timedelta(days=delta)
        tanggal.append(datetime(hasil.year, hasil.month, hasil.day).strftime("%Y-%m-%d"))

    unik = sorted(set(tanggal))
    if len(unik) < 2:
        return []

    logger.info(f"Beberapa hari terdeteksi: {[n for n, _ in nama_hari]} -> {unik}")
    return unik


def parse_multi_dates(text: str, reference_time: datetime = None) -> list:
    """
    Ambil SEMUA tanggal yang disebut dalam satu kalimat.

    "tanggal 9, tanggal 10 dan tanggal 11 buat meeting"
      -> ["2026-09-09", "2026-09-10", "2026-09-11"]

    Dipakai saat user menyebut beberapa jadwal sekaligus. Tanpa ini, parser
    hanya mengambil tanggal PERTAMA dan dua sisanya hilang diam-diam —
    kegagalan yang tidak terlihat sampai user mengecek kalendernya.

    Return list ISO string terurut & unik. Kosong atau satu elemen berarti
    bukan permintaan banyak tanggal.
    """
    now = reference_time or datetime.now()
    t = text.lower()

    # Buang dulu semua ekspresi jam. Tanpa ini "tanggal 5 jam 9" terbaca
    # sebagai dua tanggal (5 dan 9) — angka jamnya ikut terhitung.
    t = re.sub(TIME_PATTERN, " ", t)
    t = re.sub(r"\bjam\s+\d{1,2}(?:[:.]\d{1,2})?\b", " ", t)
    t = re.sub(r"\b(?:20\d{2}|19\d{2})\b", " ", t)   # tahun bukan tanggal

    # "hari sabtu dan kamis" — daftar nama hari. Sebelumnya hanya daftar
    # ANGKA tanggal yang dikenali, sehingga hari kedua hilang diam-diam.
    hari = _daftar_hari(t, now)
    if hari:
        return hari

    hasil = []

    # "tanggal 9, 10 dan 11" — angka telanjang setelah kata "tanggal" pertama
    m_awal = re.search(r"\btanggal\s+(\d{1,2})\b", t)
    if m_awal:
        ekor = t[m_awal.start():]
        # Ambil angka yang dipisah koma / "dan" / "sama", berhenti di kata lain
        for m in re.finditer(r"\b(?:tanggal\s+)?(\d{1,2})\b(?=\s*(?:,|dan|serta|sama|$|\s))", ekor):
            angka = int(m.group(1))
            if 1 <= angka <= 31:
                hasil.append(angka)

    if len(hasil) < 2:
        return []

    # Bulan diambil dari kalimat kalau disebut, kalau tidak pakai bulan berjalan
    m_bulan = re.search(rf"\b({BULAN_PATTERN})\b", t)
    bulan = BULAN[m_bulan.group(1)] if m_bulan else now.month
    m_tahun = re.search(r"\b(20\d{2})\b", t)
    tahun = int(m_tahun.group(1)) if m_tahun else now.year

    tanggal_list = []
    for hari in dict.fromkeys(hasil):          # buang duplikat, jaga urutan
        b, th = bulan, tahun
        if not m_bulan and hari < now.day:     # hari sudah lewat -> bulan depan
            b += 1
            if b > 12:
                b, th = 1, th + 1
        try:
            if hari <= calendar.monthrange(th, b)[1]:
                tanggal_list.append(datetime(th, b, hari).strftime("%Y-%m-%d"))
        except ValueError:
            continue

    if len(tanggal_list) < 2:
        return []

    logger.info(f"Beberapa tanggal terdeteksi: {tanggal_list}")
    return sorted(set(tanggal_list))


def parse_jam_per_tanggal(text: str, reference_time: datetime = None) -> dict:
    """
    Ambil jam yang berbeda untuk tiap tanggal dalam satu kalimat.

    "tanggal 10 mulainya jam 2 siang, tanggal 12 jam 12 siang,
     tanggal 15 mulainya jam 7 pagi"
      -> {"2026-09-10": "14:00", "2026-09-12": "12:00", "2026-09-15": "07:00"}

    Tanpa ini, hanya jam pertama yang terpakai dan dipasang ke SEMUA tanggal —
    dua jadwal tersimpan di waktu yang salah tanpa ada tanda apa pun.

    Return {} kalau kalimatnya tidak menyebut jam per tanggal.
    """
    now = reference_time or datetime.now()
    t = text.lower()

    # Pecah kalimat di tiap penyebutan "tanggal N"
    potongan = re.split(r"\b(?:untuk\s+)?tanggal\s+(\d{1,2})\b", t)
    if len(potongan) < 3:
        return {}

    # Bulan & tahun diambil dari keseluruhan kalimat
    m_bulan = re.search(rf"\b({BULAN_PATTERN})\b", t)
    bulan = BULAN[m_bulan.group(1)] if m_bulan else now.month
    m_tahun = re.search(r"\b(20\d{2})\b", t)
    tahun = int(m_tahun.group(1)) if m_tahun else now.year

    hasil = {}
    # potongan = [sebelum, hari1, teks1, hari2, teks2, ...]
    for i in range(1, len(potongan) - 1, 2):
        try:
            hari = int(potongan[i])
        except ValueError:
            continue

        jam = parse_time_id(potongan[i + 1])
        if not jam:
            continue

        b, th = bulan, tahun
        if not m_bulan and hari < now.day:
            b += 1
            if b > 12:
                b, th = 1, th + 1
        try:
            if hari <= calendar.monthrange(th, b)[1]:
                hasil[datetime(th, b, hari).strftime("%Y-%m-%d")] = jam
        except ValueError:
            continue

    if len(hasil) > 1:
        logger.info(f"Jam per tanggal terdeteksi: {hasil}")
        return hasil
    return {}


# ------------------------------------------------------- tanggal tujuan
# Penanda "pindah ke": apa pun setelah kata ini adalah tanggal/jam BARU.
MARKER_TUJUAN = re.compile(
    r"\b(?:jadi|menjadi|ke tanggal|ke hari|pindah(?:kan)? ke|geser ke|ganti ke|"
    r"diganti ke|diubah ke|diundur ke|dimajukan ke|ke jam)\b"
)


# "nggak jadi", "gak jadi", "tidak jadi" = pembatalan, BUKAN penanda tujuan.
NEGASI_SEBELUM_JADI = re.compile(r"\b(?:nggak|enggak|engga|gak|ga|tidak|batal)\s+jadi\b")


def pisah_asal_tujuan(text: str) -> tuple[str, str | None]:
    """
    Pecah perintah reschedule jadi (bagian asal, bagian tujuan).

    "reschedule rapat 30 agustus jam 9 JADI tanggal 31 agustus"
      -> ("reschedule rapat 30 agustus jam 9", "tanggal 31 agustus")

    Dua pengaman supaya kata "jadi" tidak salah dianggap penanda tujuan:

    1. "nggak jadi meeting hari ini" — di sini "jadi" berarti batal.
       Kalau didahului kata negasi, penanda diabaikan.
    2. Bagian setelah penanda HARUS mengandung tanggal atau jam. Kalau tidak,
       kata itu cuma kata sambung biasa ("jadi gimana Bos") dan pemecahan
       justru merusak nama kegiatan.

    Return (teks_asli, None) kalau tidak ada penanda tujuan yang sah.
    """
    lower = text.lower()

    for m in MARKER_TUJUAN.finditer(lower):
        # Pengaman 1: "nggak jadi ..." bukan pemindahan jadwal
        potongan = lower[max(0, m.start() - 12): m.end()]
        if NEGASI_SEBELUM_JADI.search(potongan):
            logger.debug("Kata 'jadi' didahului negasi — bukan penanda tujuan")
            continue

        tujuan = text[m.end():].strip()
        if not tujuan:
            continue

        # Pengaman 2: tujuan harus benar-benar berisi waktu
        if parse_date_id(tujuan) is None and parse_time_id(tujuan) is None:
            logger.debug(f"Bagian setelah penanda ('{tujuan}') tidak berisi waktu — diabaikan")
            continue

        asal = text[: m.start()].strip()
        logger.debug(f"Reschedule dipisah — asal: '{asal}' | tujuan: '{tujuan}'")
        return asal, tujuan

    return text, None


# ------------------------------------------------------ jeda pengingat
SATUAN_MENIT = {
    "detik": 1 / 60,
    "menit": 1,
    "jam": 60,
    "hari": 1440,
    "minggu": 10080,
}

# "setengah jam sebelum", "seperempat jam sebelumnya"
PECAHAN = {"setengah": 0.5, "seperempat": 0.25, "separuh": 0.5}

ANGKA_KATA = {
    "se": 1, "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
    "lima belas": 15, "dua puluh": 20, "tiga puluh": 30, "empat puluh lima": 45,
}

SEBELUM = r"(?:sebelum(?:nya)?|sblm|lebih awal|di ?muka|duluan)"


def parse_lead_time(text: str) -> int | None:
    """
    Ambil jeda pengingat dalam MENIT dari kalimat.

    "ingatkan 1 jam sebelum acara"        -> 60
    "kasih tau 30 menit sebelumnya"       -> 30
    "ingetin sehari sebelum"              -> 1440
    "setengah jam sebelum"                -> 30
    "10 detik sebelum"                    -> 1 (dibulatkan; loop cek tiap 30 detik)

    Return None kalau tidak ada jeda yang disebut.
    """
    if not text:
        return None
    t = text.lower()
    satuan_pat = "|".join(SATUAN_MENIT)

    # "setengah jam sebelum"
    m = re.search(rf"\b(setengah|seperempat|separuh)\s+({satuan_pat})\b", t)
    if m:
        menit = PECAHAN[m.group(1)] * SATUAN_MENIT[m.group(2)]
        return max(1, int(round(menit)))

    # "1 jam sebelum", "30 menit sebelumnya", "2 hari sebelum"
    m = re.search(rf"\b(\d{{1,4}})\s*({satuan_pat})\b(?:\s+\w+){{0,2}}\s*{SEBELUM}", t)
    if m:
        return max(1, int(round(int(m.group(1)) * SATUAN_MENIT[m.group(2)])))

    # "sehari sebelum", "sejam sebelumnya", "seminggu sebelum"
    m = re.search(rf"\bse(hari|jam|minggu|menit)\b(?:\s+\w+){{0,2}}\s*{SEBELUM}", t)
    if m:
        return int(SATUAN_MENIT[m.group(1)])

    # Angka dalam kata: "dua jam sebelum"
    kata_pat = "|".join(sorted(ANGKA_KATA, key=len, reverse=True))
    m = re.search(rf"\b({kata_pat})\s+({satuan_pat})\b(?:\s+\w+){{0,2}}\s*{SEBELUM}", t)
    if m:
        return max(1, int(round(ANGKA_KATA[m.group(1)] * SATUAN_MENIT[m.group(2)])))

    # Tanpa kata "sebelum": "ingatkan 15 menit lagi" TIDAK dihitung — itu waktu
    # relatif dari sekarang, bukan jeda sebelum acara.
    return None


def ucapkan_lead_time(menit: int) -> str:
    """60 -> 'satu jam', 1440 -> 'satu hari', 30 -> '30 menit'."""
    if menit % 10080 == 0 and menit >= 10080:
        n = menit // 10080
        return "satu minggu" if n == 1 else f"{n} minggu"
    if menit % 1440 == 0 and menit >= 1440:
        n = menit // 1440
        return "satu hari" if n == 1 else f"{n} hari"
    if menit % 60 == 0 and menit >= 60:
        n = menit // 60
        return "satu jam" if n == 1 else f"{n} jam"
    return f"{menit} menit"


# ---------------------------------------------------------------- jam
def _format_jam(hour: int, minute: int) -> str | None:
    """
    Rakit HH:MM setelah memvalidasi angkanya.

    Validasi ini penting: Whisper pernah mendengar "jam 7.60", yang dulu lolos
    jadi "07:60" dan baru meledak di executor saat strptime menolaknya.
    Lebih baik ditolak di sini — state machine akan bertanya ulang.
    """
    if not (0 <= minute <= 59):
        logger.warning(f"Menit tidak valid ({minute}), jam diabaikan")
        return None
    if not (0 <= hour <= 23):
        logger.warning(f"Jam tidak valid ({hour}), jam diabaikan")
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_time_id(text: str) -> str | None:
    """
    Parse ekspresi jam Bahasa Indonesia jadi HH:MM (24 jam).
    Menangani: 'jam 3 sore', 'jam setengah 8 pagi', 'jam 14:30', '3 sore' (tanpa kata jam),
    'jam 7 lewat 15'. Angka yang tidak masuk akal (menit > 59) ditolak, bukan diteruskan.
    """
    t = text.lower()

    # "jam 7 lewat 15 menit"
    m = re.search(r"jam\s+(\d{1,2})\s+lewat\s+(\d{1,2})", t)
    if m:
        return _format_jam(_adjust_period(int(m.group(1)), _cari_periode(t)), int(m.group(2)))

    # Jangan salah ambil angka tahun sebagai jam
    t = re.sub(r"\btahun\s+\d{4}\b", " ", t)

    m = re.search(r"jam\s+setengah\s+(\d{1,2})\s*(pagi|siang|sore|malam)?", t)
    if m:
        return _format_jam(_adjust_period(int(m.group(1)) - 1, m.group(2)), 30)

    m = re.search(r"jam\s+(\d{1,2})(?:[:.](\d{1,2}))?\s*(pagi|siang|sore|malam)?", t)
    if m:
        # Periode sering disebut SEBELUM jamnya: "nanti sore ada meeting jam 4".
        # Kalau tidak menempel di belakang angka, cari di seluruh kalimat.
        periode = m.group(3) or _cari_periode(t)
        hour = _adjust_period(int(m.group(1)), periode)
        minute = int(m.group(2)) if m.group(2) else 0
        return _format_jam(hour, minute)

    # Tanpa kata "jam": "setengah 9 malam", "3 sore"
    m = re.search(r"\bsetengah\s+(\d{1,2})\s*(pagi|siang|sore|malam)\b", t)
    if m:
        return _format_jam(_adjust_period(int(m.group(1)) - 1, m.group(2)), 30)

    m = re.search(r"\b(\d{1,2})(?:[:.](\d{1,2}))?\s+(pagi|siang|sore|malam)\b", t)
    if m:
        hour = _adjust_period(int(m.group(1)), m.group(3))
        minute = int(m.group(2)) if m.group(2) else 0
        return _format_jam(hour, minute)

    logger.info(f"Tidak ada jam di: '{text}'")
    return None


def parse_time_range_id(text: str) -> tuple[str | None, str | None]:
    """
    Ambil jam MULAI dan jam SELESAI dari kalimat.
    "rapat dari jam 9 sampai jam 11" -> ("09:00", "11:00")
    "meeting jam 2 siang"            -> ("14:00", None)
    """
    t = text.lower()
    m = re.search(r"\b(?:sampai|sampe|hingga|s/d|sd|-)\s*(jam\s*)?(\d{1,2}(?:[:.]\d{1,2})?\s*(?:pagi|siang|sore|malam)?)", t)
    if not m:
        return parse_time_id(t), None

    selesai = parse_time_id("jam " + m.group(2))
    mulai = parse_time_id(t[: m.start()])
    # Periode ("sore") sering hanya disebut di ujung: "jam 3 sampai 5 sore"
    if selesai and mulai and selesai < mulai:
        periode = _cari_periode(t)
        if periode:
            mulai_ulang = parse_time_id(t[: m.start()] + f" {periode}")
            if mulai_ulang:
                mulai = mulai_ulang
    return mulai, selesai


def jam_ambigu(text: str) -> bool:
    """
    True kalau jam yang disebut bisa berarti pagi ATAU malam.

    "jam 10"        -> True  (10 pagi? 10 malam?)
    "jam 10 pagi"   -> False (sudah jelas)
    "jam 22"        -> False (format 24 jam, tidak mungkin ambigu)
    "jam 14:30"     -> False

    Dipakai state machine untuk bertanya balik "pagi atau malam?" — jauh lebih
    baik daripada menebak dan membuat jadwal di waktu yang salah.
    """
    if not text:
        return False
    t = text.lower()

    if _cari_periode(t):
        return False  # periode sudah disebut di suatu tempat

    m = re.search(r"\bjam\s+(?:setengah\s+)?(\d{1,2})(?:[:.](\d{1,2}))?", t)
    if not m:
        return False

    jam = int(m.group(1))
    # 0 dan 13-23 hanya masuk akal dalam format 24 jam, jadi tidak ambigu.
    # 12 juga jarang ambigu dalam pemakaian sehari-hari ("jam 12" = siang).
    return 1 <= jam <= 11


def _cari_periode(text: str) -> str | None:
    """Ambil kata pagi/siang/sore/malam dari kalimat, di mana pun posisinya."""
    m = re.search(r"\b(pagi|siang|sore|malam)\b", text)
    return m.group(1) if m else None


def _adjust_period(hour: int, period: str | None) -> int:
    """
    Konversi 12-jam ke 24-jam berdasarkan konteks pagi/siang/sore/malam.

    Tidak memakai modulo: "jam 25" harus DITOLAK oleh _format_jam, bukan
    diam-diam diubah jadi jam 1 dini hari.
    """
    if period == "malam" and hour == 12:
        return 0                      # "jam 12 malam" = tengah malam
    if period == "pagi" and hour == 12:
        return 0

    # "siang" dalam kebiasaan Indonesia mencakup jam 10-14. Aturan "tambah 12"
    # yang berlaku untuk sore/malam salah di sini: "jam 11 siang" itu 11:00,
    # bukan 23:00. Yang perlu digeser hanya jam 1-4 siang.
    if period == "siang":
        return hour + 12 if hour <= 4 else hour

    if period in ("sore", "malam") and hour < 12:
        return hour + 12
    return hour


# ---------------------------------------------------------------- ucapan
def jam_alami(jam: int, menit: int = 0) -> str:
    """
    Jam 24-jam dalam bentuk yang biasa diucapkan orang.

        20:00 -> "8 malam"        07:30 -> "7 lewat 30 pagi"
        12:00 -> "12 siang"       00:00 -> "12 malam"

    Tidak semua orang terbiasa dengan format 24 jam — "jam dua puluh" harus
    dihitung dulu, "jam 8 malam" langsung dipahami.
    """
    if jam == 0:
        periode = "malam"
    elif jam < 4:
        periode = "dini hari"
    elif jam < 11:
        periode = "pagi"
    elif jam < 15:
        periode = "siang"
    elif jam < 18:
        periode = "sore"
    else:
        periode = "malam"

    jam12 = jam % 12 or 12
    if menit:
        return f"{jam12} lewat {menit} {periode}"
    return f"{jam12} {periode}"


_JAM_DALAM_KALIMAT = re.compile(r"\b(jam|pukul)\s+([01]?\d|2[0-3])[:.]([0-5]\d)\b", re.I)


def ucapkan_jam_alami(teks: str) -> str:
    """
    Ganti setiap "jam 20:00" dalam kalimat jadi "jam 8 malam".

    Hanya angka yang didahului "jam" atau "pukul" yang diubah, supaya angka
    lain (tanggal, durasi) tidak ikut tersentuh.
    """
    def ganti(m):
        return f"{m.group(1)} {jam_alami(int(m.group(2)), int(m.group(3)))}"

    return _JAM_DALAM_KALIMAT.sub(ganti, teks or "")


def ucapkan_tanggal(tanggal: str, sebut_hari: bool = False, sebut_tahun: bool = True) -> str:
    """'2026-11-17' -> '17 November 2026' (opsional: 'Selasa, 17 November 2026')."""
    try:
        d = datetime.strptime(tanggal, "%Y-%m-%d")
    except (ValueError, TypeError):
        return str(tanggal)
    teks = f"{d.day} {BULAN_NAMA[d.month - 1]}"
    if sebut_tahun:
        teks += f" {d.year}"
    if sebut_hari:
        teks = f"{HARI_NAMA[d.weekday()]}, {teks}"
    return teks


if __name__ == "__main__":
    ref = datetime(2026, 8, 29, 10, 0)
    print(f"Referensi waktu: {ref}\n--- TANGGAL TUNGGAL ---")
    for t in [
        "catat jadwal tanggal 30 agustus",
        "catat jadwal 30 agustus jam 3 sore",
        "cek jadwal 17 november 2026",
        "catat meeting 5 januari",
        "coba cek dong jadwal besok",
        "jadwal hari senin",
        "3 hari lagi",
    ]:
        d = parse_date_id(t, ref)
        print(f"  {t!r:45} -> {d.date() if d else None} | jam: {parse_time_id(t)}")

    print("\n--- RENTANG ---")
    for t in [
        "bacakan jadwal saya untuk tahun 2026",
        "jadwal minggu ini",
        "jadwal seminggu ke depan",
        "jadwal bulan november",
        "jadwal 3 hari ke depan",
        "jadwal besok",
    ]:
        print(f"  {t!r:45} -> {parse_date_range_id(t, ref)}")

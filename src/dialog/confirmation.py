"""
Konfirmasi ya/tidak dan pemilihan kandidat jadwal.
Tanggung jawab: Person 4 (Voice Output, Dialog UX & QA Lead) — Sprint 3.5

Dipakai untuk aksi yang MERUSAK (hapus, reschedule) dan untuk memastikan
detail jadwal baru sebelum masuk kalender.

Semua fungsi menerima ask_fn/listen_fn sebagai parameter, jadi bisa diuji
tanpa mic dan speaker sungguhan.
"""
import re

from loguru import logger

KATA_YA = [
    "iya", "iyaa", "yoi", "betul", "benar", "bener", "sudah benar",
    "oke", "ok", "okay", "sip", "lanjut", "gas", "boleh", "setuju", "yes",
    "silakan", "silahkan", "cocok", "pas",
]

# Kata "ya" sengaja TIDAK masuk KATA_YA. Di Bahasa Indonesia lisan, "ya" sering
# jadi partikel di ujung kalimat ("apa ya", "gimana ya") yang justru menandakan
# ragu — bukan setuju. Jadi "ya" hanya dihitung setuju kalau berdiri di AWAL
# jawaban ("ya", "ya betul", "ya sudah").
YA_DI_AWAL = re.compile(r"\A(?:ya|yah|yaudah|ya sudah)\b")

# Penolakan TEGAS: langsung batal, tanpa ditanya bagian mana yang salah.
# "Batalkan" sudah menyatakan maksud dengan jelas — bertanya lagi setelah itu
# terasa seperti tidak mendengarkan.
KATA_BATAL_TEGAS = [
    "batal", "batalkan", "batalin", "jangan", "gak jadi", "nggak jadi",
    "tidak jadi", "gajadi", "cancel", "lupakan", "udahlah", "stop",
]

_BATAL_TEGAS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in KATA_BATAL_TEGAS) + r")\b"
)


def minta_batal_tegas(text: str) -> bool:
    """True kalau user jelas ingin membatalkan, bukan sekadar menjawab 'tidak'."""
    return bool(_BATAL_TEGAS_RE.search((text or "").lower()))


KATA_TIDAK = [
    "tidak", "nggak", "enggak", "engga", "gak", "ga", "bukan", "salah",
    "batal", "batalkan", "jangan", "no", "belum", "keliru", "ulangi", "ulang",
]

# Angka yang diucapkan saat memilih dari daftar
ANGKA_UCAPAN = {
    "satu": 1, "pertama": 1, "kesatu": 1,
    "dua": 2, "kedua": 2,
    "tiga": 3, "ketiga": 3,
    "empat": 4, "keempat": 4,
    "lima": 5, "kelima": 5,
}


def tafsir_ya_tidak(text: str) -> bool | None:
    """
    Tafsirkan jawaban user jadi True (ya) / False (tidak) / None (tidak jelas).

    'tidak' dicek DULU: kalimat seperti "tidak, salah" mengandung kata "oke"?
    tidak — tapi "nggak jadi ya" mengandung "ya" di ujung. Menolak harus menang,
    karena salah menafsirkan "tidak" jadi "ya" berakibat jadwal terhapus.
    """
    if not text:
        return None
    t = text.lower().strip(" .,!?")

    for kata in KATA_TIDAK:
        if re.search(rf"\b{re.escape(kata)}\b", t):
            return False
    if YA_DI_AWAL.match(t):
        return True
    for kata in KATA_YA:
        if re.search(rf"\b{re.escape(kata)}\b", t):
            return True

    logger.info(f"Jawaban '{text}' tidak jelas ya atau tidak")
    return None


def tafsir_dengan_penalaran(jawaban: str, pertanyaan: str) -> bool | None:
    """
    Tafsirkan jawaban ya/tidak dalam dua lapis, yang murah lebih dulu.

    1. Aturan kata kunci — instan, menangani "ya", "boleh", "tidak", dst.
    2. Penalaran Groq — hanya kalau aturan menyerah DAN jawabannya tidak
       kosong. Pertanyaan AKIRA ikut dikirim, karena makna jawaban sering
       hanya bisa dipahami dari pertanyaannya: "hapus aja" berarti setuju
       kalau yang ditanya "Hapus rapat?", tapi berarti perintah baru di
       konteks lain.

    Penalaran yang gagal atau ragu mengembalikan None — konfirmasi lalu
    bertanya ulang, tidak pernah menganggapnya sebagai persetujuan.
    """
    hasil = tafsir_ya_tidak(jawaban)
    if hasil is not None or not (jawaban or "").strip():
        return hasil

    try:
        from src.nlp.groq_reasoner import tafsir_jawaban_groq

        return tafsir_jawaban_groq(pertanyaan, jawaban)
    except Exception as e:
        logger.warning(f"Penalaran jawaban gagal: {e}")
        return None


def konfirmasi(pertanyaan: str, ask_fn, listen_fn, max_percobaan: int = 2) -> bool:
    """
    Ajukan pertanyaan ya/tidak. Return True hanya kalau user jelas mengiyakan.

    Default-nya TIDAK: kalau user diam atau jawabannya ambigu sampai percobaan
    habis, aksi dibatalkan. Untuk operasi yang menghapus data, diam bukan
    tanda setuju.
    """
    pertanyaan_asli = pertanyaan
    for percobaan in range(1, max_percobaan + 1):
        ask_fn(pertanyaan)
        jawaban = listen_fn()
        # Selalu tafsirkan terhadap pertanyaan ASLI, bukan "tolong jawab ya
        # atau tidak" — konteks yang berguna ada di pertanyaan pertama.
        hasil = tafsir_dengan_penalaran(jawaban, pertanyaan_asli)

        if hasil is True:
            logger.info("User mengonfirmasi")
            return True
        if hasil is False:
            logger.info("User menolak")
            return False

        if percobaan < max_percobaan:
            pertanyaan = "Maaf Bos, tolong jawab ya atau tidak."

    logger.info("Konfirmasi tidak jelas sampai batas percobaan, aksi dibatalkan")
    return False


# Kata/pola yang menandakan kalimat benar-benar menyebut TANGGAL.
PETUNJUK_TANGGAL = re.compile(
    r"\b(?:tanggal|besok|lusa|kemarin|hari ini|minggu depan|minggu ini|"
    r"bulan depan|bulan ini|senin|selasa|rabu|kamis|jumat|sabtu|ahad|minggu|"
    r"januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|"
    r"november|desember)\b|\b\d{1,2}[/-]\d{1,2}\b"
)


def _ada_petunjuk_tanggal(text: str) -> bool:
    return bool(PETUNJUK_TANGGAL.search(text))


# ------------------------------------------------------------------
# Koreksi saat beberapa tanggal dicatat sekaligus
# ------------------------------------------------------------------
_HARI_KE_INDEKS = {
    "senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4,
    "jum'at": 4, "sabtu": 5, "minggu": 6, "ahad": 6,
}


def _tanggal_disebut(jawaban: str, daftar: list) -> list:
    """Tanggal di `daftar` yang harinya disebut dalam jawaban ("minggunya")."""
    from datetime import datetime

    t = (jawaban or "").lower()
    disebut = {
        _HARI_KE_INDEKS[m]
        for m in re.findall(r"\b(senin|selasa|rabu|kamis|jum'?at|sabtu|minggu|ahad)(?:nya)?\b", t)
        if m in _HARI_KE_INDEKS
    }
    return [d for d in daftar if datetime.strptime(d, "%Y-%m-%d").weekday() in disebut]


def _siapkan_per_tanggal(data: dict):
    """Pastikan tiap tanggal punya kegiatan dan jam sendiri sebelum diubah."""
    daftar = data["tanggal_lain"]
    keg = data.setdefault("kegiatan_per_tanggal", {})
    jam = data.setdefault("jam_per_tanggal", {})
    for t in daftar:
        keg.setdefault(t, data.get("kegiatan"))
        jam.setdefault(t, data.get("jam"))


def _terapkan_ubah(data: dict, ubah: list) -> list:
    """Terapkan daftar perubahan per tanggal. Return kalimat ringkas perubahannya."""
    from src.nlp.date_time_parser import ucapkan_tanggal

    _siapkan_per_tanggal(data)
    kalimat = []
    for item in ubah:
        sasaran = data["tanggal_lain"] if item["tanggal"] == "semua" else [item["tanggal"]]
        for t in sasaran:
            if item.get("kegiatan"):
                data["kegiatan_per_tanggal"][t] = item["kegiatan"]
            if item.get("jam"):
                data["jam_per_tanggal"][t] = item["jam"]
        label = "semua hari" if item["tanggal"] == "semua" else ucapkan_tanggal(
            item["tanggal"], sebut_hari=True, sebut_tahun=False)
        isi = []
        if item.get("kegiatan"):
            isi.append(f"kegiatannya {item['kegiatan']}")
        if item.get("jam"):
            isi.append(f"jam {item['jam']}")
        kalimat.append(f"{label} {' dan '.join(isi)}")

    # Field umum ikut tanggal pertama supaya pemeriksaan kelengkapan tetap lolos
    pertama = data["tanggal_lain"][0]
    data["kegiatan"] = data["kegiatan_per_tanggal"][pertama]
    data["jam"] = data["jam_per_tanggal"][pertama]
    data["_periode_dikonfirmasi"] = True
    return kalimat


def _ubah_dari_aturan(data: dict, kalimat: str, sasaran: list) -> list:
    """Jalur cadangan tanpa LLM: pahami nilainya dengan aturan untuk tanggal sasaran."""
    from src.nlp.correction import parse_koreksi
    from src.nlp.date_time_parser import parse_time_id

    bersih = re.sub(r"\b(?:yang|hari)?\s*(?:senin|selasa|rabu|kamis|jum'?at|sabtu|minggu|ahad)(?:nya)?\b",
                    " ", (kalimat or "").lower())
    acuan = {"kegiatan": data.get("kegiatan"), "jam": data.get("jam")}
    perubahan = parse_koreksi(acuan, bersih, use_llm=False)

    item = {}
    if perubahan.get("kegiatan"):
        item["kegiatan"] = perubahan["kegiatan"]
    if perubahan.get("jam"):
        item["jam"] = perubahan["jam"]

    if not item:
        # Jawaban atas "apa yang berbeda?" sering berupa nama kegiatan saja,
        # atau jam saja — tanpa kata "kegiatannya"/"jamnya".
        jam = parse_time_id(bersih)
        if jam:
            item["jam"] = jam
        else:
            sisa = re.sub(r"\b(?:beda|berbeda|lain|jadi|diganti|ganti|kegiatannya|acaranya)\b",
                          " ", bersih).strip(" .,!?")
            if sisa and len(sisa.split()) <= 5:
                item["kegiatan"] = " ".join(sisa.split())

    return [{"tanggal": t, **item} for t in sasaran] if item else []


def _koreksi_per_tanggal(data: dict, jawaban: str, ask_fn, listen_fn, use_llm: bool) -> bool:
    """
    Tangani koreksi ketika beberapa tanggal dicatat sekaligus.

    Contoh nyata: "Sabtu dan Minggu, makan malam jam 7", lalu user berkata
    "yang minggunya beda". Sebelumnya kalimat itu tidak bisa diproses:
    sistem koreksi hanya mengenal SATU jadwal, sehingga tidak punya konsep
    "ubah yang hari Minggu saja".

    Penalaran Groq dipakai lebih dulu — diberi daftar jadwal per hari
    supaya bisa menentukan hari mana yang dimaksud. Aturan jadi cadangan
    kalau Groq tidak tersedia.

    Return True kalau jawaban ditangani sebagai koreksi.
    """
    from src.nlp.date_time_parser import ucapkan_tanggal

    _siapkan_per_tanggal(data)
    daftar = data["tanggal_lain"]
    jadwal = [
        {"tanggal": t, "hari": ucapkan_tanggal(t, sebut_hari=True, sebut_tahun=False).split(",")[0],
         "kegiatan": data["kegiatan_per_tanggal"].get(t), "jam": data["jam_per_tanggal"].get(t)}
        for t in daftar
    ]

    hasil = None
    if use_llm:
        try:
            from src.nlp.groq_reasoner import koreksi_banyak_groq

            hasil = koreksi_banyak_groq(jadwal, jawaban)
        except Exception as e:
            logger.warning(f"Penalaran koreksi per tanggal gagal: {e}")

    if hasil is None:
        # Cadangan aturan: hari disebut -> hari itu; tidak disebut -> semua
        sasaran = _tanggal_disebut(jawaban, daftar)
        ubah = _ubah_dari_aturan(data, jawaban, sasaran or daftar)
        hasil = {"ubah": ubah, "tanya": sasaran if (sasaran and not ubah) else []}

    if hasil["ubah"]:
        kalimat = _terapkan_ubah(data, hasil["ubah"])
        ask_fn(f"Baik Bos, saya ubah: {'; '.join(kalimat)}.")
        return True

    if hasil["tanya"]:
        for t in hasil["tanya"]:
            label = ucapkan_tanggal(t, sebut_hari=True, sebut_tahun=False)
            ask_fn(f"Untuk {label}, apa yang berbeda, Bos? Sebutkan kegiatan atau jamnya.")
            susulan = listen_fn()
            if minta_batal_tegas(susulan):
                continue

            ubah = None
            if use_llm:
                try:
                    from src.nlp.groq_reasoner import koreksi_banyak_groq

                    satu = [j for j in jadwal if j["tanggal"] == t]
                    r = koreksi_banyak_groq(satu, susulan)
                    ubah = [dict(u, tanggal=t) for u in (r or {}).get("ubah", [])]
                except Exception as e:
                    logger.warning(f"Penalaran susulan gagal: {e}")
            if not ubah:
                ubah = _ubah_dari_aturan(data, susulan, [t])

            if ubah:
                kalimat = _terapkan_ubah(data, ubah)
                ask_fn(f"Baik Bos, saya ubah: {'; '.join(kalimat)}.")
            else:
                ask_fn(f"Maaf Bos, perubahan untuk {label} belum tertangkap.")
        return True

    return False


def konfirmasi_dengan_koreksi(
    data: dict,
    bangun_pertanyaan,
    ask_fn,
    listen_fn,
    max_putaran: int = 4,
    use_llm: bool = True,
    model: str = None,
) -> bool:
    """
    Konfirmasi yang bisa MENGOREKSI field apa pun, bukan cuma waktu.

    Perbedaan penting dari konfirmasi_interaktif(): saat user bilang "tidak",
    AKIRA tidak langsung membatalkan — dia bertanya bagian mana yang salah.
    Mengulang seluruh perintah demi mengganti satu kata itu menyebalkan.

    Alur tiap putaran:
      "ya"            -> selesai, True
      koreksi         -> field diperbarui, ringkasan dibacakan ulang
      "tidak"         -> tanya "bagian mana yang salah?"; jawabannya
                         diperlakukan sebagai koreksi. Kalau user tetap
                         menolak atau diam, baru dibatalkan.
      tidak jelas     -> minta ulangi
    """
    from src.nlp.correction import parse_koreksi, terapkan, ucapkan_perubahan

    sudah_tanya_bagian = False

    for putaran in range(1, max_putaran + 1):
        pertanyaan = bangun_pertanyaan()
        ask_fn(pertanyaan)
        jawaban = listen_fn()
        hasil = tafsir_ya_tidak(jawaban)

        if hasil is True:
            logger.info("User mengonfirmasi")
            return True

        # Beberapa tanggal sekaligus: SEMUA koreksi lewat jalur per tanggal.
        # Kalau diterapkan ke field umum, nilai per tanggal yang sudah ada
        # akan menimpanya saat menyimpan — koreksinya hilang diam-diam.
        if len(data.get("tanggal_lain") or []) > 1 and not minta_batal_tegas(jawaban):
            if _koreksi_per_tanggal(data, jawaban, ask_fn, listen_fn, use_llm):
                sudah_tanya_bagian = False
                continue

        # Koreksi dicoba DULU, bahkan untuk jawaban yang terdengar seperti
        # penolakan: "bukan, kegiatannya futsal" mengandung kata "bukan"
        # tapi jelas berisi perbaikan.
        perubahan = parse_koreksi(data, jawaban, use_llm=use_llm, model=model)
        if perubahan:
            terapkan(data, perubahan)
            ask_fn(f"Baik Bos, saya ubah {ucapkan_perubahan(perubahan)}.")
            sudah_tanya_bagian = False
            continue

        if hasil is False:
            # "Batalkan" itu perintah, bukan keberatan atas satu detail.
            # Menanyakan "bagian mana yang salah" setelah itu terasa seperti
            # tidak mendengarkan.
            if minta_batal_tegas(jawaban):
                logger.info("User membatalkan secara tegas")
                return False

            if sudah_tanya_bagian:
                logger.info("User menolak lagi tanpa koreksi, dibatalkan")
                return False

            # "Tidak" atau "salah" saja belum tentu ingin membatalkan —
            # mungkin cuma satu field yang keliru.
            ask_fn("Bagian mana yang salah, Bos? Sebutkan yang benar saja.")
            jawaban2 = listen_fn()

            perubahan = parse_koreksi(data, jawaban2, use_llm=use_llm, model=model)
            if perubahan:
                terapkan(data, perubahan)
                ask_fn(f"Baik Bos, saya ubah {ucapkan_perubahan(perubahan)}.")
                sudah_tanya_bagian = False
                continue

            if tafsir_ya_tidak(jawaban2) is False or not jawaban2.strip():
                logger.info("User membatalkan setelah ditanya bagian mana")
                return False

            sudah_tanya_bagian = True
            continue

        # Aturan dan pemahaman koreksi sama-sama menyerah. Sebelum meminta
        # user mengulang, tanyakan ke penalaran apakah jawaban itu
        # sebenarnya persetujuan atau penolakan yang tidak lazim.
        if use_llm and (jawaban or "").strip():
            tafsiran = tafsir_dengan_penalaran(jawaban, pertanyaan)
            if tafsiran is True:
                logger.info("User mengonfirmasi (lewat penalaran)")
                return True
            if tafsiran is False:
                logger.info("User menolak (lewat penalaran)")
                return False

        if putaran < max_putaran:
            ask_fn("Maaf Bos, jawab ya atau sebutkan bagian yang perlu diubah.")

    logger.info("Konfirmasi tidak selesai sampai batas putaran, aksi dibatalkan")
    return False


# Penanda "pilih semuanya", bukan salah satu.
SEMUA_KANDIDAT = "SEMUA"

# Bentuk berakhiran -nya WAJIB untuk kata urutan: "ketiganya" berarti
# semuanya, tapi "yang ketiga" berarti nomor 3. Tanpa pembedaan ini,
# memilih satu jadwal bisa berubah jadi menghapus tiga.
PILIH_SEMUA = re.compile(
    r"\b(?:semua(?:nya)?|seluruhnya|sekalian|borong)\b"
    r"|\b(?:keduanya|ketiganya|keempatnya|kelimanya)\b"
    r"|\b(?:dua-?duanya|tiga-?tiganya|empat-?empatnya)\b"
)


def tafsir_pilihan(text: str, jumlah: int):
    """
    Tafsirkan jawaban user jadi indeks pilihan (0-based) dari daftar kandidat.

    Menerima angka ("dua", "2", "yang kedua"), kata batal, dan permintaan
    memilih SEMUANYA ("dua-duanya", "semuanya") yang mengembalikan
    SEMUA_KANDIDAT.

    Perhatikan urutannya: "dua-duanya" mengandung kata "dua" dan dulu terbaca
    sebagai memilih nomor 2 — sasaran yang salah, dan untuk penghapusan itu
    berbahaya. Karena itu "semua" diperiksa DULU.
    """
    if not text:
        return None
    t = text.lower().strip(" .,!?")

    if any(re.search(rf"\b{k}\b", t) for k in ("batal", "batalkan", "jangan", "tidak jadi")):
        return None

    if PILIH_SEMUA.search(t):
        logger.info("User memilih SEMUA kandidat")
        return SEMUA_KANDIDAT

    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= jumlah:
            return n - 1

    for kata, n in ANGKA_UCAPAN.items():
        if re.search(rf"\b{kata}\b", t) and n <= jumlah:
            return n - 1

    return None


def pilih_kandidat(kandidat: list, deskripsi_fn, ask_fn, listen_fn):
    """
    Bacakan daftar kandidat dan minta user memilih.

    kandidat     : list event
    deskripsi_fn : fungsi(event) -> str, kalimat pendek untuk dibacakan

    Return:
      int            indeks terpilih (0-based)
      SEMUA_KANDIDAT user ingin semuanya ("dua-duanya", "semuanya")
      None           dibatalkan atau tidak jelas
    """
    if not kandidat:
        return None
    if len(kandidat) == 1:
        return 0

    daftar = ". ".join(
        f"Nomor {i + 1}, {deskripsi_fn(e)}" for i, e in enumerate(kandidat[:5])
    )
    ask_fn(
        f"Ada {len(kandidat)} jadwal yang cocok, Bos. {daftar}. "
        f"Pilih nomor berapa, atau bilang semuanya?"
    )

    jawaban = listen_fn()
    pilihan = tafsir_pilihan(jawaban, min(len(kandidat), 5))

    if pilihan is None:
        logger.info(f"Pilihan tidak jelas dari jawaban '{jawaban}', dibatalkan")
        return None

    # SEMUA_KANDIDAT adalah string, bukan indeks — menambahinya 1 untuk log
    # membuat fungsi ini gagal tepat sebelum penghapusan dijalankan.
    if pilihan == SEMUA_KANDIDAT:
        logger.info(f"User memilih SEMUA {len(kandidat)} kandidat")
        return pilihan

    logger.info(f"User memilih kandidat nomor {pilihan + 1}")
    return pilihan


if __name__ == "__main__":
    # python -m src.dialog.confirmation
    print("=== Tafsir ya / tidak ===")
    for t in ["ya", "iya benar", "sudah benar", "oke", "tidak", "salah Bos",
              "batalkan aja", "hmm", "", "nggak jadi ya"]:
        print(f"  {t!r:20} -> {tafsir_ya_tidak(t)}")

    print("\n=== Tafsir pilihan (dari 3 kandidat) ===")
    for t in ["nomor dua", "2", "yang ketiga", "batal", "apa ya"]:
        print(f"  {t!r:20} -> {tafsir_pilihan(t, 3)}")

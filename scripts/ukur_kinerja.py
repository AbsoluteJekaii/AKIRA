"""
Hitung metrik kinerja AKIRA dari log — untuk Tabel 7.5 proposal.

Semua angka diambil dari logs/akira.log yang ditulis AKIRA sendiri, jadi
tidak ada yang diperkirakan. Jalankan dari folder `akira`:

    python scripts/ukur_kinerja.py perintah --mulai 14:00 --sampai 14:45
    python scripts/ukur_kinerja.py wake     --mulai 14:50 --sampai 14:55
    python scripts/ukur_kinerja.py palsu    --mulai 15:00 --sampai 15:30
    python scripts/ukur_kinerja.py groq

`--mulai` dan `--sampai` adalah jam (HH:MM) pada tanggal terakhir di log,
atau tambahkan `--tanggal 2026-09-30`.

Mode `perintah` mencocokkan ucapan dengan scripts/kalimat_uji.txt SESUAI
URUTAN, lalu menulis scripts/hasil_uji.csv untuk diperiksa manual: skrip
hanya bisa menilai AKSI, sedangkan benar-tidaknya detail (tanggal, jam,
nama kegiatan) tetap harus dinilai manusia.
"""
import argparse
import csv
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Format berkas log (bawaan loguru): "2026-09-30 14:48:09.123 | INFO | modul:fungsi:baris - pesan"
POLA_BERKAS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}\.\d+)\s*\|\s*(\w+)\s*\|\s*[^-]*- (.*)$")
# Format terminal: "14:48:09 | INFO | pesan" (bila log disalin dari layar)
POLA_TERMINAL = re.compile(r"^(\d{2}:\d{2}:\d{2})\s*\|\s*(\w+)\s*\|\s*(.*)$")


@dataclass
class Baris:
    waktu: datetime
    pesan: str


@dataclass
class Ucapan:
    rekaman_selesai: datetime | None = None
    whisper: str = ""
    akhir: str = ""
    waktu_transkripsi: datetime | None = None
    jawab_pertama: datetime | None = None
    aksi: str = ""
    groq: list = field(default_factory=list)


def baca_log(path: Path) -> list:
    hasil = []
    for teks in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = POLA_BERKAS.match(teks)
        if m:
            tgl, jam, _, pesan = m.groups()
            hasil.append(Baris(datetime.strptime(f"{tgl} {jam[:12]}", "%Y-%m-%d %H:%M:%S.%f"), pesan))
            continue
        m = POLA_TERMINAL.match(teks)
        if m:
            jam, _, pesan = m.groups()
            hasil.append(Baris(datetime.combine(datetime.today(), time.fromisoformat(jam)), pesan))
    return hasil


def saring_waktu(baris: list, mulai: str, sampai: str, tanggal: str | None) -> list:
    if not baris:
        return baris
    hari = datetime.strptime(tanggal, "%Y-%m-%d").date() if tanggal else baris[-1].waktu.date()
    t0 = datetime.combine(hari, time.fromisoformat(mulai)) if mulai else None
    t1 = datetime.combine(hari, time.fromisoformat(sampai)) if sampai else None
    return [b for b in baris if b.waktu.date() == hari
            and (t0 is None or b.waktu >= t0) and (t1 is None or b.waktu <= t1)]


def kumpulkan_ucapan(baris: list) -> list:
    """Satu ucapan = satu baris 'Transkripsi [...]', beserta yang terjadi sesudahnya."""
    daftar, kini, rekaman, whisper = [], None, None, ""
    for b in baris:
        p = b.pesan
        if p.startswith("Rekaman selesai"):
            rekaman, whisper = b.waktu, ""
        elif p.strip().startswith("[whisper] '"):
            whisper = p.strip()[len("[whisper] '"):-1]
        elif p.startswith("Transkripsi ["):
            kini = Ucapan(rekaman_selesai=rekaman, whisper=whisper,
                          akhir=p.split("]: '", 1)[-1].rstrip("'"), waktu_transkripsi=b.waktu)
            daftar.append(kini)
        elif kini is not None:
            if p.startswith("AKIRA: ") and kini.jawab_pertama is None:
                kini.jawab_pertama = b.waktu
            if not kini.aksi:
                m = re.search(r"'aksi': '(\w+)'", p) if p.startswith("Hasil parsing") else None
                if m:
                    kini.aksi = m.group(1)
                elif p.startswith("Timer dipasang"):
                    kini.aksi = "timer"
                elif p.startswith("Alarm dipasang"):
                    kini.aksi = "alarm"
                elif p.startswith("Nama panggilan diubah") or p.startswith("Permintaan ganti nama"):
                    kini.aksi = "ganti_nama"
            if p.startswith(("Groq memahami", "Groq menafsirkan", "Groq menalar", "Perekonsiliasi")):
                kini.groq.append(p)
    return daftar


# ------------------------------------------------------------------ teks
def _normal(teks: str) -> list:
    try:
        from src.nlp.text_normalizer import normalize
        teks = normalize(teks)
    except Exception:
        teks = teks.lower()
    return re.sub(r"[^\w\s]", " ", teks).split()


def _mirip(a: str, b: str) -> float:
    ka, kb = set(_normal(a)), set(_normal(b))
    return len(ka & kb) / len(ka | kb) if ka and kb else 0.0


def _wer(rujukan: str, hipotesis: str) -> float:
    """Word error rate: jarak edit tingkat kata dibagi panjang rujukan."""
    r, h = _normal(rujukan), _normal(hipotesis)
    if not r:
        return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        sebelum, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            sebelum, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, sebelum + (r[i - 1] != h[j - 1]))
    return d[len(h)] / len(r)


def baca_kalimat_uji(path: Path) -> list:
    hasil = []
    for baris in path.read_text(encoding="utf-8").splitlines():
        baris = baris.strip()
        if baris and not baris.startswith("#") and "|" in baris:
            aksi, kalimat = (x.strip() for x in baris.split("|", 1))
            hasil.append((aksi, kalimat))
    return hasil


def cocokkan(uji: list, ucapan: list) -> list:
    """Cocokkan kalimat uji ke ucapan sesuai urutan (ucapan jawaban dialog dilompati)."""
    hasil, j = [], 0
    for aksi, kalimat in uji:
        terbaik, skor = None, 0.0
        for k in range(j, min(j + 8, len(ucapan))):
            s = _mirip(kalimat, ucapan[k].akhir)
            if s > skor:
                terbaik, skor = k, s
        if terbaik is not None and skor >= 0.3:
            hasil.append((aksi, kalimat, ucapan[terbaik], skor))
            j = terbaik + 1
        else:
            hasil.append((aksi, kalimat, None, 0.0))
    return hasil


# ------------------------------------------------------------------ mode
def mode_perintah(baris, args):
    uji = baca_kalimat_uji(Path(args.kalimat))
    ucapan = kumpulkan_ucapan(baris)
    pasangan = cocokkan(uji, ucapan)

    benar_aksi = sum(1 for a, _, u, _ in pasangan if u and u.aksi == a)
    terekam = [p for p in pasangan if p[2]]
    latensi = [(u.jawab_pertama - u.rekaman_selesai).total_seconds()
               for u in (p[2] for p in terekam)
               if u.rekaman_selesai and u.jawab_pertama
               and 0 < (u.jawab_pertama - u.rekaman_selesai).total_seconds() < 30]
    wer_lokal = [_wer(k, u.whisper) for _, k, u, _ in terekam if u.whisper]
    wer_akhir = [_wer(k, u.akhir) for _, k, u, _ in terekam]
    tepat_lokal = sum(1 for _, k, u, _ in terekam if u.whisper and _wer(k, u.whisper) <= 0.15)
    tepat_akhir = sum(1 for _, k, u, _ in terekam if _wer(k, u.akhir) <= 0.15)

    out = Path(args.keluaran)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["no", "kalimat uji", "transkripsi whisper lokal", "transkripsi akhir (ensemble)",
                    "aksi diharapkan", "aksi dikenali", "aksi benar", "detail benar? (isi Y/T)"])
        for i, (a, k, u, _) in enumerate(pasangan, 1):
            w.writerow([i, k, u.whisper if u else "(tidak terekam)", u.akhir if u else "",
                        a, u.aksi if u else "", "Y" if u and u.aksi == a else "T", ""])

    print(f"\nKalimat uji             : {len(uji)}")
    print(f"Terekam di log          : {len(terekam)}")
    print(f"AKSI dikenali benar     : {benar_aksi} / {len(uji)}")
    print(f"  -> buka {out} dan isi kolom 'detail benar?' untuk angka akhir")
    if latensi:
        print(f"\nLatensi (akhir rekaman -> AKIRA mulai menjawab), {len(latensi)} ucapan:")
        print(f"  median {statistics.median(latensi):.1f} dtk | rata-rata {statistics.mean(latensi):.1f} dtk"
              f" | tercepat {min(latensi):.1f} | terlama {max(latensi):.1f}")
    if wer_lokal:
        print("\nPengaruh ensemble (terhadap kalimat uji yang sama):")
        print(f"  Whisper lokal saja : kesalahan kata {statistics.mean(wer_lokal) * 100:.0f}% | "
              f"transkripsi tepat {tepat_lokal} / {len(wer_lokal)}")
        print(f"  Tiga mesin         : kesalahan kata {statistics.mean(wer_akhir) * 100:.0f}% | "
              f"transkripsi tepat {tepat_akhir} / {len(wer_akhir)}")
        print("  ('tepat' = kesalahan kata <= 15%; angka dibandingkan setelah normalisasi AKIRA)")
    else:
        print("\n(Tidak ada keluaran [whisper] di log — pastikan tiga mesin STT aktif)")


def mode_wake(baris, _args):
    deteksi = [b for b in baris if "terdeteksi!" in b.pesan and "Wake word" in b.pesan]
    skor = [float(m.group(1)) for b in deteksi if (m := re.search(r"skor ([\d.]+)", b.pesan))]
    print(f"\nWake word terdeteksi : {len(deteksi)} kali")
    if skor:
        print(f"Skor                 : terendah {min(skor):.3f} | tertinggi {max(skor):.3f}")
    print("Bandingkan dengan jumlah ucapan \"AKIRA WAKE UP\" selama rentang waktu itu.")


def mode_palsu(baris, _args):
    pola = ("terdeteksi!", "Disapa tanpa wake word", "Frasa bangun terdeteksi")
    kejadian = [b for b in baris if any(p in b.pesan for p in pola)]
    print(f"\nPemicuan selama rentang waktu ini : {len(kejadian)} kali")
    for b in kejadian:
        print(f"  {b.waktu:%H:%M:%S}  {b.pesan[:90]}")
    print("Selama rentang ini tidak ada yang memanggil AKIRA, jadi setiap baris di atas adalah pemicuan palsu.")


def mode_groq(baris, _args):
    jenis = {
        "Rekonsiliasi transkripsi": "Perekonsiliasi '",
        "Terjemahan maksud": "Groq memahami",
        "Tafsir jawaban": "Groq menafsirkan",
        "Koreksi per tanggal": "Groq menalar",
        "Penilaian sapaan": "untuk AKIRA",
    }
    print()
    for nama, penanda in jenis.items():
        cocok = [b for b in baris if penanda in b.pesan and ("Groq" in b.pesan or "Perekonsiliasi" in b.pesan)]
        print(f"{nama:26}: {len(cocok)} kali")
        for b in cocok[:2]:
            print(f"    contoh {b.waktu:%H:%M:%S}: {b.pesan[:95]}")
    gagal = [b for b in baris if "Groq" in b.pesan and ("gagal" in b.pesan.lower() or "tidak tersedia" in b.pesan.lower())]
    print(f"\nPanggilan Groq yang gagal : {len(gagal)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["perintah", "wake", "palsu", "groq"])
    ap.add_argument("--log", default="logs/akira.log")
    ap.add_argument("--mulai", help="HH:MM")
    ap.add_argument("--sampai", help="HH:MM")
    ap.add_argument("--tanggal", help="YYYY-MM-DD (bawaan: tanggal terakhir di log)")
    ap.add_argument("--kalimat", default="scripts/kalimat_uji.txt")
    ap.add_argument("--keluaran", default="scripts/hasil_uji.csv")
    args = ap.parse_args()

    path = Path(args.log)
    if not path.exists():
        sys.exit(f"Log tidak ditemukan: {path}. Jalankan dari folder akira.")
    baris = saring_waktu(baca_log(path), args.mulai, args.sampai, args.tanggal)
    if not baris:
        sys.exit("Tidak ada baris log pada rentang waktu itu.")
    print(f"{len(baris)} baris log, {baris[0].waktu:%Y-%m-%d %H:%M:%S} - {baris[-1].waktu:%H:%M:%S}")
    {"perintah": mode_perintah, "wake": mode_wake, "palsu": mode_palsu, "groq": mode_groq}[args.mode](baris, args)


if __name__ == "__main__":
    main()

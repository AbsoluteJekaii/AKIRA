"""
Antarmuka grafis AKIRA.
Tanggung jawab: Person 4 (Dialog UX & QA Lead) — Sprint 4

Jalankan dengan:  python akira_app.py

Empat tab:
  Status     — kesiapan komponen, tombol jalan/berhenti, log langsung
  Kalender   — lihat, segarkan, dan hapus jadwal
  Perintah   — jalur ketik saat suara bermasalah
  Pengaturan — ubah config tanpa membuka editor teks

Dibangun dengan Tkinter karena sudah menyatu dengan Python — tidak menambah
satu pun dependensi. Untuk aplikasi yang harus andal saat demo, jumlah
komponen yang bisa rusak adalah hal yang perlu ditekan.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.gui.tema import WARNA, Kartu, Lencana, pasang_tema

# Sensitivitas self destruct, dipetakan ke ambang skor model wake word.
#
# Ditampilkan sebagai tingkat, bukan angka mentah: "0.7" tidak berarti apa pun
# bagi pemakai, sedangkan "Sedang" langsung dipahami. Sensitivitas TINGGI
# berarti ambang RENDAH — lebih mudah terpicu, termasuk tanpa sengaja.
#
# Dua batas yang disengaja:
# - Atas 0.85, bukan 0.95: di atas itu frasa rahasia nyaris mustahil dipicu,
#   dan pengujian menunjukkan 0.8 pun sudah terlalu sulit.
# - Bawah 0.65, SELALU di atas ambang wake word utama (0.6). Kedua frasa
#   diawali "AKIRA"; kalau ambangnya sama, "AKIRA WAKE UP" berisiko ikut
#   menaikkan skor frasa penghancur. Salah picu di arah ini fatal.
TINGKAT_SENSITIVITAS = {
    "Rendah (sulit terpicu)": 0.85,
    "Sedang": 0.72,
    "Tinggi (mudah terpicu)": 0.65,
}


class AplikasiAkira(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AKIRA")
        # Seukuran jendela pesan, bukan jendela penuh. Aplikasi ini dipakai
        # berdampingan dengan pekerjaan lain — memenuhi layar justru merepotkan.
        self.geometry("880x620")
        self.minsize(760, 540)

        self.font = pasang_tema(self)
        self.config_data = self._muat_config()

        self._buat_kepala()
        self._buat_tab()
        self._pantau_log()
        self.protocol("WM_DELETE_WINDOW", self._tutup)

    def _buka_halaman(self, indeks: int):
        """Tampilkan satu halaman dan tandai tombolnya di navigasi."""
        for i, (_, _, frame) in enumerate(self._halaman):
            item, penanda, teks, lbl_judul, lbl_sub = self._tombol_nav[i]
            aktif = i == indeks
            latar = WARNA["aksen_lembut"] if aktif else WARNA["panel"]
            for w in (item, teks, lbl_judul, lbl_sub):
                w.configure(bg=latar)
            penanda.configure(bg=WARNA["aksen"] if aktif else latar)
            lbl_judul.configure(fg=WARNA["aksen"] if aktif else WARNA["teks"])
            if aktif:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

    # ----------------------------------------------------------- kepala
    def _buat_kepala(self):
        """
        Baris atas: nama aplikasi, status berjalan, dan tombol utama.

        Status ditaruh di sini — bukan di dalam tab — supaya selalu terlihat
        dari tab mana pun. Pertanyaan "AKIRA-nya jalan atau tidak?" adalah
        yang paling sering muncul saat memakai aplikasi ini.
        """
        kepala = tk.Frame(self, bg=WARNA["panel"])
        kepala.pack(fill="x")

        isi = ttk.Frame(kepala, style="Panel.TFrame")
        isi.pack(fill="x", padx=16, pady=11)

        kiri = ttk.Frame(isi, style="Panel.TFrame")
        kiri.pack(side="left")
        ttk.Label(kiri, text="AKIRA", style="Judul.TLabel").pack(anchor="w")
        ttk.Label(kiri, text="Audio-driven Kalendar & Interactive Reminder Assistant",
                  style="Lembut.TLabel").pack(anchor="w")

        kanan = ttk.Frame(isi, style="Panel.TFrame")
        kanan.pack(side="right")

        self.tombol_jalan = ttk.Button(kanan, text="Jalankan AKIRA",
                                       style="Aksen.TButton", command=self._mulai)
        self.tombol_jalan.pack(side="right")

        self.lencana_jalan = Lencana(kanan, "netral", "Berhenti", font=self.font["kecil"])
        self.lencana_jalan.pack(side="right", padx=(0, 14))

        tk.Frame(self, bg=WARNA["garis"], height=1).pack(fill="x")

    # ------------------------------------------------------------- utilitas
    def _muat_config(self) -> dict:
        try:
            import yaml

            with open("config/settings.yaml", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            messagebox.showerror("Config", f"Gagal membaca settings.yaml:\n{e}")
            return {}

    def _di_latar(self, fungsi, selesai=None):
        """
        Jalankan pekerjaan lambat di thread terpisah.

        Semua yang menyentuh jaringan atau model WAJIB lewat sini. Memanggilnya
        langsung dari tombol akan membekukan jendela selama beberapa detik —
        dan Windows menandainya "Not Responding".
        """
        def bungkus():
            try:
                hasil = fungsi()
            except Exception as e:
                hasil = e
            if selesai:
                # after() menjadwalkan di thread Tkinter; memperbarui widget
                # dari thread lain menyebabkan crash yang sulit dilacak.
                self.after(0, lambda: selesai(hasil))

        threading.Thread(target=bungkus, daemon=True).start()

    # ------------------------------------------------------------------ tab
    def _buat_tab(self):
        """
        Navigasi samping + area isi.

        Pola ini menggantikan deretan tab di atas. Dengan navigasi samping,
        halaman aktif selalu jelas dari penanda warnanya, dan isi halaman
        mendapat lebar penuh — tab di atas memakan satu baris tinggi dan
        membuat lima judulnya tampak setara padahal Status jauh lebih sering
        dibuka.
        """
        badan = tk.Frame(self, bg=WARNA["latar"])
        badan.pack(fill="both", expand=True)

        samping = tk.Frame(badan, bg=WARNA["panel"], width=176)
        samping.pack(side="left", fill="y")
        samping.pack_propagate(False)
        tk.Frame(badan, bg=WARNA["garis"], width=1).pack(side="left", fill="y")

        self._area = tk.Frame(badan, bg=WARNA["latar"])
        self._area.pack(side="left", fill="both", expand=True, padx=14, pady=12)

        self.tab_status = ttk.Frame(self._area)
        self.tab_kalender = ttk.Frame(self._area)
        self.tab_perintah = ttk.Frame(self._area)
        self.tab_pintasan = ttk.Frame(self._area)
        self.tab_setelan = ttk.Frame(self._area)

        self._halaman = [
            ("Status", "Kesiapan & log", self.tab_status),
            ("Kalender", "Jadwal mendatang", self.tab_kalender),
            ("Perintah", "Ketik perintah", self.tab_perintah),
            ("Pintasan", "Tanpa bicara", self.tab_pintasan),
            ("Pengaturan", "Setelan AKIRA", self.tab_setelan),
        ]
        self._tombol_nav = []
        tk.Frame(samping, bg=WARNA["panel"], height=10).pack(fill="x")

        for i, (judul, sub, _) in enumerate(self._halaman):
            item = tk.Frame(samping, bg=WARNA["panel"], cursor="hand2")
            item.pack(fill="x", padx=8, pady=2)
            penanda = tk.Frame(item, bg=WARNA["panel"], width=3)
            penanda.pack(side="left", fill="y")
            teks = tk.Frame(item, bg=WARNA["panel"])
            teks.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=7)
            lbl_judul = tk.Label(teks, text=judul, bg=WARNA["panel"], fg=WARNA["teks"],
                                 font=self.font["subjudul"], anchor="w")
            lbl_judul.pack(fill="x")
            lbl_sub = tk.Label(teks, text=sub, bg=WARNA["panel"], fg=WARNA["teks_redup"],
                               font=self.font["kecil"], anchor="w")
            lbl_sub.pack(fill="x")

            bagian = (item, penanda, teks, lbl_judul, lbl_sub)
            self._tombol_nav.append(bagian)
            for w in bagian:
                w.bind("<Button-1>", lambda _e, n=i: self._buka_halaman(n))

        self._buka_halaman(0)

        self._isi_tab_status()
        self._isi_tab_kalender()
        self._isi_tab_perintah()
        self._isi_tab_pintasan()
        self._isi_tab_setelan()
        self._pasang_pintasan(diam=True)

    # ---------------------------------------------------------- tab: status
    def _isi_tab_status(self):
        f = self.tab_status

        kartu = Kartu(
            f, "Kesiapan Komponen",
            "Periksa sebelum demo. Hijau siap, kuning perlu perhatian, "
            "merah harus diperbaiki.",
            font=self.font,
        )
        kartu.pack(fill="x", pady=(0, 10))

        bar = ttk.Frame(kartu.isi, style="Panel.TFrame")
        bar.pack(fill="x", pady=(0, 12))
        ttk.Button(bar, text="Periksa Komponen",
                   command=self._periksa).pack(side="left")
        ttk.Button(bar, text="Uji Mikrofon",
                   command=self._uji_mic).pack(side="left", padx=8)

        self.label_status = ttk.Label(bar, text="Belum diperiksa", style="Lembut.TLabel")
        self.label_status.pack(side="right")

        self.tabel_komponen = ttk.Treeview(
            kartu.isi, columns=("status", "ket"), show="tree headings", height=7
        )
        self.tabel_komponen.heading("#0", text="KOMPONEN")
        self.tabel_komponen.heading("status", text="STATUS")
        self.tabel_komponen.heading("ket", text="KETERANGAN")
        # Lebar awal dijumlah < lebar area isi; kolom terakhir yang melar.
        # Sebelumnya total 890 px — kolom keterangan terpotong di tepi kanan.
        self.tabel_komponen.column("#0", width=170, minwidth=140, stretch=False)
        self.tabel_komponen.column("status", width=96, minwidth=90, anchor="center", stretch=False)
        self.tabel_komponen.column("ket", width=360, minwidth=200, stretch=True)
        self.tabel_komponen.pack(fill="x")

        for status in ("ok", "peringatan", "gagal"):
            self.tabel_komponen.tag_configure(status, foreground=WARNA[status])

        kartu_log = Kartu(f, "Log", "Apa yang sedang dikerjakan AKIRA.",
                          font=self.font)
        kartu_log.pack(fill="both", expand=True)

        bingkai = tk.Frame(kartu_log.isi, bg=WARNA["log_latar"])
        bingkai.pack(fill="both", expand=True)

        self.teks_log = tk.Text(
            bingkai, bg=WARNA["log_latar"], fg=WARNA["log_teks"],
            font=self.font["mono"], wrap="word", state="disabled",
            bd=0, padx=14, pady=12, insertbackground=WARNA["log_teks"],
        )
        gulir = ttk.Scrollbar(bingkai, command=self.teks_log.yview)
        self.teks_log.configure(yscrollcommand=gulir.set)
        gulir.pack(side="right", fill="y")
        self.teks_log.pack(side="left", fill="both", expand=True)

        # Panel hitam kosong tanpa keterangan terlihat seperti rusak.
        self._log_kosong = True
        self.teks_log.configure(state="normal")
        self.teks_log.insert("end", "Log akan muncul di sini setelah AKIRA dijalankan.")
        self.teks_log.configure(state="disabled")

    def _periksa(self):
        self._set_status("Memeriksa...")
        for baris in self.tabel_komponen.get_children():
            self.tabel_komponen.delete(baris)

        def kerja():
            from src.gui.runner import cek_komponen

            return cek_komponen(self.config_data)

        def selesai(hasil):
            if isinstance(hasil, Exception):
                self._set_status(f"Gagal memeriksa: {hasil}")
                return

            gagal = sum(1 for _, s, _ in hasil if s == "gagal")
            for nama, status, ket in hasil:
                label = Lencana.GAYA[status][2]
                self.tabel_komponen.insert(
                    "", "end", text=nama, values=(label, ket), tags=(status,)
                )

            if gagal:
                self._set_status(f"{gagal} komponen belum siap")
            else:
                self._set_status("Semua komponen penting siap")

        self._di_latar(kerja, selesai)

    def _uji_mic(self):
        self._set_status("Merekam 3 detik — bicaralah...")

        def kerja():
            from src.gui.runner import uji_mikrofon

            return uji_mikrofon(3.0)

        def selesai(hasil):
            if isinstance(hasil, Exception):
                messagebox.showerror("Mikrofon", str(hasil))
                self._set_status("Uji mikrofon gagal")
                return
            baik, pesan = hasil
            (messagebox.showinfo if baik else messagebox.showwarning)("Mikrofon", pesan)
            self._set_status(pesan)

        self._di_latar(kerja, selesai)

    def _mulai(self):
        from src.gui.runner import mulai, sedang_berjalan

        if sedang_berjalan():
            messagebox.showinfo("AKIRA", "AKIRA sudah berjalan.")
            return

        if mulai():
            self.tombol_jalan.config(state="disabled", text="Sedang Berjalan")
            self._set_lencana("ok", "Berjalan")
            self._set_status("Panggil 'AKIRA WAKE UP' atau pakai tab Pintasan")

    def _set_status(self, teks):
        """Baris status kecil di tab Status."""
        self.label_status.config(text=teks)

    def _set_lencana(self, status: str, teks: str):
        """Penanda berjalan/berhenti di kepala jendela, terlihat dari tab mana pun."""
        self.lencana_jalan.ubah(status, teks)

    def _pantau_log(self):
        """Salin log dari antrean ke kotak teks setiap 200 ms."""
        try:
            from src.gui.runner import baca_log

            baris = baca_log()
            if baris:
                self.teks_log.config(state="normal")
                if self._log_kosong:
                    self.teks_log.delete("1.0", "end")
                    self._log_kosong = False
                for b in baris:
                    self.teks_log.insert("end", b + "\n")
                # Batasi panjang: log panjang membuat Tkinter melambat
                if int(self.teks_log.index("end-1c").split(".")[0]) > 1500:
                    self.teks_log.delete("1.0", "500.0")
                self.teks_log.see("end")
                self.teks_log.config(state="disabled")
        except Exception as e:
            # Jangan ditelan diam-diam: kalau jalur ini gagal, panel Log
            # kosong tanpa jejak — persis gejala yang sulit dilacak.
            print(f"[antarmuka] gagal menampilkan log: {e}")
        self.after(200, self._pantau_log)

    # -------------------------------------------------------- tab: kalender
    def _isi_tab_kalender(self):
        f = self.tab_kalender

        kartu = Kartu(
            f, "Jadwal Mendatang",
            "Diambil langsung dari Google Calendar. Pilih baris lalu Hapus "
            "untuk menghapus (bisa lebih dari satu dengan Ctrl+klik).",
            font=self.font,
        )
        kartu.pack(fill="both", expand=True)

        bar = ttk.Frame(kartu.isi, style="Panel.TFrame")
        bar.pack(fill="x", pady=(0, 12))

        ttk.Button(bar, text="Muat Jadwal", style="Aksen.TButton",
                   command=self._muat_jadwal).pack(side="left")

        self.pilihan_rentang = ttk.Combobox(
            bar, width=18, state="readonly",
            values=["7 hari ke depan", "30 hari ke depan", "90 hari ke depan"],
        )
        self.pilihan_rentang.current(0)
        self.pilihan_rentang.pack(side="left", padx=10)

        ttk.Button(bar, text="Hapus Terpilih", style="Bahaya.TButton",
                   command=self._hapus_jadwal).pack(side="left")

        self.label_kalender = ttk.Label(bar, text="Belum dimuat", style="Lembut.TLabel")
        self.label_kalender.pack(side="right")

        bingkai = ttk.Frame(kartu.isi, style="Panel.TFrame")
        bingkai.pack(fill="both", expand=True)

        self.tabel_jadwal = ttk.Treeview(
            bingkai, columns=("tanggal", "jam", "kegiatan"), show="headings"
        )
        for kolom, judul, lebar in [
            ("tanggal", "TANGGAL", 170), ("jam", "JAM", 150), ("kegiatan", "KEGIATAN", 300)
        ]:
            self.tabel_jadwal.heading(kolom, text=judul)
            self.tabel_jadwal.column(kolom, width=lebar, stretch=(kolom == "kegiatan"))

        gulir = ttk.Scrollbar(bingkai, command=self.tabel_jadwal.yview)
        self.tabel_jadwal.configure(yscrollcommand=gulir.set)
        gulir.pack(side="right", fill="y")
        self.tabel_jadwal.pack(side="left", fill="both", expand=True)

        self._peta_event = {}

    def _muat_jadwal(self):
        self.label_kalender.config(text="Memuat...")
        hari = int(self.pilihan_rentang.get().split()[0])

        def kerja():
            from datetime import datetime, timedelta

            from src.calendar_service.executor import _ambil_event_rentang

            mulai = datetime.now().strftime("%Y-%m-%d")
            akhir = (datetime.now() + timedelta(days=hari)).strftime("%Y-%m-%d")
            return _ambil_event_rentang(mulai, akhir)

        def selesai(hasil):
            if isinstance(hasil, Exception):
                self.label_kalender.config(text="Gagal memuat")
                messagebox.showerror(
                    "Kalender",
                    f"{hasil}\n\nKalau muncul 'invalid_grant', token kedaluwarsa:\n"
                    f"hapus config/token.json lalu jalankan AKIRA untuk login ulang.",
                )
                return

            for baris in self.tabel_jadwal.get_children():
                self.tabel_jadwal.delete(baris)
            self._peta_event.clear()

            from src.nlp.date_time_parser import ucapkan_tanggal

            for e in hasil:
                mulai = e.get("start", {})
                dt = mulai.get("dateTime") or mulai.get("date", "")
                tanggal = ucapkan_tanggal(dt[:10], sebut_hari=True)
                jam = dt[11:16] if mulai.get("dateTime") else "sepanjang hari"
                baris = self.tabel_jadwal.insert(
                    "", "end", values=(tanggal, jam, e.get("summary", "(tanpa nama)"))
                )
                self._peta_event[baris] = e

            self.label_kalender.config(text=f"{len(hasil)} jadwal")

        self._di_latar(kerja, selesai)

    def _hapus_jadwal(self):
        terpilih = self.tabel_jadwal.selection()
        if not terpilih:
            messagebox.showinfo("Kalender", "Pilih jadwal yang mau dihapus dulu.")
            return

        judul = [self._peta_event[b].get("summary", "?") for b in terpilih]
        if not messagebox.askyesno(
            "Konfirmasi",
            f"Hapus {len(terpilih)} jadwal berikut?\n\n" + "\n".join(f"- {j}" for j in judul)
            + "\n\nTindakan ini tidak bisa dibatalkan.",
        ):
            return

        event_terpilih = [self._peta_event[b] for b in terpilih]

        def kerja():
            from src.calendar_service.executor import hapus_banyak

            return hapus_banyak(event_terpilih)

        def selesai(hasil):
            if isinstance(hasil, Exception):
                messagebox.showerror("Kalender", str(hasil))
                return
            messagebox.showinfo("Kalender", hasil["message"])
            self._muat_jadwal()

        self._di_latar(kerja, selesai)

    # -------------------------------------------------------- tab: perintah
    def _isi_tab_perintah(self):
        f = self.tab_perintah

        kartu = Kartu(
            f, "Ketik Perintah",
            "Jalur cadangan saat suara bermasalah. Ketik seperti yang biasa "
            "diucapkan, lalu tekan Enter.",
            font=self.font,
        )
        kartu.pack(fill="both", expand=True)

        baris = ttk.Frame(kartu.isi, style="Panel.TFrame")
        baris.pack(fill="x")

        self.isian_perintah = ttk.Entry(baris, font=self.font["isi"])
        self.isian_perintah.pack(side="left", fill="x", expand=True)
        self.isian_perintah.bind("<Return>", lambda _: self._kirim_perintah())

        ttk.Button(baris, text="Kirim", style="Aksen.TButton",
                   command=self._kirim_perintah).pack(side="left", padx=(10, 0))
        ttk.Button(baris, text="Uraikan Saja",
                   command=self._urai_perintah).pack(side="left", padx=(8, 0))

        opsi = ttk.Frame(kartu.isi, style="Panel.TFrame")
        opsi.pack(fill="x", pady=(10, 0))

        self.pakai_suara = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opsi, text="Jawab dengan suara", variable=self.pakai_suara,
        ).pack(side="left")

        ttk.Label(
            opsi, style="Redup.TLabel",
            text=("  — AKIRA menjawab lewat speaker dan bisa bertanya balik "
                  "kalau perintahnya belum lengkap"),
        ).pack(side="left")

        ttk.Label(
            kartu.isi, style="Redup.TLabel",
            text=('Contoh:  "catat meeting besok jam 3 sore"   '
                  '"cek jadwal besok"   "sekarang jam berapa"'),
        ).pack(anchor="w", pady=(8, 10))

        bingkai = tk.Frame(kartu.isi, bg=WARNA["latar"])
        bingkai.pack(fill="x")
        self.hasil_perintah = tk.Text(
            bingkai, height=5, font=self.font["mono"], wrap="word",
            state="disabled", bd=0, bg=WARNA["latar"], fg=WARNA["teks"],
            padx=14, pady=12,
        )
        self.hasil_perintah.pack(fill="x")


    def _tulis_hasil(self, teks):
        self.hasil_perintah.config(state="normal")
        self.hasil_perintah.delete("1.0", "end")
        self.hasil_perintah.insert("1.0", teks)
        self.hasil_perintah.config(state="disabled")

    def _urai_perintah(self):
        kalimat = self.isian_perintah.get().strip()
        if not kalimat:
            return
        self._tulis_hasil("Menguraikan...")

        def kerja():
            from src.nlp.parser import parse_command

            return parse_command(kalimat, use_slm=True,
                                 model=self.config_data.get("nlp", {}).get("ollama_model"))

        def selesai(hasil):
            if isinstance(hasil, Exception):
                self._tulis_hasil(f"Gagal: {hasil}")
                return
            penting = {k: v for k, v in hasil.items() if v not in (None, [], {}, False)}
            self._tulis_hasil(
                "\n".join(f"{k:18} : {v}" for k, v in penting.items())
            )

        self._di_latar(kerja, selesai)

    def _kirim_perintah(self):
        """
        Jalankan perintah ketik. Dua jalur, tergantung pilihan "Jawab dengan suara".

        **Dengan suara** — perintah dititipkan ke sesi AKIRA yang sedang
        berjalan. Hasilnya sama persis dengan mengucapkannya: AKIRA menjawab
        lewat speaker, bertanya balik kalau ada yang kurang, dan meminta
        konfirmasi untuk aksi yang mengubah data. Ini yang membuat perintah
        tidak lengkap tetap bisa diselesaikan.

        **Tanpa suara** — dieksekusi langsung dan hasilnya ditulis di kotak
        bawah. Cepat, tapi hanya untuk perintah yang sudah lengkap dan tidak
        destruktif.
        """
        kalimat = self.isian_perintah.get().strip()
        if not kalimat:
            return

        if self.pakai_suara.get():
            self._kirim_lewat_suara(kalimat)
        else:
            self._kirim_diam(kalimat)

    def _kirim_lewat_suara(self, kalimat):
        from src.gui.runner import sedang_berjalan
        from src.utils import trigger

        if not sedang_berjalan():
            self._tulis_hasil(
                "AKIRA belum berjalan.\n\n"
                "Jalankan dulu di tab Status, atau hilangkan centang "
                "'Jawab dengan suara' untuk menjalankan tanpa suara."
            )
            return

        trigger.picu_perintah(kalimat, sumber="ketikan")
        self._tulis_hasil(
            f"Dikirim ke AKIRA: \"{kalimat}\"\n\n"
            f"Dengarkan jawabannya lewat speaker. Kalau AKIRA bertanya balik, "
            f"jawab lewat mikrofon — atau ketik lagi di sini.\n\n"
            f"Jalannya bisa dipantau di tab Status."
        )
        self.isian_perintah.delete(0, "end")

    def _kirim_diam(self, kalimat):
        self._tulis_hasil("Memproses...")

        def kerja():
            from src.calendar_service.executor import execute
            from src.dialog.state_machine import check_missing_fields
            from src.nlp.parser import parse_command

            data = parse_command(kalimat, use_slm=True,
                                 model=self.config_data.get("nlp", {}).get("ollama_model"))

            if not data.get("aksi"):
                return {"ok": False, "pesan": "Maksud perintah tidak dikenali."}

            kurang = check_missing_fields(data)
            if kurang:
                return {"ok": False, "pesan":
                        f"Perintah belum lengkap — {', '.join(kurang)} belum disebut.\n"
                        f"Centang 'Jawab dengan suara' agar AKIRA bisa bertanya, "
                        f"atau lengkapi kalimatnya."}

            if data["aksi"] in ("hapus", "reschedule", "edit"):
                return {"ok": False, "pesan":
                        f"Aksi '{data['aksi']}' perlu konfirmasi.\n"
                        f"Centang 'Jawab dengan suara', atau hapus lewat tab Kalender."}

            hasil = execute(data)
            return {"ok": hasil.get("success"), "pesan": hasil.get("message")}

        def selesai(hasil):
            if isinstance(hasil, Exception):
                self._tulis_hasil(f"Gagal: {hasil}")
                return
            tanda = "BERHASIL" if hasil["ok"] else "TIDAK DIJALANKAN"
            self._tulis_hasil(f"[{tanda}]\n{hasil['pesan']}")
            if hasil["ok"]:
                self.isian_perintah.delete(0, "end")

        self._di_latar(kerja, selesai)

    # --------------------------------------------------------- tab: pintasan
    def _isi_tab_pintasan(self):
        f = self.tab_pintasan

        kartu = Kartu(
            f, "Aksi Cepat",
            "Membangunkan AKIRA tanpa wake word. Konfirmasi tetap berjalan "
            "seperti biasa — yang dilewati hanya frasa aktivasinya.",
            font=self.font,
        )
        kartu.pack(fill="x", pady=(0, 10))

        grup = [
            ("Mendengarkan", [("Dengarkan Sekarang", "dengar", True)]),
            ("Membaca", [("Jadwal Hari Ini", "baca_hari_ini", False),
                         ("Jadwal Besok", "baca_besok", False),
                         ("Jam Berapa", "jam_berapa", False)]),
            ("Mengubah jadwal", [("Catat", "catat", False),
                                 ("Hapus", "hapus", False),
                                 ("Pindah", "reschedule", False),
                                 ("Edit", "edit", False)]),
        ]

        # Label kelompok sebaris dengan tombolnya — di baris sendiri, tiga
        # label memakan ruang yang dibutuhkan tabel pintasan di bawahnya.
        for judul, tombol in grup:
            baris = ttk.Frame(kartu.isi, style="Panel.TFrame")
            baris.pack(fill="x", pady=3)
            ttk.Label(baris, text=judul.upper(), style="Redup.TLabel",
                      width=17).pack(side="left")
            for label, aksi, utama in tombol:
                ttk.Button(
                    baris, text=label,
                    style="Aksen.TButton" if utama else "TButton",
                    command=lambda a=aksi: self._picu(a),
                ).pack(side="left", padx=(0, 8))

        kartu2 = Kartu(
            f, "Pintasan Keyboard",
            "Wajib memakai Ctrl, Alt, atau Shift — tanpa itu, tombol biasa "
            "akan memicu AKIRA saat kamu mengetik di aplikasi lain.",
            font=self.font,
        )
        kartu2.pack(fill="both", expand=True)

        form = ttk.Frame(kartu2.isi, style="Panel.TFrame")
        form.pack(fill="x", pady=(0, 10))

        ttk.Label(form, text="Aksi", style="Lembut.TLabel").pack(side="left")
        from src.gui.hotkeys import AKSI_PINTASAN

        self._nama_ke_aksi = {nama: kunci for kunci, (nama, _) in AKSI_PINTASAN.items()}
        self.pilihan_aksi_pintasan = ttk.Combobox(
            form, width=20, state="readonly", values=list(self._nama_ke_aksi)
        )
        self.pilihan_aksi_pintasan.current(0)
        self.pilihan_aksi_pintasan.pack(side="left", padx=(8, 12))

        ttk.Label(form, text="Kombinasi", style="Lembut.TLabel").pack(side="left")
        self.isian_kombinasi = ttk.Entry(form, width=11)
        self.isian_kombinasi.insert(0, "ctrl+alt+")
        self.isian_kombinasi.pack(side="left", padx=(8, 12))

        # Tombol di baris sendiri: empat kontrol dalam satu baris tidak muat
        # di jendela ringkas — tombol terakhir sempat terdorong keluar layar.
        tombol = ttk.Frame(kartu2.isi, style="Panel.TFrame")
        tombol.pack(fill="x", pady=(0, 8))
        ttk.Button(tombol, text="Pasang", style="Aksen.TButton",
                   command=self._pasang_satu).pack(side="left")
        ttk.Button(tombol, text="Lepas Terpilih", style="Bahaya.TButton",
                   command=self._lepas_satu).pack(side="left", padx=8)

        self.label_pintasan = ttk.Label(kartu2.isi, text="", style="Lembut.TLabel",
                                        wraplength=600, justify="left")
        self.label_pintasan.pack(anchor="w", pady=(0, 10))

        self.tabel_pintasan = ttk.Treeview(
            kartu2.isi, columns=("kombinasi", "aksi", "jelas"), show="headings", height=6
        )
        for kolom, judul, lebar in [
            ("kombinasi", "KOMBINASI", 120),
            ("aksi", "AKSI", 190),
            ("jelas", "KETERANGAN", 310),
        ]:
            self.tabel_pintasan.heading(kolom, text=judul)
            self.tabel_pintasan.column(kolom, width=lebar, stretch=(kolom == "jelas"))
        self.tabel_pintasan.pack(fill="both", expand=True)

        self._muat_pintasan()

    def _picu(self, aksi):
        """Kirim aksi ke mesin AKIRA lewat saluran pemicu."""
        from src.gui.hotkeys import _jalankan
        from src.gui.runner import sedang_berjalan

        if aksi != "buka_jendela" and not sedang_berjalan():
            messagebox.showinfo(
                "AKIRA belum berjalan",
                "Jalankan AKIRA dulu di tab Status, baru aksi ini bisa dipakai.",
            )
            return

        _jalankan(aksi, saat_buka_jendela=self._ke_depan)
        self._set_status(f"Pemicu '{aksi}' dikirim")

    def _ke_depan(self):
        """Munculkan jendela ke depan. Dipanggil pintasan 'buka_jendela'."""
        self.after(0, lambda: (self.deiconify(), self.lift(), self.focus_force()))

    def _muat_pintasan(self):
        from src.gui.hotkeys import AKSI_PINTASAN, muat

        for baris in self.tabel_pintasan.get_children():
            self.tabel_pintasan.delete(baris)
        for aksi, kombinasi in muat().items():
            nama, jelas = AKSI_PINTASAN.get(aksi, (aksi, ""))
            self.tabel_pintasan.insert("", "end", values=(kombinasi, nama, jelas))

    def _pasang_satu(self):
        from src.gui.hotkeys import muat, simpan, validasi

        nama = self.pilihan_aksi_pintasan.get()
        aksi = self._nama_ke_aksi.get(nama)
        semua = muat()

        boleh, hasil = validasi(self.isian_kombinasi.get(), aksi, semua)
        if not boleh:
            messagebox.showwarning("Tidak bisa dipasang", hasil)
            return

        semua[aksi] = hasil
        if simpan(semua):
            self._muat_pintasan()
            self._pasang_pintasan()

    def _lepas_satu(self):
        from src.gui.hotkeys import muat, simpan

        terpilih = self.tabel_pintasan.selection()
        if not terpilih:
            return
        semua = muat()
        for baris in terpilih:
            kombinasi = self.tabel_pintasan.item(baris)["values"][0]
            semua = {a: k for a, k in semua.items() if k != kombinasi}
        if simpan(semua):
            self._muat_pintasan()
            self._pasang_pintasan()

    def _pasang_pintasan(self, diam=False):
        """
        Pasang pintasan global, lalu pasang cadangan dalam jendela.

        Cadangan selalu dipasang — meski pintasan global berhasil. Kalau
        pustaka `keyboard` gagal menangkap tombol (di Windows kadang butuh
        hak Administrator), pintasan tetap berfungsi saat jendela aktif.
        """
        from src.gui.hotkeys import ke_format_tkinter, muat, pasang_global

        pemasangan = muat()
        berhasil, pesan = pasang_global(pemasangan, saat_buka_jendela=self._ke_depan)

        if hasattr(self, "label_pintasan"):
            self.label_pintasan.config(text=pesan)

        for aksi, kombinasi in pemasangan.items():
            urutan = ke_format_tkinter(kombinasi)
            if urutan:
                try:
                    self.bind_all(urutan, lambda _e, a=aksi: self._picu(a))
                except Exception:
                    pass

        if not diam and not berhasil:
            messagebox.showinfo("Pintasan", pesan)

    # ------------------------------------------------------ tab: pengaturan
    def _isi_tab_setelan(self):
        f = self.tab_setelan

        kartu = Kartu(
            f, "Pengaturan",
            "Berlaku setelah AKIRA dijalankan ulang. Menyimpan lewat sini "
            "menghapus komentar penjelasan di settings.yaml.",
            font=self.font,
        )
        kartu.pack(fill="both", expand=True)

        isi = ttk.Frame(kartu.isi, style="Panel.TFrame")
        isi.pack(fill="both", expand=True)
        isi.columnconfigure(1, minsize=200)
        isi.columnconfigure(3, minsize=200)

        self.kolom_setelan = {}
        setelan = [
            ("Nama panggilan", ("_khusus", "nama_panggilan"), "teks"),
            ("Model LLM lokal", ("nlp", "ollama_model"), "teks"),
            ("Ambang wake word", ("wakeword", "threshold"), "angka"),
            ("Ambang derau mikrofon", ("audio", "rms_ambang"), "angka"),
            ("Jeda diam (frame)", ("audio", "max_silence_frames"), "angka"),
            ("Model Whisper lokal", ("stt", "model_size"), "pilihan:tiny,base,small,medium"),
            ("Mode ambient", ("ambient", "enabled"), "boolean"),
            ("Ambient timeout (menit)", ("ambient", "timeout_menit"), "angka"),
            ("Briefing saat start", ("dialog", "briefing_on_start"), "boolean"),
            ("Cakupan briefing (hari)", ("dialog", "briefing_days"), "angka"),
            ("Tingkat self destruct", ("self_destruct", "tingkat"), "pilihan:data,model,total"),
            ("Cadangan self destruct", ("self_destruct", "backup"), "boolean"),
            ("Sensitivitas self destruct", ("self_destruct", "threshold"), "sensitivitas"),
            ("Self destruct lewat teks", ("self_destruct", "aktif_lewat_teks"), "boolean"),
        ]

        # Dua kolom: 12 baris tunggal memaksa menggulir tanpa alasan
        per_kolom = (len(setelan) + 1) // 2
        for i, (label, jalur, jenis) in enumerate(setelan):
            baris, kolom = i % per_kolom, (i // per_kolom) * 2

            ttk.Label(isi, text=label, style="Panel.TLabel").grid(
                row=baris, column=kolom, sticky="w", pady=9, padx=(0, 12))

            nilai = self._ambil_nilai(jalur)
            if jenis == "sensitivitas":
                var = tk.StringVar(value=self._ambang_ke_tingkat(nilai))
                widget = ttk.Combobox(isi, textvariable=var, state="readonly",
                                      width=18, values=list(TINGKAT_SENSITIVITAS))
            elif jenis == "boolean":
                var = tk.BooleanVar(value=bool(nilai))
                widget = ttk.Checkbutton(isi, variable=var)
            elif jenis.startswith("pilihan:"):
                var = tk.StringVar(value=str(nilai))
                widget = ttk.Combobox(isi, textvariable=var, state="readonly",
                                      width=18, values=jenis.split(":")[1].split(","))
            else:
                var = tk.StringVar(value="" if nilai is None else str(nilai))
                widget = ttk.Entry(isi, textvariable=var, width=20)

            widget.grid(row=baris, column=kolom + 1, sticky="w", padx=(0, 40))
            self.kolom_setelan[label] = (jalur, jenis, var)

        tombol = ttk.Frame(kartu.isi, style="Panel.TFrame")
        tombol.pack(fill="x", pady=(18, 0))
        ttk.Button(tombol, text="Simpan", style="Aksen.TButton",
                   command=self._simpan_setelan).pack(side="left")
        ttk.Button(tombol, text="Muat Ulang",
                   command=self._muat_ulang_setelan).pack(side="left", padx=8)

        self.label_setelan = ttk.Label(tombol, text="", style="Lembut.TLabel")
        self.label_setelan.pack(side="right")

    @staticmethod
    def _ambang_ke_tingkat(ambang) -> str:
        """Ambil tingkat terdekat dari nilai ambang di config."""
        try:
            ambang = float(ambang)
        except (TypeError, ValueError):
            return "Sedang"
        return min(TINGKAT_SENSITIVITAS,
                   key=lambda t: abs(TINGKAT_SENSITIVITAS[t] - ambang))

    def _ambil_nilai(self, jalur):
        if jalur[0] == "_khusus":
            from src.utils.user_settings import get_nama_panggilan

            return get_nama_panggilan()
        simpul = self.config_data
        for k in jalur:
            if not isinstance(simpul, dict):
                return None
            simpul = simpul.get(k)
        return simpul

    def _muat_ulang_setelan(self):
        self.config_data = self._muat_config()
        for label, (jalur, jenis, var) in self.kolom_setelan.items():
            nilai = self._ambil_nilai(jalur)
            if jenis == "boolean":
                var.set(bool(nilai))
            elif jenis == "sensitivitas":
                var.set(self._ambang_ke_tingkat(nilai))
            else:
                var.set("" if nilai is None else str(nilai))
        self.label_setelan.config(text="Dimuat ulang dari berkas")

    def _simpan_setelan(self):
        import yaml

        from src.utils.user_settings import set_nama_panggilan

        try:
            for label, (jalur, jenis, var) in self.kolom_setelan.items():
                nilai = var.get()

                if jalur[0] == "_khusus":
                    if str(nilai).strip():
                        set_nama_panggilan(str(nilai))
                    continue

                if jenis == "angka":
                    teks = str(nilai).strip()
                    nilai = float(teks) if "." in teks else int(teks)
                elif jenis == "boolean":
                    nilai = bool(nilai)
                elif jenis == "sensitivitas":
                    nilai = TINGKAT_SENSITIVITAS.get(nilai, 0.7)

                simpul = self.config_data
                for k in jalur[:-1]:
                    simpul = simpul.setdefault(k, {})
                simpul[jalur[-1]] = nilai

            with open("config/settings.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config_data, f, allow_unicode=True, sort_keys=False)

            self.label_setelan.config(text="Tersimpan")
            messagebox.showinfo(
                "Pengaturan",
                "Tersimpan.\n\nCatatan: komentar penjelasan di settings.yaml "
                "hilang saat disimpan lewat antarmuka.\n\n"
                "Jalankan ulang AKIRA agar perubahan berlaku.",
            )
        except ValueError as e:
            messagebox.showerror("Pengaturan", f"Nilai tidak valid: {e}")
        except Exception as e:
            messagebox.showerror("Pengaturan", f"Gagal menyimpan: {e}")

    # ---------------------------------------------------------------- tutup
    def _tutup(self):
        from src.gui.runner import sedang_berjalan

        if sedang_berjalan():
            if not messagebox.askyesno(
                "Tutup", "AKIRA sedang berjalan. Tutup aplikasi dan hentikan AKIRA?"
            ):
                return
        self.destroy()


def main():
    if not os.path.exists("config/settings.yaml"):
        print("Jalankan dari folder akira (tempat run.py berada).")
        sys.exit(1)
    AplikasiAkira().mainloop()


if __name__ == "__main__":
    main()

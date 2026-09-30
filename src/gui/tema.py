"""
Tema visual aplikasi AKIRA.
Tanggung jawab: Person 4 (Dialog UX) — Sprint 4.2

Tkinter bawaan terlihat kuno karena memakai tema "winnative" yang tidak
berubah sejak Windows 95: sudut siku, warna abu-abu sistem, jarak antar
elemen nyaris nol, dan satu ukuran huruf untuk semuanya.

Tiga hal yang paling mengubah kesan, berurutan dari yang paling berpengaruh:

1. **Jarak.** Elemen yang berdempetan terlihat berantakan apa pun warnanya.
2. **Hierarki huruf.** Judul, isi, dan keterangan harus jelas berbeda.
3. **Warna terbatas.** Satu warna aksen saja; sisanya abu-abu bertingkat.

Tema "clam" dipakai sebagai dasar karena satu-satunya tema bawaan ttk yang
benar-benar menghormati pengaturan warna kustom di Windows.
"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# Palet: satu aksen, sisanya netral bertingkat.
WARNA = {
    "latar": "#f6f7f9",
    "panel": "#ffffff",
    "garis": "#e3e6ea",
    "garis_tebal": "#cdd3da",
    "teks": "#1c2024",
    "teks_lembut": "#6b7280",
    "teks_redup": "#9aa2ac",
    "aksen": "#2563eb",
    "aksen_gelap": "#1d4ed8",
    "aksen_lembut": "#eff4ff",
    "ok": "#15803d",
    "ok_lembut": "#ecfdf3",
    "peringatan": "#b45309",
    "peringatan_lembut": "#fffaeb",
    "gagal": "#b42318",
    "gagal_lembut": "#fef3f2",
    "log_latar": "#11161c",
    "log_teks": "#d5dbe3",
}


def pasang_tema(root: tk.Misc) -> dict:
    """
    Terapkan tema dan kembalikan kamus font siap pakai.

    Dipanggil sekali di awal, sebelum widget apa pun dibuat.
    """
    gaya = ttk.Style(root)
    gaya.theme_use("clam")

    keluarga = _pilih_font(root)
    font = {
        "judul": tkfont.Font(family=keluarga, size=15, weight="bold"),
        "subjudul": tkfont.Font(family=keluarga, size=11, weight="bold"),
        "isi": tkfont.Font(family=keluarga, size=10),
        "kecil": tkfont.Font(family=keluarga, size=9),
        "mono": tkfont.Font(family=_pilih_mono(root), size=9),
    }

    root.configure(bg=WARNA["latar"])

    # --- Dasar
    gaya.configure(".", background=WARNA["latar"], foreground=WARNA["teks"],
                   font=font["isi"], borderwidth=0, focuscolor=WARNA["aksen"])

    gaya.configure("TFrame", background=WARNA["latar"])
    gaya.configure("Panel.TFrame", background=WARNA["panel"])

    gaya.configure("TLabel", background=WARNA["latar"], foreground=WARNA["teks"])
    gaya.configure("Panel.TLabel", background=WARNA["panel"])
    gaya.configure("Judul.TLabel", font=font["judul"], background=WARNA["panel"])
    gaya.configure("Subjudul.TLabel", font=font["subjudul"], background=WARNA["panel"])
    gaya.configure("Lembut.TLabel", font=font["kecil"],
                   foreground=WARNA["teks_lembut"], background=WARNA["panel"])
    gaya.configure("Redup.TLabel", font=font["kecil"],
                   foreground=WARNA["teks_redup"], background=WARNA["panel"])

    # --- Tombol
    #
    # Tema clam menggambar tepi dari TIGA properti sekaligus: bordercolor,
    # lightcolor, dan darkcolor. Mengatur bordercolor saja membuat tepinya
    # tidak terlihat sama sekali — tombol tampak seperti teks biasa, dan
    # orang tidak tahu itu bisa diklik.
    gaya.configure("TButton", padding=(12, 7), background=WARNA["panel"],
                   foreground=WARNA["teks"], borderwidth=1, relief="solid",
                   bordercolor=WARNA["garis_tebal"],
                   lightcolor=WARNA["garis_tebal"],
                   darkcolor=WARNA["garis_tebal"])
    gaya.map("TButton",
             background=[("pressed", WARNA["aksen_lembut"]),
                         ("active", WARNA["aksen_lembut"]),
                         ("disabled", WARNA["latar"])],
             foreground=[("active", WARNA["aksen_gelap"]),
                         ("disabled", WARNA["teks_redup"])],
             bordercolor=[("active", WARNA["aksen"])],
             lightcolor=[("active", WARNA["aksen"])],
             darkcolor=[("active", WARNA["aksen"])])

    gaya.configure("Aksen.TButton", padding=(15, 8), background=WARNA["aksen"],
                   foreground="#ffffff", borderwidth=1, relief="solid",
                   bordercolor=WARNA["aksen"], lightcolor=WARNA["aksen"],
                   darkcolor=WARNA["aksen"])
    gaya.map("Aksen.TButton",
             background=[("pressed", WARNA["aksen_gelap"]),
                         ("active", WARNA["aksen_gelap"]),
                         ("disabled", WARNA["garis_tebal"])],
             foreground=[("disabled", "#ffffff")],
             bordercolor=[("active", WARNA["aksen_gelap"]),
                          ("disabled", WARNA["garis_tebal"])],
             lightcolor=[("active", WARNA["aksen_gelap"]),
                         ("disabled", WARNA["garis_tebal"])],
             darkcolor=[("active", WARNA["aksen_gelap"]),
                        ("disabled", WARNA["garis_tebal"])])

    gaya.configure("Bahaya.TButton", padding=(12, 7), background=WARNA["panel"],
                   foreground=WARNA["gagal"], borderwidth=1, relief="solid",
                   bordercolor=WARNA["garis_tebal"],
                   lightcolor=WARNA["garis_tebal"],
                   darkcolor=WARNA["garis_tebal"])
    gaya.map("Bahaya.TButton",
             background=[("active", WARNA["gagal_lembut"])],
             bordercolor=[("active", WARNA["gagal"])],
             lightcolor=[("active", WARNA["gagal"])],
             darkcolor=[("active", WARNA["gagal"])])

    # --- Tab
    gaya.configure("TNotebook", background=WARNA["latar"], borderwidth=0,
                   tabmargins=(0, 4, 0, 0))
    gaya.configure("TNotebook.Tab", padding=(16, 9), background=WARNA["latar"],
                   foreground=WARNA["teks_lembut"], borderwidth=1,
                   bordercolor=WARNA["latar"], lightcolor=WARNA["latar"],
                   darkcolor=WARNA["latar"], font=font["isi"])
    gaya.map("TNotebook.Tab",
             background=[("selected", WARNA["panel"]),
                         ("active", WARNA["aksen_lembut"])],
             foreground=[("selected", WARNA["aksen"])],
             bordercolor=[("selected", WARNA["garis"])],
             lightcolor=[("selected", WARNA["panel"])],
             darkcolor=[("selected", WARNA["panel"])])

    # --- Tabel
    gaya.configure("Treeview", background=WARNA["panel"], fieldbackground=WARNA["panel"],
                   foreground=WARNA["teks"], rowheight=27, borderwidth=1,
                   relief="solid", bordercolor=WARNA["garis"],
                   lightcolor=WARNA["garis"], darkcolor=WARNA["garis"],
                   font=font["isi"])
    gaya.configure("Treeview.Heading", background=WARNA["latar"],
                   foreground=WARNA["teks_lembut"], font=font["kecil"],
                   padding=(10, 8), borderwidth=0, relief="flat")
    gaya.map("Treeview",
             background=[("selected", WARNA["aksen_lembut"])],
             foreground=[("selected", WARNA["teks"])])
    gaya.map("Treeview.Heading", background=[("active", WARNA["latar"])])

    # --- Isian
    gaya.configure("TEntry", padding=9, fieldbackground=WARNA["panel"],
                   foreground=WARNA["teks"], borderwidth=1, relief="solid",
                   bordercolor=WARNA["garis_tebal"],
                   lightcolor=WARNA["garis_tebal"],
                   darkcolor=WARNA["garis_tebal"],
                   insertcolor=WARNA["teks"])
    gaya.map("TEntry",
             bordercolor=[("focus", WARNA["aksen"])],
             lightcolor=[("focus", WARNA["aksen"])],
             darkcolor=[("focus", WARNA["aksen"])])

    gaya.configure("TCombobox", padding=8, fieldbackground=WARNA["panel"],
                   background=WARNA["panel"], foreground=WARNA["teks"],
                   borderwidth=1, relief="solid",
                   bordercolor=WARNA["garis_tebal"],
                   lightcolor=WARNA["garis_tebal"],
                   darkcolor=WARNA["garis_tebal"],
                   arrowcolor=WARNA["teks_lembut"], arrowsize=14)
    gaya.map("TCombobox",
             fieldbackground=[("readonly", WARNA["panel"])],
             background=[("readonly", WARNA["panel"])],
             bordercolor=[("focus", WARNA["aksen"])],
             lightcolor=[("focus", WARNA["aksen"])],
             darkcolor=[("focus", WARNA["aksen"])])

    gaya.configure("TCheckbutton", background=WARNA["panel"])
    gaya.map("TCheckbutton", background=[("active", WARNA["panel"])])

    gaya.configure("TScrollbar", background=WARNA["latar"], borderwidth=0,
                   troughcolor=WARNA["latar"], arrowcolor=WARNA["teks_redup"])

    gaya.configure("TSeparator", background=WARNA["garis"])

    return font


def _pilih_font(root) -> str:
    """Pilih font antarmuka terbaik yang tersedia di sistem."""
    tersedia = set(tkfont.families(root))
    for nama in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue",
                 "Ubuntu", "DejaVu Sans"):
        if nama in tersedia:
            return nama
    return "TkDefaultFont"


def _pilih_mono(root) -> str:
    tersedia = set(tkfont.families(root))
    for nama in ("Cascadia Mono", "Consolas", "JetBrains Mono", "Menlo",
                 "DejaVu Sans Mono"):
        if nama in tersedia:
            return nama
    return "TkFixedFont"


class Kartu(ttk.Frame):
    """
    Panel putih dengan judul dan keterangan.

    Menggantikan LabelFrame bawaan, yang menggambar kotak bergaris di sekeliling
    isinya — pola visual yang membuat antarmuka terlihat seperti aplikasi lama.
    """

    def __init__(self, induk, judul: str, keterangan: str = "", font: dict = None,
                 **kwargs):
        super().__init__(induk, style="Panel.TFrame", **kwargs)

        kepala = ttk.Frame(self, style="Panel.TFrame")
        kepala.pack(fill="x", padx=14, pady=(11, 0))

        ttk.Label(kepala, text=judul, style="Subjudul.TLabel").pack(anchor="w")
        if keterangan:
            ket = ttk.Label(kepala, text=keterangan, style="Lembut.TLabel",
                            wraplength=600, justify="left")
            ket.pack(anchor="w", fill="x", pady=(2, 0))
            # Lebar lipatan mengikuti lebar kartu. Angka tetap pernah
            # membuat teks terpotong saat tata letak berubah.
            kepala.bind("<Configure>", lambda e, l=ket: l.configure(wraplength=max(200, e.width - 8)))

        self.isi = ttk.Frame(self, style="Panel.TFrame")
        self.isi.pack(fill="both", expand=True, padx=14, pady=(9, 12))


class Lencana(tk.Label):
    """
    Penanda status berwarna: SIAP / PERHATIAN / GAGAL.

    Lebih mudah dipindai daripada teks biasa — mata menangkap warna sebelum
    membaca kata.
    """

    GAYA = {
        "ok": (WARNA["ok"], WARNA["ok_lembut"], "SIAP"),
        "peringatan": (WARNA["peringatan"], WARNA["peringatan_lembut"], "PERHATIAN"),
        "gagal": (WARNA["gagal"], WARNA["gagal_lembut"], "GAGAL"),
        "netral": (WARNA["teks_lembut"], WARNA["latar"], "—"),
    }

    def __init__(self, induk, status: str = "netral", teks: str = None, font=None):
        depan, belakang, label = self.GAYA.get(status, self.GAYA["netral"])
        super().__init__(
            induk, text=teks or label, fg=depan, bg=belakang,
            font=font, padx=10, pady=3, bd=0,
        )

    def ubah(self, status: str, teks: str = None):
        depan, belakang, label = self.GAYA.get(status, self.GAYA["netral"])
        self.config(text=teks or label, fg=depan, bg=belakang)



# ============================================================
#  Mencabut auto-start AKIRA.
#
#      powershell -ExecutionPolicy Bypass -File scripts\hapus_autostart.ps1
#
#  Ini TIDAK menghapus kode atau data apa pun — hanya membatalkan
#  penjadwalan agar AKIRA tidak lagi jalan sendiri saat login.
# ============================================================

$NamaTask = "AKIRA Voice Assistant"

if (-not (Get-ScheduledTask -TaskName $NamaTask -ErrorAction SilentlyContinue)) {
    Write-Host "Auto-start memang belum terpasang. Tidak ada yang perlu dicabut."
    exit 0
}

# Hentikan dulu kalau sedang berjalan, supaya prosesnya tidak menggantung
Stop-ScheduledTask -TaskName $NamaTask -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $NamaTask -Confirm:$false

Write-Host "[BERHASIL] Auto-start dicabut. AKIRA tidak akan jalan sendiri lagi." -ForegroundColor Green
Write-Host "Untuk menjalankan manual seperti biasa:  python run.py"

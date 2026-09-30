# ============================================================
#  Mendaftarkan AKIRA agar jalan otomatis saat login Windows.
#
#  Jalankan sekali dari folder proyek:
#      powershell -ExecutionPolicy Bypass -File scripts\pasang_autostart.ps1
#
#  Untuk mencabutnya:  scripts\hapus_autostart.ps1
# ============================================================

$ErrorActionPreference = "Stop"

$NamaTask   = "AKIRA Voice Assistant"
$FolderKode = Split-Path -Parent $PSScriptRoot
$Peluncur   = Join-Path $PSScriptRoot "akira_start_hidden.vbs"
$Venv       = Join-Path $FolderKode "venv\Scripts\python.exe"

Write-Host "Folder proyek : $FolderKode"
Write-Host "Peluncur      : $Peluncur"
Write-Host ""

# --- Pemeriksaan sebelum mendaftarkan ---------------------------------
if (-not (Test-Path $Peluncur)) {
    Write-Host "[GAGAL] $Peluncur tidak ditemukan." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Venv)) {
    Write-Host "[GAGAL] venv belum dibuat. Jalankan dulu:" -ForegroundColor Red
    Write-Host "        python -m venv venv"
    exit 1
}
if (-not (Test-Path (Join-Path $FolderKode "models\akira_wake_up.onnx"))) {
    Write-Host "[PERINGATAN] Model wake word belum ada." -ForegroundColor Yellow
    Write-Host "             AKIRA akan gagal start. Lanjut mendaftarkan saja."
}

# --- Susun task -------------------------------------------------------
$Aksi = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "`"$Peluncur`"" -WorkingDirectory $FolderKode

# Jeda 1 menit setelah login: wifi, driver audio, dan Ollama perlu waktu
# untuk siap. Tanpa jeda, percobaan pertama sering gagal.
$Pemicu = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Pemicu.Delay = "PT1M"

# Catatan penting: JANGAN pakai -RunLevel Highest atau "run whether user is
# logged on or not". Keduanya memutus akses ke mikrofon dan speaker.
$Prinsipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

$Pengaturan = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)

# --- Daftarkan --------------------------------------------------------
if (Get-ScheduledTask -TaskName $NamaTask -ErrorAction SilentlyContinue) {
    Write-Host "Task lama ditemukan, diganti..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $NamaTask -Confirm:$false
}

Register-ScheduledTask -TaskName $NamaTask -Action $Aksi -Trigger $Pemicu `
    -Principal $Prinsipal -Settings $Pengaturan `
    -Description "Asisten jadwal berbasis suara. Jalan otomatis saat login." | Out-Null

Write-Host ""
Write-Host "[BERHASIL] AKIRA akan jalan otomatis 1 menit setelah login." -ForegroundColor Green
Write-Host ""
Write-Host "Uji sekarang tanpa restart:"
Write-Host "    Start-ScheduledTask -TaskName '$NamaTask'"
Write-Host ""
Write-Host "Lihat log:"
Write-Host "    Get-Content logs\autostart.log -Tail 30 -Wait"
Write-Host ""
Write-Host "Hentikan sementara:"
Write-Host "    Stop-ScheduledTask -TaskName '$NamaTask'"
Write-Host ""
Write-Host "Cabut sepenuhnya:"
Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\hapus_autostart.ps1"

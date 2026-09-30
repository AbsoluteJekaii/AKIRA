@echo off
rem ============================================================
rem  Peluncur AKIRA — dipakai Task Scheduler saat laptop menyala
rem  Jalankan manual untuk menguji:  scripts\akira_start.bat
rem ============================================================

rem Pindah ke folder proyek (satu tingkat di atas folder scripts ini).
rem %~dp0 selalu berisi path folder skrip ini, jadi tidak ada path
rem yang di-hardcode — folder proyek boleh dipindah tanpa mengedit apa pun.
cd /d "%~dp0.."

rem Pastikan folder log ada sebelum menulis ke sana
if not exist "logs" mkdir "logs"

rem Tunggu jaringan & mikrofon siap. Saat laptop baru menyala, wifi sering
rem belum terhubung dan Edge TTS akan gagal di percobaan pertama.
if "%AKIRA_DELAY_DETIK%"=="" set AKIRA_DELAY_DETIK=20
timeout /t %AKIRA_DELAY_DETIK% /nobreak >nul

echo. >> "logs\autostart.log"
echo ===== AKIRA start: %DATE% %TIME% ===== >> "logs\autostart.log"

rem Pakai python di dalam venv langsung, tanpa "activate".
rem Lebih andal untuk Task Scheduler: tidak bergantung pada
rem ExecutionPolicy PowerShell maupun variabel lingkungan sesi.
if not exist "venv\Scripts\python.exe" (
    echo [GAGAL] venv tidak ditemukan. Buat dulu: python -m venv venv >> "logs\autostart.log"
    exit /b 1
)

"venv\Scripts\python.exe" run.py >> "logs\autostart.log" 2>&1

echo ===== AKIRA berhenti: %DATE% %TIME% (kode %ERRORLEVEL%) ===== >> "logs\autostart.log"

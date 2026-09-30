@echo off
rem ============================================================
rem  Buka antarmuka AKIRA dengan klik ganda, tanpa mengetik.
rem  Taruh pintasan ke berkas ini di Desktop bila perlu.
rem ============================================================
cd /d "%~dp0.."

if not exist "venv\Scripts\python.exe" (
    echo [GAGAL] venv tidak ditemukan. Buat dulu: python -m venv venv
    pause
    exit /b 1
)

rem Jangan pakai pythonw: kalau aplikasi gagal start, pesan errornya
rem harus terlihat. Jendela hitam sedikit mengganggu, tapi jauh lebih
rem baik daripada klik ganda yang tidak menghasilkan apa-apa.
"venv\Scripts\python.exe" akira_app.py

if errorlevel 1 (
    echo.
    echo AKIRA berhenti dengan error. Baca pesan di atas.
    pause
)

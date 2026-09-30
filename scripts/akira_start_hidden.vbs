' ============================================================
'  Menjalankan akira_start.bat TANPA jendela hitam.
'
'  Kenapa perlu: Task Scheduler bisa menyembunyikan jendela lewat opsi
'  "Run whether user is logged on or not", tapi opsi itu memutus akses ke
'  mikrofon dan speaker — AKIRA jadi tuli dan bisu.
'
'  Jadi task-nya dijalankan sebagai user biasa (punya akses audio), dan
'  jendela hitamnya disembunyikan di sini.
' ============================================================

Dim shell, folderSkrip
Set shell = CreateObject("WScript.Shell")

' Folder tempat file .vbs ini berada
folderSkrip = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

' Argumen kedua 0 = jendela disembunyikan
' Argumen ketiga False = jangan tunggu prosesnya selesai
shell.Run """" & folderSkrip & "akira_start.bat""", 0, False

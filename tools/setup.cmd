@echo off
rem Chay ben trong CalForge_Setup.exe (IExpress giai nen app.zip + file nay vao thu muc tam roi goi file nay).
rem Chep tool vao %LOCALAPPDATA%\CalForge Studio (khong can quyen admin), GIU NGUYEN du lieu cu
rem (projects, tai khoan, calforge.json, .venv) khi cai de len ban cu, roi chay buoc cai dat.
title Cai dat CalForge Studio
set "DEST=%LOCALAPPDATA%\CalForge Studio"
set "TMPX=%TEMP%\calforge_setup"
echo.
echo  Dang chep CalForge Studio vao may...
if exist "%TMPX%" rmdir /s /q "%TMPX%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~dp0app.zip' -DestinationPath $env:TMPX -Force"
if errorlevel 1 goto fail
robocopy "%TMPX%\CalForge_Studio" "%DEST%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto fail
rmdir /s /q "%TMPX%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\tools\cai_dat.ps1"
exit /b 0

:fail
echo.
echo  Loi khi chep file. Chup man hinh nay gui nguoi ho tro.
pause
exit /b 1

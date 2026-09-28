@echo off
title CalForge Studio - dong cua so nay la tat tool
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
echo ========================================================
echo   Dang mo CalForge Studio...  (dong cua so nay = tat tool)
echo ========================================================
"%PY%" -m calforge ui
if errorlevel 1 (
  echo.
  echo  Loi khi mo tool. Neu chua cai, hay bam dup CAI_DAT.bat truoc.
  pause
)

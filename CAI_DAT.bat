@echo off
title Cai dat CalForge Studio
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\cai_dat.ps1"

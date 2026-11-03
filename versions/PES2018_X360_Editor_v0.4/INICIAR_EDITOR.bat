@echo off
setlocal
cd /d "%~dp0"
py -3 pes2018_editor_xbox360_v0_4.py %*
if errorlevel 1 pause

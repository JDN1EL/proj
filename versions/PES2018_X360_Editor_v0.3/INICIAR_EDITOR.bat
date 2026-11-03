@echo off
cd /d "%~dp0"
python pes2018_editor_xbox360.py
if errorlevel 1 pause

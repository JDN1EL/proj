@echo off
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PES2018_X360_Editor pes2018_editor_xbox360.py
if errorlevel 1 pause

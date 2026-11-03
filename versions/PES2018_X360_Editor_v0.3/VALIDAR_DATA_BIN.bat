@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Arraste o arquivo data.bin sobre este BAT ou informe o caminho.
  pause
  exit /b 1
)
python pes2018_editor_xbox360.py --validate "%~1"
pause

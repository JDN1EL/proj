@echo off
setlocal
cd /d "%~dp0"
title PES 2018 Xbox 360 Editor v0.8 - Gerar EXE

echo ================================================
echo   PES 2018 Xbox 360 Editor v0.8
echo ================================================
echo.
py -3 --version >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python 3 nao encontrado. Instale Python 3.10 ou superior.
  pause
  exit /b 1
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (echo ERRO: e necessario Python 3.10 ou superior.& pause & exit /b 1)
py -3 -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
  echo Instalando PyInstaller...
  py -3 -m pip install --upgrade pyinstaller
  if errorlevel 1 goto erro
)
echo.
echo Gerando executavel Windows sem conectores de API...
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name PES2018_X360_Editor_v0_8 pes2018_editor_xbox360_v0_8.py
if errorlevel 1 goto erro
echo.
echo SUCESSO: dist\PES2018_X360_Editor_v0_8.exe
echo A base PlayersDB sera salva em %%APPDATA%%\PES2018_X360_Editor\database
pause
exit /b 0
:erro
echo ERRO ao gerar o executavel. Confira Python, PyInstaller e as mensagens acima.
pause
exit /b 1

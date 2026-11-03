@echo off
setlocal
cd /d "%~dp0"
title Gerar PES2018 X360 Editor v0.4 Beta

echo ================================================
echo   PES2018 X360 Editor v0.4 Beta - Gerar EXE
echo ================================================
echo.

py -3 --version >nul 2>nul
if errorlevel 1 (
  echo ERRO: Python 3 nao encontrado.
  echo Instale Python 3.10 ou superior em https://www.python.org/downloads/windows/
  echo Marque a opcao Add Python to PATH durante a instalacao.
  pause
  exit /b 1
)

py -3 -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
  echo Instalando PyInstaller...
  py -3 -m pip install --upgrade pyinstaller
  if errorlevel 1 goto erro
)

echo.
echo Gerando executavel Windows...
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name PES2018_X360_Editor_Beta --hidden-import pes2018_stfs pes2018_editor_xbox360_v0_4.py
if errorlevel 1 goto erro

echo.
echo SUCESSO: dist\PES2018_X360_Editor_Beta.exe
 echo Copie o EXE para qualquer pasta; o modulo STFS ja esta incorporado.
pause
exit /b 0

:erro
echo.
echo ERRO ao gerar o executavel. Verifique a instalacao do Python/PyInstaller.
pause
exit /b 1

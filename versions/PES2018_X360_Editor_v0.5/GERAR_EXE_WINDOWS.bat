@echo off
title Gerando Executavel Windows - PES 2018 Editor v0.5
color 0A
echo ===================================================
echo   Compilador do PES 2018 Xbox 360 Editor v0.5
echo ===================================================
echo.
echo Verificando e instalando PyInstaller e dependencias...
python -m pip install --upgrade pip
pip install pyinstaller requests pillow pypdf

echo.
echo Compilando arquivo pes2018_editor_xbox360_v0_4.py em Executavel Standalone (.exe)...
pyinstaller --noconfirm --onedir --windowed --name "PES2018_X360_Editor_v0.5" pes2018_editor_xbox360_v0_4.py

echo.
echo ===================================================
echo COMPILACAO CONCLUIDA COM SUCESSO!
echo O arquivo executavel (.exe) esta na pasta dist\PES2018_X360_Editor_v0.5\
echo ===================================================
pause

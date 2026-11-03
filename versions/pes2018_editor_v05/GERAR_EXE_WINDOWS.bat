@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (echo Python 3 nao encontrado. Instale em https://www.python.org/downloads/ e marque Add Python to PATH.& pause & exit /b 1)
python -c "import tkinter" >nul 2>nul
if errorlevel 1 (echo Tkinter nao esta disponivel nesta instalacao do Python.& pause & exit /b 1)
python -m pip install --upgrade pyinstaller
if errorlevel 1 (echo Falha ao instalar PyInstaller.& pause & exit /b 1)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PES2018_X360_Editor pes2018_editor_xbox360_v0_5.py --hidden-import=api_rosters
if errorlevel 1 (echo Falha ao gerar EXE.& pause & exit /b 1)
echo EXE criado em dist\PES2018_X360_Editor.exe
pause

@echo off
setlocal
cd /d "%~dp0"
echo ================================================
echo PES 2018 XBOX 360 EDITOR v1.0 - GERAR EXE
echo ================================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher nao encontrado. Instale Python 3.10+ com Tcl/Tk.
  pause
  exit /b 1
)
py -3 -m pip install --upgrade pyinstaller
if errorlevel 1 goto erro
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name PES2018_X360_Editor_v1_0 --hidden-import=editor_core --hidden-import=playersdb_local --hidden-import=official_names --hidden-import=pes2018_stfs --hidden-import=transfer_data --hidden-import=binary_layout --hidden-import=historical_names pes2018_editor_xbox360_v1_0.py
if errorlevel 1 goto erro
for %%F in (team_aliases.csv national_team_aliases.csv competition_aliases.csv player_name_aliases.csv VERSION.txt) do (
  copy /Y "%%F" "dist\%%F" >nul
  if errorlevel 1 goto erro
)
if not exist "dist\logs" mkdir "dist\logs"
echo.
echo EXE criado em: dist\PES2018_X360_Editor_v1_0.exe
echo Mapas CSV copiados para dist. Mantenha-os junto do EXE.
echo Logs e bases serao guardados na pasta do programa/AppData.
pause
exit /b 0
:erro
echo.
echo ERRO ao gerar o EXE. Verifique a instalacao do Python e a conexao para instalar PyInstaller.
pause
exit /b 1

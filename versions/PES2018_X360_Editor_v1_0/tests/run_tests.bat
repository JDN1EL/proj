@echo off
cd /d "%~dp0.."
py -3 -m unittest discover -s tests -p "test_*.py" -v
pause

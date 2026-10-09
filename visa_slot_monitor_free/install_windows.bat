@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if errorlevel 1 goto fail
python -m playwright install chromium
if errorlevel 1 goto fail
if not exist .env copy .env.example .env
 echo.
 echo Installation complete. Open .env in Notepad; follow README_UZ.md
pause
exit /b 0
:fail
 echo Installation failed. Ensure Python 3.11+ is installed and py is on PATH.
pause
exit /b 1

@echo off
cd /d "%~dp0"
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Starting FARHAN GAMEHUB at http://127.0.0.1:5000
python -c "from waitress import serve; from app import app; serve(app, host='127.0.0.1', port=5000, threads=8)"
pause

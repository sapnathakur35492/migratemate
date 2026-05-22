@echo off
cd /d "%~dp0"
echo Adzuna USA scraper — http://127.0.0.1:8000/
echo Set ADZUNA_APP_ID and ADZUNA_APP_KEY before Start (see .env.example)
python manage.py runserver 8000 --noreload
pause

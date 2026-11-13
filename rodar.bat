@echo off
REM Inicia o sistema em http://localhost:8000 (nao precisa ativar o venv)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERRO] Ambiente .venv nao encontrado. Rode: python -m venv .venv  e  .venv\Scripts\pip install -r requirements.txt
  pause & exit /b 1
)
echo Abrindo http://localhost:8000  (CTRL+C para parar)
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
pause

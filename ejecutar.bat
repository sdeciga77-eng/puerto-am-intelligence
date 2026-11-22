@echo off
CHCP 65001 >nul
title Puerto A&M | Plataforma segura
cd /d "%~dp0"

set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist %PY% set PY=python

echo.
echo   PUERTO A&M | PLATAFORMA SEGURA
echo   Landing publica + panel financiero autenticado
echo.

%PY% -c "import fastapi, uvicorn, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo Instalando dependencias...
  %PY% -m pip install -r requirements.txt
)

if not exist "data\Puerto_AM_Base_Datos_DEMO.xlsx" (
  echo Generando archivo Excel de demostracion...
  %PY% scripts\generate_excel.py
)

echo.
echo   Landing:  http://127.0.0.1:8000/
echo   Panel:    http://127.0.0.1:8000/admin
echo   API docs: solo si ENABLE_DOCS=true en .env
echo.
echo   Si es la primera vez, la contraseña de acceso se muestra
echo   UNA SOLA VEZ en esta consola. Guardala antes de cerrar.
echo   Presiona CTRL+C para detener el servidor.
echo.

%PY% -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause

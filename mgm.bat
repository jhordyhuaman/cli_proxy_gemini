@echo off
REM Lanzador portable de mgm: usa el .venv que esté junto a este archivo.
setlocal
set "RAIZ=%~dp0"
set "PY=%RAIZ%.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] No encuentro el entorno virtual en "%RAIZ%.venv".
    echo         Ejecuta primero:  powershell -ExecutionPolicy Bypass -File installer\instalar.ps1
    exit /b 1
)
"%PY%" -m mgm.cli %*

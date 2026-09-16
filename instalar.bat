@echo off
REM Atajo: lanza el instalador de PowerShell sin permisos de administrador.
powershell -ExecutionPolicy Bypass -File "%~dp0installer\instalar.ps1"
pause

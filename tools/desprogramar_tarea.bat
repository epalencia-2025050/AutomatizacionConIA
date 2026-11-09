@echo off
REM Cancela la corrida diaria automática (Fase 6)
schtasks /Delete /F /TN "AutomatizacionDTE_Diario"
if %ERRORLEVEL%==0 (echo Tarea eliminada) else (echo La tarea no existia)

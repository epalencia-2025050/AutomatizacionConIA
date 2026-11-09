@echo off
REM ============================================================
REM  Fase 6: programa la corrida diaria automatica del sistema
REM  Uso (ejecutar UNA VEZ, como Administrador):
REM     tools\programar_tarea_diaria.bat
REM
REM  Resultado: todos los dias a las 08:00 corre
REM     python main.py --headless
REM  (reintenta solo ante fallos de red y hace backup de la BD)
REM
REM  La sesion del SAT debe estar vigente; si el SAT pidio 2FA
REM  el dia de la corrida, la ejecucion queda registrada como
REM  ERROR en logs\automatizacion.log (revisar correos del dia).
REM ============================================================

setlocal
set ROOT=%~dp0..
set PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe
if not exist "%PYTHON%" set PYTHON=python

schtasks /Create /F /TN "AutomatizacionDTE_Diario" ^
  /SC DAILY /ST 08:00 ^
  /TR "cmd /c cd /d %ROOT% && %PYTHON% main.py --headless >> logs\scheduler.log 2>&1"

if %ERRORLEVEL%==0 (
  echo Tarea programada: AutomatizacionDTE_Diario a las 08:00
  echo Revisar logs\automatizacion.log y logs\scheduler.log
) else (
  echo Fallo al programar. Prueba ejecutando como Administrador.
)
endlocal

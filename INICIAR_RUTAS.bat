@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 src\rutas_salud_panama_floyd.py
) else (
  python src\rutas_salud_panama_floyd.py
)
echo.
echo Si hubo un error, comprueba que Python 3.10+ este instalado.
pause

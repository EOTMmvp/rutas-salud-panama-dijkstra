# -*- coding: utf-8 -*-
"""Entrada de compatibilidad: la aplicación principal está en src/.

Use src/rutas_salud_panama_floyd.py para estudiar el código actualizado.
Esta entrada conserva los comandos antiguos sin duplicar el motor.
"""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "src" / "rutas_salud_panama_floyd.py"),
        run_name="__main__",
    )

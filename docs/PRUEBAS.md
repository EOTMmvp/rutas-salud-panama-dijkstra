# Pruebas reproducibles

## Entorno de auditoría

- Fecha: 21 de noviembre de 2026 (revisión inicial).
- Entorno: Linux, Python 3.13.5.
- Se tomó el archivo `cosas/rutas_salud_panama_laboratorio_v4_1_colas_propias.py` de la entrega.
- **El archivo de código del repositorio es una copia byte por byte**, renombrada a `rutas_salud_panama.py`; SHA-256 del original y de esta copia: `f06a6914328f9be1855a7b79f0ae2e3793512375d8f1b4cd126cad25c1705033`.

## Ejecución mínima

```bash
python rutas_salud_panama.py --autotest
python rutas_salud_panama.py --validar
python rutas_salud_panama.py --sin-osrm --consulta "8.98,-79.52" --top 3
python -m unittest discover -s tests -v
```

## Resultados reproducidos al preparar el repositorio

| Prueba | Resultado | Advertencia |
| --- | --- | --- |
| Autotest del script | 38/38, salida 0 | incluye servicios simulados |
| Validación del dataset | 93 registros, 0 errores | 7 avisos + 2 observaciones |
| Consulta CLI sin OSRM | salida 0, muestra ranking de centros | distancias/ETA del modelo, no atención recomendada |
| Exportar dataset | JSON con 93 registros | datos estimados, sujetos a verificación |

El validador marca coordenadas de baja resolución en siete centros. Los dos pares de puntos señalados están muy próximos, lo que provoca agrupación visual en el mapa. Más detalles al ejecutar `--validar`.

## Pruebas agregadas al repositorio

En `tests/test_cli.py` se incluyeron cinco **pruebas externas de humo** (`unittest`): ayuda de la CLI, autotest interno, validación de dataset, exportación JSON y consulta offline. No reemplazan las 38 verificaciones internas: las invocan y comprueban también flujos de ejecución.

Se añadió un workflow de GitHub Actions para ejecutar estas pruebas en las versiones de Python 3.11, 3.12 y 3.13 cuando se publique el repositorio. **El CI todavía no se ha ejecutado en GitHub**.

## Extensión propuesta

- Tests por módulo cuando se extraigan las responsabilidades del archivo monolítico.
- Datos sintéticos de prueba para casos de duplicados y regiones aisladas.
- Tests end-to-end de la interfaz con navegador y red simulada.
- Medición de tiempos/precisión sobre trayectos verificables, con fuentes citadas.

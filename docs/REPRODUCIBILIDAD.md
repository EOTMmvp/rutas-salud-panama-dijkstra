# Reproducibilidad y límites

## Experimentos registrados

El paquete `data/raw/Experimentos_Djistraka.zip` conserva los archivos exportados durante los diez casos documentados, en formatos JSON y CSV. Los datos se refieren a operaciones de **noviembre de 2026**, no a una captura permanente de todo OpenStreetMap.

`results/Comparacion_Dijkstra_BFS_Floyd_10_Casos.json` conserva la comparación verificada con las especificaciones del entorno y las medianas de 25 repeticiones por caso.

Para repetir la comparación sobre el grafo hospitalario abstracto desde la raíz del repositorio:

```bash
python scripts/reproducir_comparacion_tres_algoritmos.py
```

Los archivos nuevos se escriben en `results/reproduccion/`, sin sustituir los resultados archivados.

Para ejecutar la suite interna:

```bash
python src/rutas_salud_panama_floyd.py --autotest
```

## Interpretación correcta

- Los **tiempos de cálculo** son mediciones computacionales del entorno de prueba; las **duraciones de viaje** son estimaciones, con congestión sintética.
- El laboratorio de calles utiliza **subgrafos OSM** y no la red completa de Panamá. Por lo tanto, su camino mínimo se refiere al subgrafo disponible.
- El grafo de instalaciones aproxima conectividad mediante k vecinos + MST; **no** representa directamente calles reales.
- **BFS** optimiza número de conexiones, no la suma de pesos.
- **Floyd–Warshall** calcula todos los pares, mientras Dijkstra y BFS se detienen tras una consulta; los tiempos no corresponden a cargas de trabajo equivalentes.
- Las 20 consultas con OSRM comparan modelos diferentes, **no** constituyen verificación de precisión con tráfico observado.
- No se preservaron copias completas de todas las redes viales descargadas en el momento de la prueba; repetirlas puede arrojar diferencias si OSM cambió.

## Lo que falta para una investigación editorial final

1. Registrar el equipo y el entorno exactos de ejecución de los experimentos principales.
2. Aprobar el texto final entre los coautores y ajustarlo a la plantilla de la revista elegida.
3. Conservar capturas representativas y, de ser posible, instantáneas de los grafos OSM consultados.
4. No representar el manuscrito como publicado o aceptado sin constancia editorial.

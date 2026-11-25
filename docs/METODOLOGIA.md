# Visión metodológica

El proyecto contiene **dos grafos distintos**, que no deben confundirse en informes:

1. **Grafo hospitalario abstracto**: conjunto de establecimientos terrestres, conexiones geográficas mediante k vecinos + MST, pesos sintéticos. Sirve para comparar colas propias, Dijkstra, BFS y Floyd–Warshall y para presentar la estructura de datos.
2. **Grafo de calles OpenStreetMap (OSM)**: subgrafo dirigido, obtenido mediante Overpass únicamente para ciertos trayectos locales. Sirve para demostrar el enrutamiento ponderado por distancia o tiempo sintético y los bloqueos simulados.

El prototipo no incluye mediciones de tráfico vivo; un menor costo modelado no equivale a una validación de tiempo real de respuesta sanitaria. El sitio web en `site/` utiliza otro grafo, pequeño y totalmente sintético, con fines didácticos.

Más detalles, tablas, resultados y bibliografía en el artículo incluido en `paper/`.

# Caso de estudio: rutas de acceso a centros de salud en Panamá

## Contexto
La dificultad abordada en este ejercicio de ingeniería de software es comparar rutas candidatas y modelos de distancia entre orígenes geográficos y establecimientos sanitarios, usando un dataset de 93 registros de la provincia de Panamá.

## Desafío técnico
Un centro cercano en distancia geodésica no necesariamente está cerca por calles. El programa permite experimentar con esa diferencia y con criterios de peso de un grafo. No demuestra cuál es la mejor institución para tratar una condición médica.

## Enfoque implementado
1. Construir nodos a partir del catálogo de instalaciones y agregar el origen de una consulta.
2. Construir una estructura conectada con vecinos cercanos (kNN) y árbol de expansión mínima (MST).
3. Aplicar Dijkstra y contrastar resultados con métodos alternativos en experimentos.
4. Si se solicita, consultar servicios externos de ruteo/OSM para analizar segmentos viales reales (sujeto a límites de cobertura y disponibilidad).
5. Presentar resultados en mapa o terminal y ofrecer validación/exportación de datos.

## Resultados observados
- 93 registros de instalaciones cargados.
- 38 de 38 pruebas internas superadas localmente.
- 0 errores, 7 avisos y 2 notas de información al ejecutar el validador de coordenadas.

Son resultados de pruebas y validación del **software y sus reglas internas**. No se midió reducción de tiempos de ambulancias, beneficio clínico ni precisión independiente de las rutas.

## Competencias que documenta
Algoritmos y estructuras de datos; validación de entradas; CLI; HTTP local; procesamiento de JSON/CSV; pruebas automatizadas; comunicación de limitaciones y documentación reproducible.

## Evidencias para agregar antes de la presentación pública
- Capturas auténticas de la interfaz tomadas al ejecutarlo en Windows.
- Un video corto demostrando consulta por origen, validación y laboratorio de algoritmos.
- El DOI/enlace del artículo **solo si fue aceptado/publicado**.
- Confirmación de quién diseñó e implementó cada componente del proyecto.

**Contribución individual:** pendiente de confirmar y describir con precisión. No debe asumirse que una aplicación académica desarrollada en equipo fue creada por una sola persona.

# Metodología, fuentes y limitaciones

## Qué calcula

- **Distancia directa:** línea geodésica estimada entre origen y destino; no sigue calles.
- **Grafo-modelo:** vecinos cercanos y conexión garantizada entre establecimientos, con una función de coste aproximada que incorpora sinuosidad y fricción sintética.
- **Rutas por calles (OSRM):** al estar activadas y disponibles, se consultan servicios externos de ruteo vial; no implican tráfico en vivo.
- **Laboratorio OSM (Overpass):** se solicitan segmentos reales de vías para experimentos específicos y acotados. El script limita las peticiones a trayectos locales y dispone de controles de seguridad en parámetros.

## Dataset

El programa incluye **93 instalaciones** con campos como nombre, coordenadas aproximadas, horarios y especialidades descritas en texto. Algunos registros pueden resultar incompletos o incorrectos y necesitan contraste con fuentes oficiales y revisión de la licencia/origen de datos. Los datos de centros de salud **no son una base certificada** por MINSA/CSS.

Resultado de `--validar` en el entorno de preparación: **0 errores, 7 avisos por precisión de coordenadas y 2 observaciones por centros cercanos**. Un validador interno con cero errores significa que los registros pasaron reglas técnicas implementadas, **no** que las ubicaciones sean exactas.

## Servicios externos

- OpenStreetMap y proveedores de mosaicos: cartografía y datos de referencia (atribución y condiciones de uso aplicables).
- OSRM: consultas de rutas y/o matrices cuando esté habilitado.
- Nominatim: geocodificación/verificación opcional; respetar límites de uso y User-Agent cuando corresponda.
- Overpass: descarga puntual de segmentos del grafo vial.
- Leaflet: librería de visualización de mapas cargada mediante CDN.

Enlaces de referencia: https://www.openstreetmap.org/copyright · https://operations.osmfoundation.org/policies/nominatim/ · https://project-osrm.org/ · https://leafletjs.com/

## Limitaciones importantes

1. Sin verificación independiente de localizaciones, especialidades, horarios y cobertura sanitaria.
2. El tráfico es sintético, no mediciones de tráfico en vivo.
3. Los tiempos son **estimaciones** sensibles a velocidad, penalizaciones y datos de origen.
4. Las rutas directas no corresponden a carreteras; el grafo entre centros es un modelo simplificado.
5. Servicios externos pueden fallar, imponer límites o cambiar su comportamiento.
6. Centros insulares requieren otros medios de acceso; el programa no sustituye la logística terrestre, marítima y aérea.
7. **No debe utilizarse para elegir un hospital en una emergencia, planificar ambulancias o tomar decisiones clínicas.**

## Qué faltaría para uso aplicado

Verificación oficial y continua de datos, consentimiento/licencia de fuentes, infraestructura resiliente, evaluación geoespacial rigurosa, pruebas de seguridad, mediciones de precisión, pruebas de accesibilidad y, especialmente, un marco de validación médica e institucional.

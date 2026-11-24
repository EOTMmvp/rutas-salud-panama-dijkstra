# Arquitectura y flujo de ejecución

## Estado actual del código

El motor original se conserva **en un archivo Python** `rutas_salud_panama.py` (~5.8 mil líneas); contiene lógica de datos, algoritmos, HTTP local y una plantilla HTML/JS embebida. El nombre largo del archivo de origen se acortó para facilitar su ejecución; el contenido se mantuvo idéntico.

```text
Entrada CLI (`argparse`)
   |
   +-- Carga datos embebidos / correcciones JSON / dataset CSV o JSON
   |     +-- normalización, horarios y validación
   |
   +-- Modo offline: pruebas, consultas, informes y exportaciones
   |     +-- estimador con grafos + Dijkstra
   |
   +-- Servidor HTTP local
         +-- genera una página HTML con JavaScript/Leaflet
         +-- APIs locales (validador, PDF, experimentos)
         +-- integraciones opcionales OSRM / OSM / Nominatim / Overpass
```

### Componentes principales identificados

| Componente | Ubicación | Responsabilidad |
| --- | --- | --- |
| Configuración | `CONFIG` y constantes | parámetros de grafos, modo de ruta, fricción y zona |
| Dataset | `hospitales` y carga de datos | datos de instalaciones y correcciones locales |
| Grafo | funciones de distancias y construcción de red | red sintética entre establecimientos |
| Laboratorio | funciones de algoritmos y experimentos | comparar técnicas con entradas acotadas |
| Presentación | HTML/CSS/JS generado | controles y mapa interactivo |
| Servicio local | `crear_servidor` | peticiones HTTP y operaciones con token |
| CLI | `construir_parser` y `main` | argumentos y modos de ejecución |

**Distinción relevante:** el grafo kNN+MST construido entre establecimientos es un **modelo abstracto**; no es en sí una representación fiel de todas las calles. Los laboratorios opcionales sobre segmentos OSM ofrecen un análisis diferente, limitado por cobertura y conectividad.

### Mejoras arquitectónicas futuras
- Separar `data/`, `routing/`, `services/`, `web/` y `cli/` **sin alterar las funcionalidades verificadas**.
- Externalizar la plantilla HTML/CSS/JS para facilitar pruebas y mantenimiento.
- Incorporar tests unitarios propios de cada módulo y evaluaciones contra trayectos de referencia documentados.
- Añadir control de versiones y procedencia verificable a cada registro geográfico.

No se ha hecho esta refactorización en la versión preparada para GitHub: evitamos introducir cambios de comportamiento antes de revisar el original conjuntamente.

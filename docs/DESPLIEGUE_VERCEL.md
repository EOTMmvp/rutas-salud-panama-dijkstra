# Despliegue de la demostración en Vercel

**Objetivo:** publicar la página estática en `site/` (presentación y mini laboratorio sintético); **no** publicar el servidor Python del programa original.

1. Crear un repositorio en GitHub e incorporar **todo el contenido de este paquete**.
2. Comprobar que `README.md`, `vercel.json` y `site/index.html` están en la raíz/rutas correctas.
3. Entrar a [Vercel](https://vercel.com/) y seleccionar **Add New → Project**.
4. Importar el repositorio GitHub; elegir el **directorio raíz del repositorio**.
5. Preset **Other**, sin comando de compilación; el archivo `vercel.json` fija `outputDirectory: site`.
6. Pulsar **Deploy**. Tras finalizar, comprobar la portada, el botón de comparación, el PDF y los CSV.

**No activar exposición pública del puerto local** de Python ni cambiarlo a `0.0.0.0` para este despliegue. El backend contiene operaciones de archivos, consultas externas y experimentos intensivos, y necesitaría una adaptación y revisión de seguridad antes de ponerlo en internet.

Si se desea alojar la aplicación Python completa en la web, es otro desarrollo: extraer APIs, diseñar autenticación/autorización, límites de costos, cachés y manejo de servicios OSM/OSRM.

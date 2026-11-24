# Seguridad y privacidad

Este es un proyecto de **demostración académica**, no una aplicación médica. No incluye datos de pacientes ni se debe usar para recolectarlos.

## Uso local recomendado

- Mantener el servidor en su host predeterminado `127.0.0.1`.
- **No configurar `--host 0.0.0.0` en una red pública**, ni exponer directamente este servidor a Internet sin revisión profesional y endurecimiento de seguridad.
- Las operaciones POST locales utilizan un token y otras comprobaciones, pero **no equivalen a autenticación multiusuario ni a una evaluación de seguridad de producción**.
- Evitar colocar información personal, contraseñas o claves en datasets CSV/JSON, argumentos de terminal o registros de salida.
- Los archivos de corrección, reportes y exports locales están excluidos de Git de forma predeterminada.

## Internet y servicios terceros

El navegador descarga Leaflet/tiles de terceros; con OSRM, Nominatim y Overpass habilitados se enviarán coordenadas/solicitudes a servicios externos. No ingresar ubicaciones privadas o sensibles en una demostración pública. Revisar políticas de uso y privacidad antes de habilitar estas consultas.

## Revisión antes de subir

- Revisar `git status`, `git diff --cached` y contenidos de los archivos en staging.
- Inspeccionar rutas, correos, tokens, datos de pacientes y archivos grandes.
- Confirmar permisos de publicación del código, de los datos y de aportaciones ajenas.
- Si una clave llegara a publicarse accidentalmente, **revocarla y rotarla**: borrarla del commit más reciente no la elimina necesariamente del historial de Git.

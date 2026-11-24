# Cómo publicar este proyecto en tu GitHub — paso a paso

Tu cuenta: https://github.com/EOTMmvp  
Nombre sugerido del repositorio: `rutas-salud-panama-dijkstra`

## Antes de publicar

**No publiques aún en modo público** hasta completar el checklist de [CREDITOS.md](../CREDITOS.md). En especial, comprueba autorización del equipo y reglas del artículo científico.

## Opción A: GitHub Desktop (recomendado si estás empezando)

1. Descarga GitHub Desktop desde https://desktop.github.com/ e inicia sesión en `EOTMmvp`.
2. Descomprime `Rutas_Salud_Panama_GitHub_Listo.zip` en una carpeta propia, por ejemplo `Documentos/Proyectos/rutas-salud-panama-dijkstra`.
3. En GitHub Desktop selecciona **File → Add local repository**, y elige la carpeta descomprimida.
4. Si indica que todavía no es un repositorio Git, usa **Create a repository here**. Mantén el nombre `rutas-salud-panama-dijkstra`.
5. Revisa el panel de archivos antes de confirmar. Comprueba que no hay `index.html`, informes locales, `.env` ni datos personales.
6. Escribe un primer mensaje de commit, por ejemplo `docs: initial academic routing portfolio repository`.
7. Haz clic en **Commit to main** y luego en **Publish repository**. **Elige Private mientras faltan las autorizaciones**.
8. Después de contar con permisos de publicación, puedes cambiar el repositorio a Public desde sus Settings, previa revisión del contenido y el historial.

## Opción B: terminal PowerShell

Desde la carpeta extraída:

```powershell
git init
git branch -M main
git add .
git status
git commit -m "docs: initial academic routing portfolio repository"
```

Crea un repositorio **vacío y privado** en GitHub y sigue las instrucciones que GitHub muestre para asociar el `remote`. Evita copiar URLs de repositorios que aún no existen.

## Cómo probarlo después

```powershell
py rutas_salud_panama.py --autotest
py rutas_salud_panama.py --validar
py rutas_salud_panama.py --sin-osrm --consulta "8.98,-79.52" --top 3
py -m unittest discover -s tests -v
py rutas_salud_panama.py --sin-osrm
```

El último comando abre el mapa local. Para verlo en otros dispositivos, no expongas directamente el servidor: primero estudia despliegue seguro.

## Qué mostrar en el portafolio web

Solo cuando sea público y esté verificado: enlace real del repositorio, una captura auténtica, el breve caso de estudio y resultados de las 38 pruebas internas. No presentarlo como servicio médico, producto comercial ni ruta garantizada. Si el repositorio sigue privado, muestra un caso de estudio sin link al código y reconoce su estado.

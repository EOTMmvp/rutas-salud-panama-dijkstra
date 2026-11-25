# Publicar este repositorio por primera vez

Guía para Windows usando **GitHub Desktop**. No requiere copiar manualmente cada archivo al navegador.

1. Descargar `Repositorio_GitHub_Rutas_Salud_Panama_V1.zip` y elegir **Extraer todo**.
2. Comprobar que, dentro de `rutas-salud-panama-research`, aparecen `README.md`, `vercel.json`, `site/`, `src/`, `paper/` y `results/`.
3. Abrir **GitHub Desktop** e iniciar sesión con tu cuenta.
4. Ir a **File → Add local repository…** y seleccionar la carpeta `rutas-salud-panama-research`.
5. Si GitHub Desktop dice que esa carpeta todavía no es un repositorio Git, seleccionar **Create a repository here** (crear repositorio aquí).
6. Escribir un mensaje de confirmación, por ejemplo `Initial academic research project`, y hacer clic en **Commit to main**.
7. Pulsar **Publish repository**. Confirmar el nombre, propietario y visibilidad. Si desea que los profesores vean el código sin iniciar sesión, elegir **Public**, una vez que el grupo acuerde hacer público el material.
8. Revisar la página del repositorio y comprobar que aparecen el README y las carpetas.

**Antes de publicar:** el artículo tiene cuatro coautores; confirmar que el equipo acepta publicar públicamente código, manuscrito y datos. No se ha asignado una licencia abierta al trabajo de los autores.

**Alternativa por terminal** (para quienes tengan Git instalado):

```bash
git init
git add .
git commit -m "Initial academic research project"
git branch -M main
# Crear primero un repositorio vacío en GitHub y sustituir TU-USUARIO y TU-REPO.
git remote add origin https://github.com/TU-USUARIO/TU-REPO.git
git push -u origin main
```

Después de publicar, continuar con `docs/DESPLIEGUE_VERCEL.md`.

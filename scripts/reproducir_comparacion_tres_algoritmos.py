"""Reproduce 10 consultas de la comparación sobre el grafo hospitalario.

No descarga OpenStreetMap. Cada caso usa exactamente los parámetros de las
exportaciones colas_propias.json anteriores. Ejecuta 25 repeticiones por
algoritmo y caso; los tiempos NO son comparables entre entornos.
"""
import csv
import hashlib
import importlib.util
import json
import os
import platform
import re
import statistics
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CODIGO = RAIZ / 'src' / 'rutas_salud_panama_floyd.py'
ZIP_ORIGEN = RAIZ / 'data' / 'raw' / 'Experimentos_Djistraka.zip'
JSON_SALIDA = RAIZ / 'results' / 'reproduccion' / 'Comparacion_Dijkstra_BFS_Floyd_10_Casos.json'
CSV_SALIDA = RAIZ / 'results' / 'reproduccion' / 'Comparacion_Dijkstra_BFS_Floyd_10_Casos.csv'
JSON_SALIDA.parent.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location('rutas_floyd', CODIGO)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
registros, _avisos = mod.cargar_dataset()
filas = []
with zipfile.ZipFile(ZIP_ORIGEN) as z:
    nombres = [n for n in z.namelist() if n.endswith('laboratorio_dijkstra_colas_propias.json')]
    nombres.sort(key=lambda n: int(re.search(r'Caso\s*(\d+)', n, re.I).group(1)))
    assert len(nombres) == 10, f'Se esperaban 10 casos: {len(nombres)}'
    for pos, nombre in enumerate(nombres, 1):
        anterior = json.loads(z.read(nombre))
        r = mod.ejecutar_laboratorio(anterior['parametros'], registros)
        datos = {x['algoritmo'].split(' (')[0]: x for x in r['filas']}
        dij, bfs, flo = datos['Dijkstra'], datos['BFS'], datos['Floyd-Warshall']
        assert abs(dij['costo_min'] - flo['costo_min']) <= 0.00011
        assert abs(dij['costo_min'] - anterior['filas'][0]['costo_min']) <= 0.00011
        assert abs(bfs['costo_min'] - anterior['filas'][1]['costo_min']) <= 0.00011
        assert r['metadatos']['aristas_dirigidas'] == anterior['metadatos']['aristas_dirigidas'] == 714
        filas.append({
            'caso': pos,
            'destino': r['metadatos']['destino'],
            'vertices_totales': r['metadatos']['vertices'],
            'arcos_dirigidos': r['metadatos']['aristas_dirigidas'],
            'dijkstra_ms_mediana_25': dij['tiempo_ms'],
            'bfs_ms_mediana_25': bfs['tiempo_ms'],
            'floyd_ms_mediana_25': flo['tiempo_ms'],
            'dijkstra_costo_min': dij['costo_min'],
            'bfs_costo_min': bfs['costo_min'],
            'floyd_costo_min': flo['costo_min'],
            'saltos_dijkstra': dij['saltos'],
            'saltos_bfs': bfs['saltos'],
            'saltos_floyd': flo['saltos'],
            'floyd_pares_alcanzables': r['metadatos']['floyd_pares_alcanzables'],
            'comprobacion': 'coincidencia_Floyd_Dijkstra_y_historico',
        })
        print(f"{pos:2}: {r['metadatos']['destino'][:35]:35} | D {dij['tiempo_ms']:7.4f} | B {bfs['tiempo_ms']:7.4f} | F {flo['tiempo_ms']:8.4f} ms", flush=True)

claves = list(filas[0])
with CSV_SALIDA.open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=claves)
    writer.writeheader()
    writer.writerows(filas)

metadatos = {
    'fecha_utc': datetime.now(timezone.utc).isoformat(),
    'version_python': sys.version,
    'plataforma': platform.platform(),
    'procesador_reconocido': platform.processor() or 'no declarado por el contenedor',
    'fuente_original': str(ZIP_ORIGEN.name),
    'sha256_zip_original': hashlib.sha256(ZIP_ORIGEN.read_bytes()).hexdigest(),
    'codigo': str(CODIGO.name),
    'sha256_codigo': hashlib.sha256(CODIGO.read_bytes()).hexdigest(),
    'metodo_temporizacion': 'mediana de 25 ejecuciones por algoritmo y caso (función integrada del programa)',
    'observacion': 'Floyd calcula TODOS los pares de vértices; Dijkstra/BFS se detienen en el destino. Computadora de ejecución distinta de la de los experimentos originales.',
}
for key in ('dijkstra_ms_mediana_25', 'bfs_ms_mediana_25', 'floyd_ms_mediana_25', 'dijkstra_costo_min', 'bfs_costo_min', 'floyd_costo_min'):
    metadatos['media_de_mediana_'+key] = statistics.mean(f[key] for f in filas)
metadatos['casos_dijkstra_igual_floyd'] = sum(abs(f['dijkstra_costo_min']-f['floyd_costo_min']) < 1e-8 for f in filas)
metadatos['casos_bfs_mayor_costo'] = sum(f['bfs_costo_min'] > f['dijkstra_costo_min'] + 1e-4 for f in filas)
JSON_SALIDA.write_text(json.dumps({'metadatos':metadatos,'filas':filas},ensure_ascii=False,indent=2),encoding='utf-8')
print('\nMETADATOS:\n',json.dumps(metadatos,indent=2,ensure_ascii=False))

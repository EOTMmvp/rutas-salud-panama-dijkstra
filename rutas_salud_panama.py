# -*- coding: utf-8 -*-
"""
Rutas de acceso a salud · Provincia de Panamá  (v4.0 · Laboratorio)
================================================================================
Demostrador científico de enrutamiento hospitalario con Dijkstra.

NOVEDADES v4 (TODAS OPCIONALES POR BOTÓN EN EL MAPA)
-------------------------------------------------
* Laboratorio de Dijkstra propio sobre segmentos OSM (Overpass, red real dirigida).
* Comparativa de ruta mínima por distancia y mínima por tiempo.
* Escenarios de tráfico SINTÉTICO y cierres de vías con nueva búsqueda.
* Dijkstra vs Bellman-Ford vs A*; escalabilidad 100–10.000 nodos.
* Validación contrastada con OSRM y exportaciones JSON/CSV.
* Se admite un destino cualquiera elegido mediante clic en el mapa.
* Octavo experimento opcional: montículo mínimo y FIFO propios en Python; Dijkstra vs BFS.

Los experimentos no se ejecutan automáticamente. La red OSM real se
consulta solo si se solicita, y solo para trayectos locales de hasta 11 km.
El programa NO utiliza tráfico en vivo ni sirve para decisiones de emergencia.

QUÉ SE CORRIGIÓ EN LA v3.0
--------------------------
1. MAPA LIMPIO
   * Solo se dibuja la ruta entre el origen y el hospital elegido (el más cercano o el
     que el usuario seleccione). Antes se dibujaba una línea del origen a TODOS los
     centros, lo que hacía parecer que el programa unía todos los puntos.
   * La red completa entre hospitales y las líneas de referencia ahora son capas
     opcionales y están DESACTIVADAS por defecto.

2. DOS MODOS DE RUTA CLAROS
   * «1 · Vía directa»: distancia geodésica origen → hospital, sin calles, sin tráfico
     y sin escalas. Responde a “lo más rápido, sin importar nada más”.
   * «2 · Por calles»: ruta real siguiendo las calles del país con OSRM, ponderada por
     el modelo de tráfico. Si OSRM no responde, se usa la estimación del grafo.

3. DIJKSTRA REAL
   * El origen se conecta con sus k hospitales más cercanos (kOrigen), no con todos.
   * La red entre hospitales es kNN + árbol de expansión mínima (MST), de modo que el
     grafo siempre es conexo y Dijkstra puede atravesar la red.
   * El destino es el hospital de menor ETA entre los candidatos de la especialidad.

4. LOCALIZACIONES
   * Se corrigieron 50+ coordenadas con OpenStreetMap/Nominatim (ver
     CORRECCIONES_DATASET). Las correcciones están documentadas y marcadas como
     verificadas.
   * Se corrigió la máscara de costa: antes todo el este de la provincia por debajo de
     la latitud 8.93 se consideraba mar, lo que obligó a mover Chimán ~24 km tierra
     adentro. Ahora Chimán vuelve a su posición real y la costa oriental tiene puntos
     de control.
   * Se corrigieron duplicados (Centro Médico Nacional / CHEMSA, etc.).

5. FUNCIONES NUEVAS
   * Buscador de lugares por nombre: catálogo local (hospitales + localidades) y, si no
     hay coincidencia, consulta a OpenStreetMap/Nominatim desde el navegador.
   * Comparador «1 vs 2»: para el mismo hospital muestra distancia y tiempo por vía
     directa y por calles, con la diferencia entre ambas.
   * Indicaciones paso a paso de la ruta por calles (OSRM steps).
   * Exportación JSON/CSV/GeoJSON/PDF y validación del dataset desde la terminal.
   * Se conservan cobertura territorial, edición de posiciones, calibración y autotest.

NOTA METODOLÓGICA: las coordenadas son aproximaciones corregidas con OSM y NO
sustituyen los datos oficiales del MINSA/CSS ni deben usarse para decisiones clínicas.
El tráfico es un modelo sintético (núcleos gaussianos), no datos en vivo.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import hmac
import http.server
import io
import json
import math
import os
import re
import secrets
import sys
import textwrap
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

# La consola de Windows suele usar cp1252 y no puede escribir ✔, ⚠, →, etc. Forzar UTF-8
# (con reemplazo) evita que --autotest o --validar terminen con UnicodeEncodeError.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

VERSION = "4.0-laboratorio"

# ---------------------------------------------------------------------------
# 0. CONFIGURACIÓN ÚNICA (la usan el modelo en Python y el mapa en JavaScript)
# ---------------------------------------------------------------------------
CONFIG: dict = {
    "kVecinos": 6,                  # vecinos más cercanos entre instalaciones
    "kOrigen": 8,                   # accesos del origen a los hospitales más cercanos
    "velocidadLibreKmh": 45.0,      # velocidad a flujo libre sobre calles (calibrable)
    "velocidadDirectaKmh": 60.0,    # velocidad del modo «vía directa» (sin calles)
    "sinuosidad": 1.30,             # km por calle / km en línea recta (calibrable)
    "repeticionesBenchmark": 10,
    "radioCoberturaKm": 5.0,
    "umbralCoberturaMin": 15,
    "modoCobertura": "radio",       # "radio" | "tiempo"
    "modoRuta": "calles",           # "calles" (OSRM + tráfico) | "directa" (línea recta)
    "maxFriccion": 2.8,
    "muestrasFriccionKm": 1.0,      # un punto de muestreo de fricción por cada km de tramo
    "maxCandidatosOSRM": 30,        # candidatos que se consultan a OSRM en /table
    "areaAnalisis": {"latMin": 8.82, "latMax": 9.26, "lonMin": -79.68, "lonMax": -79.08, "paso": 0.025},
    "limites": {"latMin": 7.9, "latMax": 9.5, "lonMin": -80.1, "lonMax": -78.3},
    "origenInicial": {"lat": 9.0350, "lon": -79.4850},
    "osrm": {
        "activo": True,
        "url": "https://router.project-osrm.org",
        "timeoutMs": 9000,
        "maxTabla": 90,             # máx. coordenadas por petición /table
        "retardoMs": 350,           # espera antes de consultar (evita saturar con clics)
    },
    "zonaHoraria": "America/Panama",
}

# Núcleos de fricción urbana: peso (incremento de tiempo) y radio gaussiano (km).
ZONAS_FRICCION = [
    {"nombre": "Centro de Panamá", "lat": 8.980, "lon": -79.528, "peso": 0.85, "radio": 2.8},
    {"nombre": "Vía España / Obarrio", "lat": 8.990, "lon": -79.520, "peso": 0.60, "radio": 2.2},
    {"nombre": "San Miguelito", "lat": 9.040, "lon": -79.500, "peso": 0.65, "radio": 3.0},
    {"nombre": "Juan Díaz / Costa del Este", "lat": 9.020, "lon": -79.465, "peso": 0.55, "radio": 3.0},
    {"nombre": "Tocumen / 24 de Diciembre", "lat": 9.080, "lon": -79.370, "peso": 0.45, "radio": 3.8},
    {"nombre": "Las Cumbres / Panamá Norte", "lat": 9.100, "lon": -79.545, "peso": 0.50, "radio": 3.2},
    {"nombre": "Chilibre", "lat": 9.155, "lon": -79.615, "peso": 0.25, "radio": 2.5},
    {"nombre": "Ancón / Balboa", "lat": 8.960, "lon": -79.550, "peso": 0.35, "radio": 2.2},
    {"nombre": "Pacora / San Martín", "lat": 9.095, "lon": -79.250, "peso": 0.25, "radio": 5.0},
    {"nombre": "Chepo", "lat": 9.165, "lon": -79.102, "peso": 0.20, "radio": 3.0},
    {"nombre": "Acceso Puente de las Américas", "lat": 8.985, "lon": -79.585, "peso": 0.45, "radio": 2.5},
]

# Línea de costa APROXIMADA del Golfo de Panamá, de oeste a este: (lon, lat).
# Sirve solo para (a) detectar posiciones que caen en el mar y (b) no contar el mar
# como "desierto de atención". Error esperado ~1-2 km: es una máscara, no cartografía.
# v3: se agregaron puntos al este de -79.08. Antes la costa se prolongaba artificialmente
# a lat 8.93 hasta -78.55 y por eso Chimán (lat 8.72) "caía en el mar" y fue movido
# erróneamente 24 km tierra adentro.
COSTA_APROX = [
    (-79.700, 8.860), (-79.640, 8.880), (-79.600, 8.895), (-79.575, 8.930),
    (-79.560, 8.940), (-79.545, 8.955), (-79.535, 8.945), (-79.520, 8.960),
    (-79.505, 8.968), (-79.480, 8.985), (-79.460, 8.985), (-79.440, 9.000),
    (-79.400, 9.025), (-79.380, 9.045), (-79.300, 9.020), (-79.200, 8.990),
    (-79.080, 8.950), (-78.980, 8.915), (-78.900, 8.875), (-78.820, 8.830),
    (-78.740, 8.770), (-78.680, 8.730), (-78.633, 8.700), (-78.590, 8.675),
    (-78.550, 8.650), (-78.450, 8.600), (-78.300, 8.550),
]

# Centros en islas: no hay ruta terrestre (requieren traslado marítimo o aéreo).
NOMBRES_INSULARES = {
    "Centro de Salud de Taboga",
    "Centro de Salud de Contadora",
    "Centro de Salud de Isla de Balboa",
}

ARCHIVO_CORRECCIONES = "correcciones_coordenadas.json"

# Anclas de localidad: centro APROXIMADO (lat, lon) de barrios y corregimientos que aparecen en
# los nombres. Permiten detectar sin conexión posiciones muy alejadas de su localidad. Error del
# ancla ~1 km; por eso el umbral es generoso. Es una alerta de revisión, no una verdad.
ANCLAS_LOCALIDAD = {
    "tocumen": (9.0847, -79.3836), "pacora": (9.0794, -79.2889), "chepo": (9.1700, -79.1000),
    "chiman": (8.7169, -78.6332), "san martin": (9.1167, -79.2333), "24 de diciembre": (9.0950, -79.3450),
    "cerro azul": (9.1667, -79.4167), "chilibre": (9.1500, -79.6167), "caimitillo": (9.1588, -79.5399),
    "las cumbres": (9.1000, -79.5450), "alcalde diaz": (9.1167, -79.5500), "villa zaita": (9.0867, -79.5367),
    "juan diaz": (9.0300, -79.4600), "pedregal": (9.0750, -79.4250), "costa del este": (9.0120, -79.4690),
    "punta pacifica": (8.9760, -79.5100), "paitilla": (8.9800, -79.5150), "bella vista": (8.9750, -79.5300),
    "via espana": (8.9890, -79.5230), "obarrio": (8.9890, -79.5200), "betania": (9.0000, -79.5200),
    "calidonia": (8.9680, -79.5360), "curundu": (8.9720, -79.5450), "el chorrillo": (8.9540, -79.5430),
    "santa ana": (8.9550, -79.5340), "ancon": (8.9650, -79.5500), "albrook": (8.9750, -79.5530),
    "taboga": (8.7900, -79.5550), "contadora": (8.6330, -79.0350), "villa lucre": (9.0400, -79.4800),
    "brisas del golf": (9.0560, -79.4450), "cerro viento": (9.0650, -79.4850), "don bosco": (9.0200, -79.4700),
    "las mananitas": (9.0800, -79.4000), "rio abajo": (9.0200, -79.4900), "pueblo nuevo": (8.9980, -79.5050),
    "san francisco": (8.9900, -79.5100), "boca la caja": (8.9820, -79.5170),
    "parque lefevre": (9.0221, -79.4873), "isla de balboa": (8.3481, -78.8962),
    "chemsa": (8.9685, -79.5350), "ciudad de la salud": (9.0246, -79.5787),
}
UMBRAL_ANCLA_KM = 3.5

# ---------------------------------------------------------------------------
# 1. DATASET BASE DE INSTALACIONES DE SALUD (Provincia de Panamá)
#    Posiciones aproximadas. Para corregirlas sin tocar el código usa
#    `--verificar-coordenadas` o edita correcciones_coordenadas.json (ver la
#    función cargar_dataset).
#    Corregido en v2: Chimán (lat 8.7175 -> 8.9333; estaba en el mar).
# ---------------------------------------------------------------------------
def _h(nombre: str, lat: float, lon: float, horario: str,
       descripcion: str, especialidades: str) -> dict:
    """Construye un registro hospitalario homogéneo."""
    return {
        "nombre": nombre,
        "lat": lat,
        "lon": lon,
        "horario": horario,
        "descripcion": descripcion,
        "especialidades": especialidades,
    }


hospitales = [
    # --- Ciudad de Panamá y San Miguelito (dataset base) -------------------
    _h("Hospital Brisas", 9.0631, -79.4623, "Lunes a Domingo: 24 horas",
       "Atención médica general y de urgencias para residentes de Brisas del Golf.",
       "Urgencias 24h, Medicina General, Pediatría, Ginecología, Ortopedia, Laboratorio"),
    _h("Hospital MiniMed (Golden Point)", 9.0065, -79.5290, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Clínica ambulatoria rápida, laboratorio clínico y medicina general.",
       "Medicina General, Urgencias Menores, Laboratorio, Rayos X, Salud Ocupacional"),
    _h("MiniMed Centennial", 9.0298, -79.5284, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Atención médica primaria y pruebas de laboratorio sin cita previa.",
       "Medicina General, Urgencias Menores, Laboratorio, Electrocardiograma"),
    _h("MiniMed Calle 50", 8.9830, -79.5150, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Sucursal céntrica para consultas rápidas, laboratorios y farmacia.",
       "Medicina General, Urgencias Menores, Laboratorio, Hisopados, Farmacia"),
    _h("MiniMed Los Andes", 9.0485, -79.5060, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Clínica de atención rápida ubicada en el área norte de San Miguelito.",
       "Medicina General, Laboratorio Clínico, Curaciones, Urgencias Menores"),
    _h("MiniMed Vía España", 8.9839, -79.5230, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Servicios médicos generales y diagnósticos rápidos sobre Vía España.",
       "Medicina General, Laboratorio, Inyectables, Urgencias Menores"),
    _h("Clínica Hosp. San Fernando", 9.0003, -79.5101, "Lunes a Domingo: 24 horas",
       "Centro privado de referencia en cardiología, oncología y cirugía.",
       "Urgencias 24h, Cardiología, Oncología, Maternidad, Cuidados Intensivos, Cirugía General"),
    _h("Hospital Santa Fe", 8.9885, -79.5420, "Lunes a Domingo: 24 horas",
       "Centro médico privado enfocado en atención personalizada y quirúrgica.",
       "Urgencias 24h, Cirugía General, Medicina Interna, Maternidad, Urología"),
    _h("Pacífica Salud (Punta Pacífica)", 8.9744, -79.5085, "Lunes a Domingo: 24 horas",
       "Hospital privado de alta tecnología afiliado con Johns Hopkins Medicine.",
       "Urgencias 24h, Trauma, Neurología, Oncología, Cardiología Avanzada, Maternidad"),
    _h("The Panama Clinic", 8.9755, -79.5090, "Lunes a Domingo: 24 horas",
       "Moderno complejo hospitalario con helipuerto y alta especialización.",
       "Urgencias 24h, Cirugía Robótica, Cardiología, Pediatría, Maternidad VIP, Cirugía Plástica"),
    _h("Clínica Hosp. Mar del Sur", 8.9795, -79.5268, "Lunes a Domingo: 24 horas",
       "Centro clínico privado con servicios de urgencias y consultorios.",
       "Urgencias 24h, Medicina General, Consultas Especializadas, Laboratorio Clínico"),
    _h("Hospital Nacional", 8.9806, -79.5255, "Lunes a Domingo: 24 horas",
       "Destacado hospital privado con sólida trayectoria en ginecología y pediatría.",
       "Urgencias 24h, Ginecología, Neonatología, Cirugía Pediátrica, Medicina Interna"),
    _h("Hospiten Paitilla", 8.9774, -79.5148, "Lunes a Domingo: 24 horas",
       "Hospital privado de prestigio con urgencias 24h y especialistas.",
       "Urgencias 24h, Ortopedia, Ginecología, Urología, Cirugía General, UCI"),
    _h("Pacífica Salud (Costa del Este)", 9.0142, -79.4678, "Lunes a Sábado: 7:00 am - 7:00 pm",
       "Centro médico ambulatorio y de urgencias para Costa del Este.",
       "Urgencias Menores, Pediatría, Medicina General, Laboratorio, Imagenología"),
    _h("Clínica San Fernando (Brisas del Golf)", 9.0573, -79.4449, "Lunes a Sábado: 7:00 am - 7:00 pm",
       "Extensión de servicios ambulatorios y diagnósticos de San Fernando.",
       "Consulta Externa, Urgencias Menores, Laboratorio, Rayos X, Farmacia"),
    _h("Hospital Santo Tomás (MINSA)", 8.9715, -79.5312, "Lunes a Domingo: 24 horas",
       "Hospital público general más grande e histórico del país.",
       "Trauma, Urgencias 24h, Cirugía Mayor, UCI, Maternidad, Neumología, Nefrología"),
    _h("Hospital del Niño (MINSA)", 8.9708, -79.5323, "Lunes a Domingo: 24 horas",
       "Centro pediátrico de referencia nacional para la salud infantil.",
       "Urgencias Pediátricas, Neonatología, Infectología Pediátrica, Cirugía Pediátrica, Hematología"),
    _h("Hosp. Especialidades Pediátricas (CSS)", 8.9995, -79.5120, "Lunes a Domingo: 24 horas",
       "Unidad de alta especialidad médica infantil de la Caja de Seguro Social.",
       "Oncología Pediátrica, Nefrología Pediátrica, Ortopedia Infantil, Trasplantes"),
    _h("Complejo Hosp. Arnulfo Arias Madrid (CSS)", 8.9863, -79.5298, "Lunes a Domingo: 24 horas",
       "Núcleo principal de la CSS con múltiples torres de especialidades.",
       "Urgencias 24h, Trasplantes, Hemodiálisis, Neurocirugía, Cardiología Invasiva"),
    _h("Ciudad de la Salud (CSS)", 9.0270, -79.5936, "Lunes a Domingo: 24 horas",
       "Moderno complejo hospitalario público con institutos de alta complejidad.",
       "Cardiovascular, Trasplantes, Nefrología, Oncología, Hematología, Rehabilitación"),
    _h("Instituto Oncológico Nacional (MINSA)", 8.9664, -79.5448, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Hospital público especializado en la prevención y tratamiento del cáncer.",
       "Oncología Médica, Radioterapia, Quimioterapia, Cirugía Oncológica, Cuidados Paliativos"),
    _h("Hosp. San Miguel Arcángel - HISMA", 9.0352, -79.5034, "Lunes a Domingo: 24 horas",
       "Hospital público que atiende al distrito de San Miguelito y áreas colindantes.",
       "Urgencias 24h, Ginecobstetricia, Cirugía General, Pediatría, Ortopedia"),
    _h("Hosp. Susana Jones Cano (CSS)", 9.0435, -79.4795, "Lunes a Domingo: 24 horas",
       "Hospital policlínico de la CSS ubicado en Villa Lucre.",
       "Urgencias 24h, Hemodiálisis, Cirugía Ambulatoria, Ortopedia, Medicina Interna"),
    _h("Hosp. Irma De Lourdes Tzanetatos (CSS)", 9.0838, -79.3789, "Lunes a Domingo: 24 horas",
       "Hospital público regional ubicado en la zona este (Tocumen).",
       "Urgencias 24h, Psiquiatría, Trauma, Ginecología, Cirugía General, Pediatría"),
    _h("Policlínica Manuel María Valdés (CSS)", 9.0341, -79.4975, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Policlínica de atención ambulatoria en San Miguelito.",
       "Medicina General, Pediatría, Odontología, Ginecología, Laboratorio, Farmacia"),
    _h("Policlínica Generoso Guardia (CSS)", 9.0818, -79.5215, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de atención médica institucional en el área norte.",
       "Medicina General, Odontología, Pediatría, Fisioterapia, Laboratorio"),
    _h("Policlínica Carlos N. Brin (CSS)", 8.9912, -79.4996, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Instalación de salud de la CSS en San Francisco.",
       "Medicina General, Especialidades Básicas, Laboratorio, Clínica de Heridas, Rayos X"),
    _h("Policlínica Alejandro De La Guardia (CSS)", 9.0069, -79.5255, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Policlínica Betania (El Vigía) con servicios de consulta externa.",
       "Medicina General, Pediatría, Odontología, Ginecología, Programa de Tercera Edad"),
    _h("Policlínica Manuel Ferrer Valdés (CSS)", 8.9657, -79.5392, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Policlínica de Calle 25 con servicios de urgencias y laboratorios.",
       "Urgencias, Medicina General, Odontología, Clínica de Curaciones, Laboratorio"),
    _h("Policlínica J.J. Vallarino (CSS)", 9.0439, -79.4518, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Importante centro de atención especializada en Juan Díaz.",
       "Urgencias, Fisioterapia, Especialidades Médicas, Ginecología, Odontología"),
    _h("Policentro de San Isidro", 9.0653, -79.5142, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro integral de salud primaria en San Isidro.",
       "Medicina General, Vacunación, Odontología, Salud Mental, Control de Embarazo"),
    _h("Centro Médico Paitilla", 8.9779, -79.5139, "Lunes a Domingo: 24 horas",
       "Histórico centro médico privado con servicios integrales.",
       "Urgencias 24h, Oncología, Neurocirugía, Cuidados Intensivos, Maternidad"),
    _h("Clínica Hospital San Judas Tadeo (Villa Lucre)", 9.0345, -79.4838, "Lunes a Domingo: 24 horas",
       "Clínica privada con hospitalización y urgencias en Villa Lucre.",
       "Urgencias 24h, Maternidad, Cirugía Ambulatoria, Laboratorio, Rayos X"),
    _h("Clínica Albrook", 8.9742, -79.5538, "Lunes a Sábado: 8:00 am - 6:00 pm",
       "Centro de salud y consultorios en la zona de Albrook.",
       "Medicina General, Fisioterapia, Laboratorio, Odontología"),
    _h("MiniMed Costa del Este", 9.0125, -79.4690, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Clínica rápida y laboratorio en Costa del Este.",
       "Medicina General, Urgencias Menores, Hisopados, Pruebas de Laboratorio"),
    _h("Clínica Docati (Bella Vista)", 8.9838, -79.5275, "Lunes a Sábado: 8:00 am - 5:00 pm",
       "Clínica médica especializada en Bella Vista.",
       "Medicina Interna, Cardiología, Laboratorio Especializado, Check-ups"),
    _h("Clínica Bella Vista", 8.9738, -79.5345, "Lunes a Sábado: 8:00 am - 6:00 pm",
       "Clínica médica general y consultorios en Bella Vista.",
       "Medicina General, Odontología, Ginecología, Psicología"),
    _h("Centro Médico Nacional", 8.9720, -79.5335, "Lunes a Sábado: 7:00 am - 7:00 pm",
       "Edificio y centro de consultorios médicos especializados.",
       "Consultas Privadas de Especialidades, Imagenología, Nutrición"),
    _h("Clínica Hospital CHEMSA", 8.9721, -79.5336, "Lunes a Sábado: 7:00 am - 7:00 pm",
       "Clínica hospital ubicada en Calidonia (Av. Justo Arosemena).",
       "Cirugía Ambulatoria, Medicina General, Rayos X, Salud Ocupacional"),
    _h("MiniMed Las Mañanitas", 9.0795, -79.3994, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Sucursal de clínicas rápidas MiniMed en Las Mañanitas.",
       "Medicina General, Curaciones, Laboratorio Básico, Urgencias Menores"),
    _h("MiniMed Villa Lucre", 9.0405, -79.4793, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Clínica de atención rápida y laboratorio en Villa Lucre.",
       "Medicina General, Inyectables, Laboratorio, Control Médico"),
    _h("MiniMed Versalles", 9.0428, -79.4142, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Clínica ambulatoria en la zona de Versalles.",
       "Medicina General, Papanicolau, Urgencias Menores, Farmacia Básica"),
    _h("Policentro de Salud de Parque Lefevre", 9.0090, -79.4795, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de atención primaria del MINSA con medicina general y preventiva.",
       "Medicina General, Odontología, Prevención Comunitaria, Vacunación, Ginecología"),
    _h("Centro de Salud de Alcalde Díaz", 9.1126, -79.5559, "Lunes a Domingo: 24 horas",
       "Instalación pública de salud primaria que atiende el área norte del distrito.",
       "Urgencias Médicas, Medicina General, Saneamiento Ambiental, Odontología"),
    _h("Centro de Salud Boca la Caja", 8.9810, -79.5180, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención médica básica y programas comunitarios de salud para la zona costera.",
       "Medicina General, Vacunación, Programa de Crecimiento y Desarrollo"),
    _h("Centro de Salud de Santa Ana", 8.9532, -79.5412, "Lunes a Viernes: 6:00 am - 3:00 pm",
       "Centro histórico de atención primaria y medicina general en Santa Ana.",
       "Medicina General, Epidemiología, Salud Pública, Control de Enfermedades"),
    _h("Centro Médico San Luis", 9.0005, -79.5085, "Lunes a Sábado: 7:00 am - 8:00 pm",
       "Consultorios médicos, laboratorio clínico y estudios de diagnóstico con más de 40 años.",
       "Laboratorio Clínico, Electrocardiograma, Medicina General, Evaluaciones Médicas"),
    _h("Centro Médico Plaza Cecilia", 9.0342, -79.5250, "Lunes a Sábado: 8:00 am - 6:00 pm",
       "Establecimiento privado enfocado en consultas especializadas y servicios diagnósticos.",
       "Consultas Especializadas, Ultrasonidos, Ginecología, Pediatría"),

    _h("Centro de Salud de Torrijos Carter (MINSA)", 9.0715, -79.4985, "Lunes a Viernes: 7:00 am - 11:00 pm",
       "Vital centro de atención del MINSA en el corazón de San Miguelito con atención extendida.",
       "Medicina General, Urgencias, Pediatría, Odontología, Vacunación, Saneamiento"),
    _h("Centro de Salud de Veranillo (MINSA)", 9.0450, -79.5020, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria de salud enfocada en la población del sector de Veranillo y aledaños.",
       "Medicina General, Urgencias Menores, Farmacia, Laboratorio, Ginecología"),
    _h("Centro de Salud de Pedregal (MINSA)", 9.0700, -79.4320, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Instalación pública de atención primaria en el área de Pedregal.",
       "Medicina General, Odontología, Control Pre-natal, Psicología, Vacunación"),
    _h("Centro de Salud de Juan Díaz (MINSA)", 9.0305, -79.4600, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de salud del estado enfocado en prevención y atención familiar.",
       "Medicina General, Pediatría, Psiquiatría, Trabajo Social, Farmacia Institucional"),
    _h("Centro de Salud de Río Abajo (MINSA)", 9.0180, -79.4880, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Centro de atención básica y programas de fomento de salud en Río Abajo.",
       "Medicina General, Clínica de Heridas, Odontología, Enfermería"),
    _h("Centro de Salud de Tocumen (MINSA)", 9.0850, -79.3850, "Lunes a Domingo: 24 horas",
       "Importante centro público con urgencias 24h para el sector Este de la capital.",
       "Urgencias 24h, Medicina General, Odontología, Farmacia, Curaciones"),
    _h("Instituto Nacional de Salud Mental (INSAM)", 9.0060, -79.5250, "Lunes a Domingo: 24 horas",
       "Hospital público de tercer nivel especializado en la salud mental y psiquiatría.",
       "Psiquiatría, Urgencias Psiquiátricas, Psicología, Terapia Ocupacional, Trabajo Social"),
    _h("ULAPS Las Cumbres (CSS)", 9.0980, -79.5350, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Unidad Local de Atención Primaria en Salud (ULAPS) en Panamá Norte.",
       "Medicina General, Pediatría, Ginecología, Odontología, Laboratorio"),
    _h("Centro de Salud de Pueblo Nuevo (MINSA)", 9.0050, -79.5050, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Clínica comunitaria del MINSA en el corregimiento de Pueblo Nuevo.",
       "Medicina General, Control de Embarazo, Enfermería, Vacunas"),
    _h("Nova Medical Center", 8.9860, -79.5220, "Lunes a Sábado: 7:00 am - 7:00 pm",
       "Clínica privada integral y centro de salud ocupacional en Obarrio.",
       "Salud Ocupacional, Medicina General, Laboratorio, Evaluaciones Pre-Empleo"),
    _h("Centro de Salud de San Francisco (MINSA)", 8.9890, -79.5020, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Establecimiento estatal que vela por la salud primaria del corregimiento.",
       "Medicina General, Pediatría Básica, Vacunación, Salud Reproductiva"),
    _h("Clínica Integral de Salud Especializada", 8.9950, -79.5200, "Lunes a Sábado: 8:00 am - 5:00 pm",
       "Clínica de especialidades y pruebas diagnósticas avanzadas cerca de Vía Argentina.",
       "Ginecología, Dermatología, Nutrición, Laboratorio de Alta Complejidad"),

    # --- Panamá Este: Pacora, Chepo, San Martín y periferia -----------------
    _h("Hospital de Chepo (MINSA)", 9.1640, -79.1035, "Lunes a Domingo: 24 horas",
       "Hospital público de referencia para el distrito de Chepo y la comarca colindante.",
       "Urgencias 24h, Medicina General, Pediatría, Ginecobstetricia, Cirugía General, Laboratorio, Rayos X"),
    _h("Centro de Salud de Chepo (MINSA)", 9.1695, -79.0970, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria y programas preventivos en el casco urbano de Chepo.",
       "Medicina General, Odontología, Vacunación, Control Prenatal, Farmacia"),
    _h("Hospital de Pacora (MINSA)", 9.0805, -79.2900, "Lunes a Domingo: 24 horas",
       "Instalación hospitalaria del sector este con servicios de urgencia permanente.",
       "Urgencias 24h, Medicina General, Pediatría, Ginecobstetricia, Laboratorio, Rayos X"),
    _h("Centro de Salud de Pacora (MINSA)", 9.0772, -79.2861, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de salud de atención familiar y crónicos en Pacora.",
       "Medicina General, Odontología, Farmacia, Vacunación, Psicología"),
    _h("Centro de Salud de Las Garzas de Pacora", 9.0630, -79.3120, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Puesto de salud rural para las comunidades de Las Garzas y aledañas.",
       "Medicina General, Enfermería, Control Prenatal, Vacunación, Saneamiento Ambiental"),
    _h("Centro de Salud de San Martín (Panamá Este)", 9.1172, -79.2318, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria para el corregimiento de San Martín y su área de influencia.",
       "Medicina General, Odontología, Vacunación, Control de Embarazo, Enfermería"),
    _h("Centro de Salud de 24 de Diciembre", 9.0930, -79.3452, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de salud urbano con atención de urgencias menores en el este capitalino.",
       "Urgencias Menores, Medicina General, Pediatría, Odontología, Laboratorio, Farmacia"),
    _h("Centro de Salud de Cerro Azul", 9.1655, -79.4183, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Puesto de salud de montaña para las comunidades de Cerro Azul y Los Altos.",
       "Medicina General, Enfermería, Vacunación, Saneamiento Ambiental, Prevención Comunitaria"),
    _h("Centro de Salud de Chimán", 8.9333, -78.6167, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Única instalación pública de salud en el distrito costero de Chimán.",
       "Medicina General, Urgencias Básicas, Enfermería, Vacunación, Odontología"),
    _h("Centro de Salud de Taboga", 8.7845, -79.5560, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria insular para la población de Taboga y visitantes.",
       "Medicina General, Enfermería, Vacunación, Atención a la Mujer, Curaciones"),

    # --- Panamá Norte: Chilibre, Las Cumbres, Caimitillo --------------------
    _h("Centro de Salud de Chilibre (MINSA)", 9.1558, -79.6172, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de salud de referencia para el corregimiento de Chilibre.",
       "Urgencias Menores, Medicina General, Pediatría, Odontología, Vacunación, Laboratorio"),
    _h("ULAPS Chilibre (CSS)", 9.1512, -79.6118, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Unidad local de atención primaria de la CSS en Panamá Norte.",
       "Medicina General, Pediatría, Ginecología, Laboratorio, Farmacia"),
    _h("Centro de Salud de Las Cumbres (MINSA)", 9.1035, -79.5420, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de salud para la creciente población de Las Cumbres.",
       "Urgencias Menores, Medicina General, Odontología, Vacunación, Psicología"),
    _h("Centro de Salud de Caimitillo", 9.1675, -79.5735, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Puesto de salud rural al norte de Chilibre, sobre la vía Transístmica.",
       "Medicina General, Enfermería, Vacunación, Control Prenatal, Saneamiento Ambiental"),
    _h("Centro de Salud de Villa Zaita", 9.0860, -79.5390, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria para Villa Zaita y comunidades del norte capitalino.",
       "Medicina General, Pediatría, Odontología, Vacunación, Farmacia"),
    _h("Centro de Salud de San Antonio (Panamá Norte)", 9.1150, -79.5560, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Centro comunitario de salud en el corregimiento de San Antonio.",
       "Medicina General, Enfermería, Control de Embarazo, Vacunación, Nutrición"),

    # --- Balboa, Ancón, Calidonia y corregimientos centrales ---------------
    _h("Centro de Salud de Ancón (MINSA)", 8.9580, -79.5500, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Centro de atención primaria en el corregimiento de Ancón, junto a la zona canalera.",
       "Medicina General, Odontología, Vacunación, Enfermería, Salud Pública"),
    _h("Instituto Conmemorativo Gorgas (ICGES)", 8.9630, -79.5470, "Lunes a Viernes: 8:00 am - 4:00 pm",
       "Centro de investigación y referencia nacional en salud pública y enfermedades infecciosas.",
       "Epidemiología, Salud Pública, Virología, Investigación Biomédica, Laboratorio de Referencia"),
    _h("Centro de Salud de Curundú (MINSA)", 8.9700, -79.5400, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria y programas sociales para la comunidad de Curundú.",
       "Medicina General, Pediatría, Odontología, Vacunación, Trabajo Social"),
    _h("Centro de Salud de El Chorrillo (MINSA)", 8.9550, -79.5420, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Centro de salud comunitario en el casco antiguo de la ciudad.",
       "Medicina General, Enfermería, Vacunación, Atención Primaria, Curaciones"),
    _h("Centro de Salud de Calidonia (MINSA)", 8.9680, -79.5360, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria para residentes y población flotante de Calidonia.",
       "Medicina General, Odontología, Curaciones, Farmacia, Vacunación"),
    _h("Centro de Salud de Betania (MINSA)", 9.0018, -79.5128, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Centro de salud familiar del corregimiento de Betania.",
       "Medicina General, Pediatría, Odontología, Vacunación, Salud Mental"),
    _h("Centro de Salud de Vista Alegre", 9.0250, -79.5100, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria para Vista Alegre y sectores aledaños de Río Abajo.",
       "Medicina General, Enfermería, Vacunación, Control Prenatal, Farmacia"),
    _h("Centro de Salud de Cerro Viento", 9.0600, -79.4800, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Centro de salud para la zona residencial de Cerro Viento y Don Bosco.",
       "Medicina General, Pediatría, Odontología, Vacunación, Laboratorio"),
    _h("Centro de Salud de Nueva Esperanza", 9.0500, -79.4000, "Lunes a Viernes: 7:00 am - 7:00 pm",
       "Atención primaria en el corregimiento de Nueva Esperanza, San Miguelito.",
       "Medicina General, Urgencias Menores, Pediatría, Vacunación, Psicología"),
    _h("Centro de Salud de Don Bosco", 9.0200, -79.4700, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Centro comunitario de salud en el sector de Don Bosco, Juan Díaz.",
       "Medicina General, Odontología, Enfermería, Vacunación, Trabajo Social"),

    # --- Área insular: Archipiélago de las Perlas --------------------------
    _h("Centro de Salud de Isla de Balboa", 8.3500, -78.7800, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Puesto de salud para la población de Isla de Balboa, Archipiélago de las Perlas.",
       "Medicina General, Enfermería, Vacunación, Urgencias Básicas, Curaciones"),
    _h("Centro de Salud de Contadora", 8.6333, -79.0333, "Lunes a Viernes: 7:00 am - 3:00 pm",
       "Atención primaria y turística en la isla de Contadora.",
       "Medicina General, Enfermería, Curaciones, Vacunación, Urgencias Básicas"),

    # --- Centros especializados y periféricos adicionales ------------------
    _h("Clínica Oftalmológica de Panamá", 8.9925, -79.5180, "Lunes a Sábado: 8:00 am - 5:00 pm",
       "Centro privado de referencia en cirugía refractiva y enfermedades oculares.",
       "Oftalmología, Cirugía Refractiva, Retina, Glaucoma, Optometría"),
    _h("Centro Médico Panamá Este", 9.0880, -79.3250, "Lunes a Sábado: 8:00 am - 6:00 pm",
       "Clínica privada de apoyo a la creciente población del corredor este.",
       "Medicina General, Cardiología, Pediatría, Laboratorio, Ultrasonido"),
    _h("Clínica de Especialidades de Chepo", 9.1620, -79.1060, "Lunes a Sábado: 8:00 am - 5:00 pm",
       "Consultorios privados de apoyo a la red pública de Panamá Este.",
       "Medicina General, Ginecología, Pediatría, Laboratorio, Farmacia"),
    _h("Centro Médico Chilibre", 9.1580, -79.6220, "Lunes a Sábado: 8:00 am - 6:00 pm",
       "Clínica ambulatoria y de rehabilitación para Panamá Norte.",
       "Medicina General, Odontología, Laboratorio, Fisioterapia, Farmacia"),
    _h("Clínica Panamá Norte", 9.1070, -79.5520, "Lunes a Sábado: 8:00 am - 6:00 pm",
       "Centro de especialidades para Las Cumbres y Alcalde Díaz.",
       "Medicina General, Pediatría, Ginecología, Nutrición, Psicología"),
]


# ---------------------------------------------------------------------------
# 1b. CORRECCIONES DE POSICIÓN (v3.0)
#     Fuente: OpenStreetMap/Nominatim (consultado en 2026) y revisión manual.
#     Se aplican al dataset base al arrancar; también quedan documentadas para
#     que el usuario pueda auditarlas. No se tocan los nombres ni los horarios.
# ---------------------------------------------------------------------------
CORRECCIONES_DATASET: dict[str, dict] = {
    # --- Ciudad de Panamá: hospitales privados y públicos -------------------
    "Hospital Santa Fe": {"lat": 8.976101, "lon": -79.538379, "nota": "OSM: Av. Simón Bolívar, Perejil (1.4 km)"},
    "Clínica Hosp. San Fernando": {"lat": 9.003604, "lon": -79.516431, "nota": "OSM: Calle 67 Oeste, La Loma (0.8 km)"},
    "Pacífica Salud (Punta Pacífica)": {"lat": 8.982017, "lon": -79.510255, "nota": "OSM: Boulevard Isaac Hanono Missri"},
    "The Panama Clinic": {"lat": 8.978523, "lon": -79.511463, "nota": "OSM: Corredor Sur, Punta Paitilla"},
    "Clínica Hosp. Mar del Sur": {"lat": 8.972328, "lon": -79.531388, "nota": "OSM: Calle 40 Este, Perejil (0.9 km)"},
    "Hospital Nacional": {"lat": 8.972662, "lon": -79.533648, "nota": "OSM: Av. Cuba, Perejil (1.2 km)"},
    "Hospiten Paitilla": {"lat": 8.977770, "lon": -79.517960, "nota": "OSM: Hospital Paitilla"},
    "Pacífica Salud (Costa del Este)": {"lat": 9.015582, "lon": -79.464440, "nota": "OSM: Hospital Pacifica Salud, Costa del Este"},
    "Hospital Santo Tomás (MINSA)": {"lat": 8.969849, "lon": -79.532432, "nota": "OSM: Calle 36, Calidonia (0.2 km)"},
    "Hospital del Niño (MINSA)": {"lat": 8.968807, "lon": -79.532340, "nota": "OSM: Calle 35 Este, Calidonia (0.2 km)"},
    "Hosp. Especialidades Pediátricas (CSS)": {"lat": 9.000945, "lon": -79.517204, "nota": "OSM: Calle Jorge Zarak, Vía España (0.6 km)"},
    "Complejo Hosp. Arnulfo Arias Madrid (CSS)": {"lat": 8.980850, "lon": -79.534740, "nota": "OSM: Complejo Hospitalario Dr. Arnulfo Arias Madrid (0.8 km)"},
    "Ciudad de la Salud (CSS)": {"lat": 9.024610, "lon": -79.578722, "nota": "OSM/Nominatim: Av. Foresta, Ancón (1.7 km)"},
    "Instituto Oncológico Nacional (MINSA)": {"lat": 8.959857, "lon": -79.545587, "nota": "Nominatim: Calle Gorgas, Ancón (1.2 km)"},
    "Hosp. San Miguel Arcángel - HISMA": {"lat": 9.032179, "lon": -79.508655, "nota": "OSM: Vía Ricardo J. Alfaro, Victoriano Lorenzo (0.7 km)"},
    "Hosp. Susana Jones Cano (CSS)": {"lat": 9.037689, "lon": -79.483337, "nota": "OSM: Calle El Sisne, Villa Lucre (0.8 km)"},
    "Policlínica Manuel María Valdés (CSS)": {"lat": 9.037950, "lon": -79.495720, "nota": "OSM: San Miguelito (0.5 km)"},
    "Policlínica Alejandro De La Guardia (CSS)": {"lat": 9.021410, "lon": -79.525840, "nota": "OSM: Policlínica Don Alejandro de la Guardia, Betania (1.6 km)"},
    "Policlínica Manuel Ferrer Valdés (CSS)": {"lat": 8.962220, "lon": -79.539320, "nota": "OSM: Policlínica Pediátrica Manuel Ferrer Valdés (0.4 km)"},
    "Policlínica J.J. Vallarino (CSS)": {"lat": 9.055300, "lon": -79.435460, "nota": "OSM: Joaquín José Vallarino Zebede, Juan Díaz (2.2 km)"},
    "Policentro de San Isidro": {"lat": 9.064200, "lon": -79.511070, "nota": "OSM: Centro de Salud de San Isidro (0.4 km)"},
    "Centro Médico Plaza Cecilia": {"lat": 9.035130, "lon": -79.527972, "nota": "OSM: Vía Principal Condado del Rey (0.3 km)"},
    "Centro Médico Nacional": {"lat": 8.971970, "lon": -79.533560, "nota": "OSM: Av. Justo Arosemena, Calidonia"},
    "Clínica Hospital CHEMSA": {"lat": 8.968532, "lon": -79.535023, "nota": "OSM: farmacia Chemsa, Av. Justo Arosemena; clínica contigua (se eliminó el duplicado con Centro Médico Nacional)"},
    "Clínica Bella Vista": {"lat": 8.973790, "lon": -79.534442, "nota": "OSM: Av. Perú, Perejil"},
    "MiniMed Vía España": {"lat": 8.990399, "lon": -79.521385, "nota": "OSM: Av. Central España, Obarrio (0.7 km)"},
    "MiniMed Las Mañanitas": {"lat": 9.079529, "lon": -79.399395, "nota": "OSM: Carretera Panamericana, Las Mañanitas"},
    "Policentro de Salud de Parque Lefevre": {"lat": 9.022126, "lon": -79.487324, "nota": "OSM: Policentro de Salud Luis H. Moreno, Parque Lefevre (1.8 km)"},
    # --- San Miguelito y Panamá Norte --------------------------------------
    "Centro de Salud de Torrijos Carter (MINSA)": {"lat": 9.080496, "lon": -79.491565, "nota": "OSM: Centro de Salud Beliario Frías, Torrijos Carter (1.3 km)"},
    "Centro de Salud de Veranillo (MINSA)": {"lat": 9.047392, "lon": -79.499178, "nota": "OSM: Centro de Salud Nuevo Veranillo (0.4 km)"},
    "Centro de Salud de Pedregal (MINSA)": {"lat": 9.070105, "lon": -79.424322, "nota": "OSM: Av. José María Torrijos, Pedregal (0.8 km)"},
    "Centro de Salud de Juan Díaz (MINSA)": {"lat": 9.044729, "lon": -79.445078, "nota": "OSM: Calle 127 Este, Juan Díaz (2.3 km)"},
    "Centro de Salud de Río Abajo (MINSA)": {"lat": 9.013095, "lon": -79.502250, "nota": "OSM: Calle 87 Oeste, Río Abajo (1.7 km)"},
    "Centro de Salud de Tocumen (MINSA)": {"lat": 9.092437, "lon": -79.378780, "nota": "OSM: Calle Bajo Cordero, Tocumen (1.1 km)"},
    "Instituto Nacional de Salud Mental (INSAM)": {"lat": 9.031485, "lon": -79.482078, "nota": "OSM: Av. 2 F Norte, Río Abajo (5.5 km)"},
    "Centro de Salud de Pueblo Nuevo (MINSA)": {"lat": 9.016379, "lon": -79.515454, "nota": "OSM: Av. Fernández de Córdoba, Pueblo Nuevo (1.7 km)"},
    "Centro de Salud de Alcalde Díaz": {"lat": 9.112679, "lon": -79.555915, "nota": "OSM: Calle Central Alcalde Díaz"},
    "Centro de Salud de Santa Ana": {"lat": 8.953180, "lon": -79.541220, "nota": "OSM: Calle 17 Este, Santa Ana"},
    "Centro de Salud de Curundú (MINSA)": {"lat": 8.970211, "lon": -79.543309, "nota": "OSM: Av. 4A Norte, Curundú (0.4 km)"},
    "Centro de Salud de El Chorrillo (MINSA)": {"lat": 8.947475, "lon": -79.548420, "nota": "OSM: Calle 27, El Chorrillo (1.1 km)"},
    "Centro de Salud de Calidonia (MINSA)": {"lat": 8.973711, "lon": -79.535909, "nota": "OSM: Centro de Diagnóstico Ambulatorio, Av. Central (0.6 km)"},
    # --- Panamá Este --------------------------------------------------------
    "Hospital de Chepo (MINSA)": {"lat": 9.161071, "lon": -79.095869, "nota": "OSM: Hospital Regional de Chepo (0.9 km)"},
    "Centro de Salud de Pacora (MINSA)": {"lat": 9.087445, "lon": -79.289886, "nota": "OSM: Calle 1era, Las Colinas de Pacora (1.2 km)"},
    "Centro de Salud de Cerro Azul": {"lat": 9.182382, "lon": -79.408595, "nota": "OSM: Paseo Vistamares, Cerro Azul (2.2 km)"},
    "Centro de Salud de Chimán": {"lat": 8.716884, "lon": -78.633195, "nota": "Nominatim: casco urbano de Chimán; la v2 lo había movido 24 km al norte por un error de la máscara de costa"},
    "Centro de Salud de Taboga": {"lat": 8.794976, "lon": -79.554845, "nota": "OSM: Calle Francisco Pizarro, Taboga (1.2 km)"},
    # --- Panamá Norte / Chilibre -------------------------------------------
    "Centro de Salud de Chilibre (MINSA)": {"lat": 9.174299, "lon": -79.611182, "nota": "OSM: Av. Madden, Villa Unida, Chilibre (2.2 km)"},
    "Centro de Salud de Caimitillo": {"lat": 9.158763, "lon": -79.539870, "nota": "OSM: Calle Calzada Larga, Caimitillo (3.8 km)"},
    # --- Área insular -------------------------------------------------------
    "Centro de Salud de Isla de Balboa": {"lat": 8.348062, "lon": -78.896185, "nota": "Nominatim: Isla del Rey, Archipiélago de las Perlas; centro insular (sin ruta terrestre)"},
}


def _aplicar_correcciones_base(registros: list[dict]) -> None:
    """Mueve las coordenadas corregidas y las marca como verificadas."""
    por_nombre = {r["nombre"]: r for r in registros}
    for nombre, cambio in CORRECCIONES_DATASET.items():
        r = por_nombre.get(nombre)
        if r is None:
            continue
        r["lat"] = float(cambio["lat"])
        r["lon"] = float(cambio["lon"])
        r["verificada"] = True
        r["fuente"] = "OpenStreetMap/Nominatim"
        r["nota"] = cambio.get("nota", "")


_aplicar_correcciones_base(hospitales)



# ---------------------------------------------------------------------------
# 2. UTILIDADES GEOGRÁFICAS Y DE TEXTO
# ---------------------------------------------------------------------------
RADIO_TIERRA_KM = 6371.0088


def sin_acentos(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def normalizar_clave(texto: str) -> str:
    return re.sub(r"\s+", " ", sin_acentos(texto).lower()).strip()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia ortodrómica en km (misma fórmula y radio que el mapa JS)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return RADIO_TIERRA_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def costa_lat(lon: float) -> float:
    """Latitud de la costa aproximada en una longitud dada (interpolación lineal)."""
    pts = COSTA_APROX
    if lon <= pts[0][0]:
        return pts[0][1]
    if lon >= pts[-1][0]:
        return pts[-1][1]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x1 <= lon <= x2:
            return y1 + (y2 - y1) * (lon - x1) / (x2 - x1)
    return pts[-1][1]


def en_el_mar(lat: float, lon: float, tolerancia: float = 0.006) -> bool:
    """True si el punto cae al sur de la costa aproximada (tolerancia ~0.7 km)."""
    return lat < costa_lat(lon) - tolerancia


def _decimales(valor: float) -> int:
    s = repr(float(valor))
    return len(s.split(".")[1]) if "." in s and "e" not in s else 0


# ---------------------------------------------------------------------------
# 3. HORARIOS ("Lunes a Sábado: 7:00 am - 8:00 pm") -> estructura evaluable
# ---------------------------------------------------------------------------
_DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4,
         "sabado": 5, "domingo": 6}
_RE_HORARIO = re.compile(
    r"^(?P<d1>[a-záéíóú]+) a (?P<d2>[a-záéíóú]+):\s*"
    r"(?:(?P<h24>24 horas)|(?P<a>\d{1,2}:\d{2}) (?P<ap1>[ap])m\s*-\s*(?P<c>\d{1,2}:\d{2}) (?P<ap2>[ap])m)$",
    re.IGNORECASE,
)


def _minutos(hhmm: str, ampm: str) -> int:
    h, m = (int(x) for x in hhmm.split(":"))
    h = h % 12 + (12 if ampm.lower() == "p" else 0)
    return h * 60 + m


def parsear_horario(texto: str) -> dict | None:
    """Devuelve {'dias': [0..6], 'h24': bool, 'abre': min, 'cierra': min} o None."""
    m = _RE_HORARIO.match(str(texto).strip())
    if not m:
        return None
    d1 = _DIAS.get(normalizar_clave(m["d1"]))
    d2 = _DIAS.get(normalizar_clave(m["d2"]))
    if d1 is None or d2 is None:
        return None
    dias = list(range(d1, d2 + 1)) if d1 <= d2 else list(range(d1, 7)) + list(range(0, d2 + 1))
    if m["h24"]:
        return {"dias": dias, "h24": True}
    return {"dias": dias, "h24": False,
            "abre": _minutos(m["a"], m["ap1"]), "cierra": _minutos(m["c"], m["ap2"])}


def ahora_panama():
    """Hora local de Panamá (UTC-5 todo el año, sin horario de verano)."""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-5)))


def esta_abierto(info: dict | None, ahora, offset_min: float = 0.0):
    """True/False según el horario; None si el horario no se pudo interpretar."""
    if not info:
        return None
    from datetime import timedelta
    t = ahora + timedelta(minutes=offset_min)
    dia, minuto = t.weekday(), t.hour * 60 + t.minute
    if info["h24"]:
        return dia in info["dias"]
    abre, cierra = info["abre"], info["cierra"]
    if abre < cierra:
        return dia in info["dias"] and abre <= minuto < cierra
    ayer = (dia - 1) % 7                      # el turno cruza la medianoche
    return (dia in info["dias"] and minuto >= abre) or (ayer in info["dias"] and minuto < cierra)


# ---------------------------------------------------------------------------
# 4. CARGA, CORRECCIONES Y ENRIQUECIMIENTO DEL DATASET
# ---------------------------------------------------------------------------
CAMPOS_BASE = ("nombre", "lat", "lon", "horario", "descripcion", "especialidades")


def directorio_script() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _a_bool(valor) -> bool:
    return str(valor).strip().lower() in {"1", "true", "si", "sí", "yes", "x"}


def leer_dataset_externo(ruta: str) -> list[dict]:
    """Carga un dataset propio desde .json (lista de objetos) o .csv (con encabezados)."""
    if ruta.lower().endswith(".json"):
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, list):
            raise ValueError("El JSON debe ser una lista de instalaciones.")
        return datos
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    salida = []
    for fila in filas:
        reg = {k: (fila.get(k) or "").strip() for k in CAMPOS_BASE}
        reg["lat"], reg["lon"] = float(fila["lat"]), float(fila["lon"])
        if fila.get("insular"):
            reg["insular"] = _a_bool(fila["insular"])
        if fila.get("verificada"):
            reg["verificada"] = _a_bool(fila["verificada"])
        salida.append(reg)
    return salida


def aplicar_correcciones(registros: list[dict], correcciones: dict) -> tuple[list[str], list[str]]:
    """Aplica {nombre: {lat, lon, verificada, fuente, nota}}. Devuelve (aplicadas, desconocidas)."""
    por_nombre = {r["nombre"]: r for r in registros}
    aplicadas, desconocidas = [], []
    for nombre, cambio in correcciones.items():
        reg = por_nombre.get(nombre)
        if reg is None:
            desconocidas.append(nombre)
            continue
        for clave in ("lat", "lon"):
            if clave in cambio:
                reg[clave] = float(cambio[clave])
        for clave in ("verificada", "fuente", "nota"):
            if clave in cambio:
                reg[clave] = cambio[clave]
        aplicadas.append(nombre)
    return aplicadas, desconocidas


def enriquecer(registros: list[dict]) -> list[dict]:
    """Agrega id, insular, resolución numérica, verificada y horario estructurado."""
    salida = []
    for i, h in enumerate(registros):
        r = dict(h)
        dec = min(_decimales(r["lat"]), _decimales(r["lon"]))
        r["id"] = i
        r["insular"] = bool(r.get("insular")) or r["nombre"] in NOMBRES_INSULARES
        r["resolucion_m"] = max(1, int(round(55660 * 10 ** -dec)))   # semi-paso del último decimal
        r["verificada"] = bool(r.get("verificada", False))
        r["fuente"] = str(r.get("fuente") or "")
        r["horario_info"] = parsear_horario(r.get("horario", ""))
        salida.append(r)
    return salida


def cargar_dataset(ruta_datos: str | None = None,
                   ruta_correcciones: str | None = None) -> tuple[list[dict], list[str]]:
    """Dataset final = base (o archivo propio) + correcciones_coordenadas.json si existe."""
    base = leer_dataset_externo(ruta_datos) if ruta_datos else [dict(h) for h in hospitales]
    avisos: list[str] = []
    ruta_corr = ruta_correcciones or os.path.join(directorio_script(), ARCHIVO_CORRECCIONES)
    if os.path.exists(ruta_corr):
        with open(ruta_corr, encoding="utf-8") as f:
            correcciones = json.load(f)
        aplicadas, desconocidas = aplicar_correcciones(base, correcciones)
        avisos.append(f"Correcciones aplicadas desde {os.path.basename(ruta_corr)}: {len(aplicadas)}")
        for nombre in desconocidas:
            avisos.append(f"Corrección ignorada (nombre no encontrado): {nombre}")
    return enriquecer(base), avisos


def exportar_dataset(registros: list[dict], ruta: str) -> None:
    """Guarda el dataset (JSON o CSV) para editarlo y volver a cargarlo con --datos."""
    limpio = [{k: r.get(k) for k in CAMPOS_BASE + ("insular", "verificada")} for r in registros]
    if ruta.lower().endswith(".json"):
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(limpio, f, ensure_ascii=False, indent=2)
        return
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CAMPOS_BASE) + ["insular", "verificada"])
        w.writeheader()
        w.writerows(limpio)


# ---------------------------------------------------------------------------
# 5. VALIDACIÓN DEL DATASET
# ---------------------------------------------------------------------------
def validar_dataset(registros: list[dict], umbral_solape_m: float = 150.0) -> list[dict]:
    """Lista de hallazgos {nivel: 'error'|'aviso'|'info', nombre, msg}."""
    hallazgos: list[dict] = []

    def add(nivel: str, nombre: str, msg: str) -> None:
        hallazgos.append({"nivel": nivel, "nombre": nombre, "msg": msg})

    lim = CONFIG["limites"]
    vistos: dict[str, int] = {}
    for h in registros:
        n = h.get("nombre", "?")
        vistos[n] = vistos.get(n, 0) + 1
        faltan = [c for c in CAMPOS_BASE if not str(h.get(c, "")).strip()]
        if faltan:
            add("error", n, f"campos vacíos: {', '.join(faltan)}")
            continue
        lat, lon = h["lat"], h["lon"]
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            add("error", n, "lat/lon no numéricos")
            continue
        if not (lim["latMin"] <= lat <= lim["latMax"] and lim["lonMin"] <= lon <= lim["lonMax"]):
            add("error", n, f"fuera de la Provincia de Panamá ({lat}, {lon})")
        if not h.get("insular") and en_el_mar(lat, lon):
            add("error", n, f"la posición ({lat}, {lon}) cae en el mar según la costa aproximada")
        if min(_decimales(lat), _decimales(lon)) <= 2 and not h.get("verificada"):
            add("aviso", n, f"resolución baja ({lat}, {lon}): error posible de ~{h.get('resolucion_m', '?')} m o más")
        if not h.get("horario_info"):
            add("aviso", n, f"horario no interpretable: «{h.get('horario')}»")
        nombre_norm = normalizar_clave(n)
        for clave_loc, (a_lat, a_lon) in ANCLAS_LOCALIDAD.items():
            if re.search(r"\b" + re.escape(clave_loc) + r"\b", nombre_norm):
                d_loc = haversine_km(lat, lon, a_lat, a_lon)
                if d_loc > UMBRAL_ANCLA_KM:
                    add("aviso", n, f"queda a {d_loc:.1f} km del centro de «{clave_loc}»; revisar la posición")
                break
    for n, c in vistos.items():
        if c > 1:
            add("error", n, f"nombre duplicado ({c} veces)")

    for i in range(len(registros)):
        for j in range(i + 1, len(registros)):
            a, b = registros[i], registros[j]
            try:
                d = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) * 1000
            except (KeyError, TypeError):
                continue
            if d < 30:
                add("aviso", a["nombre"], f"a solo {d:.0f} m de «{b['nombre']}»: ¿coordenadas copiadas? Conviene verificar ambas")
            elif d < umbral_solape_m:
                add("info", a["nombre"], f"a {d:.0f} m de «{b['nombre']}» (marcadores solapados; el mapa los agrupa)")
    return hallazgos


def imprimir_validacion(hallazgos: list[dict], detallado: bool) -> None:
    cuenta = {n: sum(1 for h in hallazgos if h["nivel"] == n) for n in ("error", "aviso", "info")}
    print(f"  Validación del dataset    : {cuenta['error']} errores · {cuenta['aviso']} avisos · "
          f"{cuenta['info']} observaciones")
    if detallado:
        iconos = {"error": "✖", "aviso": "!", "info": "·"}
        for nivel in ("error", "aviso", "info"):
            for h in hallazgos:
                if h["nivel"] == nivel:
                    print(f"    {iconos[nivel]} [{nivel}] {h['nombre']}: {h['msg']}")


# ---------------------------------------------------------------------------
# 6. MODELO DE REFERENCIA EN PYTHON (mismo modelo que el mapa JS)
# ---------------------------------------------------------------------------
def factor_friccion(lat: float, lon: float, cfg: dict = CONFIG) -> float:
    f = 1.0
    for z in ZONAS_FRICCION:
        d = haversine_km(lat, lon, z["lat"], z["lon"])
        f += z["peso"] * math.exp(-(d * d) / (z["radio"] * z["radio"]))
    return min(f, cfg["maxFriccion"])


def friccion_segmento(lat1, lon1, lat2, lon2, d_recta: float, cfg: dict = CONFIG) -> float:
    """Fricción media a lo largo del tramo (regla del punto medio), no solo en los extremos."""
    m = min(12, max(1, math.ceil(d_recta / cfg["muestrasFriccionKm"])))
    s = 0.0
    for k in range(m):
        t = (k + 0.5) / m
        s += factor_friccion(lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t, cfg)
    return s / m


def crear_arista(d_recta: float, friccion: float, cfg: dict = CONFIG, sinuosidad: float | None = None,
                 velocidad: float | None = None) -> tuple:
    """(km por calle, km en recta, ETA min, fricción). Los km incorporan la sinuosidad vial
    (`sinuosidad=1.0` da el modo de línea recta). `velocidad` permite el modo directo."""
    s = cfg["sinuosidad"] if sinuosidad is None else sinuosidad
    v = cfg["velocidadLibreKmh"] if velocidad is None else velocidad
    km = max(d_recta * s, 0.05)
    f = min(max(friccion, 1.0), cfg["maxFriccion"])
    return km, d_recta, km * f * 60 / v, f


def _agregar_arista(adj: list[list[tuple]], pares: set, registros: list[dict],
                    u: int, v: int, cfg: dict = CONFIG) -> None:
    """Agrega una arista no dirigida una sola vez (nodos 1..N)."""
    a, b = min(u, v), max(u, v)
    if a == b or (a, b) in pares:
        return
    pares.add((a, b))
    ha, hb = registros[a - 1], registros[b - 1]
    d = haversine_km(ha["lat"], ha["lon"], hb["lat"], hb["lon"])
    km, _rect, eta, _f = crear_arista(
        d, friccion_segmento(ha["lat"], ha["lon"], hb["lat"], hb["lon"], d, cfg), cfg)
    adj[a].append((b, km, eta))
    adj[b].append((a, km, eta))


def construir_grafo_base(registros: list[dict], cfg: dict = CONFIG) -> list[list[tuple]]:
    """Grafo de instalaciones terrestres: kNN + árbol de expansión mínima (MST).

    El MST garantiza que el grafo sea conexo (con kNN puro podía dividirse en islas y
    dejar centros inalcanzables). Nodo 0 reservado al origen; hospital i -> nodo i+1."""
    adj: list[list[tuple]] = [[] for _ in range(len(registros) + 1)]
    ids = [i + 1 for i, h in enumerate(registros) if not h.get("insular")]
    pares: set = set()
    # 1) k vecinos más cercanos de cada instalación
    for u in ids:
        hu = registros[u - 1]
        vec = sorted(((haversine_km(hu["lat"], hu["lon"], registros[v - 1]["lat"], registros[v - 1]["lon"]), v)
                      for v in ids if v != u), key=lambda x: x[0])
        for _d, v in vec[:cfg["kVecinos"]]:
            _agregar_arista(adj, pares, registros, u, v, cfg)
    # 2) MST (Prim) para conectar todos los componentes
    if len(ids) > 1:
        en_arbol = {ids[0]}
        while len(en_arbol) < len(ids):
            mejor = None
            for u in en_arbol:
                hu = registros[u - 1]
                for v in ids:
                    if v in en_arbol:
                        continue
                    d = haversine_km(hu["lat"], hu["lon"], registros[v - 1]["lat"], registros[v - 1]["lon"])
                    if mejor is None or d < mejor[0]:
                        mejor = (d, u, v)
            if mejor is None:
                break
            _agregar_arista(adj, pares, registros, mejor[1], mejor[2], cfg)
            en_arbol.add(mejor[2])
    return adj


def grafo_con_origen(base, registros, lat, lon, cfg: dict = CONFIG, sinuosidad: float | None = None,
                     modo: str = "calles"):
    """Agrega el origen al grafo.

    modo="directa": solo enlaces directos origen -> cada instalación terrestre, sin calles,
    sin tráfico y a `velocidadDirectaKmh` (es el modo «1 · Vía directa»).
    modo="calles" : enlaces del origen a sus `kOrigen` instalaciones más cercanas; el resto se
    alcanza por la red de hospitales (Dijkstra)."""
    if modo == "directa":
        adj = [[] for _ in range(len(registros) + 1)]
        for i, h in enumerate(registros):
            if h.get("insular"):
                continue
            d = haversine_km(lat, lon, h["lat"], h["lon"])
            km, rect, eta, f = crear_arista(d, 1.0, cfg, sinuosidad=1.0,
                                            velocidad=cfg["velocidadDirectaKmh"])
            adj[0].append((i + 1, km, eta))
            adj[i + 1].append((0, km, eta))
        return adj
    adj = [list(v) for v in base]
    cercanos = sorted(((haversine_km(lat, lon, h["lat"], h["lon"]), i + 1)
                       for i, h in enumerate(registros) if not h.get("insular")),
                      key=lambda x: x[0])
    for d, nodo in cercanos[:max(1, int(cfg.get("kOrigen", 8)))]:
        h = registros[nodo - 1]
        km, rect, eta, f = crear_arista(
            d, friccion_segmento(lat, lon, h["lat"], h["lon"], d, cfg), cfg, sinuosidad)
        adj[0].append((nodo, km, eta))
        adj[nodo].append((0, km, eta))
    return adj


def dijkstra(adj, origen: int, objetivos: set | None = None, detener_en_primero: bool = False) -> dict:
    n = len(adj)
    dist = [math.inf] * n
    dist_km = [0.0] * n
    prev = [-1] * n
    hecho = [False] * n
    explorados = relajaciones = 0
    destino = -1
    dist[origen] = 0.0
    cola = [(0.0, origen)]
    while cola:
        d, u = heapq.heappop(cola)
        if hecho[u] or d > dist[u] + 1e-12:
            continue
        hecho[u] = True
        explorados += 1
        if objetivos and u in objetivos:
            destino = u
            if detener_en_primero:
                break
        for v, km, eta in adj[u]:
            relajaciones += 1
            nuevo = dist[u] + eta
            if nuevo < dist[v] - 1e-12:
                dist[v] = nuevo
                dist_km[v] = dist_km[u] + km
                prev[v] = u
                heapq.heappush(cola, (nuevo, v))
    return {"dist": dist, "dist_km": dist_km, "prev": prev, "explorados": explorados,
            "relajaciones": relajaciones, "destino": destino, "total": n}


def reconstruir_camino(res: dict, destino: int) -> list[int] | None:
    if destino < 0 or not math.isfinite(res["dist"][destino]):
        return None
    camino, actual = [], destino
    while actual != -1:
        camino.append(actual)
        actual = res["prev"][actual]
    return camino[::-1]


def consulta_modelo(registros: list[dict], lat: float, lon: float, especialidad: str | None = None,
                    top: int = 5, solo_abiertos: bool = False, cfg: dict = CONFIG,
                    modo: str = "calles", destino: int | None = None) -> dict:
    """Ranking por ETA desde (lat, lon) con Dijkstra.

    modo="calles"  : red de instalaciones (kNN + MST) + accesos del origen a sus k más
                     cercanos, con sinuosidad vial y fricción de tráfico.
    modo="directa" : solo enlaces directos origen -> centro, sin calles, sin tráfico y a
                     `velocidadDirectaKmh`. `destino` fuerza un índice concreto.
    """
    modo = "directa" if modo == "recta" else modo
    if modo not in ("calles", "directa"):
        raise ValueError("modo debe ser 'calles' o 'directa'")
    clave = normalizar_clave(especialidad) if especialidad else None
    cand = [i for i, h in enumerate(registros) if not h.get("insular") and (
        clave is None or any(clave in normalizar_clave(e) for e in h["especialidades"].split(",")))]
    if not cand:
        return {"filas": [], "camino": None, "motivo": "ninguna instalación terrestre ofrece esa especialidad",
                "modo": modo}
    if modo == "directa":
        adj = grafo_con_origen([[] for _ in range(len(registros) + 1)], registros, lat, lon, cfg, modo="directa")
    else:
        adj = grafo_con_origen(construir_grafo_base(registros, cfg), registros, lat, lon, cfg, modo="calles")
    res = dijkstra(adj, 0)
    ahora = ahora_panama()
    filas = []
    for i in cand:
        eta = res["dist"][i + 1]
        if not math.isfinite(eta):
            continue
        abierto = esta_abierto(registros[i].get("horario_info"), ahora, eta)
        filas.append({"idx": i, "nombre": registros[i]["nombre"], "eta_min": eta, "km": res["dist_km"][i + 1],
                      "recta_km": haversine_km(lat, lon, registros[i]["lat"], registros[i]["lon"]),
                      "abierto_a_la_llegada": abierto})
    filas.sort(key=lambda f: f["eta_min"])
    if solo_abiertos:
        abiertas = [f for f in filas if f["abierto_a_la_llegada"] is not False]
        filas = abiertas or filas
    if not filas:
        return {"filas": [], "camino": None, "motivo": "ningún centro alcanzable por la red", "modo": modo}
    elegido = filas[0]
    if destino is not None:
        elegido = next((f for f in filas if f["idx"] == destino), elegido)
    camino = reconstruir_camino(res, elegido["idx"] + 1)
    return {"filas": filas[:top], "camino": camino, "elegido": elegido,
            "eta_elegido": elegido["eta_min"], "km_elegido": elegido["km"],
            "explorados": res["explorados"], "relajaciones": res["relajaciones"],
            "nodos": res["total"], "modo": modo}


# ---------------------------------------------------------------------------
# 7. RUTAS REALES (OSRM) Y VERIFICACIÓN CONTRA OPENSTREETMAP (Nominatim)
# ---------------------------------------------------------------------------
def _http_get_json(url: str, timeout: float = 10.0, user_agent: str = f"rutas-salud-panama/{VERSION}") -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def osrm_ruta(base_url: str, lat1, lon1, lat2, lon2, timeout: float = 10.0) -> dict | None:
    """Distancia (km) y tiempo (min) reales por calles entre dos puntos, o None si falla."""
    url = (f"{base_url.rstrip('/')}/route/v1/driving/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
           "?overview=false&alternatives=false")
    try:
        datos = _http_get_json(url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(datos, dict) or datos.get("code") != "Ok" or not datos.get("routes"):
        return None
    r = datos["routes"][0]
    return {"km": r["distance"] / 1000.0, "min": r["duration"] / 60.0}


TIPOS_SALUD = {"hospital", "clinic", "doctors", "health_post", "centre", "laboratory", "dentist", "nursing_home"}
CATEGORIAS_SALUD = {"amenity", "healthcare"}
_ETIQUETAS_INSTITUCION = re.compile(r"\s*\((?:MINSA|CSS|ICGES)\)", re.IGNORECASE)


def consultas_nominatim(nombre: str) -> list[str]:
    """Variantes del nombre para geocodificar (sin siglas institucionales, abreviaturas expandidas)."""
    n = _ETIQUETAS_INSTITUCION.sub("", nombre)
    n = re.sub(r"\bHosp\.\s*", "Hospital ", n)
    n = re.sub(r"\bHospital\s+Hospital\b", "Hospital", n)
    n = n.replace("Clínica Hosp.", "Clínica Hospital").replace("  ", " ").strip()
    sin_parentesis = re.sub(r"\s*\([^)]*\)", "", n).strip()
    con_parentesis = re.sub(r"[()]", "", n).strip()
    variantes = [f"{con_parentesis}, Panamá", f"{sin_parentesis}, Panamá"]
    return list(dict.fromkeys(variantes))


def geocodificar_nominatim(consulta: str, user_agent: str, timeout: float = 15.0) -> list[dict]:
    lim = CONFIG["limites"]
    params = urllib.parse.urlencode({
        "q": consulta, "format": "jsonv2", "limit": 5, "countrycodes": "pa", "addressdetails": 0,
        "viewbox": f"{lim['lonMin']},{lim['latMax']},{lim['lonMax']},{lim['latMin']}", "bounded": 1,
    })
    return _http_get_json(f"https://nominatim.openstreetmap.org/search?{params}", timeout, user_agent)  # type: ignore[return-value]


def clasificar_discrepancia(dist_m: float | None) -> str:
    if dist_m is None:
        return "sin_resultado"
    if dist_m <= 150:
        return "ok"
    if dist_m <= 3000:
        return "revisar"
    return "discrepante"


def verificar_coordenadas(registros: list[dict], directorio: str, email: str = "", aplicar: bool = False,
                          pausa_s: float = 1.1) -> dict:
    """Compara cada instalación con OSM/Nominatim (política: 1 petición/s, User-Agent propio, caché).

    Escribe en `directorio`: verificacion_coordenadas.csv, correcciones_sugeridas.json y, con
    aplicar=True, actualiza correcciones_coordenadas.json (solo casos 'ok' -> verificada, y
    'revisar' con tipo de salud en OSM -> mueve el punto). Los 'discrepantes' NUNCA se aplican solos.
    """
    ua = f"rutas-salud-panama/{VERSION} (proyecto academico{'; ' + email if email else ''})"
    ruta_cache = os.path.join(directorio, "cache_nominatim.json")
    cache: dict = {}
    if os.path.exists(ruta_cache):
        with open(ruta_cache, encoding="utf-8") as f:
            cache = json.load(f)

    filas, sugeridas = [], {}
    for k, h in enumerate(registros, 1):
        print(f"  [{k:>3}/{len(registros)}] {h['nombre']}", flush=True)
        candidatos = []
        for q in consultas_nominatim(h["nombre"]):
            if q not in cache:
                try:
                    cache[q] = geocodificar_nominatim(q, ua)
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                    print(f"      sin respuesta ({exc}); se continúa", flush=True)
                    cache[q] = []
                time.sleep(pausa_s)
            candidatos += [r for r in cache[q]
                           if r.get("category") in CATEGORIAS_SALUD and r.get("type") in TIPOS_SALUD]
            if candidatos:
                break
        # Con varias sedes homónimas (MiniMed, ULAPS...) se toma la más cercana a la posición actual.
        elegido = min(candidatos, key=lambda r: haversine_km(h["lat"], h["lon"], float(r["lat"]), float(r["lon"])),
                      default=None)
        if elegido:
            lat_o, lon_o = float(elegido["lat"]), float(elegido["lon"])
            d = haversine_km(h["lat"], h["lon"], lat_o, lon_o) * 1000
        else:
            lat_o = lon_o = d = None
        estado = clasificar_discrepancia(d)
        filas.append({"nombre": h["nombre"], "lat_actual": h["lat"], "lon_actual": h["lon"],
                      "lat_osm": lat_o, "lon_osm": lon_o, "distancia_m": None if d is None else round(d),
                      "estado": estado, "osm": (elegido or {}).get("display_name", "")})
        if estado in ("ok", "revisar"):
            sug = {"verificada": True, "fuente": "OpenStreetMap/Nominatim"}
            if estado == "revisar":
                sug.update(lat=round(lat_o, 6), lon=round(lon_o, 6),
                           nota=f"movida {round(d)} m según OSM")
            sugeridas[h["nombre"]] = sug

    with open(ruta_cache, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    with open(os.path.join(directorio, "verificacion_coordenadas.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    with open(os.path.join(directorio, "correcciones_sugeridas.json"), "w", encoding="utf-8") as f:
        json.dump(sugeridas, f, ensure_ascii=False, indent=2)

    if aplicar:
        ruta_corr = os.path.join(directorio, ARCHIVO_CORRECCIONES)
        actuales = {}
        if os.path.exists(ruta_corr):
            with open(ruta_corr, encoding="utf-8") as f:
                actuales = json.load(f)
        actuales.update(sugeridas)
        with open(ruta_corr, "w", encoding="utf-8") as f:
            json.dump(actuales, f, ensure_ascii=False, indent=2)
    resumen = {e: sum(1 for x in filas if x["estado"] == e) for e in ("ok", "revisar", "discrepante", "sin_resultado")}
    return {"filas": filas, "resumen": resumen, "sugeridas": sugeridas}


# ---------------------------------------------------------------------------
# 7b. EXPORTACIÓN A PDF  (función aparte; reportlab es OPCIONAL)
#     Con reportlab: informe con tablas y croquis. Sin reportlab: PDF de texto generado con
#     un escritor mínimo propio (sin dependencias), con las mismas tablas.
#     API pública:  exportar_pdf_ranking(datos, ruta)  ·  exportar_pdf_dataset(registros, hallazgos, ruta)
# ---------------------------------------------------------------------------
MAX_FILAS_PDF = 60
_SUSTITUCIONES_PDF = {"→": "->", "≈": "~", "≤": "<=", "≥": ">=", "✓": "si", "✖": "x", "▸": ">", "▾": "v"}


def _latin(texto) -> str:
    """Texto seguro para las fuentes estándar de PDF (WinAnsi/cp1252)."""
    t = "" if texto is None else str(texto)
    for a, b in _SUSTITUCIONES_PDF.items():
        t = t.replace(a, b)
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t)
    return t.encode("cp1252", errors="replace").decode("cp1252")


def _txt(valor, largo: int = 160) -> str:
    t = "" if valor is None else str(valor)
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t).strip()[:largo]


def _num(valor, defecto=None):
    if isinstance(valor, bool):
        return defecto
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return defecto
    return x if math.isfinite(x) else defecto


def _fmt(valor, decimales: int = 1, sufijo: str = "") -> str:
    return "—" if valor is None else f"{valor:.{decimales}f}{sufijo}"


def normalizar_payload_pdf(datos) -> dict:
    """Valida y limpia el JSON que llega del navegador (o de la consulta por terminal)."""
    if not isinstance(datos, dict):
        raise ValueError("el cuerpo debe ser un objeto JSON")
    origen = datos.get("origen") if isinstance(datos.get("origen"), dict) else {}
    lat, lon = _num(origen.get("lat")), _num(origen.get("lon"))
    if lat is None or lon is None:
        raise ValueError("falta el origen (lat/lon)")
    lim = CONFIG["limites"]
    if not (lim["latMin"] <= lat <= lim["latMax"] and lim["lonMin"] <= lon <= lim["lonMax"]):
        raise ValueError("el origen está fuera de la Provincia de Panamá")
    filas = []
    for f in (datos.get("filas") or [])[:MAX_FILAS_PDF]:
        if not isinstance(f, dict):
            continue
        valores = [_num(f.get(k)) for k in ("lat", "lon", "eta", "km")]
        if any(v is None for v in valores):
            continue
        filas.append({"nombre": _txt(f.get("nombre"), 90), "lat": valores[0], "lon": valores[1],
                      "eta": valores[2], "km": valores[3], "recta_km": _num(f.get("recta_km")),
                      "abierto": f.get("abierto") if isinstance(f.get("abierto"), bool) else None,
                      "horario": _txt(f.get("horario"), 70)})
    if not filas:
        raise ValueError("no hay filas de ranking para exportar")
    d = datos.get("destino") if isinstance(datos.get("destino"), dict) else {}
    cfg = datos.get("cfg") if isinstance(datos.get("cfg"), dict) else {}
    return {
        "origen": {"lat": lat, "lon": lon, "nombre": _txt(origen.get("nombre") or "Punto de consulta", 80)},
        "especialidad": _txt(datos.get("especialidad") or "cualquier especialidad", 90),
        "modo": "directa" if datos.get("modo") in ("directa", "recta") else "calles",
        "velocidad_directa": _num(datos.get("velocidad_directa")) or CONFIG["velocidadDirectaKmh"],
        "fuente": "real" if datos.get("fuente") == "real" else "modelo",
        "cfg": {"sinuosidad": _num(cfg.get("sinuosidad")), "velocidad": _num(cfg.get("velocidad"))},
        "destino": {
            "nombre": _txt(d.get("nombre"), 90), "horario": _txt(d.get("horario"), 70),
            "especialidades": _txt(d.get("especialidades"), 300),
            "km": _num(d.get("km")), "eta": _num(d.get("eta")), "recta_km": _num(d.get("recta_km")),
            "penal_pct": _num(d.get("penal_pct")), "min_libre": _num(d.get("min_libre")),
            "abierto": d.get("abierto") if isinstance(d.get("abierto"), bool) else None,
        },
        "filas": filas,
    }


def payload_desde_consulta(registros: list[dict], res: dict, lat: float, lon: float,
                           especialidad: str | None, modo: str) -> dict:
    """Convierte el resultado de consulta_modelo() en el payload del informe PDF."""
    filas = []
    for f in res["filas"]:
        h = registros[f["idx"]]
        filas.append({"nombre": h["nombre"], "lat": h["lat"], "lon": h["lon"], "eta": f["eta_min"],
                      "km": f["km"], "recta_km": f["recta_km"], "abierto": f["abierto_a_la_llegada"],
                      "horario": h["horario"]})
    top = res["filas"][0]
    h0 = registros[top["idx"]]
    if modo in ("directa", "recta"):
        modo = "directa"
        libre = top["km"] * 60 / CONFIG["velocidadDirectaKmh"]
    else:
        libre = top["km"] * 60 / CONFIG["velocidadLibreKmh"]
    return normalizar_payload_pdf({
        "origen": {"lat": lat, "lon": lon, "nombre": "Punto de consulta"},
        "especialidad": especialidad or "cualquier especialidad", "modo": modo, "fuente": "modelo",
        "cfg": {"sinuosidad": 1.0 if modo == "directa" else CONFIG["sinuosidad"],
                "velocidad": CONFIG["velocidadDirectaKmh"] if modo == "directa" else CONFIG["velocidadLibreKmh"]},
        "velocidad_directa": CONFIG["velocidadDirectaKmh"],
        "destino": {"nombre": h0["nombre"], "horario": h0["horario"], "especialidades": h0["especialidades"],
                    "km": top["km"], "eta": top["eta_min"], "recta_km": top["recta_km"],
                    "penal_pct": (top["eta_min"] - libre) / libre * 100 if libre > 0 else 0.0,
                    "min_libre": libre, "abierto": top["abierto_a_la_llegada"]},
        "filas": filas,
    })


def _etiqueta_modo(p: dict) -> str:
    if p["modo"] == "directa":
        return (f"Vía directa en línea recta ({p.get('velocidad_directa', CONFIG['velocidadDirectaKmh']):.0f} km/h; "
                "sin calles y sin tráfico)")
    if p["fuente"] == "real":
        return "Por calles: rutas reales (OSRM) ponderadas por tráfico"
    return "Por calles: estimación del modelo (sinuosidad vial + tráfico)"


def elementos_ranking(p: dict) -> list:
    """Contenido del informe de ranking como lista neutra de elementos (la dibuja cualquier motor)."""
    o, d = p["origen"], p["destino"]
    cfg = p["cfg"]
    modelo = "—"
    if cfg["sinuosidad"] is not None and cfg["velocidad"] is not None:
        modelo = f"sinuosidad ×{cfg['sinuosidad']:.2f}, {cfg['velocidad']:.0f} km/h a flujo libre"
    estado = {True: "abierto a la llegada", False: "CERRADO a la llegada", None: "horario no interpretable"}
    el: list = [
        ("titulo", "Informe de acceso a servicios de salud"),
        ("sub", f"Provincia de Panamá · generado {ahora_panama():%d/%m/%Y %H:%M} (hora de Panamá) · v{VERSION}"),
        ("h", "Parámetros de la consulta"),
        ("kv", [("Origen", f"{o['nombre']} ({o['lat']:.5f}, {o['lon']:.5f})"),
                ("Especialidad", p["especialidad"]),
                ("Camino más rápido", _etiqueta_modo(p)),
                ("Modelo", modelo)]),
    ]
    if d["nombre"]:
        el += [("h", "Centro más rápido"),
               ("kv", [("Centro", d["nombre"]), ("Horario", f"{d['horario']} — {estado[d['abierto']]}"),
                       ("ETA con tráfico", _fmt(d["eta"], 1, " min")),
                       ("Tiempo a flujo libre", _fmt(d["min_libre"], 1, " min")),
                       ("Distancia", _fmt(d["km"], 2, " km")),
                       ("Línea recta", _fmt(d["recta_km"], 2, " km")),
                       ("Penalización por tráfico", "no aplica" if p["modo"] == "directa" else _fmt(d["penal_pct"], 1, " %")),
                       ("Servicios", d["especialidades"] or "—")])]
    filas_t = []
    for k, f in enumerate(p["filas"], 1):
        filas_t.append([str(k), f["nombre"], _fmt(f["eta"], 1), _fmt(f["km"], 2), _fmt(f["recta_km"], 2),
                        {True: "abierto", False: "cerrado", None: "?"}[f["abierto"]]])
    el += [("h", f"Ranking de centros ({len(filas_t)})"),
           ("tabla", ["#", "Instalación", "ETA (min)", "Distancia (km)", "Recta (km)", "A la llegada"],
            filas_t, [0.6, 5.2, 1.3, 1.5, 1.3, 1.5], ["R", "L", "R", "R", "R", "L"])]
    puntos = [(k, f["lat"], f["lon"], k == 1) for k, f in enumerate(p["filas"][:12], 1)]
    el += [("h", "Croquis del origen y los centros mejor clasificados"),
           ("croquis", {"origen": (o["lat"], o["lon"]), "puntos": puntos})]
    el += [("h", "Notas metodológicas"),
           ("p", "El tiempo estimado (ETA) combina distancia, velocidad a flujo libre y un modelo SINTÉTICO de fricción "
                 "de tráfico (núcleos gaussianos); no usa datos de tráfico en vivo."),
           ("p", "Los horarios se evalúan a la hora estimada de llegada (hora de Panamá, UTC-5). Las posiciones del "
                 "dataset son aproximadas salvo las marcadas como verificadas."),
           ("p", "Uso académico. No reemplaza registros oficiales del MINSA/CSS ni sirve para decisiones clínicas. "
                 "En una emergencia llame al 911.")]
    return el


def elementos_dataset(registros: list[dict], hallazgos: list[dict]) -> list:
    cuenta = {n: sum(1 for h in hallazgos if h["nivel"] == n) for n in ("error", "aviso", "info")}
    verificadas = sum(1 for h in registros if h.get("verificada"))
    insulares = sum(1 for h in registros if h.get("insular"))
    el: list = [
        ("titulo", "Reporte del dataset de instalaciones de salud"),
        ("sub", f"Provincia de Panamá · generado {ahora_panama():%d/%m/%Y %H:%M} (hora de Panamá) · v{VERSION}"),
        ("h", "Resumen"),
        ("kv", [("Instalaciones", f"{len(registros)} ({len(registros) - insulares} terrestres, {insulares} insulares)"),
                ("Posiciones verificadas", f"{verificadas} de {len(registros)}"),
                ("Validación", f"{cuenta['error']} errores · {cuenta['aviso']} avisos · {cuenta['info']} observaciones")]),
    ]
    if hallazgos:
        orden = {"error": 0, "aviso": 1, "info": 2}
        filas = [[h["nivel"], h["nombre"], h["msg"]] for h in sorted(hallazgos, key=lambda x: orden[x["nivel"]])][:200]
        el += [("h", "Hallazgos de la validación"),
               ("tabla", ["Nivel", "Instalación", "Detalle"], filas, [0.8, 3.0, 5.2], ["L", "L", "L"])]
    filas = []
    for i, h in enumerate(registros, 1):
        pos = "verificada" if h.get("verificada") else f"aprox. ±{h.get('resolucion_m', '?')} m"
        filas.append([str(i), h["nombre"] + (" (insular)" if h.get("insular") else ""),
                      f"{h['lat']:.5f}", f"{h['lon']:.5f}", pos, h["horario"]])
    el += [("h", "Listado de instalaciones"),
           ("tabla", ["#", "Instalación", "Lat", "Lon", "Posición", "Horario"], filas,
            [0.5, 4.2, 1.1, 1.2, 1.6, 3.4], ["R", "L", "R", "R", "L", "L"])]
    el += [("p", "Las coordenadas son aproximaciones y no sustituyen datos oficiales. Para corregirlas: modo "
                 "«Editar posiciones» del mapa, o `--verificar-coordenadas`.")]
    return el


def _render_reportlab(elementos: list, pie: str) -> bytes:
    from xml.sax.saxutils import escape
    from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    verde = colors.HexColor("#0b6b4a")
    gris = colors.HexColor("#c9d5d0")
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=12)
    est = {
        "titulo": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=verde),
        "sub": ParagraphStyle("s", parent=base, fontSize=8.5, textColor=colors.HexColor("#555555"), spaceAfter=6),
        "h": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                            textColor=verde, spaceBefore=10, spaceAfter=4),
        "p": ParagraphStyle("p", parent=base, fontSize=8.5, leading=11.5, spaceAfter=3),
        "celda": ParagraphStyle("c", parent=base, fontSize=7.8, leading=9.6),
        "celdaR": ParagraphStyle("cr", parent=base, fontSize=7.8, leading=9.6, alignment=2),
        "cab": ParagraphStyle("cb", parent=base, fontName="Helvetica-Bold", fontSize=7.8, leading=9.6,
                              textColor=colors.white),
        "cabR": ParagraphStyle("cbr", parent=base, fontName="Helvetica-Bold", fontSize=7.8, leading=9.6,
                               textColor=colors.white, alignment=2),
    }
    ancho_util = A4[0] - 32 * mm

    def par(texto, estilo):
        return Paragraph(escape(_latin(texto)), est[estilo])

    def croquis(c, ancho):
        alto = 230
        dib = Drawing(ancho, alto)
        dib.add(Rect(0, 0, ancho, alto, strokeColor=gris, fillColor=colors.HexColor("#fafcfb")))
        olat, olon = c["origen"]
        k = math.cos(math.radians(olat))
        pts = [(n, (plon - olon) * k, plat - olat, dest) for n, plat, plon, dest in c["puntos"]]
        xs, ys = [q[1] for q in pts] + [0.0], [q[2] for q in pts] + [0.0]
        sx, sy = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
        m = 28
        esc_ = min((ancho - 2 * m) / sx, (alto - 2 * m - 10) / sy)
        cx = (ancho - sx * esc_) / 2 - min(xs) * esc_
        cy = (alto - sy * esc_) / 2 - min(ys) * esc_ + 4
        ox, oy = cx, cy
        for n, x, y, dest in pts:
            dib.add(Line(ox, oy, cx + x * esc_, cy + y * esc_,
                         strokeColor=colors.HexColor("#d84315") if dest else colors.HexColor("#9aa9a3"),
                         strokeWidth=2 if dest else 0.7))
        for n, x, y, dest in pts:
            px, py = cx + x * esc_, cy + y * esc_
            dib.add(Circle(px, py, 4, fillColor=colors.HexColor("#d84315") if dest else colors.HexColor("#455a64"),
                           strokeColor=colors.white, strokeWidth=0.8))
            dib.add(String(px + 5, py + 3, str(n), fontName="Helvetica-Bold", fontSize=7.5))
        dib.add(Circle(ox, oy, 5.5, fillColor=colors.HexColor("#00a86b"), strokeColor=colors.black, strokeWidth=0.8))
        dib.add(String(ox + 8, oy - 11, "Origen", fontName="Helvetica-Bold", fontSize=7.5))
        dib.add(String(ancho - 22, alto - 14, "N", fontName="Helvetica-Bold", fontSize=9))
        dib.add(Line(ancho - 18, alto - 34, ancho - 18, alto - 18, strokeColor=colors.black, strokeWidth=1))
        dib.add(String(8, 6, "Croquis a escala uniforme, sin mapa base. Los números son el puesto del ranking.",
                       fontName="Helvetica", fontSize=6.5))
        return dib

    historia = []
    for el in elementos:
        tipo = el[0]
        if tipo in ("titulo", "sub", "h", "p"):
            historia.append(par(el[1], tipo))
        elif tipo == "kv":
            filas = [[Paragraph("<b>%s</b>" % escape(_latin(k)), est["celda"]), par(v, "celda")] for k, v in el[1]]
            t = Table(filas, colWidths=[42 * mm, ancho_util - 42 * mm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5ddd9")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
            historia.append(t)
        elif tipo == "tabla":
            _, cab, filas, pesos, alin = el
            total = float(sum(pesos))
            datos = [[par(c, "cabR" if a == "R" else "cab") for c, a in zip(cab, alin)]]
            datos += [[par(c, "celdaR" if a == "R" else "celda") for c, a in zip(f, alin)] for f in filas]
            t = Table(datos, colWidths=[ancho_util * w / total for w in pesos], repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), verde),
                                   ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f6f4")]),
                                   ("GRID", (0, 0), (-1, -1), 0.25, gris), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
            historia.append(t)
        elif tipo == "croquis":
            historia.append(croquis(el[1], ancho_util))

    def pie_pagina(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(16 * mm, 9 * mm, _latin(pie))
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Página {doc_.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm,
                            bottomMargin=17 * mm, title=_latin(next((e[1] for e in elementos if e[0] == "titulo"), "Informe")),
                            author="rutas_salud_panama_cientifico")
    doc.build(historia, onFirstPage=pie_pagina, onLaterPages=pie_pagina)
    return buf.getvalue()


def _pdf_minimo(paginas: list, pie: str) -> bytes:
    """Escritor de PDF mínimo (Courier, texto). Cada página: lista de (texto, negrita)."""
    def esc(t: str) -> bytes:
        return t.encode("cp1252", errors="replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    n = len(paginas)
    objs: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{5 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold /Encoding /WinAnsiEncoding >>",
    }
    for i, lineas in enumerate(paginas):
        partes = [b"BT", b"12 TL", b"50 790 Td"]
        for texto, negrita in lineas:
            partes += [b"/F2 9 Tf" if negrita else b"/F1 9 Tf", b"(" + esc(texto) + b") Tj", b"T*"]
        partes += [b"ET", b"BT", b"/F1 7 Tf", b"50 28 Td",
                   b"(" + esc(f"{pie}   -   pagina {i + 1}/{n}") + b") Tj", b"ET"]
        flujo = b"\n".join(partes)
        objs[6 + 2 * i] = b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream"
        objs[5 + 2 * i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                           f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>").encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    inicio_xref = len(out)
    total = max(objs) + 1
    out += f"xref\n0 {total}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, total):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n".encode()
    return bytes(out)


def _render_texto(elementos: list, pie: str) -> bytes:
    ANCHO, POR_PAGINA = 98, 58
    lineas: list = []

    def envolver(t: str, sangria: int = 0, negrita: bool = False) -> None:
        for ln in textwrap.wrap(_latin(t), ANCHO - sangria) or [""]:
            lineas.append((" " * sangria + ln, negrita))

    def celda(c: str, w: int, a: str) -> str:
        if len(c) > w:
            c = c[:max(w - 1, 0)] + "."
        return c.ljust(w) if a == "L" else c.rjust(w)

    for el in elementos:
        tipo = el[0]
        if tipo == "titulo":
            envolver(el[1].upper(), negrita=True)
            lineas.append(("=" * ANCHO, False))
        elif tipo == "sub":
            envolver(el[1])
        elif tipo == "h":
            lineas.append(("", False))
            envolver(el[1], negrita=True)
            lineas.append(("-" * min(ANCHO, len(_latin(el[1]))), False))
        elif tipo == "p":
            envolver(el[1])
        elif tipo == "kv":
            for k, v in el[1]:
                envolver(f"{k}: {v}", sangria=2)
        elif tipo == "tabla":
            _, cab, filas, _pesos, alin = el
            cab = [_latin(c) for c in cab]
            filas = [[_latin(c) for c in f] for f in filas]
            anchos = [max([len(cab[i])] + [len(f[i]) for f in filas]) for i in range(len(cab))]
            exceso = sum(anchos) + 2 * (len(anchos) - 1) - ANCHO
            while exceso > 0:
                i = max(range(len(anchos)), key=lambda j: anchos[j])
                quitar = min(exceso, max(anchos[i] - 8, 0))
                if quitar <= 0:
                    break
                anchos[i] -= quitar
                exceso -= quitar
            unir = lambda f: "  ".join(celda(c, w, a) for c, w, a in zip(f, anchos, alin)).rstrip()  # noqa: E731
            lineas.append((unir(cab), True))
            lineas.append(("-" * min(ANCHO, sum(anchos) + 2 * (len(anchos) - 1)), False))
            lineas += [(unir(f), False) for f in filas]
        elif tipo == "croquis":
            envolver("(El croquis requiere reportlab: pip install reportlab)")
    paginas = [lineas[i:i + POR_PAGINA] for i in range(0, len(lineas), POR_PAGINA)] or [[("", False)]]
    return _pdf_minimo(paginas, _latin(pie))


# NUEVO: indica si la importación dinámica de reportlab funciona (la UI lo usa para el botón de PDF).
def reportlab_instalado() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


def _construir_pdf(elementos: list, forzar_texto: bool = False) -> bytes:
    pie =f"rutas_salud_panama v{VERSION} - uso academico, no apto para decisiones clinicas"
    if not forzar_texto:
        try:
            import reportlab  # noqa: F401
        except ImportError:
            pass
        else:
            try:
                return _render_reportlab(elementos, pie)
            except Exception as exc:  # noqa: BLE001  (si reportlab falla, el informe sigue saliendo)
                print(f"[aviso] reportlab falló ({type(exc).__name__}: {exc}); se usa el PDF de texto.", file=sys.stderr)
    return _render_texto(elementos, pie)


def construir_pdf_ranking(datos: dict, forzar_texto: bool = False) -> bytes:
    return _construir_pdf(elementos_ranking(normalizar_payload_pdf(datos)), forzar_texto)


def exportar_pdf_ranking(datos: dict, ruta: str, forzar_texto: bool = False) -> str:
    """Informe PDF de un ranking (payload del mapa o de payload_desde_consulta). Devuelve la ruta."""
    with open(ruta, "wb") as f:
        f.write(construir_pdf_ranking(datos, forzar_texto))
    return ruta


def exportar_pdf_dataset(registros: list[dict], hallazgos: list[dict], ruta: str, forzar_texto: bool = False) -> str:
    """Informe PDF del dataset (instalaciones, posiciones y hallazgos de validación)."""
    with open(ruta, "wb") as f:
        f.write(_construir_pdf(elementos_dataset(registros, hallazgos), forzar_texto))
    return ruta


# ---------------------------------------------------------------------------
# 7c. GUARDADO DE CORRECCIONES Y SERVIDOR LOCAL SEGURO
# ---------------------------------------------------------------------------
MAX_BYTES_POST = 2_000_000


def guardar_correcciones(registros: list[dict], cambios, ruta: str) -> dict:
    """Valida y mezcla {nombre: {lat, lon, ...}} en el archivo de correcciones (escritura atómica)."""
    if not isinstance(cambios, dict) or not cambios:
        raise ValueError("no hay cambios que guardar")
    por_nombre = {r["nombre"]: r for r in registros}
    lim = CONFIG["limites"]
    nuevos: dict = {}
    rechazadas: list[str] = []
    for nombre, c in cambios.items():
        reg = por_nombre.get(nombre)
        if reg is None or not isinstance(c, dict):
            rechazadas.append(f"{_txt(nombre, 60)}: no existe en el dataset")
            continue
        lat, lon = _num(c.get("lat")), _num(c.get("lon"))
        if lat is None or lon is None:
            rechazadas.append(f"{nombre}: coordenadas no numéricas")
        elif not (lim["latMin"] <= lat <= lim["latMax"] and lim["lonMin"] <= lon <= lim["lonMax"]):
            rechazadas.append(f"{nombre}: fuera de la Provincia de Panamá")
        elif not reg.get("insular") and en_el_mar(lat, lon):
            rechazadas.append(f"{nombre}: la posición cae en el mar")
        else:
            nuevos[nombre] = {"lat": round(lat, 6), "lon": round(lon, 6), "verificada": True,
                              "fuente": _txt(c.get("fuente") or "edición manual en el mapa", 80),
                              "nota": _txt(c.get("nota"), 160)}
    if not nuevos:
        raise ValueError("; ".join(rechazadas) or "sin cambios válidos")
    actuales: dict = {}
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding="utf-8") as f:
                actuales = json.load(f)
        except (OSError, ValueError) as exc:
            raise ValueError(f"el archivo de correcciones existente no se pudo leer ({exc}); no se sobrescribió")
        if not isinstance(actuales, dict):
            raise ValueError("el archivo de correcciones existente no es un objeto JSON; no se sobrescribió")
    actuales.update(nuevos)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(actuales, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)
    return {"guardadas": len(nuevos), "rechazadas": rechazadas, "archivo": os.path.basename(ruta)}


def crear_servidor(host: str, puerto: int, html: str, registros: list[dict], ruta_correcciones: str,
                   token: str) -> http.server.ThreadingHTTPServer:
    """Servidor local que sirve la página y POST protegidos (informes, correcciones,
    diagnóstico de coordenadas y experimentos opcionales).

    No publica el directorio del script (en la v2 sí lo hacía). Los POST exigen el token que
    lleva incrustada la página, un Host/Origin del propio servidor y un cuerpo de tamaño acotado,
    para que otra página abierta en el navegador no pueda escribir archivos ni gastar CPU."""
    cuerpo_html = html.encode("utf-8")

    class Manejador(http.server.BaseHTTPRequestHandler):
        server_version = f"RutasSalud/{VERSION}"
        hosts_permitidos: set = set()

        def log_message(self, formato: str, *args) -> None:  # noqa: A003
            pass

        def _responder(self, codigo: int, cuerpo: bytes = b"", tipo: str = "text/plain; charset=utf-8",
                       extra: dict | None = None) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD" and cuerpo:
                self.wfile.write(cuerpo)

        def _json(self, codigo: int, obj: dict) -> None:
            self._responder(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8")

        def _origen_valido(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            if self.hosts_permitidos and host not in self.hosts_permitidos:
                return False
            origen = self.headers.get("Origin")
            return not origen or urllib.parse.urlsplit(origen).netloc.lower() in (self.hosts_permitidos or {host})

        def do_GET(self) -> None:  # noqa: N802
            if not self._origen_valido():
                return self._responder(403, b"Host no permitido")
            ruta = urllib.parse.urlsplit(self.path).path
            if ruta in ("/", "/index.html"):
                self._responder(200, cuerpo_html, "text/html; charset=utf-8")
            elif ruta == "/favicon.ico":
                self._responder(204)
            else:
                self._responder(404, b"No encontrado")

        do_HEAD = do_GET  # noqa: N815

        def do_POST(self) -> None:  # noqa: N802
            if not self._origen_valido():
                return self._json(403, {"error": "origen no permitido"})
            if not token or not hmac.compare_digest(self.headers.get("X-Token", ""), token):
                return self._json(403, {"error": "token inválido: recarga la página desde el servidor local"})
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"error": "Content-Length inválido"})
            if largo <= 0 or largo > MAX_BYTES_POST:
                return self._json(413, {"error": f"el cuerpo debe pesar entre 1 B y {MAX_BYTES_POST // 1000} kB"})
            try:
                datos = json.loads(self.rfile.read(largo).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"error": "JSON inválido"})
            ruta = urllib.parse.urlsplit(self.path).path
            try:
                if ruta == "/experimento":
                    return self._json(200, ejecutar_laboratorio(datos, registros))
                if ruta == "/pdf":
                    pdf = construir_pdf_ranking(datos)
                    return self._responder(200, pdf, "application/pdf",
                                           {"Content-Disposition": 'attachment; filename="informe_ruta_salud.pdf"'})
                if ruta == "/correcciones":
                    return self._json(200, guardar_correcciones(registros, datos, ruta_correcciones))
                # NUEVO: diagnóstico de coordenadas en JSON (antes solo se imprimía en la terminal).
                if ruta == "/validar_coordenadas":
                    hallazgos = validar_dataset(registros)
                    cuenta = {n: sum(1 for h in hallazgos if h["nivel"] == n) for n in ("error", "aviso", "info")}
                    return self._json(200, {"instalaciones": len(registros), "errores": cuenta["error"],
                                            "avisos": cuenta["aviso"], "info": cuenta["info"],
                                            "hallazgos": hallazgos})
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            except OSError as exc:
                return self._json(500, {"error": f"no se pudo escribir: {exc}"})
            except Exception as exc:  # noqa: BLE001
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            self._json(404, {"error": "ruta desconocida"})

    httpd = http.server.ThreadingHTTPServer((host, puerto), Manejador)
    p = httpd.server_address[1]
    Manejador.hosts_permitidos = {f"{h}:{p}" for h in {host, "127.0.0.1", "localhost"}}
    return httpd


# ---------------------------------------------------------------------------
# 7d. LABORATORIO OPCIONAL DE ESTRUCTURAS DE DATOS (v4)
# Todos los experimentos se ejecutan SOLAMENTE al pulsar un botón del panel.
# Dependencias: biblioteca estándar de Python. Para vías reales: Overpass / OSM.
# ---------------------------------------------------------------------------
import random as _lab_random
import statistics as _lab_stats
import threading as _lab_threading
import tracemalloc as _lab_tracemalloc

_LAB_CACHE: dict[tuple, dict] = {}
_LAB_LOCK = _lab_threading.RLock()
_LAB_OVERPASS = "https://overpass-api.de/api/interpreter"
_LAB_TAMANIO_MAX_KM = 11.0  # red local; no descargar toda la provincia vía demo
_LAB_MAX_NODOS = 34000
_LAB_VELOCIDADES = {
    "motorway": 90, "motorway_link": 45, "trunk": 75, "trunk_link": 40,
    "primary": 55, "primary_link": 30, "secondary": 45, "secondary_link": 25,
    "tertiary": 40, "tertiary_link": 22, "residential": 30,
    "unclassified": 35, "living_street": 15, "service": 20,
}
_LAB_ESCENARIOS = {"ligero": .2, "moderado": 1.0, "intenso": 2.5}


def _lab_validar_par(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ValueError("Las coordenadas deben ser numéricas.") from None
    l = CONFIG["limites"]
    if not (math.isfinite(lat) and math.isfinite(lon) and
            l["latMin"] <= lat <= l["latMax"] and l["lonMin"] <= lon <= l["lonMax"]):
        raise ValueError("El origen está fuera de los límites admitidos de Panamá.")
    return lat, lon


def _lab_velocidad(tags):
    via = tags.get("highway", "residential")
    if isinstance(via, list):
        via = via[0]
    v_base = _LAB_VELOCIDADES.get(via, 30)
    ms = str(tags.get("maxspeed", ""))
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", ms)
    if m:
        v = float(m.group(1)) * (1.609344 if "mph" in ms.lower() else 1.0)
        if 5 <= v <= 140:
            return min(v, 110.0)
    return float(v_base)


def _lab_grafo_osm(elementos):
    """Grafo dirigido real: nodos OSM, segmentos de ways, sentidos y velocidades aproximadas.

    Adyacencia: u -> [(v, longitud_km, minutos_libres, friccion_local), ...]
    Un cruce geométrico sin nodo compartido NO se trata como intersección.
    """
    puntos = {}
    vias = []
    for el in elementos:
        if el.get("type") == "node":
            puntos[el["id"]] = (el["lat"], el["lon"])
        elif el.get("type") == "way":
            vias.append(el)
    if len(puntos) > _LAB_MAX_NODOS:
        raise ValueError(f"Área demasiado grande ({len(puntos)} nodos); utiliza dos puntos más cercanos.")
    ady = {}
    conexiones = 0
    for via in vias:
        tags = via.get("tags") or {}
        highway = tags.get("highway")
        if highway not in _LAB_VELOCIDADES:
            continue
        if tags.get("access") in ("private", "no") or tags.get("motor_vehicle") in ("no", "private"):
            continue
        nodos = via.get("nodes") or []
        o = str(tags.get("oneway", "")).lower()
        if o == "-1":
            nodos = nodos[::-1]
            sentido = True
        else:
            sentido = o in ("yes", "true", "1") or tags.get("junction") == "roundabout" or highway in ("motorway", "motorway_link")
        velocidad = _lab_velocidad(tags)
        for u, v in zip(nodos, nodos[1:]):
            if u == v or u not in puntos or v not in puntos:
                continue
            a, b = puntos[u], puntos[v]
            km = haversine_km(a[0], a[1], b[0], b[1])
            if km <= 0 or km > 8:
                continue
            fric = factor_friccion((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            dato = (v, km, km * 60 / velocidad, fric)
            ady.setdefault(u, []).append(dato)
            conexiones += 1
            if not sentido:
                ady.setdefault(v, []).append((u, km, km * 60 / velocidad, fric))
                conexiones += 1
    validos = set(ady)
    for vecinos in ady.values():
        validos.update(e[0] for e in vecinos)
    puntos = {u: p for u, p in puntos.items() if u in validos}
    if len(puntos) < 5 or conexiones < 8:
        raise ValueError("La consulta OSM no proporcionó una red vial suficiente en la zona.")
    return {"puntos": puntos, "ady": ady, "nodos": len(puntos), "arcos": conexiones}


def _lab_bbox(origen, destino):
    lat1, lon1 = origen
    lat2, lon2 = destino
    recta = haversine_km(lat1, lon1, lat2, lon2)
    if recta > _LAB_TAMANIO_MAX_KM:
        raise ValueError(
            f"El trayecto mide {recta:.1f} km en línea recta. El laboratorio de calles admite "
            f"hasta {_LAB_TAMANIO_MAX_KM:.0f} km para evitar saturar Overpass. "
            "Selecciona un destino más próximo. La ruta OSRM normal sigue disponible.")
    margen = max(.009, min(.018, .15 * recta / 111))
    sur, norte = min(lat1, lat2) - margen, max(lat1, lat2) + margen
    oeste, este = min(lon1, lon2) - margen, max(lon1, lon2) + margen
    return sur, oeste, norte, este


def _lab_obtener_red(origen, destino):
    caja = _lab_bbox(origen, destino)
    clave = tuple(round(x, 4) for x in caja)
    with _LAB_LOCK:
        entrada = _LAB_CACHE.get(clave)
        if entrada and time.monotonic() - entrada["descargado"] < 45 * 60:
            return entrada["grafo"], True
    filtrado = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service"
    bbox = ",".join(f"{v:.5f}" for v in caja)
    consulta = f'[out:json][timeout:30];way["highway"~"^({filtrado})$"]({bbox});(._;>;);out body;'
    datos = urllib.parse.urlencode({"data": consulta}).encode("utf-8")
    req = urllib.request.Request(_LAB_OVERPASS, data=datos,
             headers={"User-Agent": "UTP-RutasSalud-Laboratorio/4.0 (educational)",
                      "Content-Type": "application/x-www-form-urlencoded",
                      "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=43) as resp:
            cuerpo = resp.read(20_000_001)
            if len(cuerpo) > 20_000_000:
                raise ValueError("La consulta superó 20 MB. Reduce la distancia entre los puntos.")
            recibido = json.loads(cuerpo)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Overpass respondió HTTP {exc.code}. Puede estar ocupado; reintenta más tarde.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("No se pudo descargar la red de OpenStreetMap. Revisa tu conexión o intenta más tarde.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Overpass no devolvió datos viales JSON válidos.") from exc
    grafo = _lab_grafo_osm(recibido.get("elements", []))
    with _LAB_LOCK:
        if len(_LAB_CACHE) >= 4:
            _LAB_CACHE.pop(next(iter(_LAB_CACHE)))
        _LAB_CACHE[clave] = {"grafo": grafo, "descargado": time.monotonic()}
    return grafo, False


def _lab_acoplar(puntos, lat, lon):
    dist, nodo = min((haversine_km(lat, lon, p[0], p[1]), n) for n, p in puntos.items())
    if dist > .8:
        raise ValueError(f"No hay un nodo de calle próximo ({dist * 1000:.0f} m). Prueba otra ubicación.")
    return nodo, dist


def _lab_peso(e, criterio="tiempo", escenario="moderado"):
    if criterio == "distancia":
        return e[1]
    factor = 1.0 + _LAB_ESCENARIOS[escenario] * (e[3] - 1.0)
    return e[2] * factor


def _lab_camino(grafo, inicio, fin, criterio="tiempo", escenario="moderado",
                bloqueos=None, metodo="dijkstra"):
    """Dijkstra/A* propios; ambos respetan arcos dirigidos y costos no negativos."""
    if criterio not in ("distancia", "tiempo") or escenario not in _LAB_ESCENARIOS:
        raise ValueError("Criterio o escenario desconocido.")
    coords = grafo["puntos"]
    adj = grafo["ady"]
    max_v = 110  # km/h: cota superior conservadora de velocidades modeladas
    def h(u):
        d = haversine_km(coords[u][0], coords[u][1], coords[fin][0], coords[fin][1])
        return d if criterio == "distancia" else d * 60 / max_v
    if metodo not in ("dijkstra", "astar"):
        raise ValueError("Algoritmo no admitido.")
    t0 = time.perf_counter()
    cola = [(h(inicio) if metodo == "astar" else 0, 0, inicio)]
    costo = {inicio: 0.0}
    prev = {}
    asentados = set()
    relajaciones = 0
    bloqueos = bloqueos or set()
    while cola:
        estimacion, d, u = heapq.heappop(cola)
        if u in asentados or d > costo.get(u, math.inf) + 1e-10:
            continue
        asentados.add(u)
        if u == fin:
            break
        for e in adj.get(u, []):
            v = e[0]
            if (u, v) in bloqueos or (v, u) in bloqueos:
                continue
            relajaciones += 1
            nuevo = d + _lab_peso(e, criterio, escenario)
            if nuevo < costo.get(v, math.inf) - 1e-10:
                costo[v], prev[v] = nuevo, u
                heapq.heappush(cola, (nuevo + (h(v) if metodo == "astar" else 0), nuevo, v))
    ms = (time.perf_counter() - t0) * 1000
    if fin not in costo or fin not in asentados:
        return {"encontrada": False, "ms": ms, "explorados": len(asentados),
                "relajaciones": relajaciones, "criterio": criterio}
    nodos = [fin]
    while nodos[-1] != inicio:
        nodos.append(prev[nodos[-1]])
    nodos.reverse()
    distancia = tiempo_libre = tiempo_modelado = 0.0
    for u, v in zip(nodos, nodos[1:]):
        # En vías paralelas, seleccionar la arista de menor peso que utilizó el relajador.
        pares = [e for e in adj[u] if e[0] == v]
        edge = min(pares, key=lambda e: _lab_peso(e, criterio, escenario))
        distancia += edge[1]
        tiempo_libre += edge[2]
        tiempo_modelado += _lab_peso(edge, "tiempo", escenario)
    return {"encontrada": True, "km": distancia, "min": tiempo_modelado,
            "min_libre": tiempo_libre, "costo": costo[fin], "puntos": [list(coords[n]) for n in nodos],
            "ids": nodos, "ms": ms, "explorados": len(asentados),
            "relajaciones": relajaciones, "criterio": criterio, "escenario": escenario}


def _lab_resultado_ruta(nombre, r):
    if not r["encontrada"]:
        return {"etiqueta": nombre, "km": None, "minutos": None, "nodos": 0,
                "explorados": r["explorados"], "ms": round(r["ms"], 3)}
    return {"etiqueta": nombre, "km": round(r["km"], 3),
            "minutos": round(r["min"], 2), "nodos": len(r["ids"]),
            "explorados": r["explorados"], "relajaciones": r["relajaciones"],
            "ms": round(r["ms"], 3)}


def _lab_resumen_base(accion, grafo, origen, destino, cache):
    return {"experimento": accion, "fuente": "Grafo real de calles OSM + Dijkstra propio",
            "nota": "Velocidades inferidas de maxspeed/tipo de vía; congestión SINTÉTICA, no tráfico en vivo. "
                    "Los nodos de la ruta son intersecciones/segmentos OSM; no una red de hospitales.",
            "metadatos": {"nodos_viales": grafo["nodos"], "arcos_dirigidos": grafo["arcos"],
                           "datos_cache": cache, "origen": origen, "destino": destino},
            "filas": [], "rutas": []}


def _lab_experimento_vial(accion, origen, destino, escenario, cantidad_bloqueos):
    grafo, cache = _lab_obtener_red(origen, destino)
    inicio, snap1 = _lab_acoplar(grafo["puntos"], *origen)
    fin, snap2 = _lab_acoplar(grafo["puntos"], *destino)
    if inicio == fin:
        raise ValueError("Origen y destino se acoplaron al mismo nodo vial. Sepáralos más.")
    out = _lab_resumen_base(accion, grafo, origen, destino, cache)
    out["metadatos"].update({"acoplamiento_origen_m": round(snap1 * 1000),
                              "acoplamiento_destino_m": round(snap2 * 1000)})
    if snap1 > .25 or snap2 > .25:
        out["advertencia"] = "Alguno de los puntos está a más de 250 m de un nodo vial; revisa las coordenadas."
    if accion == "red_vial":
        r = _lab_camino(grafo, inicio, fin, escenario=escenario)
        if not r["encontrada"]:
            raise ValueError("No existe un camino dirigido entre los nodos OSM acoplados en esta área.")
        out["titulo"] = "Dijkstra propio sobre calles reales de OpenStreetMap"
        out["filas"] = [_lab_resultado_ruta("Ruta más rápida (Dijkstra)", r)]
        out["rutas"] = [{"etiqueta": "Dijkstra", "puntos": r["puntos"]}]
    elif accion == "criterios":
        rapida = _lab_camino(grafo, inicio, fin, escenario=escenario)
        corta = _lab_camino(grafo, inicio, fin, criterio="distancia", escenario=escenario)
        if not rapida["encontrada"] or not corta["encontrada"]:
            raise ValueError("No se encontraron ambos recorridos sobre la red vial disponible.")
        out["titulo"] = "Camino de menor distancia frente al de menor tiempo"
        out["filas"] = [_lab_resultado_ruta("Menor distancia (km)", corta),
                         _lab_resultado_ruta("Menor tiempo (min)", rapida)]
        out["rutas"] = [{"etiqueta": "Menor distancia", "puntos": corta["puntos"]},
                        {"etiqueta": "Menor tiempo", "puntos": rapida["puntos"]}]
    elif accion == "trafico":
        out["titulo"] = "Sensibilidad de Dijkstra a tres escenarios de congestión"
        for esc in _LAB_ESCENARIOS:
            r = _lab_camino(grafo, inicio, fin, escenario=esc)
            out["filas"].append(_lab_resultado_ruta(esc.capitalize(), r))
            if r["encontrada"]:
                out["rutas"].append({"etiqueta": esc, "puntos": r["puntos"]})
    elif accion == "bloqueos":
        base = _lab_camino(grafo, inicio, fin, escenario=escenario)
        if not base["encontrada"]:
            raise ValueError("No hay una ruta inicial en esta zona.")
        aristas = list(zip(base["ids"], base["ids"][1:]))
        # No bloquear la primera o última arista: evalúa desvíos reales por el tramo intermedio.
        interior = aristas[1:-1] or aristas
        n = min(cantidad_bloqueos, len(interior))
        posiciones = sorted(set(round((i + 1) * (len(interior) + 1) / (n + 1)) - 1 for i in range(n)))
        cerrar = {interior[min(max(0, k), len(interior)-1)] for k in posiciones}
        nueva = _lab_camino(grafo, inicio, fin, escenario=escenario, bloqueos=cerrar)
        out["titulo"] = f"Replanificación tras bloquear {len(cerrar)} segmento(s) vial(es)"
        out["filas"] = [_lab_resultado_ruta("Antes del cierre", base),
                         _lab_resultado_ruta("Después del cierre", nueva)]
        out["rutas"] = [{"etiqueta": "Ruta original", "puntos": base["puntos"]}]
        if nueva["encontrada"]:
            out["rutas"].append({"etiqueta": "Ruta alternativa", "puntos": nueva["puntos"]})
        else:
            out["advertencia"] = "Al cerrar estas aristas no queda una ruta dirigida en la red descargada."
        out["cierres"] = [[list(grafo["puntos"][u]), list(grafo["puntos"][v])] for u, v in cerrar]
    return out


# ---------------------------------------------------------------------------
# 7e. DOS COLAS IMPLEMENTADAS POR EL GRUPO (PRUEBA OPCIONAL)
# Las funciones de mapa y los siete experimentos de la v4 no se modifican.
# ---------------------------------------------------------------------------
class ColaPrioridadMinima:
    """Montículo binario mínimo propio: insertar/extraer O(log n).

    Almacena tuplas (costo, identificador); se admiten duplicados porque
    Dijkstra descarta las entradas desactualizadas al extraerlas.
    """

    def __init__(self):
        self._datos = []
        self.inserciones = 0
        self.extracciones = 0
        self.intercambios = 0

    def __len__(self):
        return len(self._datos)

    def __bool__(self):
        return bool(self._datos)

    def insertar(self, elemento):
        a = self._datos
        a.append(elemento)
        self.inserciones += 1
        i = len(a) - 1
        while i > 0:
            padre = (i - 1) // 2
            if a[padre] <= a[i]:
                break
            a[padre], a[i] = a[i], a[padre]
            self.intercambios += 1
            i = padre

    def extraer(self):
        a = self._datos
        if not a:
            raise IndexError('No se puede extraer de una cola de prioridad vacía.')
        self.extracciones += 1
        minimo = a[0]
        ultimo = a.pop()
        if a:
            a[0] = ultimo
            i = 0
            n = len(a)
            while 2 * i + 1 < n:
                hijo = 2 * i + 1
                if hijo + 1 < n and a[hijo + 1] < a[hijo]:
                    hijo += 1
                if a[i] <= a[hijo]:
                    break
                a[i], a[hijo] = a[hijo], a[i]
                self.intercambios += 1
                i = hijo
        return minimo


class ColaFIFOPropia:
    """Cola FIFO sobre arreglo con índice de lectura y compactación amortizada.

    Evita list.pop(0), que requiere desplazar todos los elementos O(n).
    Tanto encolar como desencolar tienen costo amortizado O(1).
    """

    def __init__(self):
        self._datos = []
        self._frente = 0
        self.inserciones = 0
        self.extracciones = 0

    def __len__(self):
        return len(self._datos) - self._frente

    def __bool__(self):
        return self._frente < len(self._datos)

    def encolar(self, elemento):
        self._datos.append(elemento)
        self.inserciones += 1

    def desencolar(self):
        if not self:
            raise IndexError('No se puede extraer de una cola FIFO vacía.')
        valor = self._datos[self._frente]
        self._frente += 1
        self.extracciones += 1
        if self._frente >= 64 and 2 * self._frente >= len(self._datos):
            self._datos = self._datos[self._frente:]
            self._frente = 0
        return valor


def _lab_dijkstra_cola_propia(adj, origen, destino):
    """Dijkstra con montículo propio; minimiza minutos, no número de saltos."""
    n = len(adj)
    dist, dist_km = [math.inf] * n, [0.0] * n
    prev, asentados = [-1] * n, [False] * n
    q = ColaPrioridadMinima()
    dist[origen] = 0.0
    q.insertar((0.0, origen))
    explorados = relajaciones = 0
    while q:
        d, u = q.extraer()
        if asentados[u] or d > dist[u] + 1e-12:
            continue
        asentados[u] = True
        explorados += 1
        if u == destino:
            break
        for v, km, minutos in adj[u]:
            if minutos < 0:
                raise ValueError('Dijkstra no admite aristas con pesos negativos.')
            relajaciones += 1
            nuevo = d + minutos
            if nuevo < dist[v] - 1e-12:
                dist[v], dist_km[v], prev[v] = nuevo, dist_km[u] + km, u
                q.insertar((nuevo, v))
    return {'dist': dist, 'dist_km': dist_km, 'prev': prev,
            'explorados': explorados, 'relajaciones': relajaciones,
            'inserciones': q.inserciones, 'extracciones': q.extracciones,
            'intercambios_heap': q.intercambios}


def _lab_bfs_cola_propia(adj, origen, destino):
    """BFS con FIFO propia: minimiza el número de aristas, NO los minutos."""
    n = len(adj)
    visitado = [False] * n
    saltos, tiempo, km = [-1] * n, [math.inf] * n, [0.0] * n
    prev = [-1] * n
    q = ColaFIFOPropia()
    visitado[origen] = True
    saltos[origen], tiempo[origen] = 0, 0.0
    q.encolar(origen)
    explorados = aristas_evaluadas = 0
    while q:
        u = q.desencolar()
        explorados += 1
        if u == destino:
            break
        for v, longitud, minutos in adj[u]:
            aristas_evaluadas += 1
            if not visitado[v]:
                visitado[v] = True
                saltos[v], prev[v] = saltos[u] + 1, u
                tiempo[v], km[v] = tiempo[u] + minutos, km[u] + longitud
                q.encolar(v)
    return {'dist': tiempo, 'dist_km': km, 'saltos': saltos, 'prev': prev,
            'explorados': explorados, 'relajaciones': aristas_evaluadas,
            'inserciones': q.inserciones, 'extracciones': q.extracciones}


def _lab_comparar_colas_propias(registros, origen, destino_idx):
    """Nuevo experimento opcional: 2 colas creadas desde cero, un único destino."""
    base = construir_grafo_base(registros)
    adj = grafo_con_origen(base, registros, *origen)
    destino = destino_idx + 1
    m_heap, heap_res = _lab_mediana_ms(lambda: _lab_dijkstra_cola_propia(adj, 0, destino), 25)
    m_fifo, fifo_res = _lab_mediana_ms(lambda: _lab_bfs_cola_propia(adj, 0, destino), 25)
    referencia = dijkstra(adj, 0, {destino}, True)
    dijkstra_min = heap_res['dist'][destino]
    bfs_min = fifo_res['dist'][destino]
    if math.isfinite(dijkstra_min) != math.isfinite(referencia['dist'][destino]):
        raise ValueError('La cola propia difiere de la referencia en alcanzabilidad.')
    if math.isfinite(dijkstra_min) and abs(dijkstra_min - referencia['dist'][destino]) > 1e-8:
        raise ValueError('El Dijkstra con cola propia no coincide con el original.')
    if math.isfinite(bfs_min) and bfs_min < dijkstra_min - 1e-8:
        raise ValueError('Error en la prueba: BFS encontró un costo menor que Dijkstra.')

    def saltos(prev):
        actual, numero = destino, 0
        vistos = set()
        while actual != 0 and actual != -1 and actual not in vistos:
            vistos.add(actual)
            actual = prev[actual]
            numero += 1
        return numero if actual == 0 else None

    return {
        'experimento': 'colas_propias',
        'titulo': 'Dos colas propias: Dijkstra (heap) frente a BFS (FIFO)',
        'fuente': 'Grafo hospitalario aproximado kNN + MST, no una red vial de calles',
        'nota': 'El heap mínimo prioriza por tiempo acumulado y Dijkstra garantiza el menor costo no negativo. '
                'La cola FIFO procesa por orden de llegada: BFS minimiza el número de conexiones, '
                'no el tiempo. Los resultados pueden coincidir, dependiendo del origen y destino. '
                'Los milisegundos reflejan solamente las búsquedas, sin construir el grafo.',
        'metadatos': {'vertices': len(adj), 'aristas_dirigidas': sum(map(len, adj)),
                      'destino': registros[destino_idx]['nombre'],
                      'estructuras_propias': ['montículo binario mínimo', 'cola FIFO con índice frontal'],
                      'dijkstra_coincide_con_original': True, 'repeticiones': 25},
        'filas': [
            {'algoritmo': 'Dijkstra (heap propio)', 'criterio': 'Menor tiempo',
             'tiempo_ms': round(m_heap, 4), 'costo_min': round(dijkstra_min, 4) if math.isfinite(dijkstra_min) else None,
             'saltos': saltos(heap_res['prev']), 'explorados': heap_res['explorados'],
             'encolados': heap_res['inserciones'], 'desencolados': heap_res['extracciones']},
            {'algoritmo': 'BFS (FIFO propia)', 'criterio': 'Menos conexiones',
             'tiempo_ms': round(m_fifo, 4), 'costo_min': round(bfs_min, 4) if math.isfinite(bfs_min) else None,
             'saltos': fifo_res['saltos'][destino] if fifo_res['saltos'][destino] >= 0 else None,
             'explorados': fifo_res['explorados'], 'encolados': fifo_res['inserciones'],
             'desencolados': fifo_res['extracciones']}
        ], 'rutas': []}


def _lab_dijkstra_lista(adj, inicio, destino=None):
    res = dijkstra(adj, inicio, {destino} if destino is not None else None, destino is not None)
    return res


def _lab_bellman_ford(adj, inicio):
    n = len(adj)
    dist = [math.inf] * n
    dist[inicio] = 0.0
    pasadas = 0
    relajaciones = 0
    for _ in range(n - 1):
        cambio = False
        pasadas += 1
        for u, vecinos in enumerate(adj):
            if not math.isfinite(dist[u]):
                continue
            for v, km, eta in vecinos:
                relajaciones += 1
                if dist[u] + eta < dist[v] - 1e-12:
                    dist[v] = dist[u] + eta
                    cambio = True
        if not cambio:
            break
    return {"dist": dist, "relajaciones": relajaciones, "pasadas": pasadas}


def _lab_astar_lista(adj, coords, inicio, destino, vmax=45.0):
    # h(u) = distancia geodésica / velocidad máxima permitida por el modelo.
    def h(u):
        a, b = coords[u], coords[destino]
        return haversine_km(a[0], a[1], b[0], b[1]) * 60 / vmax
    dist = {inicio: 0.0}
    cola = [(h(inicio), 0.0, inicio)]
    hecho = set()
    relaj = 0
    while cola:
        f, d, u = heapq.heappop(cola)
        if u in hecho or d > dist[u] + 1e-12:
            continue
        hecho.add(u)
        if u == destino:
            break
        for v, _km, eta in adj[u]:
            relaj += 1
            dn = d + eta
            if dn < dist.get(v, math.inf) - 1e-12:
                dist[v] = dn
                heapq.heappush(cola, (dn + h(v), dn, v))
    return {"min": dist.get(destino, math.inf), "explorados": len(hecho), "relajaciones": relaj}


def _lab_mediana_ms(fn, n=12):
    fn()  # calentamiento no medido
    veces = []
    for _ in range(n):
        t0 = time.perf_counter()
        resultado = fn()
        veces.append((time.perf_counter() - t0) * 1000)
    return _lab_stats.median(veces), resultado


def _lab_comparar_algoritmos(registros, origen, destino_idx):
    base = construir_grafo_base(registros)
    adj = grafo_con_origen(base, registros, *origen)
    d = destino_idx + 1
    coords = [origen] + [(h["lat"], h["lon"]) for h in registros]
    msd, rd = _lab_mediana_ms(lambda: _lab_dijkstra_lista(adj, 0, d), 25)
    msb, rb = _lab_mediana_ms(lambda: _lab_bellman_ford(adj, 0), 10)
    msa, ra = _lab_mediana_ms(lambda: _lab_astar_lista(adj, coords, 0, d), 25)
    kd = rd["dist"][d]
    if not math.isfinite(kd) or abs(kd - rb["dist"][d]) > 1e-7 or abs(kd - ra["min"]) > 1e-7:
        raise ValueError("Verificación de algoritmos fallida: los costos difieren.")
    return {"experimento": "algoritmos", "titulo": "Dijkstra vs Bellman-Ford vs A* (grafo de instalaciones)",
            "fuente": "Grafo aproximado kNN + MST (no calles reales)",
            "nota": "Tiempo mediano de la búsqueda en Python; sin incluir creación del grafo. "
                    "Los tres algoritmos coinciden en el costo mínimo. A* usa una heurística admisible.",
            "metadatos": {"nodos": len(adj), "conexiones": sum(map(len, adj)),
                           "distancia_origen_destino_recta_km": round(haversine_km(*origen, *coords[d]), 3)},
            "filas": [
                {"algoritmo": "Dijkstra (heap)", "tiempo_ms": round(msd, 4), "costo_min": round(kd, 4),
                 "explorados": rd["explorados"], "relajaciones": rd["relajaciones"]},
                {"algoritmo": "Bellman-Ford", "tiempo_ms": round(msb, 4), "costo_min": round(rb["dist"][d], 4),
                 "explorados": len(adj), "relajaciones": rb["relajaciones"]},
                {"algoritmo": "A* (heurística)", "tiempo_ms": round(msa, 4), "costo_min": round(ra["min"], 4),
                 "explorados": ra["explorados"], "relajaciones": ra["relajaciones"]}], "rutas": []}


def _lab_grafo_sintetico(n):
    """Malla vial ficticia de tamaño variable y conectividad asegurada."""
    columnas = math.ceil(math.sqrt(n))
    coords = [(9.0 + (i // columnas) * .0014, -79.5 + (i % columnas) * .0014) for i in range(n)]
    adj = [[] for _ in range(n)]
    def link(i, j):
        km = haversine_km(*coords[i], *coords[j])
        t = km * 60 / (25 + ((i * 17 + j * 3) % 20))
        adj[i].append((j, km, t))
        adj[j].append((i, km, t))
    for i in range(n):
        if i + 1 < n and i % columnas != columnas - 1:
            link(i, i + 1)
        if i + columnas < n:
            link(i, i + columnas)
    # Al menos un camino entre filas contiguas y vértices, por construcción.
    return adj


def _lab_escalabilidad():
    filas = []
    for n in (100, 500, 1000, 5000, 10000):
        adj = _lab_grafo_sintetico(n)
        ms, res = _lab_mediana_ms(lambda: _lab_dijkstra_lista(adj, 0, n-1), 7)
        _lab_tracemalloc.start()
        _lab_dijkstra_lista(adj, 0, n-1)
        _actual, pico = _lab_tracemalloc.get_traced_memory()
        _lab_tracemalloc.stop()
        filas.append({"vertices": n, "arcos_dirigidos": sum(len(x) for x in adj),
                      "dijkstra_ms": round(ms, 4), "pico_extra_kib": round(pico / 1024, 1),
                      "explorados": res["explorados"], "relajaciones": res["relajaciones"],
                      "costo_min": round(res["dist"][n-1], 3)})
    return {"experimento": "escalabilidad", "titulo": "Escalabilidad de Dijkstra (100–10.000 vértices)",
            "fuente": "Grafos de prueba sintéticos conectados (malla bidireccional)",
            "nota": "Medianas de 7 ejecuciones después de calentamiento. "
                    "Memoria pico adicional durante la búsqueda (no incluye el grafo). "
                    "Los resultados dependen del equipo y NO representan tráfico real.",
            "metadatos": {"repeticiones": 7, "modelo": "malla geográfica sintética"},
            "filas": filas, "rutas": []}


def _lab_validacion(registros, origen, cantidad):
    """Contraste de estimaciones del grafo aproximado con OSRM, desde un origen.

    No es medición de tráfico en vivo ni validación de tiempo real.
    """
    candidatas = [(i, h) for i, h in enumerate(registros) if not h.get("insular") and
                  haversine_km(*origen, h["lat"], h["lon"]) > .2]
    candidatas.sort(key=lambda x: haversine_km(*origen, x[1]["lat"], x[1]["lon"]))
    n = min(cantidad, len(candidatas))
    if not n:
        raise ValueError("No hay centros disponibles para validar.")
    # Muestra por cuantiles: distancias cortas, medias y largas; replicable.
    seleccion = [candidatas[round(i * (len(candidatas) - 1) / (n - 1))] for i in range(n)] if n > 1 else candidatas[:1]
    coords = [f"{origen[1]:.6f},{origen[0]:.6f}"] + [f"{h['lon']:.6f},{h['lat']:.6f}" for _, h in seleccion]
    url = f"{CONFIG['osrm']['url']}/table/v1/driving/{';'.join(coords)}?sources=0&annotations=duration,distance"
    if not CONFIG["osrm"]["activo"]:
        raise ValueError("Para la validación debes iniciar el programa sin --sin-osrm.")
    try:
        respuesta = _http_get_json(url, timeout=28)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ValueError(f"No fue posible consultar OSRM: {exc}") from exc
    if respuesta.get("code") != "Ok" or not respuesta.get("durations") or not respuesta.get("distances"):
        raise ValueError("El servicio OSRM no devolvió tabla de duraciones Y distancias; prueba con menos rutas.")
    base = construir_grafo_base(registros)
    adj = grafo_con_origen(base, registros, *origen)
    propio = dijkstra(adj, 0)
    filas = []
    for k, (idx, h) in enumerate(seleccion, start=1):
        t_ref = respuesta["durations"][0][k]
        m_ref = respuesta["distances"][0][k]
        if not isinstance(t_ref, (float, int)) or not isinstance(m_ref, (float, int)) or t_ref <= 0 or m_ref <= 0:
            continue
        tm, km = propio["dist"][idx+1], propio["dist_km"][idx+1]
        if not (math.isfinite(tm) and math.isfinite(km)):
            continue
        filas.append({"hospital": h["nombre"], "modelo_km": round(km, 2),
                     "osrm_km": round(m_ref / 1000, 2),
                     "error_km_pct": round(abs(km - m_ref / 1000) / (m_ref / 1000) * 100, 1),
                     "modelo_min_contrafico_sintetico": round(tm, 2),
                     "osrm_min_libres": round(t_ref / 60, 2),
                     "diferencia_min": round(tm - t_ref / 60, 2)})
    if not filas:
        raise ValueError("No existen pares válidos para comparar contra OSRM.")
    return {"experimento": "validacion", "titulo": "Contraste de rutas con OSRM (referencia independiente)",
            "fuente": "Dijkstra sobre grafo hospitalario aproximado vs OSRM /table",
            "nota": "OSRM calcula la distancia de su RUTA MÁS RÁPIDA, no la ruta de menor distancia. "
                    "Su tiempo es una referencia de enrutamiento, NO una medición de tráfico real. "
                    "El modelo añade fricción sintética: las diferencias temporales no son error predictivo validado.",
            "metadatos": {"pares_solicitados": n, "pares_validos": len(filas),
                "error_absoluto_medio_distancia_pct": round(_lab_stats.mean(f["error_km_pct"] for f in filas), 2)},
            "filas": filas, "rutas": []}


def ejecutar_laboratorio(datos, registros):
    if not isinstance(datos, dict):
        raise ValueError("El experimento debe ser un objeto JSON.")
    accion = datos.get("accion")
    permitidas = {"red_vial", "criterios", "trafico", "bloqueos", "algoritmos", "escalabilidad", "validacion", "colas_propias"}
    if accion not in permitidas:
        raise ValueError("Elige un experimento válido mediante un botón.")
    if accion == "escalabilidad":
        return _lab_escalabilidad()
    org = datos.get("origen") or {}
    origen = _lab_validar_par(org.get("lat"), org.get("lon"))
    idx = datos.get("destino_idx")
    vial = accion in ("red_vial", "criterios", "trafico", "bloqueos")
    libre = datos.get("destino_libre") if vial else None
    if libre is not None:
        if not isinstance(libre, dict):
            raise ValueError("El destino libre debe contener latitud y longitud.")
        dest = _lab_validar_par(libre.get("lat"), libre.get("lon"))
    else:
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(registros):
            raise ValueError("Selecciona un hospital de destino válido o indica coordenadas libres.")
        h = registros[idx]
        if h.get("insular"):
            raise ValueError("Los hospitales insulares no tienen ruta únicamente terrestre.")
        dest = (h["lat"], h["lon"])
    escenario = datos.get("escenario") or "moderado"
    if escenario not in _LAB_ESCENARIOS:
        raise ValueError("Escenario desconocido.")
    if accion in ("red_vial", "criterios", "trafico", "bloqueos"):
        b = datos.get("bloqueos", 1)
        if type(b) is not int or b not in (1, 3, 5):
            raise ValueError("El número de calles bloqueadas debe ser 1, 3 o 5.")
        return _lab_experimento_vial(accion, origen, dest, escenario, b)
    if accion == "algoritmos":
        return _lab_comparar_algoritmos(registros, origen, idx)
    if accion == "colas_propias":
        return _lab_comparar_colas_propias(registros, origen, idx)
    cantidad = datos.get("cantidad", 10)
    if type(cantidad) is not int or cantidad not in (5, 10, 20, 30):
        raise ValueError("La validación admite 5, 10, 20 o 30 rutas.")
    return _lab_validacion(registros, origen, cantidad)


# ---------------------------------------------------------------------------
# 8. PLANTILLA HTML (Leaflet + dashboard científico)
#    Marcadores __...__ para inyectar JSON sin escapar llaves de JS.
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Rutas de acceso a salud · Laboratorio Dijkstra v4</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<style>
    :root {
        --bg: #080c0b;
        --panel: rgba(12, 19, 17, 0.95);
        --border: #293b34;
        --accent: #00e08a;
        --accent-soft: #00ffb2;
        --text: #e7f0ec;
        --muted: #8ba39b;
        --danger: #ff5a36;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
        background: var(--bg); color: var(--text); overflow: hidden;
        font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    }
    #map { position: absolute; inset: 0; background: var(--bg); cursor: crosshair; }
    .leaflet-tile-pane {
        filter: invert(100%) hue-rotate(180deg) brightness(92%) contrast(88%) saturate(0.75);
    }
    .panel {
        position: absolute; z-index: 1000; background: var(--panel);
        border: 1px solid var(--border); border-radius: 11px;
        padding: 12px 14px; box-shadow: 0 12px 34px rgba(0, 0, 0, 0.62);
        backdrop-filter: blur(7px); scrollbar-width: thin;
        scrollbar-color: #2f4a40 transparent;
    }
    .panel::-webkit-scrollbar { width: 7px; }
    .panel::-webkit-scrollbar-thumb { background: #2f4a40; border-radius: 4px; }
    .panel-izq {
        top: 14px; left: 56px; width: 412px;
        max-height: calc(100% - 28px); overflow-y: auto;
    }
    .panel-der {
        top: 14px; right: 14px; width: 334px;
        max-height: calc(100% - 196px); overflow-y: auto; /* deja libre la leyenda */
    }
    .panel h1 {
        margin: 0; font-size: 14.5px; letter-spacing: 0.01em;
        color: var(--accent); line-height: 1.25;
    }
    .panel h2 {
        margin: 0; font-size: 13px; letter-spacing: 0.02em;
        color: var(--accent); text-transform: uppercase;
    }
    .subtitulo {
        margin: 4px 0 10px; font-size: 10px; color: var(--muted);
        line-height: 1.4;
    }
    label {
        display: block; margin-top: 8px; font-size: 10.5px;
        color: #b9ccc5; letter-spacing: 0.02em;
    }
    select, input {
        width: 100%; margin-top: 3px; padding: 6px 7px;
        background: #0e1715; color: var(--text);
        border: 1px solid #33483f; border-radius: 5px;
        font-size: 11.5px; font-family: inherit;
    }
    select:focus, input:focus { outline: none; border-color: var(--accent); }
    optgroup { color: #6f8a81; font-style: normal; font-size: 11px; }
    option { color: var(--text); background: #0e1715; }
    button {
        width: 100%; margin-top: 6px; padding: 7px 8px;
        background: var(--accent); color: #03120b; border: 0;
        border-radius: 5px; font-size: 11.5px; font-weight: 700;
        font-family: inherit; cursor: pointer; transition: filter 0.15s, background 0.15s;
    }
    button:hover { filter: brightness(1.12); }
    .btn-sec {
        background: #15231e; color: var(--text);
        border: 1px solid #355248; font-weight: 600;
    }
    .btn-sec.activo {
        background: #3a1a10; border-color: #ff7043; color: #ffb59b;
    }
    .fila-botones { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
    .chip {
        display: inline-block; margin-top: 5px; padding: 2px 8px;
        border-radius: 10px; background: #0e2a20; border: 1px solid #1f4a3a;
        color: var(--accent); font-size: 9.5px;
    }
    #divCoords { margin-top: 3px; }
    #estadoRuta {
        margin-top: 9px; padding: 8px 9px; font-size: 10.8px; line-height: 1.45;
        background: #0a1311; border: 1px solid #20332c; border-radius: 6px;
        max-height: 215px; overflow-y: auto;
    }
    .destino-nombre {
        margin-bottom: 4px; color: #ff8a65; font-size: 12.5px; font-weight: 700;
    }
    .linea { display: flex; gap: 6px; margin: 3px 0; color: #cbd9d4; }
    .linea span { min-width: 78px; color: #7f9a90; }
    .linea b { color: var(--accent); font-weight: 600; }
    .ruta-texto {
        margin-top: 6px; padding-top: 5px; border-top: 1px dashed #2c4038;
        color: #9fb4ac; font-size: 10px;
    }
    .error { color: #ff7043; }
    h4 {
        margin: 11px 0 4px; font-size: 10.5px; font-weight: 600;
        color: #b9ccc5; letter-spacing: 0.02em;
    }
    #tablaDistancias {
        max-height: 158px; overflow-y: auto;
        border: 1px solid #20332c; border-radius: 5px;
        scrollbar-width: thin; scrollbar-color: #2f4a40 transparent;
    }
    #tablaDistancias::-webkit-scrollbar { width: 6px; }
    #tablaDistancias::-webkit-scrollbar-thumb { background: #2f4a40; border-radius: 3px; }
    table { width: 100%; border-collapse: collapse; font-size: 10.2px; }
    th {
        position: sticky; top: 0; z-index: 1; padding: 4px 5px;
        background: #12201b; color: #7f9a90; font-weight: 600; text-align: left;
    }
    td { padding: 3px 5px; border-bottom: 1px solid #1a2924; }
    tr.fila-hospital { cursor: pointer; }
    tr.fila-hospital:hover { background: #16261f; }
    tr.fila-destino { background: #23300f; }
    tr.fila-destino td:first-child { color: #d4e8a0; }
    .eta, .km { text-align: right; white-space: nowrap; font-family: Consolas, monospace; }
    .eta { color: var(--accent); }
    .km { color: #aebfb9; }
    .seccion { margin-top: 10px; padding-top: 8px; border-top: 1px solid #20332c; }
    .seccion h3 {
        margin: 0 0 6px; font-size: 10.5px; font-weight: 600;
        color: #d3e5dd; letter-spacing: 0.03em;
    }
    .metrica {
        display: flex; justify-content: space-between; gap: 8px;
        padding: 2px 0; font-size: 10.3px; color: #a8bdb5;
    }
    .valor {
        color: var(--accent-soft); font-family: Consolas, "Cascadia Code", monospace;
        font-weight: 600; text-align: right; white-space: nowrap;
    }
    .barra {
        height: 6px; margin: 4px 0 3px; background: #15241f;
        border: 1px solid #22332c; border-radius: 3px; overflow: hidden;
    }
    .barra span {
        display: block; height: 100%; width: 0;
        background: linear-gradient(90deg, #00e08a, #ffd600);
        transition: width 0.35s ease;
    }
    .nota { margin-top: 2px; font-size: 9.2px; line-height: 1.4; color: #789088; }
    details { margin-top: 9px; }
    summary {
        cursor: pointer; font-size: 10px; color: #9fb4ac;
        padding: 3px 0; list-style: none;
    }
    summary::-webkit-details-marker { display: none; }
    summary::before { content: "▸ "; color: var(--accent); }
    details[open] summary::before { content: "▾ "; }
    details p { margin: 4px 0 0; font-size: 9.4px; line-height: 1.5; color: #8ba39b; }
    .leyenda {
        position: absolute; right: 14px; bottom: 14px; z-index: 1000;
        padding: 7px 10px; background: rgba(12, 19, 17, 0.94);
        border: 1px solid var(--border); border-radius: 8px;
        font-size: 9.2px; color: #b8c9c2; line-height: 1.45;
    }
    .escala { display: flex; margin: 3px 0 2px; }
    .escala i { display: block; width: 30px; height: 6px; }
    .leyenda b { color: var(--accent); font-weight: 600; }
    .etiqueta-origen {
        background: transparent !important; border: none !important;
        box-shadow: none !important; color: var(--accent-soft) !important;
        font-size: 10.5px; font-weight: 700;
        text-shadow: 0 0 4px #000, 0 0 4px #000, 0 0 4px #000;
    }
    .leaflet-tooltip {
        background: #0e1a16; border: 1px solid #35544a; color: #dfece7;
        font-size: 10.2px; line-height: 1.4; box-shadow: 0 4px 14px rgba(0,0,0,0.7);
    }
    .leaflet-tooltip-top:before { border-top-color: #35544a; }
    .toast {
        position: absolute; top: 16px; left: 50%; z-index: 2500;
        padding: 8px 14px; border-radius: 6px; font-size: 11px;
        background: #2a1510; border: 1px solid #ff7043; color: #ffccbc;
        opacity: 0; pointer-events: none;
        transform: translate(-50%, -18px); transition: 0.25s ease;
    }
    .toast.visible { opacity: 1; transform: translate(-50%, 0); }
    input[type="checkbox"] { width: auto; margin: 0 7px 0 0; accent-color: var(--accent); }
    .check { display: flex; align-items: center; margin-top: 6px; font-size: 10.8px; color: #cbd9d4; cursor: pointer; }
    .fila-checks { margin: 4px 0 2px; }
    .fila-botones3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
    .fila-botones3 button { padding: 7px 4px; font-size: 10.4px; }
    .pin { width: 100%; height: 100%; box-sizing: border-box; border-radius: 50%;
           border: 2px solid #fff; background: #FF3D00; box-shadow: 0 0 5px rgba(0,0,0,.7); }
    .pin-off { border: 1px solid #2b3a35; background: #5b6b65; opacity: .55; box-shadow: none; }
    .pin-ins { background: #29b6f6; border-color: #e1f5fe; }
    .badge { display: inline-block; padding: 0 6px; margin-left: 4px; border-radius: 8px;
             font-size: 9.2px; font-weight: 700; white-space: nowrap; }
    .b-ok { background: #0e2a20; color: #00e08a; border: 1px solid #1f4a3a; }
    .b-no { background: #2a1510; color: #ff8a65; border: 1px solid #5a2a1f; }
    .b-na { background: #1a2420; color: #9fb4ac; border: 1px solid #30443c; }
    .chip-osrm { margin: 6px 0 2px; padding: 4px 8px; border-radius: 6px; font-size: 10px;
                 border: 1px solid #30443c; background: #0e1715; color: #9fb4ac; }
    .chip-osrm.ok { border-color: #1f4a3a; color: #00e08a; }
    .chip-osrm.pend { color: #ffd54f; }
    .chip-osrm.err { border-color: #7a3a1f; color: #ffab91; cursor: pointer; }
    .aviso { color: #ffd54f; }
    .delta-pos { color: #ffab91; }
    .delta-neg { color: #80cbc4; }
    .segmento { display: grid; grid-template-columns: 1fr 1fr; margin-top: 3px; }
    .segmento .seg { margin-top: 0; border-radius: 0; background: #15231e; color: var(--text); border: 1px solid #355248; font-weight: 600; }
    .segmento .seg:first-child { border-radius: 5px 0 0 5px; }
    .segmento .seg:last-child { border-radius: 0 5px 5px 0; border-left: 0; }
    .segmento .seg.activo { background: var(--accent); color: #03120b; border-color: var(--accent); }
    .vias { display: grid; gap: 6px; margin-top: 4px; }
    .via {
        display: block; width: 100%; margin: 0; padding: 9px 10px; text-align: left;
        background: #10201b; color: var(--text); border: 1px solid #355248;
        border-radius: 7px; font-weight: 500; line-height: 1.35;
    }
    .via b { display: block; font-size: 12px; color: #dfece7; }
    .via span { display: block; margin-top: 2px; font-size: 9.8px; color: #8ba39b; font-weight: 400; }
    .via:hover { filter: brightness(1.12); }
    .via.activo { background: #06351f; border-color: var(--accent); }
    .via.activo b { color: var(--accent); }
    .via.activo span { color: #a9d8c7; }
    #resultadosBusqueda { max-height: 92px; overflow-y: auto; }
    .resultado-busqueda { display: block; width: 100%; margin: 2px 0; padding: 4px 6px; text-align: left;
        background: #10201b; border: 1px solid #2b4038; color: #d6e6df; font-size: 10px; border-radius: 4px; }
    .resultado-busqueda:hover { border-color: var(--accent); }
    .pin.pin-aprox { border: 2px dashed #ffd54f; }
    #panelEdicion { display: none; margin-top: 8px; padding: 8px 9px; border: 1px solid #7a5a1f; border-radius: 6px;
                    background: #1a1608; font-size: 10.4px; color: #ffe0a3; }
    #listaEdicion { max-height: 110px; overflow-y: auto; margin: 4px 0; color: #e8d6a8; font-size: 10px; }
    @media (max-width: 980px) {
        .panel-izq { left: 50px; width: calc(52% - 58px); }
        .panel-der { width: calc(48% - 30px); }
    }
    @media (max-width: 720px) {
        .panel-izq { left: 46px; width: calc(100% - 60px); max-height: 46%; }
        .panel-der { top: auto; bottom: 12px; width: calc(100% - 28px); max-height: 38%; }
        .leyenda { display: none; }
    }
    .lab-panel { margin: 11px 0; padding: 8px 9px; border: 1px solid #247254;
        background: #0a2118; border-radius: 8px; }
    .lab-panel summary { cursor: pointer; color: #00e08a; font-size: 12px; font-weight: 700; }
    .lab-panel .fila-botones > div { min-width: 0; }
    .lab-panel label { margin-top: 7px; }
    .lab-botones { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin: 7px 0; }
    .lab-botones button { text-align: left; font-size: 10px; min-height: 40px; margin: 0; }
    .lab-botones button:last-child { grid-column: 1 / -1; }
    .lab-ejecutar:disabled { opacity: .55; cursor: wait; }
    .lab-resultado { background: #080f0d; border: 1px solid #2a463a; border-radius: 7px;
        padding: 8px; margin-top: 9px; font-size: 10.4px; overflow: hidden; }
    .lab-warning { color: #ffc078; padding: 8px; border: 1px solid #805335; border-radius: 5px; margin: 6px 0; }
    .lab-meta { display: flex; flex-wrap: wrap; gap: 5px; margin: 7px 0; }
    .lab-meta span { padding: 3px 5px; background: #1d3028; border-radius: 4px; }
    .lab-tabla-scroll { overflow-x: auto; max-width: 100%; }
    .lab-tabla { border-collapse: collapse; min-width: 100%; font-size: 9.7px; }
    .lab-tabla th, .lab-tabla td { border: 1px solid #345044; padding: 5px;
        text-align: left; white-space: nowrap; }
    .lab-tabla th { background: #18392b; color: #aef5ce; }
    .lab-tabla tr:nth-child(even) { background: #13241e; }
    .lab-barras { margin-top: 10px; font-size: 10px; }
    .lab-barra-fila { display: grid; grid-template-columns: 65px 1fr 76px; gap: 6px; align-items: center; margin: 5px 0; }
    .lab-barra-pista { height: 9px; border-radius: 4px; background: #254435; overflow: hidden; }
    .lab-barra-pista div { height: 100%; background: #00e08a; border-radius: 4px; }
</style>
</head>
<body>
<div id="map"></div>

<aside class="panel panel-izq" id="panelControl">
    <h1>🩺 Rutas de acceso a salud · Provincia de Panamá</h1>
    <p class="subtitulo">Dijkstra con ETA, fricción urbana y rutas reales por calles</p>

    <label for="especialidadSelect">Especialidad médica</label>
    <select id="especialidadSelect" onchange="cambiarEspecialidad()"></select>
    <div class="chip" id="chipEspecialidad">—</div>

    <label for="buscarLugar">Buscar un lugar u hospital</label>
    <input type="text" id="buscarLugar" placeholder="Ej.: Chimán, Paitilla, Hospital Santo Tomás"
           onkeydown="if (event.key === 'Enter') buscarLugar()" />
    <div class="fila-botones">
        <button class="btn-sec" onclick="buscarLugar()">🔎 Buscar y fijar origen</button>
        <button class="btn-sec" onclick="limpiarBusqueda()">✖ Limpiar</button>
    </div>
    <div id="resultadosBusqueda" class="nota"></div>

    <label for="origenSelect">Origen</label>
    <select id="origenSelect" onchange="cambiarOrigen()">
        <option value="mapa">📍 Punto X (clic en el mapa / coordenadas)</option>
    </select>

    <div id="divCoords">
        <label for="inputCoords">Latitud, Longitud</label>
        <input type="text" id="inputCoords" value="9.03500, -79.48500" />
        <div class="fila-botones">
            <button class="btn-sec" onclick="irACoordenadas()">Actualizar ubicación</button>
            <button class="btn-sec" onclick="usarMiUbicacion()">📍 Mi ubicación</button>
        </div>
    </div>

    <label for="destinoSelect">Destino</label>
    <select id="destinoSelect" onchange="actualizarCalculo()">
        <option value="cercano">⚡ Más cercano</option>
    </select>

    <label>Camino más rápido · elige una de las dos vías</label>
    <div class="vias">
        <button type="button" class="via" id="btnModoDirecta" onclick="cambiarModoRuta('directa')">
            <b>1 · Vía directa</b><span>Idealización: línea recta, sin calles ni tráfico</span>
        </button>
        <button type="button" class="via activo" id="btnModoCalles" onclick="cambiarModoRuta('calles')">
            <b>2 · Vía por calles</b><span>La más rápida siguiendo las calles del país (OSRM + tráfico)</span>
        </button>
    </div>
    <div class="nota" id="notaModo"></div>
    <button class="btn-sec" onclick="compararVias()">⚖ Comparar las dos vías para el mismo hospital</button>
    <div id="comparacionVias" class="nota"></div>

    <div class="fila-checks">
        <label class="check"><input type="checkbox" id="chkAbiertos" onchange="actualizarCalculo()" />Solo centros abiertos a mi llegada</label>
        <label class="check"><input type="checkbox" id="chkOSRM" checked onchange="cambiarOSRM()" />Rutas reales por calles (OSRM)</label>
        <label class="check"><input type="checkbox" id="chkRed" onchange="toggleRed()" />Mostrar red de referencia entre centros</label>
        <label class="check"><input type="checkbox" id="chkEditar" onchange="toggleEdicion()" />✏️ Editar posiciones (arrastrar marcadores)</label>
    </div>

    <label for="selCobertura">Criterio de cobertura</label>
    <select id="selCobertura" onchange="cambiarCriterioCobertura()">
        <option value="radio">Radio de 5 km (línea recta)</option>
        <option value="t10">Tiempo estimado ≤ 10 min</option>
        <option value="t15">Tiempo estimado ≤ 15 min</option>
        <option value="t20">Tiempo estimado ≤ 20 min</option>
        <option value="t30">Tiempo estimado ≤ 30 min</option>
    </select>

    <div class="fila-botones">
        <button onclick="actualizarCalculo()">Calcular ruta</button>
        <button id="btnCobertura" class="btn-sec" onclick="toggleCobertura()">Mostrar Cobertura</button>
    </div>

    <details class="lab-panel" id="panelLaboratorio">
        <summary>🧪 Laboratorio de Dijkstra — experimentos opcionales</summary>
        <div class="nota" style="margin:7px 0">Elige un destino concreto o usa «Más cercano» arriba. Los experimentos <b>no se ejecutan solos</b>: cada botón inicia uno. La ruta normal del mapa permanece disponible.</div>
        <div class="fila-botones">
            <div><label for="labEscenario">Escenario de congestión</label>
                <select id="labEscenario"><option value="ligero">Ligero (simulado)</option>
                  <option value="moderado" selected>Moderado (simulado)</option>
                  <option value="intenso">Intenso (simulado)</option></select></div>
            <div><label for="labBloqueos">Calles a bloquear</label>
                <select id="labBloqueos"><option value="1">1 segmento</option><option value="3">3 segmentos</option>
                  <option value="5">5 segmentos</option></select></div>
        </div>
        <label for="labDestinoCoords">Destino libre (opcional, solo para los 4 experimentos de calles)</label>
        <input id="labDestinoCoords" placeholder="Lat, lon (vacío = hospital seleccionado)" />
        <div class="fila-botones">
          <button class="btn-sec" onclick="activarDestinoLab()">📍 Elegir destino en el mapa</button>
          <button class="btn-sec" onclick="borrarDestinoLab()">✖ Usar hospital seleccionado</button>
        </div>
    <label for="labCantidad">Número de pares para validar con OSRM</label>
        <select id="labCantidad"><option value="5">5 rutas (rápido)</option>
           <option value="10" selected>10 rutas</option><option value="20">20 rutas</option>
           <option value="30">30 rutas</option></select>
        <div class="lab-botones">
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('red_vial')">🛣️ Dijkstra en calles reales (OSM)</button>
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('criterios')">⚖️ Menor distancia vs. menor tiempo</button>
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('trafico')">🚦 Tres escenarios de congestión</button>
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('bloqueos')">🚧 Bloquear calles y recalcular</button>
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('algoritmos')">🧠 Dijkstra vs. Bellman-Ford vs. A*</button>
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('colas_propias')">🗂️ Dos colas propias: Dijkstra (heap) y BFS (FIFO)</button>
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('escalabilidad')">📈 Rendimiento: 100 a 10.000 nodos</button>
            <button class="btn-sec lab-ejecutar" onclick="ejecutarLaboratorio('validacion')">🎯 Validar 5–30 rutas con OSRM</button>
        </div>
        <div class="fila-botones3">
            <button class="btn-sec" onclick="exportarLabJSON()">⬇ JSON</button>
            <button class="btn-sec" onclick="exportarLabCSV()">⬇ CSV</button>
            <button class="btn-sec" onclick="limpiarLaboratorio()">✖ Limpiar</button>
        </div>
        <div id="labResultados" class="lab-resultado"><span class="nota">Sin resultados. Selecciona un experimento.</span></div>
        <div class="nota">Red vial: Overpass/OSM en línea, máximo 11 km entre puntos (en recta). Las velocidades y el tráfico son aproximaciones; nunca usar para emergencias reales. El modelo hospitalario y OSRM siguen separados.</div>
    </details>

    <div id="panelEdicion"></div>
    <div id="estadoRuta">Haz clic en el mapa para fijar el origen; el destino se elige automáticamente según la especialidad.</div>

    <h4>📏 Ranking de acceso (ETA desde el origen)</h4>
    <div id="tablaDistancias"></div>
</aside>

<aside class="panel panel-der" id="panelMetricas">
    <h2>📊 Dashboard de análisis</h2>
    <div class="nota">Se recalcula con cada ruta: tiempos, nodos explorados y costo penalizado.</div>
    <div id="estadoOSRM" class="chip-osrm" onclick="reintentarOSRM()"></div>
    <div id="metricas"></div>
    <div id="coberturaStats"></div>
    <div class="fila-botones3" style="margin-top:10px;">
        <button class="btn-sec" onclick="exportarJSON()">⬇ JSON</button>
        <button class="btn-sec" onclick="exportarCSV()">⬇ Ranking CSV</button>
        <button class="btn-sec" onclick="exportarGeoJSON()">⬇ Ruta GeoJSON</button>
    </div>
    <!-- NUEVO: el texto del botón lo ajusta el JS según REPORTLAB_INSTALADO -->
    <button class="btn-sec" id="btnPDF" onclick="exportarPDF()">📄 Exportar informe PDF</button>
    <!-- NUEVO: botón secundario de diagnóstico de coordenadas + contenedor de notas con los hallazgos -->
    <button class="btn-sec" id="btnCoords" onclick="analizarCoordenadas()"
            style="padding:5px 8px;font-size:10.4px;font-weight:500;">🔍 Analizar coordenadas del dataset</button>
    <div id="notasCoordenadas" class="nota" style="max-height:240px;overflow-y:auto;"></div>
    <details>
        <summary>Metodología y reproducibilidad</summary>
        <div id="metodologia"></div>
    </details>
</aside>

<div class="leyenda">
    <div><b>Fricción del corredor</b></div>
    <div class="escala">
        <i style="background:#00E676"></i><i style="background:#FFD600"></i><i style="background:#FF9100"></i><i style="background:#FF3D00"></i>
    </div>
    <div>1.0 (fluido) → ≥2.0 (congestión)</div>
    <div style="margin-top:4px;"><span style="color:#ff3d00">●</span> con la especialidad · <span style="color:#7d8c86">●</span> otro · <span style="color:#29b6f6">●</span> insular (sin ruta terrestre)</div>
    <div style="margin-top:4px;"><b>Cobertura</b> · <span id="leyendaCobertura">radio 5 km</span></div>
    <div class="escala">
        <i style="background:#00d5ff"></i><i style="background:#00e676"></i><i style="background:#ffd600"></i><i style="background:#ff3d00"></i>
    </div>
    <div>Complejidad relativa (n.º de servicios)</div>
    <div><span style="color:#ff5252">▮</span> celda terrestre sin cobertura (el mar no cuenta)</div>
    <div style="margin-top:4px;"><span style="color:#ffd54f">◌</span> borde discontinuo = posición aproximada sin verificar</div>
    <div style="margin-top:4px;"><span style="color:#00e676">━</span> ruta elegida · color por fricción del tráfico</div>
    <div>1 · vía directa = línea recta · 2 · vía por calles = trazado OSRM</div>
</div>

<div id="toast" class="toast"></div>

<script>
'use strict';

/* =====================================================================
   1. DATOS Y CONFIGURACIÓN (inyectados desde Python: fuente única de verdad)
   ===================================================================== */
const hospitales = __HOSPITALES_JSON__;
const CFG = __CONFIG_JSON__;
const ZONAS_FRICCION = __ZONAS_JSON__;
const COSTA_APROX = __COSTA_JSON__;
const TOKEN = __TOKEN_JSON__;   // vacío si la página se abrió como archivo (sin servidor local)
const LUGARES = __LUGARES_JSON__; // instalaciones + localidades para el buscador
const REPORTLAB_INSTALADO = __REPORTLAB_INSTALADO__; // NUEVO: true si el servidor pudo importar reportlab
// Dos vías: 'directa' (línea recta, sin calles ni tráfico) o 'calles' (OSRM + tráfico).
let MODO = (CFG.modoRuta === 'directa' || CFG.modoRuta === 'recta') ? 'directa' : 'calles';
const ES_DIRECTA = () => MODO === 'directa';

const CFG_ORIGINAL = { sinuosidad: CFG.sinuosidad, velocidadLibreKmh: CFG.velocidadLibreKmh };
// Los centros insulares no tienen ruta terrestre: quedan fuera del grafo y del ranking.
const IDX_TERRESTRES = hospitales.map((h, i) => i).filter(i => !hospitales[i].insular);
const N_INSULARES = hospitales.length - IDX_TERRESTRES.length;
const OSRM = { activo: !!CFG.osrm.activo, fallos: 0 };

const CATEGORIAS = [
    { nombre: '👶 Pediatría y Neonatología', patron: /pediatr|neonat|infantil/ },
    { nombre: '🤰 Ginecología y Maternidad', patron: /gineco|matern|obstet|embarazo|papanicolau|reproductiva|prenatal/ },
    { nombre: '🎗️ Oncología y Hematología', patron: /onco|quimio|radioterapia|hematolog|trasplante|paliativ/ },
    { nombre: '❤️ Cardiología y Vascular', patron: /cardio|vascular|electrocardiograma/ },
    { nombre: '🧠 Neurología y Salud Mental', patron: /neuro|psiquiatr|psicolog|salud mental|terapia ocupacional/ },
    { nombre: '🔪 Cirugía y Especialidades Quirúrgicas', patron: /cirug|ortoped|urolog|oftalm|dermat|otorrino|plastica|robotica|trauma/ },
    { nombre: '🫁 Medicina Interna y Nefrología', patron: /medicina interna|nefro|hemodi|neumolog|infectolog|endocrin|gastro|reumatolog|inmunolog/ },
    { nombre: '🚑 Urgencias y Cuidados Críticos', patron: /urgencia|emergenc|uci|cuidados intensivos/ },
    { nombre: '🔬 Diagnóstico, Imagen y Laboratorio', patron: /laboratorio|rayos|imagen|ultrasonido|ecograf|tomograf|resonancia|hisopado|patolog|check|evaluacion/ },
    { nombre: '🏥 Atención Primaria y Comunitaria', patron: /medicina general|atencion primaria|vacun|odontolog|farmacia|enfermer|curacion|saneamiento|nutricion|fisioterapia|ocupacional|epidemiolog|salud publica|prevencion|programa|trabajo social|control|consulta externa|especialidades|inyectables|pruebas/ }
];

/* =====================================================================
   2. UTILIDADES
   ===================================================================== */
function sinAcentos(texto) {
    return String(texto).normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}
function normalizarClave(texto) {
    return sinAcentos(texto).toLowerCase().replace(/\s+/g, ' ').trim();
}
function esc(texto) {
    return String(texto === null || texto === undefined ? '' : texto).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}
// Mismo radio y fórmula que el modelo de referencia en Python.
function haversine(lat1, lon1, lat2, lon2) {
    const R = 6371.0088;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
function listaEspecialidades(h) {
    return String(h.especialidades || '').split(',').map(s => s.trim()).filter(Boolean);
}
function clamp(x, a, b) { return Math.min(Math.max(x, a), b); }
function mediana(arr) {
    const a = arr.filter(Number.isFinite).sort((x, y) => x - y);
    if (!a.length) return NaN;
    const m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
function fmtMetros(m) { return m >= 1000 ? (m / 1000).toFixed(1) + ' km' : Math.round(m) + ' m'; }
function esperar(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

// Línea de costa aproximada: sirve para no contar el mar como "desierto de atención".
function latCosta(lon) {
    const p = COSTA_APROX;
    if (lon <= p[0][0]) return p[0][1];
    if (lon >= p[p.length - 1][0]) return p[p.length - 1][1];
    for (let i = 1; i < p.length; i++) {
        if (lon <= p[i][0]) {
            const t = (lon - p[i - 1][0]) / (p[i][0] - p[i - 1][0]);
            return p[i - 1][1] + (p[i][1] - p[i - 1][1]) * t;
        }
    }
    return p[p.length - 1][1];
}
function esTierra(lat, lon) { return lat >= latCosta(lon); }

function dentroDeLimites(lat, lon) {
    const L_ = CFG.limites;
    return lat >= L_.latMin && lat <= L_.latMax && lon >= L_.lonMin && lon <= L_.lonMax;
}

/* =====================================================================
   3. HORARIOS: ¿ABIERTO AHORA / AL LLEGAR? (hora de Panamá, UTC-5)
   ===================================================================== */
const DIAS_CORTO = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
const fmtPanama = new Intl.DateTimeFormat('en-US', {
    timeZone: CFG.zonaHoraria, weekday: 'short', hour: 'numeric', minute: 'numeric', hourCycle: 'h23'
});
function ahoraPanama(offsetMin) {
    const t = new Date(Date.now() + (offsetMin || 0) * 60000);
    const p = {};
    fmtPanama.formatToParts(t).forEach(x => { p[x.type] = x.value; });
    return { dia: DIAS_CORTO[p.weekday], min: (parseInt(p.hour, 10) % 24) * 60 + parseInt(p.minute, 10) };
}
// true / false, o null si el horario no pudo interpretarse. offsetMin = minutos hasta la llegada.
function estaAbierto(h, offsetMin) {
    const info = h.horario_info;
    if (!info) return null;
    const t = ahoraPanama(offsetMin);
    if (info.h24) return info.dias.includes(t.dia);
    if (info.abre < info.cierra) {
        return info.dias.includes(t.dia) && t.min >= info.abre && t.min < info.cierra;
    }
    const ayer = (t.dia + 6) % 7; // el turno cruza la medianoche
    return (info.dias.includes(t.dia) && t.min >= info.abre) || (info.dias.includes(ayer) && t.min < info.cierra);
}
function insignia(estado, textoSi, textoNo) {
    if (estado === true) return `<span class="badge b-ok">${textoSi || 'abierto'}</span>`;
    if (estado === false) return `<span class="badge b-no">${textoNo || 'cerrado'}</span>`;
    return '<span class="badge b-na">horario ?</span>';
}

/* =====================================================================
   4. CATÁLOGO DINÁMICO DE ESPECIALIDADES
   ===================================================================== */
const catalogo = new Map(); // clave normalizada -> { nombre, clave, count }

hospitales.forEach(h => {
    const vistos = new Set();
    listaEspecialidades(h).forEach(esp => {
        const clave = normalizarClave(esp);
        if (vistos.has(clave)) return;
        vistos.add(clave);
        if (!catalogo.has(clave)) catalogo.set(clave, { nombre: esp, clave, count: 0 });
        catalogo.get(clave).count += 1;
    });
});

function categoriaDe(esp) {
    const s = normalizarClave(esp);
    for (const cat of CATEGORIAS) if (cat.patron.test(s)) return cat.nombre;
    return '📦 Otras especialidades';
}

function construirSelectEspecialidades() {
    const grupos = new Map();
    catalogo.forEach(info => {
        const cat = categoriaDe(info.nombre);
        if (!grupos.has(cat)) grupos.set(cat, []);
        grupos.get(cat).push(info);
    });
    const orden = CATEGORIAS.map(c => c.nombre).concat(['📦 Otras especialidades']);
    let html = `<option value="todas">🩺 Todas las especialidades (${hospitales.length} centros)</option>`;
    orden.forEach(nombreCat => {
        const items = grupos.get(nombreCat);
        if (!items || !items.length) return;
        items.sort((a, b) => a.nombre.localeCompare(b.nombre, 'es'));
        html += `<optgroup label="${esc(nombreCat)}">`;
        items.forEach(it => {
            html += `<option value="${esc(it.clave)}">${esc(it.nombre)} (${it.count})</option>`;
        });
        html += '</optgroup>';
    });
    document.getElementById('especialidadSelect').innerHTML = html;
}

/* =====================================================================
   5. MAPA Y CAPAS
   ===================================================================== */
const map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([9.045, -79.495], 11);

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

const capaRed = L.layerGroup().addTo(map);
const capaLineas = L.layerGroup();
const capaModelo = L.layerGroup().addTo(map);
const capaRuta = L.layerGroup().addTo(map);
const capaInactivos = L.layerGroup().addTo(map);
// Marcadores solapados (p. ej. Paitilla, Punta Pacífica): se agrupan sin alterar sus coordenadas.
const hayCluster = typeof L.markerClusterGroup === 'function';
const capaActivos = hayCluster
    ? L.markerClusterGroup({ maxClusterRadius: 28, disableClusteringAtZoom: 15, showCoverageOnHover: false, spiderfyOnMaxZoom: true })
    : L.layerGroup();
capaActivos.addTo(map);
const capaOrigen = L.layerGroup().addTo(map);
const capaEdicion = L.layerGroup();
const capaCobertura = L.layerGroup();

/* =====================================================================
   6. ESTADO Y REFERENCIAS DEL DOM
   ===================================================================== */
const selEspecialidad = document.getElementById('especialidadSelect');
const selOrigen = document.getElementById('origenSelect');
const selDestino = document.getElementById('destinoSelect');
const selCobertura = document.getElementById('selCobertura');
const chkAbiertos = document.getElementById('chkAbiertos');
const chkOSRM = document.getElementById('chkOSRM');
const chkRed = document.getElementById('chkRed');
const chkEditar = document.getElementById('chkEditar');
const panelEdicion = document.getElementById('panelEdicion');
const inputCoords = document.getElementById('inputCoords');
const divCoords = document.getElementById('divCoords');
const estadoRuta = document.getElementById('estadoRuta');
const tablaDistancias = document.getElementById('tablaDistancias');
const metricasDiv = document.getElementById('metricas');
const coberturaStatsDiv = document.getElementById('coberturaStats');
const btnCobertura = document.getElementById('btnCobertura');
const chipOSRM = document.getElementById('estadoOSRM');

let puntoActual = { lat: 9.0350, lng: -79.4850 };
let coberturaActiva = false;
let ultimoResultado = null;
let temporizadorToast = null;
let secuencia = 0; // descarta respuestas OSRM obsoletas si el usuario cambia de origen

/* =====================================================================
   7. FILTRADO POR ESPECIALIDAD
   ===================================================================== */
function etiquetaEspecialidad() {
    const clave = selEspecialidad.value;
    if (clave === 'todas' || !catalogo.has(clave)) return 'cualquier especialidad';
    return catalogo.get(clave).nombre;
}

// Todas las instalaciones que ofrecen la especialidad (incluye insulares: se dibujan).
function hospitalesFiltrados() {
    const clave = selEspecialidad.value;
    const lista = hospitales.map((h, idx) => ({ h, idx }));
    if (clave === 'todas' || !catalogo.has(clave)) return lista;
    return lista.filter(x => listaEspecialidades(x.h).some(esp => normalizarClave(esp) === clave));
}
// Solo las alcanzables por tierra: son los destinos válidos del enrutamiento.
function candidatosTerrestres() {
    return hospitalesFiltrados().filter(x => !x.h.insular);
}

function actualizarChip() {
    const lista = hospitalesFiltrados();
    const total = lista.length;
    const insulares = lista.filter(x => x.h.insular).length;
    const sustantivo = total === 1 ? 'instalación' : 'instalaciones';
    const esTodas = selEspecialidad.value === 'todas' || !catalogo.has(selEspecialidad.value);
    let texto = esTodas
        ? `${total} ${sustantivo} registradas en la Provincia de Panamá`
        : `${total} ${sustantivo} ${total === 1 ? 'ofrece' : 'ofrecen'} ${etiquetaEspecialidad()}`;
    if (insulares) texto += ` · ${insulares} insular${insulares > 1 ? 'es' : ''} (sin ruta terrestre)`;
    document.getElementById('chipEspecialidad').textContent = texto;
}

function reconstruirDestinos() {
    const anterior = selDestino.value;
    const filtrados = candidatosTerrestres().slice()
        .sort((a, b) => a.h.nombre.localeCompare(b.h.nombre, 'es'));
    let html = `<option value="cercano">⚡ Más cercano con ${esc(etiquetaEspecialidad())} (${filtrados.length})</option>`;
    filtrados.forEach(x => {
        html += `<option value="${x.idx}">${esc(x.h.nombre)}</option>`;
    });
    selDestino.innerHTML = html;
    if ([...selDestino.options].some(o => o.value === anterior)) selDestino.value = anterior;
}

function textoPosicion(h) {
    return h.verificada
        ? 'posición verificada' + (h.fuente ? ' (' + h.fuente + ')' : '')
        : `posición aproximada (resolución del dato ±${fmtMetros(h.resolucion_m)})`;
}

function tooltipHospital(h) {
    return `<b>${esc(h.nombre)}</b> ${insignia(estaAbierto(h, 0), 'abierto ahora', 'cerrado ahora')}<br>` +
        `<span style="color:#8fd3c0">🕒 ${esc(h.horario)}</span><br>` +
        `<span style="color:#ffd54f">🩺 ${esc(h.especialidades)}</span><br>` +
        `<span style="color:#9fb4ac">📍 ${esc(textoPosicion(h))}</span>` +
        (h.insular ? '<br><span style="color:#81d4fa">🚤 Centro insular: acceso marítimo o aéreo; fuera del enrutamiento terrestre</span>' : '');
}

function renderHospitales() {
    capaActivos.clearLayers();
    capaInactivos.clearLayers();
    capaEdicion.clearLayers();
    const activos = new Set(hospitalesFiltrados().map(x => x.idx));
    hospitales.forEach((h, idx) => {
        const activo = activos.has(idx) || EDITANDO;
        const aprox = !h.verificada && h.resolucion_m >= 500;
        const clase = 'pin' + (h.insular ? ' pin-ins' : '') + (activo ? '' : ' pin-off') + (aprox ? ' pin-aprox' : '');
        const tam = activo ? 16 : 11;
        const marcador = L.marker([h.lat, h.lon], {
            icon: L.divIcon({ className: '', html: `<div class="${clase}"></div>`, iconSize: [tam, tam] }),
            keyboard: false, draggable: EDITANDO
        });
        marcador.bindTooltip(tooltipHospital(h), { direction: 'top', opacity: 0.97, offset: [0, -6] });
        marcador.on('click', () => seleccionarHospital(idx));
        if (EDITANDO) marcador.on('dragend', e => moverHospital(idx, e.target.getLatLng()));
        (EDITANDO ? capaEdicion : (activo ? capaActivos : capaInactivos)).addLayer(marcador);
    });
}

function seleccionarHospital(idx) {
    if (hospitales[idx] && hospitales[idx].insular) {
        mostrarToast('Centro insular: no hay ruta terrestre (requiere traslado marítimo o aéreo).');
        return;
    }
    const opcion = [...selDestino.options].find(o => o.value === String(idx));
    if (!opcion) {
        mostrarToast('Ese centro no ofrece la especialidad filtrada. Cambia la especialidad para elegirlo.');
        return;
    }
    selDestino.value = String(idx);
    actualizarCalculo();
}

function mostrarToast(mensaje) {
    const toast = document.getElementById('toast');
    toast.textContent = mensaje;
    toast.classList.add('visible');
    clearTimeout(temporizadorToast);
    temporizadorToast = setTimeout(() => toast.classList.remove('visible'), 3600);
}

function cambiarEspecialidad() {
    reconstruirDestinos();
    actualizarChip();
    renderHospitales();
    if (coberturaActiva) actualizarCobertura();
    actualizarCalculo();
}

/* =====================================================================
   8. MODELO: FRICCIÓN URBANA, SINUOSIDAD VIAL Y GRAFO
   ---------------------------------------------------------------------
   ETA(arista) = d_recta · sinuosidad · fricción_media_del_tramo · 60 / v_libre
   - sinuosidad: la v1 usaba la línea recta (relación 1.00); las calles real
     son más largas. Se calibra con OSRM (botón del dashboard).
   - fricción_media_del_tramo: integral numérica a lo largo de la recta
     (un punto por km, regla del punto medio), no solo en los extremos.
   ===================================================================== */
function factorFriccion(lat, lon) {
    let f = 1.0;
    for (const zona of ZONAS_FRICCION) {
        const d = haversine(lat, lon, zona.lat, zona.lon);
        f += zona.peso * Math.exp(-(d * d) / (zona.radio * zona.radio));
    }
    return Math.min(f, CFG.maxFriccion);
}

function friccionSegmento(lat1, lon1, lat2, lon2, dRecta) {
    const m = Math.min(12, Math.max(1, Math.ceil(dRecta / CFG.muestrasFriccionKm)));
    let s = 0;
    for (let k = 0; k < m; k++) {
        const t = (k + 0.5) / m;
        s += factorFriccion(lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t);
    }
    return s / m;
}

function sinuosidadEfectiva() { return ES_DIRECTA() ? 1 : CFG.sinuosidad; }
function velocidadEfectiva() { return ES_DIRECTA() ? CFG.velocidadDirectaKmh : CFG.velocidadLibreKmh; }

function crearArista(dRecta, friccion, sinuosidad, velocidad) {
    const sin = sinuosidad === undefined ? CFG.sinuosidad : sinuosidad;
    const v = velocidad === undefined ? CFG.velocidadLibreKmh : velocidad;
    const km = Math.max(dRecta * sin, 0.05); // evita aristas nulas por nodos colocalizados
    const f = clamp(friccion, 1, CFG.maxFriccion);
    return { distKm: km, rectaKm: dRecta, etaMin: km * f * 60 / v, friccion: f };
}

// Grafo kNN entre instalaciones terrestres: no depende del origen, se construye una vez
// (y de nuevo solo si se recalibra el modelo). Nodo 0 = origen; hospital i = nodo i+1.
let GRAFO_BASE = null;
let tGrafoBase = 0;

function agregarAristaBase(adj, pares, a, b) {
    const u = Math.min(a, b), v = Math.max(a, b);
    const clave = u + '-' + v;
    if (u === v || pares.has(clave)) return;
    pares.add(clave);
    const ha = hospitales[u - 1];
    const hb = hospitales[v - 1];
    const d = haversine(ha.lat, ha.lon, hb.lat, hb.lon);
    const ar = crearArista(d, friccionSegmento(ha.lat, ha.lon, hb.lat, hb.lon, d));
    const arista = { distKm: ar.distKm, rectaKm: ar.rectaKm, etaMin: ar.etaMin, friccion: ar.friccion };
    adj[u].push({ to: v, ...arista });
    adj[v].push({ to: u, ...arista });
}

function construirGrafoBase() {
    const t0 = performance.now();
    const adj = Array.from({ length: hospitales.length + 1 }, () => []);
    const ids = IDX_TERRESTRES.map(i => i + 1);
    const pares = new Set();
    // 1) k vecinos más cercanos entre instalaciones
    for (const u of ids) {
        const hu = hospitales[u - 1];
        const vecinos = [];
        for (const v of ids) {
            if (v === u) continue;
            vecinos.push({ v, d: haversine(hu.lat, hu.lon, hospitales[v - 1].lat, hospitales[v - 1].lon) });
        }
        vecinos.sort((a, b) => a.d - b.d);
        for (const { v } of vecinos.slice(0, CFG.kVecinos)) agregarAristaBase(adj, pares, u, v);
    }
    // 2) MST (Prim): garantiza que ningún centro quede aislado en una "isla" del kNN.
    if (ids.length > 1) {
        const enArbol = new Set([ids[0]]);
        while (enArbol.size < ids.length) {
            let mejor = null;
            for (const u of enArbol) {
                const hu = hospitales[u - 1];
                for (const v of ids) {
                    if (enArbol.has(v)) continue;
                    const d = haversine(hu.lat, hu.lon, hospitales[v - 1].lat, hospitales[v - 1].lon);
                    if (!mejor || d < mejor.d) mejor = { d, u, v };
                }
            }
            if (!mejor) break;
            agregarAristaBase(adj, pares, mejor.u, mejor.v);
            enArbol.add(mejor.v);
        }
    }
    GRAFO_BASE = adj;
    tGrafoBase = performance.now() - t0;
    return adj;
}

// Vía directa: el origen se enlaza en línea recta con todas las instalaciones (sin tráfico).
// Vía por calles: el origen entra por sus `kOrigen` centros más cercanos y luego usa la red
// kNN+MST; así no se dibujan ni se usan enlaces artificiales a los 93 centros.
function grafoConOrigen(lat, lon) {
    if (!GRAFO_BASE) construirGrafoBase();
    if (ES_DIRECTA()) {
        const adj = Array.from({ length: hospitales.length + 1 }, () => []);
        for (const i of IDX_TERRESTRES) {
            const h = hospitales[i];
            const d = haversine(lat, lon, h.lat, h.lon);
            const ar = crearArista(d, 1, 1, CFG.velocidadDirectaKmh);
            const arista = { distKm: ar.distKm, rectaKm: ar.rectaKm, etaMin: ar.etaMin, friccion: ar.friccion };
            adj[0].push({ to: i + 1, ...arista });
            adj[i + 1].push({ to: 0, ...arista });
        }
        return adj;
    }
    const adj = GRAFO_BASE.map(lista => lista.slice());
    const cercanos = IDX_TERRESTRES
        .map(i => ({ i, d: haversine(lat, lon, hospitales[i].lat, hospitales[i].lon) }))
        .sort((a, b) => a.d - b.d)
        .slice(0, Math.max(1, CFG.kOrigen | 0));
    const sin = sinuosidadEfectiva();
    for (const { i, d } of cercanos) {
        const h = hospitales[i];
        const ar = crearArista(d, friccionSegmento(lat, lon, h.lat, h.lon, d), sin);
        const arista = { distKm: ar.distKm, rectaKm: ar.rectaKm, etaMin: ar.etaMin, friccion: ar.friccion };
        adj[0].push({ to: i + 1, ...arista });
        adj[i + 1].push({ to: 0, ...arista });
    }
    return adj;
}

function contarAristas(grafo) {
    let grados = 0;
    for (const lista of grafo) grados += lista.length;
    return grados / 2;
}

/* =====================================================================
   9. DIJKSTRA CON COLA DE PRIORIDAD (heap binario)
   ===================================================================== */
class MinHeap {
    constructor() { this.a = []; }
    get size() { return this.a.length; }
    push(item) {
        const a = this.a;
        a.push(item);
        let i = a.length - 1;
        while (i > 0) {
            const p = (i - 1) >> 1;
            if (a[p].d <= a[i].d) break;
            const tmp = a[p]; a[p] = a[i]; a[i] = tmp;
            i = p;
        }
    }
    pop() {
        const a = this.a;
        if (a.length === 0) return null;
        const cima = a[0];
        const ultimo = a.pop();
        if (a.length > 0) {
            a[0] = ultimo;
            let i = 0;
            const n = a.length;
            while (true) {
                const l = 2 * i + 1, r = l + 1;
                let s = i;
                if (l < n && a[l].d < a[s].d) s = l;
                if (r < n && a[r].d < a[s].d) s = r;
                if (s === i) break;
                const tmp = a[i]; a[i] = a[s]; a[s] = tmp;
                i = s;
            }
        }
        return cima;
    }
}

function dijkstra(grafo, origen, objetivos, detenerEnPrimero) {
    const N = grafo.length;
    const dist = new Array(N).fill(Infinity);
    const distKm = new Array(N).fill(0);
    const prev = new Array(N).fill(-1);
    const hecho = new Array(N).fill(false);
    let explorados = 0;
    let relajaciones = 0;
    let destino = -1;
    const heap = new MinHeap();
    dist[origen] = 0;
    heap.push({ n: origen, d: 0 });

    while (heap.size > 0) {
        const actual = heap.pop();
        const u = actual.n;
        if (hecho[u]) continue;
        if (actual.d > dist[u] + 1e-12) continue;
        hecho[u] = true;
        explorados += 1;
        if (objetivos && objetivos.has(u)) {
            destino = u;
            if (detenerEnPrimero) break;
        }
        for (const e of grafo[u]) {
            const nuevo = dist[u] + e.etaMin;
            relajaciones += 1;
            if (nuevo < dist[e.to] - 1e-12) {
                dist[e.to] = nuevo;
                distKm[e.to] = distKm[u] + e.distKm;
                prev[e.to] = u;
                heap.push({ n: e.to, d: nuevo });
            }
        }
    }
    return { dist, distKm, prev, explorados, relajaciones, destino, total: N };
}

function reconstruirCamino(res, destino) {
    if (destino < 0 || !Number.isFinite(res.dist[destino])) return null;
    const camino = [];
    let actual = destino;
    while (actual !== -1) {
        camino.push(actual);
        actual = res.prev[actual];
    }
    return camino.reverse();
}

/* =====================================================================
   10. RUTAS REALES POR CALLES (OSRM) CON RESPALDO AL MODELO
   ===================================================================== */
async function pedirJSON(url) {
    const ctl = new AbortController();
    const temporizador = setTimeout(() => ctl.abort(), CFG.osrm.timeoutMs);
    try {
        const resp = await fetch(url, { signal: ctl.signal });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return await resp.json();
    } finally {
        clearTimeout(temporizador);
    }
}
function coordOSRM(lat, lon) { return lon.toFixed(6) + ',' + lat.toFixed(6); }

// Duración y distancia por calles desde el origen hacia muchos destinos (una sola petición por lote).
// El servidor demo de OSRM puede rechazar `annotations=duration,distance`; se reintenta solo con duración.
async function osrmTabla(origen, destinos) {
    const salida = new Array(destinos.length).fill(null);
    const tam = CFG.osrm.maxTabla - 1;
    let snapOrigenM = null;
    for (let ini = 0; ini < destinos.length; ini += tam) {
        const trozo = destinos.slice(ini, ini + tam);
        const coords = [coordOSRM(origen.lat, origen.lon), ...trozo.map(h => coordOSRM(h.lat, h.lon))].join(';');
        let d;
        try {
            d = await pedirJSON(`${CFG.osrm.url}/table/v1/driving/${coords}?sources=0&annotations=duration,distance`);
        } catch (e) {
            d = await pedirJSON(`${CFG.osrm.url}/table/v1/driving/${coords}?sources=0&annotations=duration`);
        }
        if (d.code !== 'Ok') throw new Error('OSRM table: ' + (d.code || 'sin código'));
        if (d.sources && d.sources[0] && typeof d.sources[0].distance === 'number') snapOrigenM = d.sources[0].distance;
        const dur = d.durations && d.durations[0];
        const dis = d.distances && d.distances[0];
        trozo.forEach((_, k) => {
            const s = dur ? dur[k + 1] : null;
            const m = dis ? dis[k + 1] : null;
            // Con la variante sin distancias se conserva la duración y se estima el km con la recta × sinuosidad.
            const km = (m === null || m === undefined) && s !== null && s !== undefined
                ? haversine(origen.lat, origen.lon, trozo[k].lat, trozo[k].lon) * CFG.sinuosidad : m / 1000;
            salida[ini + k] = (s === null || s === undefined) ? null : { min: s / 60, km };
        });
    }
    return { filas: salida, snapOrigenM };
}

async function osrmRuta(origen, destino) {
    const url = `${CFG.osrm.url}/route/v1/driving/${coordOSRM(origen.lat, origen.lon)};` +
        `${coordOSRM(destino.lat, destino.lon)}?overview=full&geometries=geojson&steps=true&alternatives=false`;
    const d = await pedirJSON(url);
    if (d.code !== 'Ok' || !d.routes || !d.routes.length) throw new Error('OSRM route: ' + (d.code || 'sin ruta'));
    const r = d.routes[0];
    const wp = d.waypoints || [];
    const pasos = [];
    (r.legs || []).forEach(leg => (leg.steps || []).forEach(p => {
        if (p.distance >= 1) pasos.push({ km: p.distance / 1000, min: (p.duration || 0) / 60,
            texto: p.name ? `${p.name} · ${p.maneuver && p.maneuver.type ? p.maneuver.type : ''}` : 'tramo' });
    }));
    return {
        km: r.distance / 1000,
        min: r.duration / 60,
        geom: r.geometry.coordinates.map(c => [c[1], c[0]]),
        pasos,
        snapOrigenM: wp[0] && typeof wp[0].distance === 'number' ? wp[0].distance : null,
        snapDestinoM: wp[1] && typeof wp[1].distance === 'number' ? wp[1].distance : null
    };
}

// Tráfico sobre el trazado REAL: se pondera cada tramo por la fricción en su punto medio.
function etaAjustadaGeometria(geom, minLibre) {
    const tramos = [];
    let total = 0;
    for (let i = 0; i < geom.length - 1; i++) {
        const a = geom[i];
        const b = geom[i + 1];
        const len = haversine(a[0], a[1], b[0], b[1]);
        tramos.push({ len, f: factorFriccion((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) });
        total += len;
    }
    if (total <= 0) return { eta: minLibre, fricMedia: 1 };
    let eta = 0;
    for (const t of tramos) eta += minLibre * (t.len / total) * t.f;
    return { eta, fricMedia: eta / minLibre };
}

function setEstadoOSRM(estado, detalle) {
    const textos = {
        idle: 'Rutas reales por calles (OSRM): se consultan al calcular cada ruta',
        off: 'Rutas reales desactivadas · se usan estimaciones del modelo',
        directa: 'Vía directa: no se consultan calles (OSRM no se usa)',
        pend: '⏳ Consultando rutas reales por calles…',
        ok: '✓ Rutas reales por calles (OSRM)',
        err: '⚠ Rutas reales no disponibles · se muestran estimaciones del modelo · clic para reintentar'
    };
    chipOSRM.className = 'chip-osrm ' + (estado === 'ok' ? 'ok' : estado === 'pend' ? 'pend' : estado === 'err' ? 'err' : '');
    chipOSRM.textContent = textos[estado] + (detalle ? ` (${detalle})` : '');
}

// Refina el resultado del modelo con datos reales. Si algo falla, el modelo sigue siendo válido.
async function refinarConOSRM(r, seq) {
    if (ES_DIRECTA()) { setEstadoOSRM('directa'); return; }
    if (!OSRM.activo || !chkOSRM.checked) { setEstadoOSRM('off'); return; }
    setEstadoOSRM('pend');
    await esperar(CFG.osrm.retardoMs);
    if (seq !== secuencia) return;
    try {
        const origen = r.origen;
        // Solo los N centros con mejor ETA del modelo: /table con 93 destinos es lento y el demo público lo limita.
        const top = r.candBase.slice()
            .sort((a, b) => r.completo.dist[a.idx + 1] - r.completo.dist[b.idx + 1])
            .slice(0, Math.max(1, CFG.maxCandidatosOSRM | 0));
        const tabla = await osrmTabla(origen, top.map(x => x.h));
        if (seq !== secuencia) return;
        const porIdx = new Map();
        top.forEach((x, k) => {
            const f = tabla.filas[k];
            if (!f) return;
            const recta = haversine(origen.lat, origen.lon, x.h.lat, x.h.lon);
            const fric = friccionSegmento(origen.lat, origen.lon, x.h.lat, x.h.lon, recta);
            porIdx.set(x.idx + 1, { min: f.min, km: f.km, recta, fric, etaT: f.min * fric });
        });
        if (porIdx.size === 0) throw new Error('ningún destino alcanzable por calles');

        let nodoDestino;
        if (r.modo === 'cercano') {
            let lista = r.candBase.filter(x => porIdx.has(x.idx + 1));
            if (chkAbiertos.checked) {
                const ab = lista.filter(x => estaAbierto(x.h, porIdx.get(x.idx + 1).etaT) !== false);
                if (ab.length) lista = ab;
            }
            if (!lista.length) throw new Error('ningún destino alcanzable por calles');
            lista.sort((a, b) => porIdx.get(a.idx + 1).etaT - porIdx.get(b.idx + 1).etaT);
            nodoDestino = lista[0].idx + 1;
        } else {
            nodoDestino = parseInt(r.modo, 10) + 1;
            // Aunque el destino forzado no esté en el top N de /table, /route sí puede trazarlo.
        }
        const ruta = await osrmRuta(origen, hospitales[nodoDestino - 1]);
        if (seq !== secuencia) return;
        const aj = etaAjustadaGeometria(ruta.geom, ruta.min);
        ruta.etaT = aj.eta;
        ruta.fricMedia = aj.fricMedia;
        // El destino elegido usa la misma ETA (sobre el trazado real) en tabla y dashboard.
        const filaSel = porIdx.get(nodoDestino);
        if (filaSel) { filaSel.etaT = ruta.etaT; filaSel.min = ruta.min; filaSel.km = ruta.km; }
        else porIdx.set(nodoDestino, {
            min: ruta.min, km: ruta.km, etaT: ruta.etaT, fric: ruta.fricMedia,
            recta: haversine(origen.lat, origen.lon, hospitales[nodoDestino - 1].lat, hospitales[nodoDestino - 1].lon)
        });

        // Estadísticos para calibrar el modelo (solo trayectos > 1 km para evitar ruido).
        const utiles = [...porIdx.values()].filter(v => v.recta >= 1 && v.min > 0);
        const calib = {
            n: utiles.length,
            sinuosidad: mediana(utiles.map(v => v.km / v.recta)),
            velocidad: mediana(utiles.map(v => v.km / (v.min / 60)))
        };
        r.real = {
            ok: true, tablaPorIdx: porIdx, destinoIdx: nodoDestino, ruta, calib,
            snapOrigenM: tabla.snapOrigenM !== null ? tabla.snapOrigenM : ruta.snapOrigenM
        };
        OSRM.fallos = 0;
        setEstadoOSRM('ok');
    } catch (e) {
        if (seq !== secuencia) return;
        r.real = { ok: false, error: String(e && e.message ? e.message : e) };
        OSRM.fallos += 1;
        setEstadoOSRM('err', r.real.error);
    }
    if (seq !== secuencia) return;
    ultimoResultado = r;
    renderTodo(r);
}

function cambiarOSRM() {
    OSRM.activo = chkOSRM.checked;
    actualizarCalculo();
}
function reintentarOSRM() {
    if (!chipOSRM.classList.contains('err')) return;
    OSRM.activo = true;
    chkOSRM.checked = true;
    actualizarCalculo();
}

/* =====================================================================
   11. VISUALIZACIÓN DE RED Y RUTA
   ===================================================================== */
function colorFriccion(f) {
    if (f < 1.3) return '#00E676';
    if (f < 1.65) return '#FFD600';
    if (f < 2.05) return '#FF9100';
    return '#FF3D00';
}

// La red kNN entre instalaciones ya no depende del origen: se dibuja una sola vez.
function dibujarRedBase() {
    capaRed.clearLayers();
    const vistos = new Set();
    for (let u = 1; u < GRAFO_BASE.length; u++) {
        for (const e of GRAFO_BASE[u]) {
            const a = Math.min(u, e.to);
            const b = Math.max(u, e.to);
            const clave = a + '-' + b;
            if (vistos.has(clave)) continue;
            vistos.add(clave);
            L.polyline([[hospitales[a - 1].lat, hospitales[a - 1].lon], [hospitales[b - 1].lat, hospitales[b - 1].lon]], {
                color: '#7f8c8d', weight: 1, opacity: 0.16, interactive: false
            }).addTo(capaRed);
        }
    }
}
function toggleRed() {
    if (chkRed.checked && MODO === 'calles') capaRed.addTo(map); else map.removeLayer(capaRed);
}

function dibujarCaminoModelo(r, capa, discontinua) {
    for (let i = 1; i < r.camino.length; i++) {
        const u = r.camino[i - 1];
        const v = r.camino[i];
        const arista = r.grafo[u].find(e => e.to === v);
        const linea = [[r.nodos[u].lat, r.nodos[u].lon], [r.nodos[v].lat, r.nodos[v].lon]];
        L.polyline(linea, discontinua
            ? { color: '#ffffff', weight: 2, opacity: 0.75, dashArray: '6 7' }
            : { color: arista ? colorFriccion(arista.friccion) : '#FF3D00', weight: 6, opacity: 0.95 }
        ).addTo(capa);
    }
}

// Trazado real por calles, coloreado por la fricción de tráfico de cada tramo.
function dibujarRutaReal(geom, capa) {
    let color = null;
    let tramo = [];
    const cerrar = () => {
        if (tramo.length > 1) L.polyline(tramo, { color, weight: 6, opacity: 0.95 }).addTo(capa);
    };
    for (let i = 0; i < geom.length - 1; i++) {
        const a = geom[i];
        const b = geom[i + 1];
        const c = colorFriccion(factorFriccion((a[0] + b[0]) / 2, (a[1] + b[1]) / 2));
        if (c !== color) { cerrar(); tramo = [a]; color = c; }
        tramo.push(b);
    }
    cerrar();
}

function dibujarSalida(r) {
    capaModelo.clearLayers();
    capaRuta.clearLayers();
    const real = r.real && r.real.ok ? r.real : null;
    const nodoDestino = real ? real.destinoIdx : r.destinoIdx;
    // Se dibuja SOLO la ruta elegida (origen -> hospital más cercano). Nada de abanicos de líneas.
    if (real) {
        dibujarRutaReal(real.ruta.geom, capaRuta);
    } else if (r.camino.length >= 2) {
        dibujarCaminoModelo(r, capaRuta, false);
    }
    const h = hospitales[nodoDestino - 1];
    L.circleMarker([h.lat, h.lon], {
        radius: 12, color: '#ffffff', weight: 3, fillColor: '#FF3D00', fillOpacity: 0.9
    }).addTo(capaRuta);
}

/* =====================================================================
   12. CÁLCULO DE RUTA (MODELO) Y MÉTRICAS
   ===================================================================== */
function benchmark(fn, repeticiones) {
    let resultado = null;
    const t0 = performance.now();
    for (let i = 0; i < repeticiones; i++) resultado = fn();
    const t1 = performance.now();
    return { resultado, ms: (t1 - t0) / repeticiones };
}

function calcularModelo(lat, lon, nombreOrigen) {
    const t0 = performance.now();
    const grafo = grafoConOrigen(lat, lon);
    const tGrafo = performance.now() - t0;
    const nodos = [{ nombre: nombreOrigen, lat, lon }, ...hospitales];
    const totalNodos = 1 + IDX_TERRESTRES.length;
    const aristas = contarAristas(grafo);
    const filtrados = candidatosTerrestres();
    if (filtrados.length === 0) return null;

    // Si el <select> quedó en un valor que ya no existe tras un filtrado,
    // se vuelve al modo automático para evitar estados inconsistentes.
    let valorDestino = selDestino.value;
    if (![...selDestino.options].some(o => o.value === valorDestino)) {
        valorDestino = 'cercano';
        selDestino.value = 'cercano';
    }

    let candBase = filtrados;
    if (valorDestino === 'cercano' && selOrigen.value !== 'mapa') {
        const idxOrigen = parseInt(selOrigen.value, 10);
        const sinOrigen = filtrados.filter(x => x.idx !== idxOrigen);
        if (sinOrigen.length > 0) candBase = sinOrigen;
    }

    const benchCompleto = benchmark(() => dijkstra(grafo, 0, null, false), CFG.repeticionesBenchmark);
    const completo = benchCompleto.resultado;

    // Filtro "abierto a mi llegada": se evalúa con el ETA de cada centro.
    let candidatos = candBase;
    let avisoHorario = null;
    if (chkAbiertos.checked && valorDestino === 'cercano') {
        const abiertos = candBase.filter(x => estaAbierto(x.h, completo.dist[x.idx + 1]) !== false);
        if (abiertos.length) candidatos = abiertos;
        else avisoHorario = 'Ningún centro con esta especialidad estará abierto a tu llegada; se muestra el más cercano.';
    }

    let destinosPosibles;
    if (valorDestino === 'cercano') {
        destinosPosibles = candidatos.map(x => x.idx + 1);
    } else {
        const idx = parseInt(valorDestino, 10);
        if (Number.isNaN(idx)) return null;
        destinosPosibles = [idx + 1];
    }
    const objetivos = new Set(destinosPosibles);

    const benchDirigido = benchmark(() => dijkstra(grafo, 0, objetivos, true), CFG.repeticionesBenchmark);
    const dirigido = benchDirigido.resultado;
    const destinoIdx = dirigido.destino;
    const camino = reconstruirCamino(dirigido, destinoIdx);
    if (!camino) return null;

    const distKm = dirigido.distKm[destinoIdx];
    const eta = dirigido.dist[destinoIdx];
    const tiempoLibre = distKm * 60 / velocidadEfectiva();

    return {
        origen: { lat, lon, nombre: nombreOrigen },
        modo: valorDestino,
        destinoIdx, camino, nodos, grafo, completo, filtrados, candBase,
        distKm, eta, tiempoLibre,
        friccionMedia: tiempoLibre > 0 ? eta / tiempoLibre : 1,
        velocidadMedia: eta > 0 ? distKm / (eta / 60) : 0,
        penalizacion: tiempoLibre > 0 ? (eta - tiempoLibre) / tiempoLibre * 100 : 0,
        tiempoGrafo: tGrafo, tiempoGrafoBase: tGrafoBase, tiempoDirigido: benchDirigido.ms,
        tiempoCompleto: benchCompleto.ms, tiempoTotal: tGrafo + benchDirigido.ms,
        explorados: dirigido.explorados, exploradosCompleto: completo.explorados,
        relajaciones: dirigido.relajaciones, aristas, totalNodos,
        candidatos: candidatos.length, especialidad: etiquetaEspecialidad(),
        avisoHorario, real: null, modoRuta: MODO, generado: new Date().toISOString()
    };
}

// Valores "a mostrar": ruta real (OSRM) si existe; si no, estimación del modelo.
function resumen(r) {
    const real = r.real && r.real.ok ? r.real : null;
    const nodo = real ? real.destinoIdx : r.destinoIdx;
    const h = hospitales[nodo - 1];
    const recta = haversine(r.origen.lat, r.origen.lon, h.lat, h.lon);
    const modeloKm = r.completo.distKm[nodo];
    const modeloEta = r.completo.dist[nodo];
    if (real) {
        const q = real.ruta;
        return {
            fuente: 'real', modoRuta: r.modoRuta, h, nodo, recta, modeloKm, modeloEta,
            km: q.km, minLibre: q.min, eta: q.etaT, fricMedia: q.fricMedia,
            velMedia: q.etaT > 0 ? q.km / (q.etaT / 60) : 0,
            penal: q.min > 0 ? (q.etaT - q.min) / q.min * 100 : 0
        };
    }
    return {
        fuente: 'modelo', modoRuta: r.modoRuta, h, nodo, recta, modeloKm, modeloEta,
        km: r.distKm, minLibre: r.tiempoLibre, eta: r.eta, fricMedia: r.friccionMedia,
        velMedia: r.velocidadMedia, penal: r.penalizacion
    };
}

// Filas del ranking: reales si hay OSRM (y el destino es alcanzable por calles), si no, del modelo.
function filasRanking(r) {
    const real = r.real && r.real.ok ? r.real : null;
    const filas = [];
    r.filtrados.forEach(x => {
        const nodo = x.idx + 1;
        const rr = real ? real.tablaPorIdx.get(nodo) : null;
        const etaModelo = r.completo.dist[nodo];
        const etaUso = rr ? rr.etaT : etaModelo;
        if (!Number.isFinite(etaUso)) return;
        filas.push({
            idx: x.idx, nodo, h: x.h,
            etaModelo, kmModelo: r.completo.distKm[nodo],
            etaReal: rr ? rr.etaT : null, minLibreReal: rr ? rr.min : null, kmReal: rr ? rr.km : null,
            etaUso, kmUso: rr ? rr.km : r.completo.distKm[nodo],
            abierto: estaAbierto(x.h, etaUso)
        });
    });
    filas.sort((a, b) => a.etaUso - b.etaUso);
    return filas;
}

function filaMetrica(etiqueta, valor) {
    return `<div class="metrica"><span>${etiqueta}</span><b class="valor">${valor}</b></div>`;
}

function fmtMs(valor) {
    return valor < 0.01 ? '&lt; 0.01 ms' : `${valor.toFixed(2)} ms`;
}

function fmtError(modelo, real) {
    if (!Number.isFinite(modelo) || !Number.isFinite(real) || real === 0) return '—';
    const pct = (modelo - real) / real * 100;
    const clase = pct > 0 ? 'delta-pos' : 'delta-neg';
    return `<span class="${clase}">${pct > 0 ? '+' : ''}${pct.toFixed(1)}%</span>`;
}

function renderDashboard(r) {
    const s = resumen(r);
    const real = r.real && r.real.ok ? r.real : null;
    const pct = r.totalNodos > 0 ? (r.explorados / r.totalNodos) * 100 : 0;
    const esDirecta = r.modoRuta === 'directa';
    const etiquetaFuente = real ? 'calles reales (OSRM) × tráfico'
        : (esDirecta ? 'vía directa, sin calles ni tráfico' : 'estimación del modelo');
    let html = `
        <div class="seccion">
            <h3>🧭 Ruta y costo</h3>
            ${filaMetrica('Destino', esc(s.h.nombre))}
            ${filaMetrica('Vía elegida', esDirecta ? '📏 directa (línea recta)' : '🛣️ más rápida por calles')}
            ${filaMetrica('Fuente de los valores', etiquetaFuente)}
            ${filaMetrica(real ? 'Distancia por calles' : (esDirecta ? 'Distancia (línea recta)' : 'Distancia por calles (estimada)'), `${s.km.toFixed(2)} km`)}
            ${filaMetrica('Distancia en línea recta', `${s.recta.toFixed(2)} km`)}
            ${filaMetrica('Sinuosidad (calle / recta)', `×${(s.recta > 0 ? s.km / s.recta : 1).toFixed(2)}`)}
            ${filaMetrica(esDirecta ? 'Tiempo de viaje' : 'ETA con tráfico', `${s.eta.toFixed(1)} min`)}
            ${filaMetrica('Tiempo a flujo libre', `${s.minLibre.toFixed(1)} min`)}
            ${filaMetrica('Velocidad media efectiva', `${s.velMedia.toFixed(1)} km/h`)}
            ${filaMetrica('Fricción media del corredor', `×${s.fricMedia.toFixed(2)}`)}
            ${filaMetrica('Penalización por tráfico', esDirecta ? '—' : `+${s.penal.toFixed(1)}%`)}
            ${filaMetrica('Candidatos con la especialidad', r.candidatos)}
            ${filaMetrica('Precisión de la posición del destino', s.h.verificada ? 'verificada' : `±${fmtMetros(s.h.resolucion_m)}`)}
            ${real && real.snapOrigenM !== null ? filaMetrica('Origen respecto a la calle más cercana', fmtMetros(real.snapOrigenM)) : ''}
        </div>`;

    if (real) {
        const c = real.calib;
        const cambiado = CFG.sinuosidad !== CFG_ORIGINAL.sinuosidad || CFG.velocidadLibreKmh !== CFG_ORIGINAL.velocidadLibreKmh;
        html += `
        <div class="seccion">
            <h3>🎯 Validación del modelo vs. calles reales</h3>
            ${filaMetrica('Distancia: modelo vs. real', `${s.modeloKm.toFixed(2)} vs ${s.km.toFixed(2)} km · ${fmtError(s.modeloKm, s.km)}`)}
            ${filaMetrica('ETA: modelo vs. real', `${s.modeloEta.toFixed(1)} vs ${s.eta.toFixed(1)} min · ${fmtError(s.modeloEta, s.eta)}`)}
            ${filaMetrica(`Sinuosidad observada (mediana de ${c.n})`, `×${Number.isFinite(c.sinuosidad) ? c.sinuosidad.toFixed(2) : '—'} (modelo ×${CFG.sinuosidad.toFixed(2)})`)}
            ${filaMetrica('Velocidad libre observada', `${Number.isFinite(c.velocidad) ? c.velocidad.toFixed(0) : '—'} km/h (modelo ${CFG.velocidadLibreKmh.toFixed(0)})`)}
            <button class="btn-sec" onclick="calibrarModelo()">Calibrar modelo con esta consulta</button>
            ${cambiado ? '<button class="btn-sec" onclick="restaurarModelo()">Restaurar parámetros originales</button>' : ''}
            <div class="nota">El modelo y OSRM comparten el trayecto origen → destino. La calibración ajusta sinuosidad y velocidad libre con la mediana de todos los centros de la consulta (zona local; no es un ajuste global).</div>
        </div>`;
    }

    html += `
        <div class="seccion">
            <h3>⏱️ Rendimiento del algoritmo</h3>
            ${filaMetrica('Tiempo total de la consulta (modelo)', fmtMs(r.tiempoTotal))}
            ${filaMetrica('Grafo base de instalaciones (una vez)', fmtMs(r.tiempoGrafoBase))}
            ${filaMetrica('Enlaces origen → centros', fmtMs(r.tiempoGrafo))}
            ${filaMetrica(`Dijkstra dirigido (poda, media ${CFG.repeticionesBenchmark})`, fmtMs(r.tiempoDirigido))}
            ${filaMetrica(`Dijkstra completo (referencia, media ${CFG.repeticionesBenchmark})`, fmtMs(r.tiempoCompleto))}
            ${filaMetrica('Nodos explorados (poda)', `${r.explorados} / ${r.totalNodos}`)}
            <div class="barra"><span style="width:${pct.toFixed(1)}%"></span></div>
            <div class="nota">${pct.toFixed(1)}% del grafo explorado · la referencia completa visita ${r.exploradosCompleto} nodos.</div>
            ${filaMetrica('Relajaciones de aristas', r.relajaciones)}
            ${filaMetrica('Aristas del grafo', r.aristas)}
            ${filaMetrica('Complejidad temporal', 'O((V+E) log V)')}
            <div class="nota">Tiempos de Dijkstra promediados sobre ${CFG.repeticionesBenchmark} ejecuciones. ${N_INSULARES ? N_INSULARES + ' centros insulares quedan fuera del grafo.' : ''}</div>
        </div>`;
    metricasDiv.innerHTML = html;
}

function renderTabla(r) {
    const filas = filasRanking(r);
    if (filas.length === 0) {
        tablaDistancias.innerHTML = '<div class="nota" style="padding:8px;">No hay instalaciones alcanzables con la especialidad seleccionada.</div>';
        return;
    }
    const destinoNodo = (r.real && r.real.ok) ? r.real.destinoIdx : r.destinoIdx;
    const hayReal = r.real && r.real.ok;
    let html = `<table><thead><tr><th>Instalación</th><th style="text-align:right">ETA${hayReal ? '' : ' ≈'}</th><th style="text-align:right">km${hayReal ? '' : ' ≈'}</th></tr></thead><tbody>`;
    filas.forEach(f => {
        const clase = f.nodo === destinoNodo ? 'fila-destino' : 'fila-hospital';
        const titulo = `Modelo: ${f.etaModelo.toFixed(1)} min · ${f.kmModelo.toFixed(1)} km` +
            (f.etaReal !== null ? ` | Real: ${f.etaReal.toFixed(1)} min · ${f.kmReal.toFixed(1)} km` : '');
        html += `<tr class="${clase}" title="${esc(titulo)}" onclick="seleccionarHospital(${f.idx})">` +
            `<td>${esc(f.h.nombre)}${insignia(f.abierto, 'abre ✓', 'cerrado')}</td>` +
            `<td class="eta">${f.etaUso.toFixed(1)} min</td>` +
            `<td class="km">${f.kmUso.toFixed(1)}</td></tr>`;
    });
    html += '</tbody></table>';
    const insulares = hospitalesFiltrados().filter(x => x.h.insular).length;
    if (insulares) html += `<div class="nota" style="padding:5px 7px;">🚤 ${insulares} centro(s) insular(es) excluido(s): sin ruta terrestre.</div>`;
    tablaDistancias.innerHTML = html;
}

function renderEstado(r) {
    const s = resumen(r);
    const h = s.h;
    const real = r.real && r.real.ok ? r.real : null;
    const suf = real ? '' : (r.modoRuta === 'directa' ? ' (directa)' : ' (est.)');
    let extra = '';
    if (r.avisoHorario) extra += `<div class="linea aviso">⚠ ${esc(r.avisoHorario)}</div>`;
    if (real && real.destinoIdx !== r.destinoIdx) {
        extra += `<div class="linea aviso">⚠ El modelo sugería «${esc(hospitales[r.destinoIdx - 1].nombre)}»; por calles reales conviene este centro.</div>`;
    }
    if (real && real.snapOrigenM !== null && real.snapOrigenM > 300) {
        extra += `<div class="linea aviso">⚠ El origen está a ${fmtMetros(real.snapOrigenM)} de la calle más cercana; la ruta parte desde ese punto.</div>`;
    }
    const trazado = real
        ? 'Trazado real por calles (OSRM), coloreado por la fricción de tráfico.'
        : (r.modoRuta === 'directa' ? 'Vía directa: línea recta desde el origen hasta el centro (sin calles ni tráfico).' : r.caminoNombres.map(esc).join(' → '));
    const pasos = real && real.ruta.pasos && real.ruta.pasos.length
        ? `<details><summary>Indicaciones del recorrido (${real.ruta.pasos.length})</summary>` +
          real.ruta.pasos.slice(0, 14).map(p => `<div class="linea"><span>${p.km.toFixed(2)} km</span><span style="min-width:0;color:#cbd9d4">${esc(p.texto)}</span></div>`).join('') +
          `</details>` : '';
    estadoRuta.innerHTML =
        `<div class="destino-nombre">🏥 ${esc(h.nombre)}${insignia(estaAbierto(h, s.eta), 'abierto al llegar', 'cerrado al llegar')}</div>` +
        extra +
        `<div class="linea"><span>🕒 Horario</span><span style="min-width:0;color:#cbd9d4">${esc(h.horario)}</span></div>` +
        `<div class="linea"><span>🩺 Servicios</span><span style="min-width:0;color:#ffd54f">${esc(h.especialidades)}</span></div>` +
        `<div class="linea"><span>📏 Distancia</span><b>${s.km.toFixed(2)} km${suf}</b></div>` +
        `<div class="linea"><span>⏱️ ${r.modoRuta === 'directa' ? 'Tiempo' : 'ETA'}</span><b>${s.eta.toFixed(1)} min${suf}</b></div>` +
        `<div class="linea"><span>🚦 Tráfico</span><b>${r.modoRuta === 'directa' ? 'no aplica' : '+' + s.penal.toFixed(1) + '%'}</b></div>` +
        `<div class="ruta-texto">${trazado}</div>` + pasos;
}

function renderTodo(r) {
    r.caminoNombres = r.camino.map(i => i === 0 ? r.origen.nombre : hospitales[i - 1].nombre);
    dibujarLineasOrigen(r);
    dibujarSalida(r);
    renderEstado(r);
    renderDashboard(r);
    renderTabla(r);
}

/* =====================================================================
   13. ORIGEN, INTERACCIÓN Y ESTADO DE LA RUTA
   ===================================================================== */
function limpiarRuta() {
    capaLineas.clearLayers();
    capaRuta.clearLayers();
    capaModelo.clearLayers();
    ultimoResultado = null;
    metricasDiv.innerHTML = '<div class="nota">No hay una ruta válida para los filtros y el origen actuales.</div>';
    tablaDistancias.innerHTML = '';
}

function ponerPuntoYCalcular(lat, lon, nombreOrigen) {
    secuencia += 1;
    const seq = secuencia;
    puntoActual = { lat, lng: lon, nombre: nombreOrigen };
    if (selOrigen.value === 'mapa') {
        inputCoords.value = lat.toFixed(5) + ', ' + lon.toFixed(5);
    }
    capaOrigen.clearLayers();
    const marcador = L.circleMarker([lat, lon], {
        radius: 9, fillColor: '#00FFB2', color: '#ffffff', weight: 2, fillOpacity: 1
    }).addTo(capaOrigen);
    marcador.bindTooltip('📍 ' + nombreOrigen, {
        permanent: true, direction: 'top', className: 'etiqueta-origen', offset: [0, -4]
    });

    const r = calcularModelo(lat, lon, nombreOrigen);
    if (!r) {
        limpiarRuta();
        estadoRuta.innerHTML = '<span class="error">No se encontró una ruta hacia una instalación con la especialidad seleccionada. Prueba otra especialidad u origen.</span>';
        return;
    }
    ultimoResultado = r;
    renderTodo(r);
    refinarConOSRM(r, seq);
}

function actualizarCalculo() {
    const nombre = selOrigen.value === 'mapa'
        ? (puntoActual.nombre || 'Persona (Punto X)')
        : hospitales[parseInt(selOrigen.value, 10)].nombre;
    ponerPuntoYCalcular(puntoActual.lat, puntoActual.lng, nombre);
}

// Acepta "9.035, -79.485", "9.035 -79.485", "9.035;-79.485" y también (lon, lat) tipo GeoJSON.
function parsearCoordenadas(texto) {
    const nums = (String(texto).replace(/°/g, ' ').match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
    if (nums.length !== 2 || nums.some(n => !Number.isFinite(n))) return null;
    let [lat, lon] = nums;
    let invertido = false;
    if (Math.abs(lat) > 60 && Math.abs(lon) < 20) { [lat, lon] = [lon, lat]; invertido = true; }
    return { lat, lon, invertido };
}

function irACoordenadas() {
    const c = parsearCoordenadas(inputCoords.value);
    if (!c) {
        mostrarToast('Formato esperado: latitud, longitud (ej. 9.0350, -79.4850)');
        return;
    }
    if (!dentroDeLimites(c.lat, c.lon)) {
        mostrarToast('Esas coordenadas están fuera de la Provincia de Panamá. Revisa latitud y longitud.');
        return;
    }
    if (c.invertido) mostrarToast('Interpreté el orden como (longitud, latitud) y lo corregí.');
    puntoActual.nombre = null;
    ponerPuntoYCalcular(c.lat, c.lon, 'Persona (Punto X)');
}

/* ---- Buscador de lugares: primero el catálogo local; si no hay coincidencias, Nominatim ---- */
let RESULTADOS_LUGARES = [];

function fijarLugarIdx(i, silencioso) {
    const it = RESULTADOS_LUGARES[i];
    if (!it) return;
    selOrigen.value = 'mapa';
    divCoords.style.display = 'block';
    puntoActual.nombre = it.nombre;
    if (!silencioso) {
        document.getElementById('resultadosBusqueda').innerHTML =
            `<span style="color:#00e08a">Origen fijado:</span> ${esc(it.nombre)} (${it.lat.toFixed(4)}, ${it.lon.toFixed(4)})`;
    }
    map.setView([it.lat, it.lon], Math.max(map.getZoom(), 13), { animate: false });
    ponerPuntoYCalcular(it.lat, it.lon, it.nombre);
}

function pintarResultadosLugares(items, mensaje) {
    RESULTADOS_LUGARES = items;
    const div = document.getElementById('resultadosBusqueda');
    if (!items.length) { div.innerHTML = mensaje || 'Sin coincidencias.'; return; }
    div.innerHTML = items.map((it, i) =>
        `<button type="button" class="resultado-busqueda" onclick="fijarLugarIdx(${i})">` +
        `${it.tipo === 'localidad' ? '🏘️' : '🏥'} ${esc(it.nombre)}` +
        `<span style="color:#7f9a90"> · ${it.lat.toFixed(4)}, ${it.lon.toFixed(4)}</span></button>`).join('');
}

async function buscarNominatim(q) {
    const vb = `${CFG.limites.lonMin},${CFG.limites.latMin},${CFG.limites.lonMax},${CFG.limites.latMax}`;
    const url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&countrycodes=pa&accept-language=es' +
        `&viewbox=${vb}&bounded=0&q=${encodeURIComponent(q)}`;
    try {
        const resp = await fetch(url, { headers: { Accept: 'application/json' } });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const datos = await resp.json();
        const items = (datos || []).map(d => ({
            nombre: d.display_name ? d.display_name.split(',')[0] : q,
            detalle: d.display_name || '', lat: parseFloat(d.lat), lon: parseFloat(d.lon), tipo: 'localidad'
        })).filter(d => Number.isFinite(d.lat) && Number.isFinite(d.lon) && dentroDeLimites(d.lat, d.lon));
        pintarResultadosLugares(items, 'Sin coincidencias en la Provincia de Panamá. Prueba otro nombre.');
    } catch (e) {
        pintarResultadosLugares([], 'Sin coincidencias locales y no se pudo consultar OpenStreetMap: ' + e.message);
    }
}

function buscarLugar() {
    const q = normalizarClave(document.getElementById('buscarLugar').value);
    if (q.length < 2) { mostrarToast('Escribe al menos 2 letras para buscar.'); return; }
    const local = LUGARES.filter(l => normalizarClave(l.nombre).includes(q)).slice(0, 8);
    if (local.length) {
        pintarResultadosLugares(local);
        fijarLugarIdx(0, true);   // el botón dice «Buscar y fijar origen»: fija la primera coincidencia
        return;
    }
    document.getElementById('resultadosBusqueda').textContent = 'Buscando en OpenStreetMap…';
    buscarNominatim(document.getElementById('buscarLugar').value);
}

function limpiarBusqueda() {
    document.getElementById('buscarLugar').value = '';
    document.getElementById('resultadosBusqueda').innerHTML = '';
    RESULTADOS_LUGARES = [];
}

function usarMiUbicacion() {
    if (!navigator.geolocation) {
        mostrarToast('Tu navegador no ofrece geolocalización.');
        return;
    }
    mostrarToast('Buscando tu ubicación…');
    navigator.geolocation.getCurrentPosition(pos => {
        const { latitude: lat, longitude: lon } = pos.coords;
        if (!dentroDeLimites(lat, lon)) {
            mostrarToast('Tu ubicación está fuera de la Provincia de Panamá; se mantiene el origen actual.');
            return;
        }
        selOrigen.value = 'mapa';
        divCoords.style.display = 'block';
        puntoActual.nombre = 'Mi ubicación';
        ponerPuntoYCalcular(lat, lon, 'Mi ubicación');
        map.setView([lat, lon], Math.max(map.getZoom(), 13));
    }, err => {
        mostrarToast(err && err.code === 1 ? 'Permiso de ubicación denegado.' : 'No se pudo obtener tu ubicación.');
    }, { enableHighAccuracy: true, timeout: 9000, maximumAge: 30000 });
}

function cambiarOrigen() {
    if (selOrigen.value === 'mapa') {
        divCoords.style.display = 'block';
        puntoActual.nombre = null;
        ponerPuntoYCalcular(puntoActual.lat, puntoActual.lng, 'Persona (Punto X)');
    } else {
        divCoords.style.display = 'none';
        const h = hospitales[parseInt(selOrigen.value, 10)];
        if (h) ponerPuntoYCalcular(h.lat, h.lon, h.nombre);
    }
}

/* =====================================================================
   14. CALIBRACIÓN DEL MODELO CON RUTAS REALES
   ===================================================================== */
function calibrarModelo() {
    const r = ultimoResultado;
    if (!r || !r.real || !r.real.ok || r.real.calib.n < 5 ||
        !Number.isFinite(r.real.calib.sinuosidad) || !Number.isFinite(r.real.calib.velocidad)) {
        mostrarToast('Se necesita una consulta con rutas reales y al menos 5 centros a más de 1 km.');
        return;
    }
    CFG.sinuosidad = clamp(Math.round(r.real.calib.sinuosidad * 100) / 100, 1.0, 2.5);
    CFG.velocidadLibreKmh = clamp(Math.round(r.real.calib.velocidad), 15, 110);
    construirGrafoBase();
    dibujarRedBase();
    mostrarToast(`Modelo calibrado: sinuosidad ×${CFG.sinuosidad.toFixed(2)}, ${CFG.velocidadLibreKmh} km/h a flujo libre.`);
    actualizarCalculo();
}
function restaurarModelo() {
    CFG.sinuosidad = CFG_ORIGINAL.sinuosidad;
    CFG.velocidadLibreKmh = CFG_ORIGINAL.velocidadLibreKmh;
    construirGrafoBase();
    dibujarRedBase();
    mostrarToast('Parámetros del modelo restaurados.');
    actualizarCalculo();
}

/* =====================================================================
   15. CAPA DE COBERTURA Y DESIERTOS DE ATENCIÓN
   ===================================================================== */
function colorComplejidad(n) {
    const hue = 190 - 190 * n; // cian (baja complejidad) -> rojo (alta)
    return `hsl(${hue.toFixed(0)}, 92%, 55%)`;
}

function textoCriterioCobertura() {
    return CFG.modoCobertura === 'tiempo' ? `tiempo estimado ≤ ${CFG.umbralCoberturaMin} min` : `radio ${CFG.radioCoberturaKm} km`;
}

function cambiarCriterioCobertura() {
    const v = selCobertura.value;
    if (v === 'radio') {
        CFG.modoCobertura = 'radio';
    } else {
        CFG.modoCobertura = 'tiempo';
        CFG.umbralCoberturaMin = parseInt(v.slice(1), 10);
    }
    document.getElementById('leyendaCobertura').textContent = textoCriterioCobertura();
    if (coberturaActiva) actualizarCobertura();
}

// ETA del modelo desde un punto cualquiera hasta una instalación (misma fórmula que las aristas).
function etaModeloPunto(lat, lon, h, dRecta) {
    const fric = ES_DIRECTA() ? 1 : friccionSegmento(lat, lon, h.lat, h.lon, dRecta);
    return crearArista(dRecta, fric, sinuosidadEfectiva(), velocidadEfectiva()).etaMin;
}

function analizarCobertura(filtrados) {
    const A = CFG.areaAnalisis;
    const tiempo = CFG.modoCobertura === 'tiempo';
    // Radio máximo en el que puede haber cobertura (la fricción solo alarga el tiempo: f ≥ 1).
    const dMax = tiempo
        ? (velocidadEfectiva() * CFG.umbralCoberturaMin / 60) / sinuosidadEfectiva()
        : CFG.radioCoberturaKm;
    let total = 0;
    let cubiertas = 0;
    let desiertos = 0;
    let mar = 0;
    const celdasDesierto = [];
    for (let lat = A.latMin; lat <= A.latMax + 1e-9; lat += A.paso) {
        for (let lon = A.lonMin; lon <= A.lonMax + 1e-9; lon += A.paso) {
            if (!esTierra(lat, lon)) { mar += 1; continue; } // el mar no es un "desierto de atención"
            total += 1;
            let cubierta = false;
            for (const x of filtrados) {
                const d = haversine(lat, lon, x.h.lat, x.h.lon);
                if (d > dMax) continue;
                if (!tiempo || etaModeloPunto(lat, lon, x.h, d) <= CFG.umbralCoberturaMin) { cubierta = true; break; }
            }
            if (cubierta) cubiertas += 1;
            else { desiertos += 1; celdasDesierto.push([lat, lon]); }
        }
    }
    return { total, cubiertas, desiertos, mar, celdasDesierto, pct: total ? cubiertas / total * 100 : 0 };
}

function actualizarCobertura() {
    capaCobertura.clearLayers();
    const filtrados = candidatosTerrestres();
    if (!map.hasLayer(capaCobertura)) capaCobertura.addTo(map);

    if (CFG.modoCobertura === 'radio') {
        filtrados.forEach(x => {
            const complejidad = Math.min(listaEspecialidades(x.h).length / 12, 1);
            const color = colorComplejidad(complejidad);
            L.circle([x.h.lat, x.h.lon], {
                radius: CFG.radioCoberturaKm * 1000,
                color, weight: 1, opacity: 0.6,
                fillColor: color, fillOpacity: 0.06, interactive: false
            }).addTo(capaCobertura);
            L.circle([x.h.lat, x.h.lon], {
                radius: CFG.radioCoberturaKm * 500,
                color, weight: 0, opacity: 0,
                fillColor: color, fillOpacity: 0.10, interactive: false
            }).addTo(capaCobertura);
        });
    }

    const analisis = analizarCobertura(filtrados);
    analisis.celdasDesierto.slice(0, 700).forEach(([lat, lon]) => {
        L.rectangle([
            [lat - CFG.areaAnalisis.paso / 2, lon - CFG.areaAnalisis.paso / 2],
            [lat + CFG.areaAnalisis.paso / 2, lon + CFG.areaAnalisis.paso / 2]
        ], {
            color: '#FF5252', weight: 0, fillColor: '#FF5252',
            fillOpacity: 0.10, interactive: false
        }).addTo(capaCobertura);
    });

    coberturaStatsDiv.innerHTML = `
        <div class="seccion">
            <h3>🌡️ Cobertura territorial (${esc(textoCriterioCobertura())})</h3>
            ${filaMetrica('Instalaciones terrestres con la especialidad', filtrados.length)}
            ${filaMetrica('Área terrestre cubierta (aprox.)', `${analisis.pct.toFixed(1)}%`)}
            ${filaMetrica('Celdas terrestres sin cobertura', `${analisis.desiertos} / ${analisis.total}`)}
            ${filaMetrica('Celdas de mar excluidas', analisis.mar)}
            ${filaMetrica('Especialidad filtrada', esc(etiquetaEspecialidad()))}
            <div class="nota">Malla de ${(CFG.areaAnalisis.paso * 111).toFixed(1)} km. Una celda es "desierto" si su centro no cumple el criterio (${esc(textoCriterioCobertura())}) respecto de ninguna instalación terrestre con la especialidad. Es cobertura del territorio, no de la población: no se descuentan zonas despobladas (bosque, Canal).</div>
        </div>`;
}

function toggleCobertura() {
    coberturaActiva = !coberturaActiva;
    btnCobertura.textContent = coberturaActiva ? 'Ocultar Cobertura' : 'Mostrar Cobertura';
    btnCobertura.classList.toggle('activo', coberturaActiva);
    if (coberturaActiva) {
        actualizarCobertura();
    } else {
        map.removeLayer(capaCobertura);
        capaCobertura.clearLayers();
        coberturaStatsDiv.innerHTML = '<div class="nota" style="margin-top:8px;">Capa de cobertura desactivada. Actívala para estimar desiertos de atención.</div>';
    }
}

/* =====================================================================
   16. EXPORTACIÓN Y METODOLOGÍA
   ===================================================================== */
function descargar(nombre, contenido, tipo) {
    const blob = new Blob([contenido], { type: tipo });
    const enlace = document.createElement('a');
    enlace.href = URL.createObjectURL(blob);
    enlace.download = nombre;
    document.body.appendChild(enlace);
    enlace.click();
    document.body.removeChild(enlace);
    setTimeout(() => URL.revokeObjectURL(enlace.href), 1000);
}

function exportarJSON() {
    if (!ultimoResultado) {
        mostrarToast('Calcula una ruta antes de exportar los resultados.');
        return;
    }
    const r = ultimoResultado;
    const s = resumen(r);
    const real = r.real && r.real.ok ? r.real : null;
    const datos = {
        generado: r.generado,
        configuracion: CFG,
        origen: r.origen,
        destino: {
            nombre: s.h.nombre, lat: s.h.lat, lon: s.h.lon,
            especialidades: s.h.especialidades, horario: s.h.horario,
            posicion_verificada: !!s.h.verificada, resolucion_posicion_m: s.h.resolucion_m
        },
        especialidad_filtrada: r.especialidad,
        via: r.modoRuta,
        fuente_valores: s.fuente,
        ruta_modelo: r.camino.map(i => i === 0 ? r.origen.nombre : hospitales[i - 1].nombre),
        resultado: {
            distancia_calles_km: Number(s.km.toFixed(3)),
            distancia_recta_km: Number(s.recta.toFixed(3)),
            eta_min: Number(s.eta.toFixed(3)),
            tiempo_flujo_libre_min: Number(s.minLibre.toFixed(3)),
            velocidad_media_kmh: Number(s.velMedia.toFixed(2)),
            friccion_media: Number(s.fricMedia.toFixed(3)),
            penalizacion_trafico_pct: Number(s.penal.toFixed(2))
        },
        modelo: {
            distancia_km: Number(s.modeloKm.toFixed(3)),
            eta_min: Number(s.modeloEta.toFixed(3)),
            sinuosidad: CFG.sinuosidad,
            velocidad_libre_kmh: CFG.velocidadLibreKmh
        },
        osrm: real ? {
            url: CFG.osrm.url, distancia_km: Number(real.ruta.km.toFixed(3)),
            duracion_libre_min: Number(real.ruta.min.toFixed(3)),
            origen_a_calle_m: real.snapOrigenM,
            sinuosidad_observada: real.calib.sinuosidad, velocidad_observada_kmh: real.calib.velocidad,
            centros_usados_en_calibracion: real.calib.n
        } : { disponible: false, motivo: r.real ? r.real.error : 'no consultado' },
        metricas: {
            repeticiones_benchmark: CFG.repeticionesBenchmark,
            tiempo_total_ms: Number(r.tiempoTotal.toFixed(3)),
            tiempo_grafo_base_ms: Number(r.tiempoGrafoBase.toFixed(3)),
            tiempo_enlaces_origen_ms: Number(r.tiempoGrafo.toFixed(3)),
            tiempo_dijkstra_dirigido_ms: Number(r.tiempoDirigido.toFixed(3)),
            tiempo_dijkstra_completo_ms: Number(r.tiempoCompleto.toFixed(3)),
            nodos_explorados_poda: r.explorados,
            nodos_explorados_referencia: r.exploradosCompleto,
            nodos_totales: r.totalNodos,
            relajaciones: r.relajaciones,
            aristas: r.aristas,
            candidatos_especialidad: r.candidatos
        }
    };
    descargar('resultado_ruta_salud.json', JSON.stringify(datos, null, 2), 'application/json');
    mostrarToast('Resultados exportados como JSON.');
}

function celdaCSV(v) {
    const t = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
}
function exportarCSV() {
    if (!ultimoResultado) {
        mostrarToast('Calcula una ruta antes de exportar el ranking.');
        return;
    }
    const f2 = v => (v === null || v === undefined || !Number.isFinite(v)) ? '' : v.toFixed(2);
    const cab = ['nombre', 'lat', 'lon', 'eta_usada_min', 'km_usados', 'eta_modelo_min', 'km_modelo',
        'eta_real_min', 'km_real', 'abierto_a_la_llegada', 'posicion_verificada', 'resolucion_posicion_m'];
    const lineas = [cab.join(',')];
    filasRanking(ultimoResultado).forEach(f => {
        lineas.push([f.h.nombre, f.h.lat, f.h.lon, f2(f.etaUso), f2(f.kmUso), f2(f.etaModelo), f2(f.kmModelo),
            f2(f.etaReal), f2(f.kmReal), f.abierto === null ? '' : (f.abierto ? 'si' : 'no'),
            f.h.verificada ? 'si' : 'no', f.h.resolucion_m].map(celdaCSV).join(','));
    });
    descargar('ranking_acceso_salud.csv', '\ufeff' + lineas.join('\n'), 'text/csv;charset=utf-8');
    mostrarToast('Ranking exportado como CSV.');
}

function exportarGeoJSON() {
    if (!ultimoResultado) {
        mostrarToast('Calcula una ruta antes de exportar la ruta.');
        return;
    }
    const r = ultimoResultado;
    const s = resumen(r);
    const real = r.real && r.real.ok ? r.real : null;
    const coords = real
        ? real.ruta.geom.map(p => [p[1], p[0]])
        : r.camino.map(i => [r.nodos[i].lon, r.nodos[i].lat]);
    const gj = {
        type: 'FeatureCollection',
        features: [
            { type: 'Feature', geometry: { type: 'LineString', coordinates: coords },
              properties: { tipo: 'ruta', fuente: s.fuente, distancia_km: Number(s.km.toFixed(3)), eta_min: Number(s.eta.toFixed(2)) } },
            { type: 'Feature', geometry: { type: 'Point', coordinates: [r.origen.lon, r.origen.lat] },
              properties: { tipo: 'origen', nombre: r.origen.nombre } },
            { type: 'Feature', geometry: { type: 'Point', coordinates: [s.h.lon, s.h.lat] },
              properties: { tipo: 'destino', nombre: s.h.nombre, horario: s.h.horario } }
        ]
    };
    descargar('ruta_salud.geojson', JSON.stringify(gj), 'application/geo+json');
    mostrarToast('Ruta exportada como GeoJSON.');
}

function construirMetodologia() {
    document.getElementById('metodologia').innerHTML = `
        <p><b>Grafo:</b> ${IDX_TERRESTRES.length + 1} nodos por consulta (origen + instalaciones terrestres). Entre instalaciones se usa k=${CFG.kVecinos} vecinos más cercanos más un árbol de expansión mínima (MST), que garantiza que ningún centro quede aislado. En la vía por calles el origen entra por sus ${CFG.kOrigen} centros más cercanos; en la vía directa se enlaza en línea recta con el destino. Los ${N_INSULARES} centros insulares quedan fuera.</p>
        <p><b>Costo:</b> ETA = d<sub>recta</sub> · s · f · 60 / v, con s = sinuosidad vial (×${CFG.sinuosidad.toFixed(2)}), v = ${CFG.velocidadLibreKmh} km/h a flujo libre y f = fricción media del tramo (${ZONAS_FRICCION.length} núcleos gaussianos). La <b>vía directa</b> usa s = 1, f = 1 y v = ${CFG.velocidadDirectaKmh} km/h: es la cota inferior teórica.</p>
        <p><b>Las dos vías:</b> «1 · Vía directa» dibuja una sola línea recta origen → hospital y no consulta calles. «2 · Vía por calles» busca el camino más rápido con Dijkstra sobre la red y luego lo sustituye por el trazado real de OSRM, ponderado por tráfico. En ambos casos se dibuja <b>solo la ruta elegida</b>; nunca un abanico de líneas a todos los centros.</p>
        <p><b>Búsqueda:</b> Dijkstra con heap binario O((V+E) log V). Todos los centros terrestres actúan como nodos de paso; el filtro de especialidad y el de horario solo afectan al conjunto de destinos.</p>
        <p><b>Rutas reales:</b> OSRM (${esc(CFG.osrm.url)}) entrega distancia, duración y trazado por calles. Se pondera su duración por la fricción del tráfico a lo largo del trazado. Si el servicio falla, el sistema usa el modelo. Los valores del modelo se comparan con los reales y pueden calibrarse.</p>
        <p><b>Cobertura:</b> malla de ${(CFG.areaAnalisis.paso * 111).toFixed(1)} km sobre tierra firme (costa aproximada); criterio por radio o por tiempo estimado.</p>
        <p><b>Datos:</b> ${hospitales.length} registros; ${hospitales.filter(h => h.verificada).length} con posición verificada (OpenStreetMap o edición manual). Las demás son aproximadas (borde discontinuo en el mapa). El tráfico es un modelo sintético, no datos en vivo. Uso académico; no reemplaza registros oficiales del MINSA/CSS ni sirve para decisiones clínicas.</p>`;
}

/* =====================================================================
   16b. MODO DE RUTA, LÍNEAS DEL ORIGEN, EDICIÓN DE POSICIONES E INFORME PDF
   ===================================================================== */
const NOTAS_MODO = {
    directa: `Vía 1 · directa: une el origen con el hospital en línea recta, a ${CFG.velocidadDirectaKmh} km/h y sin tráfico. Sirve como la opción más rápida posible (o para traslado aéreo).`,
    calles: 'Vía 2 · por calles: ruta real (OSRM) siguiendo las calles del país, ponderada por el tráfico. Si OSRM no responde, se usa la estimación del modelo.'
};

function actualizarBotonesModo() {
    document.getElementById('btnModoCalles').classList.toggle('activo', MODO === 'calles');
    document.getElementById('btnModoDirecta').classList.toggle('activo', MODO === 'directa');
    document.getElementById('notaModo').textContent = NOTAS_MODO[MODO];
    chkOSRM.disabled = MODO === 'directa';
    map.removeLayer(capaLineas);
    capaLineas.clearLayers();
    toggleRed();
}

function cambiarModoRuta(modo) {
    if ((modo !== 'calles' && modo !== 'directa') || modo === MODO) return;
    MODO = modo;
    CFG.modoRuta = modo;
    actualizarBotonesModo();
    if (coberturaActiva) actualizarCobertura();
    actualizarCalculo();
}

// Compara, para el MISMO hospital, el tiempo por vía directa y por calles (modelo).
function compararVias() {
    if (!ultimoResultado) { mostrarToast('Primero selecciona un origen y calcula una ruta.'); return; }
    const r = ultimoResultado;
    const idx = (r.real && r.real.ok) ? r.real.destinoIdx - 1 : r.destinoIdx - 1;
    const destinoPrevio = selDestino.value;
    const modoPrevio = MODO;
    const valores = {};
    try {
        selDestino.value = String(idx);
        for (const m of ['directa', 'calles']) {
            MODO = m;
            const rm = calcularModelo(r.origen.lat, r.origen.lon, r.origen.nombre);
            if (rm) valores[m] = rm;
        }
    } finally {
        MODO = modoPrevio;
        selDestino.value = destinoPrevio;
    }
    const div = document.getElementById('comparacionVias');
    if (!valores.directa || !valores.calles) { div.innerHTML = '<span class="error">No se pudo comparar: falta ruta en alguna vía.</span>'; return; }
    const d = valores.directa, c = valores.calles;
    const difMin = c.eta - d.eta;
    const difKm = c.distKm - d.distKm;
    div.innerHTML =
        `<b>${esc(hospitales[idx].nombre)}</b><br>` +
        `1 · directa: ${d.distKm.toFixed(2)} km · ${d.eta.toFixed(1)} min<br>` +
        `2 · calles (modelo): ${c.distKm.toFixed(2)} km · ${c.eta.toFixed(1)} min<br>` +
        `<span style="color:#ffd54f">La vía por calles suma ${difKm >= 0 ? '+' : ''}${difKm.toFixed(2)} km y ` +
        `${difMin >= 0 ? '+' : ''}${difMin.toFixed(1)} min.</span>`;
}

// La única línea que se dibuja es la ruta elegida (en capaRuta). Se conserva esta función
// para no romper llamadas antiguas, pero ya no dibuja abanicos origen -> todos los centros.
function dibujarLineasOrigen(r) {
    capaLineas.clearLayers();
}
function toggleLineas() {
    capaLineas.clearLayers();
}

/* ---- Edición de posiciones: arrastrar marcadores y guardar correcciones ---- */
let EDITANDO = false;
const EDICIONES = new Map(); // idx -> posición y estado originales

function toggleEdicion() {
    EDITANDO = chkEditar.checked;
    if (EDITANDO) {
        map.addLayer(capaEdicion);
        mostrarToast('Modo edición: arrastra un marcador a su posición correcta (compáralo con el mapa base).');
    } else {
        map.removeLayer(capaEdicion);
    }
    renderHospitales();
    actualizarPanelEdicion();
}

function moverHospital(idx, ll) {
    const h = hospitales[idx];
    const lat = Math.round(ll.lat * 1e6) / 1e6;
    const lon = Math.round(ll.lng * 1e6) / 1e6;
    if (!dentroDeLimites(lat, lon) || (!h.insular && lat < latCosta(lon) - 0.006)) {
        mostrarToast('Esa posición cae fuera de la provincia o en el mar; se restauró la anterior.');
        renderHospitales();
        return;
    }
    if (!EDICIONES.has(idx)) {
        EDICIONES.set(idx, { lat0: h.lat, lon0: h.lon, ver0: h.verificada, fuente0: h.fuente, res0: h.resolucion_m });
    }
    h.lat = lat; h.lon = lon; h.verificada = true; h.fuente = 'edición manual en el mapa'; h.resolucion_m = 10;
    aplicarCambioPosiciones();
}

function aplicarCambioPosiciones() {
    construirGrafoBase();
    dibujarRedBase();
    renderHospitales();
    actualizarPanelEdicion();
    if (coberturaActiva) actualizarCobertura();
    actualizarCalculo();
}

function deshacerEdiciones() {
    EDICIONES.forEach((o, idx) => {
        const h = hospitales[idx];
        h.lat = o.lat0; h.lon = o.lon0; h.verificada = o.ver0; h.fuente = o.fuente0; h.resolucion_m = o.res0;
    });
    EDICIONES.clear();
    aplicarCambioPosiciones();
}

function correccionesPendientes() {
    const salida = {};
    EDICIONES.forEach((o, idx) => {
        const h = hospitales[idx];
        const m = haversine(o.lat0, o.lon0, h.lat, h.lon) * 1000;
        salida[h.nombre] = {
            lat: h.lat, lon: h.lon, verificada: true, fuente: 'edición manual en el mapa',
            nota: `movida ${Math.round(m)} m desde la posición original`
        };
    });
    return salida;
}

function descargarCorrecciones() {
    if (!EDICIONES.size) { mostrarToast('No hay posiciones editadas.'); return; }
    descargar('correcciones_coordenadas.json', JSON.stringify(correccionesPendientes(), null, 2), 'application/json');
}

async function guardarCorrecciones() {
    const datos = correccionesPendientes();
    if (!Object.keys(datos).length) { mostrarToast('No hay posiciones editadas.'); return; }
    if (!TOKEN) {
        descargarCorrecciones();
        mostrarToast('Sin servidor local: se descargó el JSON; cópialo junto al script.');
        return;
    }
    try {
        const resp = await fetch('/correcciones', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN }, body: JSON.stringify(datos)
        });
        const j = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(j.error || ('HTTP ' + resp.status));
        mostrarToast(`Guardado en ${j.archivo}: ${j.guardadas} posición(es)` +
            (j.rechazadas && j.rechazadas.length ? ` · ${j.rechazadas.length} rechazada(s)` : '') + '.');
    } catch (e) {
        mostrarToast('No se pudo guardar: ' + e.message + ' · usa «⬇ JSON».');
    }
}

function actualizarPanelEdicion() {
    if (!EDITANDO && EDICIONES.size === 0) { panelEdicion.style.display = 'none'; panelEdicion.innerHTML = ''; return; }
    let lista = '';
    EDICIONES.forEach((o, idx) => {
        const h = hospitales[idx];
        const m = Math.round(haversine(o.lat0, o.lon0, h.lat, h.lon) * 1000);
        lista += `<div>• ${esc(h.nombre)} <span style="color:#b59c62">(${m} m)</span></div>`;
    });
    panelEdicion.style.display = 'block';
    panelEdicion.innerHTML =
        `<b>✏️ Edición de posiciones</b>${EDITANDO ? '' : ' (pausada)'}` +
        `<div class="nota" style="color:#caa95b">Arrastra los marcadores a su sitio correcto; el cálculo se actualiza al instante. «Guardar» los escribe en correcciones_coordenadas.json y se aplicarán en cada arranque.</div>` +
        `<div id="listaEdicion">${lista || '<i>Sin cambios todavía.</i>'}</div>` +
        `<div class="fila-botones3"><button class="btn-sec" onclick="guardarCorrecciones()">💾 Guardar</button>` +
        `<button class="btn-sec" onclick="descargarCorrecciones()">⬇ JSON</button>` +
        `<button class="btn-sec" onclick="deshacerEdiciones()">↩ Deshacer</button></div>`;
}

/* ---- Informe PDF: lo genera la función exportar_pdf_ranking() del script de Python ---- */
function construirPayloadPDF(r) {
    const s = resumen(r);
    const filas = filasRanking(r).slice(0, 40).map(f => ({
        nombre: f.h.nombre, lat: f.h.lat, lon: f.h.lon, eta: f.etaUso, km: f.kmUso,
        recta_km: haversine(r.origen.lat, r.origen.lon, f.h.lat, f.h.lon),
        abierto: f.abierto, horario: f.h.horario
    }));
    return {
        origen: { lat: r.origen.lat, lon: r.origen.lon, nombre: r.origen.nombre },
        especialidad: r.especialidad, modo: MODO, fuente: s.fuente,
        cfg: { sinuosidad: sinuosidadEfectiva(), velocidad: velocidadEfectiva() },
        velocidad_directa: CFG.velocidadDirectaKmh,
        destino: {
            nombre: s.h.nombre, horario: s.h.horario, especialidades: s.h.especialidades,
            km: s.km, eta: s.eta, recta_km: s.recta, penal_pct: s.penal, min_libre: s.minLibre,
            abierto: estaAbierto(s.h, s.eta)
        },
        filas
    };
}

async function exportarPDF() {
    if (!ultimoResultado) { mostrarToast('Calcula una ruta antes de exportar el informe.'); return; }
    if (!TOKEN) {
        mostrarToast('El PDF lo genera el script de Python: abre el mapa desde el servidor local (no el .html suelto).');
        return;
    }
    // NUEVO: sin reportlab el informe sale en texto plano y sin croquis; se avisa antes de generarlo.
    if (!REPORTLAB_INSTALADO) {
        mostrarToast('Generando PDF en texto plano (reportlab no instalado. Croquis omitido)');
    }
    try {
        const resp = await fetch('/pdf', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN },
            body: JSON.stringify(construirPayloadPDF(ultimoResultado))
        });
        if (!resp.ok) {
            const j = await resp.json().catch(() => ({}));
            throw new Error(j.error || ('HTTP ' + resp.status));
        }
        descargar('informe_ruta_salud.pdf', await resp.blob(), 'application/pdf');
        // NUEVO: sin reportlab se conserva el aviso en pantalla en vez de pisarlo con el mensaje de éxito.
        if (REPORTLAB_INSTALADO) mostrarToast('Informe PDF generado.');
    } catch (e) {
        mostrarToast('No se pudo generar el PDF: ' + e.message);
    }
}

// NUEVO: diagnóstico de coordenadas vía POST /validar_coordenadas (sustituye mirar la terminal).
async function analizarCoordenadas() {
    const cont = document.getElementById('notasCoordenadas');
    const btn = document.getElementById('btnCoords');
    if (!TOKEN) {
        mostrarToast('El análisis lo ejecuta el script de Python: abre el mapa desde el servidor local (no el .html suelto).');
        return;
    }
    btn.disabled = true;
    cont.innerHTML = '<div class="nota">Analizando coordenadas…</div>';
    try {
        const resp = await fetch('/validar_coordenadas', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN },
            body: '{}'
        });
        const j = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(j.error || ('HTTP ' + resp.status));
        const estilo = {
            error: { icono: '✖', color: '#ff7b6b', titulo: 'Errores' },
            aviso: { icono: '⚠', color: '#ffd54f', titulo: 'Avisos' },
            info:  { icono: '·', color: '#8fa89f', titulo: 'Solapamientos / observaciones' }
        };
        const grupo = nivel => (j.hallazgos || []).filter(h => h.nivel === nivel).map(h =>
            `<div style="margin:3px 0;color:${estilo[nivel].color}">${estilo[nivel].icono} <b>${esc(h.nombre)}</b>: ${esc(h.msg)}</div>`
        ).join('');
        let html = `<div style="margin-top:8px;padding:6px 8px;border:1px solid #355248;border-radius:6px;">` +
            `<b>Diagnóstico de ${j.instalaciones} instalaciones:</b> ` +
            `<span style="color:${estilo.error.color}">${j.errores} errores</span> · ` +
            `<span style="color:${estilo.aviso.color}">${j.avisos} avisos</span> · ` +
            `<span style="color:${estilo.info.color}">${j.info} observaciones</span>`;
        if (!j.hallazgos || !j.hallazgos.length) {
            html += `<div style="margin-top:4px;color:#00e676">✔ Sin hallazgos.</div>`;
        }
        for (const nivel of ['error', 'aviso']) {
            if (j[nivel === 'error' ? 'errores' : 'avisos']) {
                html += `<div style="margin-top:6px;"><b>${estilo[nivel].titulo}</b>${grupo(nivel)}</div>`;
            }
        }
        if (j.info) {
            html += `<details style="margin-top:6px;"><summary>${estilo.info.titulo} (${j.info})</summary>${grupo('info')}</details>`;
        }
        cont.innerHTML = html + '</div>';
    } catch (e) {
        cont.innerHTML = '';
        mostrarToast('No se pudo analizar el dataset: ' + e.message);
    } finally {
        btn.disabled = false;
    }
}

/* =====================================================================
   17. LABORATORIO OPTATIVO · cada botón es un experimento independiente
   ===================================================================== */
const capaLaboratorio = L.layerGroup().addTo(map);
const capaDestinoLaboratorio = L.layerGroup().addTo(map);
let seleccionandoDestinoLab = false;
let ultimoLaboratorio = null;

function activarDestinoLab() {
    seleccionandoDestinoLab = true;
    document.getElementById('panelLaboratorio').open = true;
    mostrarToast('Ahora haz clic en el mapa para fijar el DESTINO libre del experimento.');
}
function borrarDestinoLab() {
    seleccionandoDestinoLab = false;
    document.getElementById('labDestinoCoords').value = '';
    capaDestinoLaboratorio.clearLayers();
    mostrarToast('Destino libre borrado: se usará el hospital elegido arriba.');
}
function marcarDestinoLab(lat, lon) {
    document.getElementById('labDestinoCoords').value = lat.toFixed(6) + ', ' + lon.toFixed(6);
    capaDestinoLaboratorio.clearLayers();
    L.circleMarker([lat,lon], {radius:9, color:'#ffd54f', fillColor:'#ff7043',
        fillOpacity:1, weight:3}).bindTooltip('Destino libre del laboratorio')
        .addTo(capaDestinoLaboratorio);
    seleccionandoDestinoLab = false;
}
let labEjecutando = false;

function limpiarLaboratorio() {
    capaLaboratorio.clearLayers();
    document.getElementById('labResultados').innerHTML =
        '<span class="nota">Sin resultados. Selecciona un experimento y pulsa su botón.</span>';
    ultimoLaboratorio = null;
}
function labValor(x) {
    if (x === null || x === undefined) return '—';
    if (typeof x === 'boolean') return x ? 'Sí' : 'No';
    if (typeof x === 'object') return esc(JSON.stringify(x));
    return esc(String(x));
}
function pintarLaboratorio(j) {
    const div = document.getElementById('labResultados');
    const columnas = j.filas && j.filas.length ? Object.keys(j.filas[0]) : [];
    let html = `<h4 style="margin:3px 0;color:#00e08a">${esc(j.titulo || 'Experimento')}</h4>` +
        `<div class="nota"><b>Fuente:</b> ${esc(j.fuente || '—')}</div>`;
    if (j.metadatos) html += `<div class="lab-meta">${Object.entries(j.metadatos).map(([k,v]) =>
        `<span>${esc(k.replaceAll('_', ' '))}: <b>${labValor(v)}</b></span>`).join('')}</div>`;
    if (j.advertencia) html += `<div class="lab-warning">⚠ ${esc(j.advertencia)}</div>`;
    if (columnas.length) {
        html += `<div class="lab-tabla-scroll"><table class="lab-tabla"><thead><tr>${columnas.map(x =>
            `<th>${esc(x.replaceAll('_', ' '))}</th>`).join('')}</tr></thead><tbody>`;
        for (const fila of j.filas) {
            html += `<tr>${columnas.map(x => `<td>${labValor(fila[x])}</td>`).join('')}</tr>`;
        }
        html += '</tbody></table></div>';
    }
    if (j.experimento === 'escalabilidad' && j.filas?.length) {
        const max = Math.max(...j.filas.map(f => f.dijkstra_ms), .0001);
        html += '<div class="lab-barras"><b>Tiempo relativo de Dijkstra</b>';
        for (const f of j.filas) {
            html += `<div class="lab-barra-fila"><span>${f.vertices.toLocaleString('es-PA')} nodos</span>` +
                `<div class="lab-barra-pista"><div style="width:${Math.max(1, 100*f.dijkstra_ms/max)}%"></div></div>` +
                `<span>${f.dijkstra_ms} ms</span></div>`;
        }
        html += '</div>';
    }
    html += `<p class="nota" style="margin-top:8px">${esc(j.nota || '')}</p>`;
    div.innerHTML = html;
    capaLaboratorio.clearLayers();
    const colores = ['#00E676', '#00BFFF', '#FFC107', '#FF7043'];
    const limites = [];
    for (const [i, ruta] of (j.rutas || []).entries()) {
        if (!Array.isArray(ruta.puntos) || ruta.puntos.length < 2) continue;
        const linea = L.polyline(ruta.puntos, {
            color: colores[i % colores.length], weight: 5, opacity: .9,
            dashArray: i === 0 ? null : '8 5'
        }).addTo(capaLaboratorio).bindTooltip(ruta.etiqueta || 'Ruta');
        limites.push(linea.getBounds());
    }
    for (const cierre of (j.cierres || [])) {
        L.polyline(cierre, { color: '#ff1744', weight: 9, opacity: .95 })
            .bindTooltip('Calle bloqueada (simulación)').addTo(capaLaboratorio);
    }
    if (limites.length) {
        let b = limites[0];
        for (let i = 1; i < limites.length; i++) b = b.extend(limites[i]);
        map.fitBounds(b.pad(.17), { maxZoom: 16 });
    }
}
async function ejecutarLaboratorio(accion) {
    if (labEjecutando) return;
    if (!TOKEN) {
        mostrarToast('Abre el .py como servidor local. El HTML independiente no ejecuta experimentos.');
        return;
    }
    let destino = null;
    if (ultimoResultado) {
        if (/^\d+$/.test(selDestino.value)) destino = Number(selDestino.value);
        else destino = (ultimoResultado.real?.ok ? ultimoResultado.real.destinoIdx : ultimoResultado.destinoIdx) - 1;
    }
    const esVial = ['red_vial','criterios','trafico','bloqueos'].includes(accion);
    const textoLibre = document.getElementById('labDestinoCoords').value.trim();
    let destinoLibre = null;
    if (esVial && textoLibre) {
        destinoLibre = parsearCoordenadas(textoLibre);
        if (!destinoLibre || !dentroDeLimites(destinoLibre.lat, destinoLibre.lon)) {
            mostrarToast('Destino libre inválido. Escribe latitud, longitud válidas para Panamá.');
            return;
        }
        marcarDestinoLab(destinoLibre.lat, destinoLibre.lon);
    }
    if (accion !== 'escalabilidad' && !destinoLibre && (!Number.isInteger(destino) || destino < 0)) {
        mostrarToast('Selecciona un hospital o define el destino libre para el experimento vial.');
        return;
    }
    const parametros = {
        accion,
        origen: { lat: puntoActual.lat, lon: puntoActual.lng },
        destino_idx: destino,
        destino_libre: destinoLibre,
        escenario: document.getElementById('labEscenario').value,
        bloqueos: Number(document.getElementById('labBloqueos').value),
        cantidad: Number(document.getElementById('labCantidad').value)
    };
    labEjecutando = true;
    const botones = [...document.querySelectorAll('.lab-ejecutar')];
    botones.forEach(b => b.disabled = true);
    document.getElementById('labResultados').innerHTML =
        '<span class="nota">⏳ Calculando… Las consultas de red vial requieren conexión a OpenStreetMap y pueden fallar si el servicio está ocupado.</span>';
    try {
        const r = await fetch('/experimento', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN },
            body: JSON.stringify(parametros)
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
        ultimoLaboratorio = {...j, parametros, fecha: new Date().toISOString()};
        pintarLaboratorio(j);
        mostrarToast('Experimento completado. Datos disponibles en JSON y CSV.');
    } catch (e) {
        document.getElementById('labResultados').innerHTML =
            `<div class="lab-warning">No se pudo ejecutar: ${esc(e.message)}. La ruta normal del mapa no se modificó.</div>`;
        ultimoLaboratorio = null;
    } finally {
        labEjecutando = false;
        botones.forEach(b => b.disabled = false);
    }
}
function exportarLabJSON() {
    if (!ultimoLaboratorio) return mostrarToast('Ejecuta un experimento primero.');
    descargar('laboratorio_dijkstra_' + ultimoLaboratorio.experimento + '.json',
        JSON.stringify(ultimoLaboratorio, null, 2), 'application/json');
}
function exportarLabCSV() {
    if (!ultimoLaboratorio?.filas?.length) return mostrarToast('No hay una tabla de experimento para exportar.');
    const cols = Object.keys(ultimoLaboratorio.filas[0]);
    const celda = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
    const datos = [cols.map(celda).join(';'), ...ultimoLaboratorio.filas.map(f =>
        cols.map(c => celda(f[c])).join(';'))].join('\r\n');
    descargar('laboratorio_dijkstra_' + ultimoLaboratorio.experimento + '.csv', '\uFEFF' + datos, 'text/csv;charset=utf-8');
}


/* =====================================================================
   18. INICIALIZACIÓN
   ===================================================================== */
hospitales.forEach((h, idx) => {
    const opcion = document.createElement('option');
    opcion.value = String(idx);
    opcion.textContent = (h.insular ? '🚤 ' : '') + h.nombre;
    selOrigen.appendChild(opcion);
});

// NUEVO: el texto del botón de PDF refleja si el croquis (reportlab) estará disponible.
document.getElementById('btnPDF').textContent = REPORTLAB_INSTALADO
    ? '📄 Exportar informe PDF (Croquis OK)'
    : '📄 Exportar informe PDF';

construirGrafoBase();
dibujarRedBase();
chkOSRM.checked = OSRM.activo;
setEstadoOSRM(ES_DIRECTA() ? 'directa' : (OSRM.activo ? 'idle' : 'off'));
actualizarBotonesModo();

document.querySelector('.subtitulo').textContent =
    `Dijkstra con ETA, fricción urbana y rutas reales · ${hospitales.length} instalaciones (${IDX_TERRESTRES.length} terrestres) · cobertura sobre tierra firme`;

construirSelectEspecialidades();
reconstruirDestinos();
actualizarChip();
renderHospitales();
construirMetodologia();

metricasDiv.innerHTML = '<div class="nota">Selecciona una especialidad, un origen y un destino. El dashboard se actualizará con cada consulta.</div>';
coberturaStatsDiv.innerHTML = '<div class="nota" style="margin-top:8px;">Capa de cobertura desactivada. Actívala para estimar desiertos de atención.</div>';

map.on('click', e => {
    if (seleccionandoDestinoLab) {
        if (!dentroDeLimites(e.latlng.lat, e.latlng.lng)) {
            mostrarToast('Destino libre fuera de los límites admitidos para Panamá.');
            return;
        }
        marcarDestinoLab(e.latlng.lat, e.latlng.lng);
        mostrarToast('Destino libre fijado. Selecciona el experimento vial que deseas ejecutar.');
        return;
    }
    if (selOrigen.value !== 'mapa') {
        mostrarToast('El origen está fijado en un hospital. Selecciona "Punto X" para elegir sobre el mapa.');
        return;
    }
    if (!dentroDeLimites(e.latlng.lat, e.latlng.lng)) {
        mostrarToast('Ese punto está fuera de la Provincia de Panamá.');
        return;
    }
    puntoActual.nombre = null;
    ponerPuntoYCalcular(e.latlng.lat, e.latlng.lng, 'Persona (Punto X)');
});

setTimeout(() => {
    map.invalidateSize();
    ponerPuntoYCalcular(puntoActual.lat, puntoActual.lng, 'Persona (Punto X)');
}, 250);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 9. GENERACIÓN DEL HTML Y SERVIDOR LOCAL
# ---------------------------------------------------------------------------
def _json_seguro(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def construir_lugares(registros: list[dict]) -> list[dict]:
    """Catálogo de búsqueda del mapa: instalaciones + localidades/corregimientos ancla.

    Se calcula una sola vez al generar la página; el navegador lo usa para centrar el mapa
    y fijar el origen sin depender de internet."""
    vistos: set[str] = set()
    lugares: list[dict] = []
    for h in registros:
        clave = normalizar_clave(h["nombre"])
        if clave in vistos:
            continue
        vistos.add(clave)
        lugares.append({"nombre": h["nombre"], "lat": h["lat"], "lon": h["lon"], "tipo": "hospital"})
    for nombre, (lat, lon) in ANCLAS_LOCALIDAD.items():
        clave = normalizar_clave(nombre)
        if clave in vistos:
            continue
        vistos.add(clave)
        lugares.append({"nombre": nombre.title(), "lat": lat, "lon": lon, "tipo": "localidad"})
    lugares.sort(key=lambda x: (x["tipo"] != "localidad", normalizar_clave(x["nombre"])))
    return lugares


def generar_html(registros: list[dict], config: dict | None = None, token: str = "") -> str:
    """Inyecta dataset, configuración, zonas de fricción, costa y token como JSON dentro de la plantilla.

    `token` vacío = copia estática (index.html abierto como archivo): el mapa funciona, pero el
    informe PDF y el guardado de correcciones requieren el servidor local."""
    html = HTML_TEMPLATE
    for marca, valor in (
        ("__HOSPITALES_JSON__", registros),
        ("__TOKEN_JSON__", token),
        ("__CONFIG_JSON__", config or CONFIG),
        ("__ZONAS_JSON__", ZONAS_FRICCION),
        ("__COSTA_JSON__", [list(p) for p in COSTA_APROX]),
        ("__LUGARES_JSON__", construir_lugares(registros)),
        ("__REPORTLAB_INSTALADO__", reportlab_instalado()),   # NUEVO: booleano true/false para el JS
    ):
        html = html.replace(marca, _json_seguro(valor))
    return html


def listar_especialidades(registros: list[dict]) -> list[str]:
    """Catálogo único de especialidades (para el resumen de consola)."""
    catalogo = set()
    for h in registros:
        for esp in h["especialidades"].split(","):
            nombre = esp.strip()
            if nombre:
                catalogo.add(nombre)
    return sorted(catalogo, key=str.lower)


# ---------------------------------------------------------------------------
# 10. MODO TERMINAL: --consulta
# ---------------------------------------------------------------------------
def parsear_coordenadas(texto: str) -> tuple[float, float]:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", texto.replace("°", " "))]
    if len(nums) != 2:
        raise ValueError("formato esperado: \"lat,lon\" (ej. \"9.035,-79.485\")")
    lat, lon = nums
    if abs(lat) > 60 and abs(lon) < 20:        # vino como (lon, lat)
        lat, lon = lon, lat
    lim = CONFIG["limites"]
    if not (lim["latMin"] <= lat <= lim["latMax"] and lim["lonMin"] <= lon <= lim["lonMax"]):
        raise ValueError("las coordenadas están fuera de la Provincia de Panamá")
    return lat, lon


def comando_consulta(args, registros: list[dict]) -> int:
    try:
        lat, lon = parsear_coordenadas(args.consulta)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 2
    modo = "directa" if args.modo == "recta" else args.modo
    res = consulta_modelo(registros, lat, lon, args.especialidad, max(args.top, 15) if args.pdf else args.top,
                          args.solo_abiertos, modo=modo)
    if not res["filas"]:
        print(f"[ERROR] {res.get('motivo', 'sin resultados')}")
        return 1
    sin = 1.0 if modo == "directa" else CONFIG["sinuosidad"]
    vel = CONFIG["velocidadDirectaKmh"] if modo == "directa" else CONFIG["velocidadLibreKmh"]
    print(f"\nOrigen ({lat:.5f}, {lon:.5f}) · especialidad: {args.especialidad or 'cualquiera'}"
          f"{' · solo abiertos a la llegada' if args.solo_abiertos else ''}")
    print(f"Camino más rápido: {'VÍA DIRECTA (línea recta, sin calles)' if modo == 'directa' else 'POR CALLES (modelo)'} · "
          f"sinuosidad ×{sin}, {vel:.0f} km/h, "
          f"{res['explorados']}/{res['nodos']} nodos explorados\n")
    print(f"{'#':>2}  {'ETA min':>8}  {'km ruta':>8}  {'km recta':>8}  {'horario':<9} instalación")
    for k, f in enumerate(res["filas"][:args.top], 1):
        ab = {True: "abierto", False: "cerrado", None: "?"}[f["abierto_a_la_llegada"]]
        print(f"{k:>2}  {f['eta_min']:>8.1f}  {f['km']:>8.2f}  {f['recta_km']:>8.2f}  {ab:<9} {f['nombre']}")
    if modo == "calles" and res["camino"]:
        nombres = ["ORIGEN"] + [registros[i - 1]["nombre"] for i in res["camino"][1:]]
        print("\nRuta del modelo: " + " → ".join(nombres))
    if modo == "calles" and CONFIG["osrm"]["activo"]:
        top = res["filas"][0]
        h = registros[top["idx"]]
        real = osrm_ruta(CONFIG["osrm"]["url"], lat, lon, h["lat"], h["lon"])
        if real:
            err_km = (top["km"] - real["km"]) / real["km"] * 100
            print(f"\nVerificación OSRM → {h['nombre']}: {real['km']:.2f} km por calles, {real['min']:.1f} min a flujo libre "
                  f"(el modelo difiere {err_km:+.1f}% en distancia)")
        else:
            print("\nVerificación OSRM no disponible (sin conexión o servicio caído); se muestran solo valores del modelo.")
    if args.pdf:
        try:
            exportar_pdf_ranking(payload_desde_consulta(registros, res, lat, lon, args.especialidad, modo), args.pdf)
            print(f"\nInforme PDF guardado en {args.pdf}")
        except (OSError, ValueError) as exc:
            print(f"\n[ERROR] No se pudo guardar el PDF: {exc}")
            return 1
    print()
    return 0


# ---------------------------------------------------------------------------
# 11. PRUEBAS INTERNAS: --autotest
# ---------------------------------------------------------------------------
def autotest() -> int:
    import contextlib
    import io
    import random
    import tempfile
    from datetime import datetime, timedelta, timezone

    resultados: list[tuple[str, bool, str]] = []

    def prueba(nombre: str):
        def deco(fn):
            try:
                fn()
                resultados.append((nombre, True, ""))
            except AssertionError as exc:
                resultados.append((nombre, False, str(exc) or "aserción falló"))
            except Exception as exc:  # noqa: BLE001
                resultados.append((nombre, False, f"{type(exc).__name__}: {exc}"))
            return fn
        return deco

    registros, _ = cargar_dataset(ruta_correcciones=os.devnull + ".inexistente")

    @prueba("haversine: 1° de latitud ≈ 111.195 km")
    def _():
        assert abs(haversine_km(0, 0, 1, 0) - 111.195) < 0.01

    @prueba("horarios: se interpretan los 93 registros base")
    def _():
        malos = [h["nombre"] for h in registros if not h["horario_info"]]
        assert not malos, f"sin interpretar: {malos[:3]}"

    @prueba("horarios: lunes a sábado 7:00-20:00 y turno nocturno")
    def _():
        info = parsear_horario("Lunes a Sábado: 7:00 am - 8:00 pm")
        assert info == {"dias": [0, 1, 2, 3, 4, 5], "h24": False, "abre": 420, "cierra": 1200}
        tz = timezone(timedelta(hours=-5))
        lunes_10 = datetime(2026, 10, 26, 10, 0, tzinfo=tz)       # lunes
        domingo_10 = datetime(2026, 11, 1, 10, 0, tzinfo=tz)      # domingo
        assert esta_abierto(info, lunes_10) is True
        assert esta_abierto(info, domingo_10) is False
        assert esta_abierto(info, lunes_10, offset_min=11 * 60) is False   # 21:00
        noche = {"dias": [0, 1, 2, 3, 4], "h24": False, "abre": 1320, "cierra": 360}   # 22:00-06:00
        assert esta_abierto(noche, datetime(2026, 10, 27, 2, 0, tzinfo=tz)) is True    # martes 2 am (turno del lunes)
        assert esta_abierto(noche, datetime(2026, 10, 31, 2, 0, tzinfo=tz)) is True    # sábado 2 am (sigue el turno del viernes)
        assert esta_abierto(noche, datetime(2026, 11, 1, 2, 0, tzinfo=tz)) is False    # domingo 2 am (el sábado no hay turno)

    @prueba("posiciones: Chimán está en su sitio real y lejos del error de la v2")
    def _():
        assert en_el_mar(8.50, -78.62) is True          # el mar, al sur de la costa
        chiman = next(h for h in registros if "Chimán" in h["nombre"])
        assert not en_el_mar(chiman["lat"], chiman["lon"])
        assert abs(chiman["lat"] - 8.7169) < 0.01 and abs(chiman["lon"] + 78.6332) < 0.01, (chiman["lat"], chiman["lon"])
        # La v2 lo había movido ~24 km tierra adentro (8.9333, -78.6167).
        assert haversine_km(8.9333, -78.6167, chiman["lat"], chiman["lon"]) > 20

    @prueba("posiciones: el dataset base no tiene errores de validación")
    def _():
        errores = [h for h in validar_dataset(registros) if h["nivel"] == "error"]
        assert not errores, "; ".join(f"{e['nombre']}: {e['msg']}" for e in errores[:3])

    @prueba("validador: detecta mar, rango, duplicados y campos vacíos")
    def _():
        malos = [
            {"nombre": "A", "lat": 8.70, "lon": -79.50, "horario": "Lunes a Viernes: 7:00 am - 3:00 pm",
             "descripcion": "x", "especialidades": "x"},
            {"nombre": "B", "lat": 12.0, "lon": -79.50, "horario": "Lunes a Viernes: 7:00 am - 3:00 pm",
             "descripcion": "x", "especialidades": "x"},
            {"nombre": "B", "lat": 9.0, "lon": -79.50, "horario": "raro", "descripcion": "", "especialidades": "x"},
        ]
        msgs = " | ".join(h["msg"] for h in validar_dataset(enriquecer(malos)) if h["nivel"] == "error")
        for esperado in ("mar", "fuera de la Provincia", "duplicado", "campos vacíos"):
            assert esperado in msgs, f"no detectó «{esperado}»"

    @prueba("modelo: la distancia de red incorpora la sinuosidad (regresión de la v1)")
    def _():
        base = construir_grafo_base(registros)
        rnd = random.Random(7)
        for _ in range(12):
            lat, lon = rnd.uniform(8.95, 9.15), rnd.uniform(-79.6, -79.35)
            res = dijkstra(grafo_con_origen(base, registros, lat, lon), 0)
            for i, h in enumerate(registros):
                if h["insular"]:
                    continue
                recta = haversine_km(lat, lon, h["lat"], h["lon"])
                km, eta = res["dist_km"][i + 1], res["dist"][i + 1]
                assert km >= recta * CONFIG["sinuosidad"] - 1e-6, "distancia < recta × sinuosidad"
                assert eta >= recta * CONFIG["sinuosidad"] * 60 / CONFIG["velocidadLibreKmh"] - 1e-6

    @prueba("modelo: fricción siempre dentro de [1, máx]")
    def _():
        for lat in (8.9, 9.0, 9.1, 9.2):
            for lon in (-79.6, -79.5, -79.3, -79.1):
                assert 1.0 <= factor_friccion(lat, lon) <= CONFIG["maxFriccion"]

    @prueba("Dijkstra: coincide con Bellman-Ford en un grafo aleatorio")
    def _():
        rnd = random.Random(3)
        n = 40
        adj = [[] for _ in range(n)]
        aristas = []
        for _ in range(160):
            a, b = rnd.randrange(n), rnd.randrange(n)
            if a != b:
                w = rnd.uniform(0.5, 9.0)
                adj[a].append((b, w, w))
                adj[b].append((a, w, w))
                aristas += [(a, b, w), (b, a, w)]
        d = [math.inf] * n
        d[0] = 0.0
        for _ in range(n):
            for a, b, w in aristas:
                if d[a] + w < d[b]:
                    d[b] = d[a] + w
        res = dijkstra(adj, 0)["dist"]
        for x, y in zip(d, res):
            assert (math.isinf(x) and math.isinf(y)) or abs(x - y) < 1e-9

    @prueba("consulta: los centros insulares nunca son destino")
    def _():
        res = consulta_modelo(registros, 8.95, -79.54, "Vacunación", top=100)
        nombres = {f["nombre"] for f in res["filas"]}
        assert not (nombres & NOMBRES_INSULARES)

    @prueba("correcciones y CSV: se aplican y hacen ida y vuelta")
    def _():
        with tempfile.TemporaryDirectory() as tmp:
            corr = os.path.join(tmp, "c.json")
            with open(corr, "w", encoding="utf-8") as f:
                json.dump({"Hospital Brisas": {"lat": 9.05, "lon": -79.45, "verificada": True},
                           "No existe": {"lat": 1}}, f)
            datos, avisos = cargar_dataset(ruta_correcciones=corr)
            hb = next(h for h in datos if h["nombre"] == "Hospital Brisas")
            assert (hb["lat"], hb["lon"], hb["verificada"]) == (9.05, -79.45, True)
            assert any("No existe" in a for a in avisos)
            ruta_csv = os.path.join(tmp, "d.csv")
            exportar_dataset(datos, ruta_csv)
            de_vuelta = leer_dataset_externo(ruta_csv)
            assert len(de_vuelta) == len(datos) and de_vuelta[0]["nombre"] == datos[0]["nombre"]

    @prueba("verificador OSM (con Nominatim simulado): clasifica y sugiere")
    def _():
        global geocodificar_nominatim
        original = geocodificar_nominatim
        try:
            def falso(consulta, user_agent, timeout=15.0):
                if "Brisas" in consulta:    # ~1.1 km -> 'revisar'
                    return [{"lat": "9.0731", "lon": "-79.4623", "category": "amenity", "type": "hospital", "display_name": "x"}]
                if "Santo Tomás" in consulta:   # exacto -> 'ok'
                    h = next(x for x in registros if x["nombre"] == "Hospital Santo Tomás (MINSA)")
                    return [{"lat": str(h["lat"]), "lon": str(h["lon"]), "category": "amenity",
                             "type": "hospital", "display_name": "y"}]
                return []
            geocodificar_nominatim = falso
            muestra = [h for h in registros if h["nombre"] in ("Hospital Brisas", "Hospital Santo Tomás (MINSA)", "Hospital Nacional")]
            with tempfile.TemporaryDirectory() as tmp:
                with contextlib.redirect_stdout(io.StringIO()):
                    out = verificar_coordenadas(muestra, tmp, pausa_s=0, aplicar=True)
                assert out["resumen"] == {"ok": 1, "revisar": 1, "discrepante": 0, "sin_resultado": 1}, out["resumen"]
                with open(os.path.join(tmp, ARCHIVO_CORRECCIONES), encoding="utf-8") as f:
                    aplicado = json.load(f)
                assert aplicado["Hospital Brisas"]["lat"] == 9.0731 and aplicado["Hospital Brisas"]["verificada"]
                assert "lat" not in aplicado["Hospital Santo Tomás (MINSA)"]      # 'ok' solo se marca verificada
        finally:
            geocodificar_nominatim = original

    @prueba("HTML: se inyectan todos los marcadores y no queda ninguno sin reemplazar")
    def _():
        html = generar_html(registros)
        for marca in ("__HOSPITALES_JSON__", "__CONFIG_JSON__", "__ZONAS_JSON__", "__COSTA_JSON__", "__LUGARES_JSON__",
                      "__REPORTLAB_INSTALADO__"):   # NUEVO: el booleano de reportlab también debe inyectarse
            assert marca not in html, f"quedó sin reemplazar: {marca}"
        assert f"const REPORTLAB_INSTALADO = {'true' if reportlab_instalado() else 'false'};" in html

    @prueba("grafo: el origen solo entra por kOrigen centros (vía calles); la vía directa lo une a todos")
    def _():
        base = construir_grafo_base(registros)
        adj_calles = grafo_con_origen(base, registros, 9.035, -79.485, modo="calles")
        terrestres = sum(1 for h in registros if not h.get("insular"))
        assert len(adj_calles[0]) == CONFIG["kOrigen"], len(adj_calles[0])
        assert len(adj_calles) == len(registros) + 1
        adj_directa = grafo_con_origen(base, registros, 9.035, -79.485, modo="directa")
        assert len(adj_directa[0]) == terrestres
        assert all(len(adj_directa[n]) == 1 for n in range(1, len(adj_directa)) if not registros[n - 1].get("insular"))
        # El MST hace que todos los centros terrestres sean alcanzables en la vía por calles.
        res = dijkstra(adj_calles, 0)
        assert all(math.isfinite(res["dist"][i + 1]) for i, h in enumerate(registros) if not h.get("insular"))

    @prueba("buscador: el catálogo de lugares incluye hospitales y localidades corregidas")
    def _():
        lugares = construir_lugares(registros)
        claves = {normalizar_clave(l["nombre"]) for l in lugares}
        assert "chiman" in claves and "hospital santo tomas (minsa)" in claves
        assert all(CONFIG["limites"]["latMin"] <= l["lat"] <= CONFIG["limites"]["latMax"] for l in lugares)
        assert all(CONFIG["limites"]["lonMin"] <= l["lon"] <= CONFIG["limites"]["lonMax"] for l in lugares)

    @prueba("vía directa: enlaces directos, sin tráfico, sinuosidad 1 y ruta de un solo salto")
    def _():
        lat, lon = 9.035, -79.485
        rec = consulta_modelo(registros, lat, lon, top=500, modo="directa")
        assert rec["modo"] == "directa" and len(rec["camino"]) == 2
        assert rec["filas"] == sorted(rec["filas"], key=lambda f: f["eta_min"])
        for f in rec["filas"]:
            h = registros[f["idx"]]
            d = haversine_km(lat, lon, h["lat"], h["lon"])
            esperado = crear_arista(d, 1.0, sinuosidad=1.0, velocidad=CONFIG["velocidadDirectaKmh"])
            assert abs(f["km"] - esperado[0]) < 1e-9 and abs(f["eta_min"] - esperado[2]) < 1e-9
        cal = consulta_modelo(registros, lat, lon, top=500, modo="calles")
        assert sum(f["km"] for f in cal["filas"]) > sum(f["km"] for f in rec["filas"])   # las calles son más largas
        alias = consulta_modelo(registros, lat, lon, top=5, modo="recta")
        assert alias["modo"] == "directa"
        try:
            consulta_modelo(registros, lat, lon, modo="volando")
            raise AssertionError("debía rechazar un modo desconocido")
        except ValueError:
            pass

    @prueba("validador: avisa si un centro queda lejos de su localidad o duplica coordenadas")
    def _():
        copia = [dict(h) for h in hospitales]
        chemsa = next(h for h in hospitales if "CHEMSA" in h["nombre"])
        for h in copia:
            if h["nombre"] == "Hospital de Chepo (MINSA)":
                h["lat"], h["lon"] = 9.0000, -79.5000          # Chepo está ~45 km al este
        for h in copia:
            if h["nombre"] == "Centro Médico Nacional":
                h["lat"], h["lon"] = chemsa["lat"], chemsa["lon"]   # coordenadas copiadas de CHEMSA
        msgs = " | ".join(f"{h['nombre']}: {h['msg']}" for h in validar_dataset(enriquecer(copia)) if h["nivel"] == "aviso")
        assert "Hospital de Chepo (MINSA): queda a" in msgs and "chepo" in msgs
        assert "¿coordenadas copiadas?" in msgs

    @prueba("PDF: payload validado; informe con reportlab (si hay) y con el escritor de texto")
    def _():
        res = consulta_modelo(registros, 9.035, -79.485, "cardio", top=15)
        payload = payload_desde_consulta(registros, res, 9.035, -79.485, "cardio", "calles")
        for forzar in (False, True):
            pdf = construir_pdf_ranking(payload, forzar_texto=forzar)
            assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF"), "cabecera/cierre PDF"
            if forzar:
                pos = int(re.search(rb"startxref\n(\d+)", pdf)[1])
                assert pdf[pos:pos + 4] == b"xref", "xref mal apuntado"
        with tempfile.TemporaryDirectory() as tmp:
            ruta = exportar_pdf_dataset(registros, validar_dataset(registros), os.path.join(tmp, "d.pdf"), forzar_texto=True)
            assert os.path.getsize(ruta) > 2000
        for malo in ({}, {"origen": {"lat": 50, "lon": 0}, "filas": [{}]}, {"origen": {"lat": 9, "lon": -79.5}, "filas": []}):
            try:
                normalizar_payload_pdf(malo)
                raise AssertionError("debía rechazar el payload")
            except ValueError:
                pass
        limpio = normalizar_payload_pdf({"origen": {"lat": 9.0, "lon": -79.5, "nombre": "A\x00(B)"},
                                         "filas": [{"nombre": "x", "lat": 9, "lon": -79.5, "eta": float("nan"), "km": 1},
                                                   {"nombre": "y", "lat": 9, "lon": -79.5, "eta": 5, "km": 1}]})
        assert len(limpio["filas"]) == 1 and "\x00" not in limpio["origen"]["nombre"]

    @prueba("correcciones: se validan (mar, rango), se mezclan y no pisan un archivo dañado")
    def _():
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "c.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"Hospital Brisas": {"lat": 9.05, "lon": -79.45, "verificada": True}}, f)
            out = guardar_correcciones(registros, {
                "Hospital Santo Tomás (MINSA)": {"lat": 8.9701, "lon": -79.5302},
                "Hospital Nacional": {"lat": 8.5, "lon": -79.5},          # en el mar
                "No existe": {"lat": 9, "lon": -79.5}}, ruta)
            assert out["guardadas"] == 1 and len(out["rechazadas"]) == 2, out
            with open(ruta, encoding="utf-8") as f:
                guardado = json.load(f)
            assert set(guardado) == {"Hospital Brisas", "Hospital Santo Tomás (MINSA)"}
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("{roto")
            try:
                guardar_correcciones(registros, {"Hospital Brisas": {"lat": 9.06, "lon": -79.46}}, ruta)
                raise AssertionError("debía negarse a sobrescribir")
            except ValueError:
                pass
            with open(ruta, encoding="utf-8") as f:
                assert f.read() == "{roto"

    @prueba("servidor: solo sirve la página; POST exige token, Host válido y tamaño acotado")
    def _():
        import http.client
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            ruta_corr = os.path.join(tmp, "c.json")
            token = "tok-de-prueba"
            httpd = crear_servidor("127.0.0.1", 0, generar_html(registros, token=token), registros, ruta_corr, token)
            hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
            hilo.start()
            puerto = httpd.server_address[1]

            def llamar(metodo, ruta, cuerpo=None, cabeceras=None):
                con = http.client.HTTPConnection("127.0.0.1", puerto, timeout=10)
                con.request(metodo, ruta, body=cuerpo, headers=cabeceras or {})
                r = con.getresponse()
                datos = r.read()
                con.close()
                return r.status, r.getheader("Content-Type", ""), datos

            try:
                st, tipo, cuerpo = llamar("GET", "/")
                assert st == 200 and b"tok-de-prueba" in cuerpo and "text/html" in tipo
                assert llamar("GET", "/rutas_salud_panama_cientifico.py")[0] == 404, "no debe publicar el script"
                assert llamar("GET", "/", cabeceras={"Host": "evil.example"})[0] == 403
                payload = json.dumps({"origen": {"lat": 9.0, "lon": -79.5}, "especialidad": "x",
                                      "filas": [{"nombre": "A", "lat": 9.01, "lon": -79.5, "eta": 4.0, "km": 2.0}]})
                cab = {"Content-Type": "application/json"}
                assert llamar("POST", "/pdf", payload, cab)[0] == 403                      # sin token
                st, tipo, cuerpo = llamar("POST", "/pdf", payload, {**cab, "X-Token": token})
                assert st == 200 and tipo == "application/pdf" and cuerpo.startswith(b"%PDF")
                assert llamar("POST", "/pdf", "{}", {**cab, "X-Token": token})[0] == 400  # payload inválido
                assert llamar("POST", "/pdf", payload, {**cab, "X-Token": token, "Origin": "http://evil.example"})[0] == 403
                con = http.client.HTTPConnection("127.0.0.1", puerto, timeout=10)
                con.putrequest("POST", "/pdf")
                con.putheader("X-Token", token)
                con.putheader("Content-Length", str(MAX_BYTES_POST + 1))
                con.endheaders()
                assert con.getresponse().status == 413
                con.close()
                cambios = json.dumps({"Hospital Brisas": {"lat": 9.05, "lon": -79.45}})
                st, _t, cuerpo = llamar("POST", "/correcciones", cambios, {**cab, "X-Token": token})
                assert st == 200 and json.loads(cuerpo)["guardadas"] == 1 and os.path.exists(ruta_corr)
                # NUEVO: /validar_coordenadas exige token y devuelve los hallazgos de validar_dataset en JSON
                assert llamar("POST", "/validar_coordenadas", "{}", cab)[0] == 403
                st, tipo, cuerpo = llamar("POST", "/validar_coordenadas", "{}", {**cab, "X-Token": token})
                rep = json.loads(cuerpo)
                assert st == 200 and "json" in tipo and rep["instalaciones"] == len(registros)
                assert rep["errores"] + rep["avisos"] + rep["info"] == len(rep["hallazgos"])
            finally:
                httpd.shutdown()
                httpd.server_close()

    @prueba("verificador OSM: con varias sedes homónimas elige la más cercana a la posición actual")
    def _():
        global geocodificar_nominatim
        original = geocodificar_nominatim
        try:
            def falso(consulta, user_agent, timeout=15.0):
                return [{"lat": "9.2000", "lon": "-79.3000", "category": "amenity", "type": "hospital", "display_name": "lejos"},
                        {"lat": "9.0640", "lon": "-79.4623", "category": "amenity", "type": "hospital", "display_name": "cerca"}]
            geocodificar_nominatim = falso
            muestra = [h for h in registros if h["nombre"] == "Hospital Brisas"]
            with tempfile.TemporaryDirectory() as tmp:
                with contextlib.redirect_stdout(io.StringIO()):
                    out = verificar_coordenadas(muestra, tmp, pausa_s=0)
            assert out["filas"][0]["osm"] == "cerca" and out["filas"][0]["estado"] == "ok", out["filas"][0]
        finally:
            geocodificar_nominatim = original

    @prueba("HTML: el token, los lugares y el modo de ruta llegan al navegador")
    def _():
        html = generar_html(registros, token="abc")
        assert 'const TOKEN = "abc";' in html and '"modoRuta":"calles"' in html
        assert "__TOKEN_JSON__" not in html and 'id="btnModoDirecta"' in html and "exportarPDF()" in html
        assert 'const LUGARES = ' in html and '"chiman"' in normalizar_clave(html)
        # NUEVO: botones de PDF y de diagnóstico de coordenadas presentes en el dashboard
        assert 'id="btnPDF"' in html and 'id="btnCoords"' in html and 'id="notasCoordenadas"' in html

    @prueba("estructuras: cola mínima propia conserva el orden de prioridades y empates")
    def _():
        cola = ColaPrioridadMinima()
        elementos = [(8.5, 2), (1.0, 7), (2.0, 5), (1.0, 3), (0.0, 0), (7.0, 9)]
        for e in elementos:
            cola.insertar(e)
        assert [cola.extraer() for _ in elementos] == sorted(elementos)
        assert len(cola) == 0 and not cola
        assert cola.inserciones == cola.extracciones == len(elementos)
        try:
            cola.extraer()
        except IndexError:
            pass
        else:
            raise AssertionError('Se permitió extraer de una cola vacía')

    @prueba("estructuras: cola FIFO propia mantiene orden y compacta la memoria")
    def _():
        cola = ColaFIFOPropia()
        for i in range(300):
            cola.encolar(i)
        for i in range(200):
            assert cola.desencolar() == i
        for i in range(300, 500):
            cola.encolar(i)
        assert [cola.desencolar() for _ in range(300)] == list(range(200, 500))
        assert not cola and len(cola) == 0

    @prueba("estructuras: Dijkstra propio coincide con heapq y BFS minimiza saltos")
    def _():
        # A->B directo tarda 10; A->C->B tarda 2: BFS prioriza 1 salto,
        # mientras Dijkstra encuentra la ruta de 2 minutos con 2 saltos.
        g = [[(1, 2.0, 10.0), (2, 1.0, 1.0)], [], [(1, 1.0, 1.0)]]
        propio = _lab_dijkstra_cola_propia(g, 0, 1)
        fifo = _lab_bfs_cola_propia(g, 0, 1)
        original = dijkstra(g, 0, {1}, True)
        assert propio['dist'][1] == original['dist'][1] == 2.0
        assert reconstruir_camino(propio, 1) == [0, 2, 1]
        assert fifo['dist'][1] == 10.0 and fifo['saltos'][1] == 1

    @prueba("laboratorio: botón de las dos colas propias devuelve resultados sin cambiar la ruta")
    def _():
        html = generar_html(registros, token='prueba-colas')
        assert "ejecutarLaboratorio('colas_propias')" in html
        r = ejecutar_laboratorio({'accion': 'colas_propias',
                                 'origen': {'lat': 9.035, 'lon': -79.485},
                                 'destino_idx': 18}, registros)
        assert r['experimento'] == 'colas_propias' and len(r['filas']) == 2
        assert r['metadatos']['dijkstra_coincide_con_original']
        assert r['filas'][0]['costo_min'] <= r['filas'][1]['costo_min'] + 1e-6

    @prueba("laboratorio: grafo OSM dirigido y sentidos de circulación")
    def _():
        elementos = [
            {"type":"node", "id":1, "lat":9.000, "lon":-79.500},
            {"type":"node", "id":2, "lat":9.000, "lon":-79.499},
            {"type":"node", "id":3, "lat":9.000, "lon":-79.498},
            {"type":"node", "id":4, "lat":9.001, "lon":-79.500},
            {"type":"node", "id":5, "lat":9.001, "lon":-79.499},
            {"type":"node", "id":6, "lat":9.001, "lon":-79.498},
            {"type":"way", "id":100, "nodes":[1,2,3], "tags":{"highway":"residential", "maxspeed":"10"}},
            {"type":"way", "id":101, "nodes":[1,4,5,6,3], "tags":{"highway":"primary", "maxspeed":"80"}},
            {"type":"way", "id":102, "nodes":[2,5], "tags":{"highway":"service", "oneway":"yes"}},
        ]
        grafo = _lab_grafo_osm(elementos)
        assert grafo["nodos"] == 6
        assert any(e[0] == 5 for e in grafo["ady"][2])
        assert not any(e[0] == 2 for e in grafo["ady"][5])
        assert _lab_velocidad({"highway":"residential", "maxspeed":"30 mph"}) > 48
        globals()["_lab_fixture"] = grafo

    @prueba("laboratorio: Dijkstra real diferencia menor distancia y tiempo")
    def _():
        g = globals()["_lab_fixture"]
        rapida = _lab_camino(g, 1, 3, criterio="tiempo", escenario="ligero")
        corta = _lab_camino(g, 1, 3, criterio="distancia", escenario="ligero")
        assert rapida["encontrada"] and corta["encontrada"]
        assert rapida["ids"] != corta["ids"], (rapida["ids"], corta["ids"])
        assert corta["km"] < rapida["km"] and rapida["min"] < corta["min"]
        assert abs(corta["costo"] - corta["km"]) < 1e-9

    @prueba("laboratorio: bloqueo físico de segmentos produce desvío")
    def _():
        g = globals()["_lab_fixture"]
        base = _lab_camino(g, 1, 3, escenario="ligero")
        bloqueada = set(zip(base["ids"][1:-1], base["ids"][2:]))
        nueva = _lab_camino(g, 1, 3, escenario="ligero", bloqueos=bloqueada)
        assert nueva["encontrada"]
        assert nueva["ids"] != base["ids"]
        assert nueva["min"] >= base["min"] - 1e-10

    @prueba("laboratorio: congestión creciente y rutas son no negativas")
    def _():
        g = globals()["_lab_fixture"]
        tiempos = [_lab_camino(g, 1, 3, escenario=esc)["min"] for esc in
                   ("ligero", "moderado", "intenso")]
        assert tiempos[0] <= tiempos[1] <= tiempos[2], tiempos
        assert all(t > 0 and math.isfinite(t) for t in tiempos)

    @prueba("laboratorio: comparación algoritmos obtiene mismo mínimo")
    def _():
        r = _lab_comparar_algoritmos(registros, (9.035, -79.485), 18)
        valores = [f["costo_min"] for f in r["filas"]]
        assert max(valores) - min(valores) < 1e-6, valores
        assert len(r["filas"]) == 3

    @prueba("laboratorio: escalabilidad real de 100 a 10.000 vértices")
    def _():
        o = _lab_escalabilidad()
        assert [f["vertices"] for f in o["filas"]] == [100, 500, 1000, 5000, 10000]
        assert all(f["dijkstra_ms"] >= 0 and f["pico_extra_kib"] > 0 for f in o["filas"])
        assert all(math.isfinite(f["costo_min"]) for f in o["filas"])

    @prueba("laboratorio: botones optativos presentes, sin autoejecución")
    def _():
        html = generar_html(registros, token="prueba")
        assert html.count('class="btn-sec lab-ejecutar"') == 8
        assert 'id="panelLaboratorio"' in html and 'ejecutarLaboratorio(' in html
        assert "ejecutarLaboratorio('escalabilidad')" in html
        assert not 'setTimeout(() => ejecutarLaboratorio(' in html

    @prueba("laboratorio: validación rechaza parámetros no permitidos")
    def _():
        for peticion in ({"accion":"cualquier_cosa"},
                         {"accion":"red_vial", "origen":{"lat":50, "lon":0}, "destino_idx":0},
                         {"accion":"bloqueos", "origen":{"lat":9.0, "lon":-79.5},
                          "destino_idx":0, "bloqueos":100}):
            try:
                ejecutar_laboratorio(peticion, registros)
            except ValueError:
                continue
            raise AssertionError(f"petición inválida aceptada: {peticion}")

    @prueba("laboratorio: servicio /experimento requiere token y responde JSON")
    def _():
        import threading
        server = crear_servidor("127.0.0.1", 0, generar_html(registros, token="test-lab"),
                               registros, os.devnull + '.corr', "test-lab")
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/experimento"
            datos = json.dumps({"accion":"algoritmos", "origen":{"lat":9.035,"lon":-79.485},
                                "destino_idx":18}).encode()
            req = urllib.request.Request(url, data=datos, headers={"Content-Type":"application/json", "X-Token":"test-lab"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.load(resp)
                assert body["experimento"] == "algoritmos" and len(body["filas"]) == 3
            req_mala = urllib.request.Request(url, data=datos, headers={"Content-Type":"application/json"})
            try:
                urllib.request.urlopen(req_mala, timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
            else:
                raise AssertionError('El servicio aceptó una petición sin token')
        finally:
            server.shutdown()
            server.server_close()

    @prueba("laboratorio: destino libre elegido por coordenadas funciona")
    def _():
        original = globals()["_lab_obtener_red"]
        try:
            globals()["_lab_obtener_red"] = lambda origen, destino: (globals()["_lab_fixture"], True)
            out = ejecutar_laboratorio({"accion":"criterios", "origen":{"lat":9.0,"lon":-79.5},
                "destino_libre":{"lat":9.0,"lon":-79.498}, "bloqueos":1}, registros)
            assert len(out["rutas"]) == 2 and out["filas"][0]["km"] < out["filas"][1]["km"]
        finally:
            globals()["_lab_obtener_red"] = original

    @prueba("laboratorio: servicio Overpass valida y reutiliza caché")
    def _():
        origen_urlopen = urllib.request.urlopen
        elementos = [
            {"type":"node", "id":1, "lat":9.000, "lon":-79.500},
            {"type":"node", "id":2, "lat":9.000, "lon":-79.499},
            {"type":"node", "id":3, "lat":9.000, "lon":-79.498},
            {"type":"node", "id":4, "lat":9.001, "lon":-79.500},
            {"type":"node", "id":5, "lat":9.001, "lon":-79.499},
            {"type":"node", "id":6, "lat":9.001, "lon":-79.498},
            {"type":"way", "id":11, "nodes":[1,2,3], "tags":{"highway":"residential"}},
            {"type":"way", "id":12, "nodes":[1,4,5,6,3], "tags":{"highway":"primary"}},
        ]
        class FalsaRespuesta:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n): return json.dumps({"elements":elementos}).encode()
        llamadas = [0]
        def falsa_urlopen(*args, **kwargs):
            llamadas[0] += 1
            return FalsaRespuesta()
        urllib.request.urlopen = falsa_urlopen
        _LAB_CACHE.clear()
        try:
            red, en_cache = _lab_obtener_red((9.0,-79.5), (9.0,-79.498))
            red2, en_cache2 = _lab_obtener_red((9.0,-79.5), (9.0,-79.498))
            assert red["nodos"] == 6 and not en_cache and en_cache2
            assert red is red2 and llamadas[0] == 1
        finally:
            urllib.request.urlopen = origen_urlopen
            _LAB_CACHE.clear()

    @prueba("laboratorio: validación OSRM usa tabla simulada y reporta errores")
    def _():
        original = globals()["_http_get_json"]
        def fake(url, timeout=10, *args, **kwargs):
            assert "/table/v1/driving/" in url and "annotations=duration,distance" in url
            n = len(url.split('/table/v1/driving/')[1].split('?')[0].split(';'))
            return {"code":"Ok", "durations": [[0]+[600]*(n-1)],
                    "distances": [[0]+[5000]*(n-1)]}
        try:
            globals()["_http_get_json"] = fake
            o = _lab_validacion(registros, (9.035,-79.485), 5)
            assert o["metadatos"]["pares_validos"] == 5
            assert o["metadatos"]["error_absoluto_medio_distancia_pct"] >= 0
        finally:
            globals()["_http_get_json"] = original

    ancho = max(len(n) for n, _, _ in resultados)
    print("\nPRUEBAS INTERNAS")
    for nombre, ok, detalle in resultados:
        print(f"  {'✔' if ok else '✖'} {nombre.ljust(ancho)}{'' if ok else '  -> ' + detalle}")
    fallos = sum(1 for _, ok, _ in resultados if not ok)
    print(f"\n{len(resultados) - fallos}/{len(resultados)} pruebas correctas\n")
    return 1 if fallos else 0


# ---------------------------------------------------------------------------
# 12. PUNTO DE ENTRADA
# ---------------------------------------------------------------------------
def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Mapa interactivo de rutas hospitalarias (Dijkstra + ETA + rutas reales OSRM).")
    g = p.add_argument_group("servidor")
    g.add_argument("--host", default="127.0.0.1", help="Interfaz de escucha (default: 127.0.0.1)")
    g.add_argument("--port", type=int, default=0, help="Puerto (0 = libre automático)")
    g.add_argument("--no-browser", action="store_true", help="No abrir el navegador automáticamente")
    g = p.add_argument_group("datos")
    g.add_argument("--datos", metavar="ARCHIVO", help="Dataset propio (.json o .csv) en lugar del incluido")
    g.add_argument("--correcciones", metavar="ARCHIVO",
                   help=f"Correcciones de coordenadas (default: {ARCHIVO_CORRECCIONES} junto al script)")
    g.add_argument("--exportar-dataset", metavar="ARCHIVO", help="Guardar el dataset efectivo (.json/.csv) y salir")
    g.add_argument("--validar", action="store_true", help="Validar el dataset en detalle y salir (código 1 si hay errores)")
    g.add_argument("--verificar-coordenadas", action="store_true",
                   help="Comparar cada posición con OpenStreetMap/Nominatim (~2 min; requiere internet)")
    g.add_argument("--aplicar", action="store_true",
                   help="Con --verificar-coordenadas: guardar las correcciones seguras en el archivo de correcciones")
    g.add_argument("--email", default="", help="Contacto para el User-Agent de Nominatim (buena práctica)")
    g = p.add_argument_group("rutas")
    g.add_argument("--osrm-url", metavar="URL", help="Servidor OSRM propio (default: demo pública)")
    g.add_argument("--sin-osrm", action="store_true", help="Trabajar solo con el modelo (sin rutas reales)")
    g = p.add_argument_group("terminal")
    g.add_argument("--consulta", metavar='"LAT,LON"', help="Ranking de centros desde ese punto, sin abrir el mapa")
    g.add_argument("--especialidad", metavar="TEXTO", help="Filtro por especialidad (coincidencia parcial, ej. cardio)")
    g.add_argument("--top", type=int, default=5, help="Cuántos centros mostrar con --consulta (default: 5)")
    g.add_argument("--solo-abiertos", action="store_true", help="Con --consulta: solo centros abiertos a la llegada")
    g.add_argument("--modo", choices=("calles", "directa", "recta"), default=CONFIG["modoRuta"],
                   help="Camino más rápido: 'calles' (OSRM + tráfico) o 'directa' (línea recta sin calles; "
                        "'recta' es un alias de 'directa'). Default: calles")
    g = p.add_argument_group("informes")
    g.add_argument("--pdf", metavar="ARCHIVO.pdf",
                   help="Con --consulta: informe PDF del ranking. Solo o con --validar: reporte PDF del dataset")
    p.add_argument("--autotest", action="store_true", help="Ejecutar las pruebas internas y salir")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    if args.autotest:
        return autotest()
    CONFIG["modoRuta"] = "directa" if args.modo == "recta" else args.modo
    if args.sin_osrm:
        CONFIG["osrm"]["activo"] = False
    if args.osrm_url:
        CONFIG["osrm"]["url"] = args.osrm_url.rstrip("/")

    directorio = directorio_script()
    try:
        registros, avisos = cargar_dataset(args.datos, args.correcciones)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[ERROR] No se pudo cargar el dataset: {exc}")
        return 2

    if args.exportar_dataset:
        exportar_dataset(registros, args.exportar_dataset)
        print(f"Dataset ({len(registros)} instalaciones) guardado en {args.exportar_dataset}")
        return 0

    hallazgos = validar_dataset(registros)
    errores = sum(1 for h in hallazgos if h["nivel"] == "error")
    if args.validar:
        print(f"\nVALIDACIÓN DEL DATASET ({len(registros)} instalaciones)")
        imprimir_validacion(hallazgos, detallado=True)
        print()
        if args.pdf:
            exportar_pdf_dataset(registros, hallazgos, args.pdf)
            print(f"Reporte PDF guardado en {args.pdf}\n")
        return 1 if errores else 0

    if args.pdf and not args.consulta:
        try:
            exportar_pdf_dataset(registros, hallazgos, args.pdf)
        except OSError as exc:
            print(f"[ERROR] No se pudo guardar el PDF: {exc}")
            return 1
        print(f"Reporte PDF del dataset ({len(registros)} instalaciones) guardado en {args.pdf}")
        return 0

    if args.verificar_coordenadas:
        print(f"\nVerificando {len(registros)} posiciones contra OpenStreetMap (≈1 petición por segundo)…\n")
        out = verificar_coordenadas(registros, directorio, args.email, args.aplicar)
        print("\nResumen:", out["resumen"])
        print(f"Reporte: {os.path.join(directorio, 'verificacion_coordenadas.csv')}")
        print(f"Sugerencias: {os.path.join(directorio, 'correcciones_sugeridas.json')}")
        if args.aplicar:
            print(f"Aplicadas en: {os.path.join(directorio, ARCHIVO_CORRECCIONES)}")
        print("Los casos «discrepante» y «sin_resultado» requieren revisión manual.\n")
        return 0

    if args.consulta:
        return comando_consulta(args, registros)

    ruta_correcciones = args.correcciones or os.path.join(directorio, ARCHIVO_CORRECCIONES)
    try:
        archivo_html = os.path.join(directorio, "index.html")
        with open(archivo_html, "w", encoding="utf-8") as f:       # copia estática, sin token
            f.write(generar_html(registros))
    except OSError:                       # carpeta de solo lectura: usar una temporal
        import tempfile
        archivo_html = os.path.join(tempfile.mkdtemp(prefix="rutas_salud_"), "index.html")
        with open(archivo_html, "w", encoding="utf-8") as f:
            f.write(generar_html(registros))

    token = secrets.token_urlsafe(24)
    try:
        httpd = crear_servidor(args.host, args.port, generar_html(registros, token=token),
                               registros, ruta_correcciones, token)
    except OSError as exc:
        print(f"\n[ERROR] No se pudo abrir el puerto {args.port}: {exc}")
        print("Sugerencia: usa --port 0 para elegir un puerto libre.\n")
        return 1

    with httpd:
        puerto = httpd.server_address[1]
        host_url = "127.0.0.1" if args.host in ("", "0.0.0.0") else args.host
        url = f"http://{host_url}:{puerto}/"
        especialidades = listar_especialidades(registros)
        terrestres = sum(1 for h in registros if not h["insular"])
        verificadas = sum(1 for h in registros if h["verificada"])
        print("\n" + "=" * 64)
        print(f"  RED DE RUTAS DE SALUD · PROVINCIA DE PANAMÁ  (v{VERSION})")
        print("=" * 64)
        print(f"  Instalaciones registradas : {len(registros)} ({terrestres} terrestres, "
              f"{len(registros) - terrestres} insulares)")
        print(f"  Posiciones verificadas OSM: {verificadas}")
        print(f"  Especialidades únicas     : {len(especialidades)}")
        for aviso in avisos:
            print(f"  {aviso}")
        imprimir_validacion(hallazgos, detallado=False)
        if errores:
            print("  ⚠ Hay errores en el dataset: ejecuta con --validar para ver el detalle.")
        print(f"  Rutas reales (OSRM)       : {'activadas' if CONFIG['osrm']['activo'] else 'desactivadas'}"
              f"{' · ' + CONFIG['osrm']['url'] if CONFIG['osrm']['activo'] else ''}")
        print(f"  Camino más rápido (inicio): {'vía directa (línea recta)' if CONFIG['modoRuta'] == 'directa' else 'por calles'}")
        print(f"  Correcciones se guardan en: {ruta_correcciones}")
        print(f"  Copia estática del HTML   : {archivo_html} (sin PDF ni guardado)")
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print("  ⚠ Escuchas fuera de loopback: otros equipos de la red podrán abrir la página.")
        print(f"  Mapa disponible en        : {url}")
        print("  Ctrl+C para detener el servidor.")
        print("=" * 64 + "\n")

        if not args.no_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido por el usuario.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

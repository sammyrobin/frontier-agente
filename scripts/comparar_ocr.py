"""Compara configuraciones de OCR sobre capturas/captura.png (sin conectarse).

Uso (desde agente/):  python scripts/comparar_ocr.py [repeticiones]

Métricas contra la verdad escrita a mano de la pantalla de bienvenida:
  recall    = palabras esperadas leídas EXACTAS (con acentos y mayúsculas)
  precisión = palabras leídas que son correctas (lo demás es basura/errores)
  claves    = datos que el agente necesita sí o sí: fecha, menú, avisos
  tiempo    = mediana de N corridas (incluye escalar y convertir a gris)
"""
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np
from PIL import Image

from agente.percepcion import buscar_texto, leer_pantalla, ocr_palabras, agrupar_lineas

ESPERADO = """
SIGECOM Distribuidora Andina v3.9 Hoy: 14/10/2026 Usuario: operador2
Archivo Comercial Cartera Herramientas Ayuda
Bienvenido a SIGECOM
Sistema de gestión comercial. Use el menú superior para acceder a los módulos.
Soporte: extensión 214 (fuera de servicio).
""".split()

CLAVES = ["14/10/2026", "Archivo", "Comercial", "Cartera", "Herramientas", "Ayuda",
          "Bienvenido a SIGECOM", "extensión 214", "fuera de servicio", "operador2"]

CONFIGS = [(3, 1), (3, 2), (11, 1), (11, 2)]


def es_puntuacion(t):
    return all(not c.isalnum() for c in t)


def evaluar(palabras):
    leidas = Counter(p.texto for p in palabras if not es_puntuacion(p.texto))
    esperadas = Counter(ESPERADO)
    aciertos = sum((leidas & esperadas).values())
    total_leidas = sum(leidas.values())
    lineas = agrupar_lineas(palabras)
    claves = [c for c in CLAVES if buscar_texto(lineas, c)]
    errores = sorted((leidas - esperadas).elements())
    return aciertos / len(ESPERADO), aciertos / max(total_leidas, 1), claves, errores


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    imagen = np.array(Image.open(RAIZ / "capturas" / "captura.png").convert("RGB"))
    filas = []
    for psm, esc in CONFIGS:
        tiempos = []
        for _ in range(reps):
            t = time.perf_counter()
            palabras = ocr_palabras(imagen, psm, esc)
            tiempos.append(time.perf_counter() - t)
        rec, prec, claves, errores = evaluar(palabras)
        filas.append((psm, esc, rec, prec, claves, statistics.median(tiempos), errores))

    print(f"\n{len(ESPERADO)} palabras esperadas · {len(CLAVES)} claves · {reps} corridas\n")
    print("| psm | escala | recall | precisión | claves | tiempo (mediana) |")
    print("|-----|--------|--------|-----------|--------|------------------|")
    for psm, esc, rec, prec, claves, t, _ in filas:
        print(f"| {psm:>3} | x{esc:<5} | {rec:6.0%} | {prec:9.0%} | {len(claves):>2}/{len(CLAVES)}  | {t:14.2f} s |")

    print("\nDetalle por configuración:")
    for psm, esc, _, _, claves, _, errores in filas:
        faltan = [c for c in CLAVES if c not in claves]
        print(f"  psm {psm} x{esc}: claves que faltan {faltan or '-'}")
        print(f"               palabras mal leídas/sobrantes {errores or '-'}")

    print("\nLíneas leídas con la configuración por defecto (psm 3, x1):")
    for ln in leer_pantalla(imagen, 3, 1):
        x, y, w, h = ln.caja
        print(f"  ({x:4},{y:3}) conf≥{ln.confianza:3.0f}  {ln.texto}")


if __name__ == "__main__":
    main()

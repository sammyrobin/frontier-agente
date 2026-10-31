"""Prueba de regresión de percepcion.py (sin conexión). Repetir tras el incidente de las 15:00.

Uso (desde agente/):  python scripts/probar_percepcion.py [captura.png]
Imprime OK/FALLA por caso y el tiempo de OCR por captura. Sale con código 1 si algo falla.
"""
import statistics
import sys
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np
from PIL import Image

from agente.percepcion import (ESCALA, ESCALA_OSCURAS, PSM, Linea, Palabra, agrupar_lineas, buscar_texto,
                               fecha_hoy, leer_pantalla, verificar_tesseract)

fallas = 0


def caso(nombre, obtenido, esperado):
    global fallas
    ok = obtenido == esperado
    fallas += not ok
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre}: {obtenido!r}" + ("" if ok else f" (esperado {esperado!r})"))


def linea_sintetica(*tokens, y=10):
    """Arma palabras de 10 px de alto separadas por 6 px (una sola línea)."""
    x, palabras = 0, []
    for t in tokens:
        w = 8 * len(t)
        palabras.append(Palabra(t, x, y, w, 10, 95.0))
        x += w + 6
    return palabras


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    verificar_tesseract()
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "capturas" / "captura.png"
    imagen = np.array(Image.open(ruta).convert("RGB"))

    print(f"\n1. Captura real ({ruta.name}) con psm {PSM}, cuerpo x{ESCALA}, zonas oscuras x{ESCALA_OSCURAS}")
    tiempos = []
    for _ in range(3):
        t = time.perf_counter()
        lineas = leer_pantalla(imagen)
        tiempos.append(time.perf_counter() - t)
    print(f"  OCR por captura: mediana {statistics.median(tiempos):.2f} s "
          f"(min {min(tiempos):.2f}, max {max(tiempos):.2f})")
    caso("fecha_hoy", fecha_hoy(lineas), date(2026, 10, 14))
    for clave in ["Archivo", "Comercial", "Cartera", "Herramientas", "Ayuda", "Bienvenido a SIGECOM"]:
        caso(f"encuentra '{clave}'", bool(buscar_texto(lineas, clave)), True)

    clientes = RAIZ / "capturas" / "clientes.png"   # la genera scripts/probar_navegacion.py
    if clientes.exists():
        print(f"\n1b. Captura real ({clientes.name}): texto claro sobre color y botones con borde")
        img_c = np.array(Image.open(clientes).convert("RGB"))
        tiempos = []
        for _ in range(3):
            t = time.perf_counter()
            lineas_c = leer_pantalla(img_c)
            tiempos.append(time.perf_counter() - t)
        print(f"  OCR por captura: mediana {statistics.median(tiempos):.2f} s "
              f"(min {min(tiempos):.2f}, max {max(tiempos):.2f})")
        caso("fecha_hoy", fecha_hoy(lineas_c), date(2026, 10, 14))
        for clave in ["Buscar", "Siguiente", "Limpiar", "Nuevo cliente", "Exportar", "Nombre"]:
            caso(f"encuentra '{clave}'", bool(buscar_texto(lineas_c, clave)), True)
    else:
        print(f"\n1b. (omitido: falta {clientes.name}; correr probar_navegacion.py)")

    print("\n2. Búsqueda (sintética)")
    ls = agrupar_lineas(linea_sintetica("CL-0007", "Distribuciones", "El", "Faro", "Calle", "45")
                        + linea_sintetica("Eliminar", "cliente", y=40)
                        + linea_sintetica("Ana", "Torres", y=70) + linea_sintetica("Ana", "Torres", y=100))
    c = buscar_texto(ls, "Distribuciones El Faro")
    lx, _, lw, _ = ls[0].caja  # línea del CL-0007
    caso("frase: centro x de la frase < centro x de la línea", c[0].centro[0] < lx + lw / 2, True)
    caso("homónimos: 'Ana Torres' devuelve 2", len(buscar_texto(ls, "Ana Torres")), 2)
    caso("'cliente' no cae en 'Eliminar cliente'", [x.linea for x in buscar_texto(ls, "cliente")], [])
    caso("'Eliminar' exacta", len(buscar_texto(ls, "Eliminar")), 1)
    caso("'Elimnar' (destructiva) sin flexible", buscar_texto(ls, "Elimnar"), [])

    print("\n3. Fecha 'Hoy' (sintética)")
    for txt, esperado in [("14/10/2026", date(2026, 10, 14)), ("31/02/2026", None), ("14/13/2026", None),
                          ("1/9/2026", date(2026, 9, 1)), ("114/10/2026", None)]:
        caso(f"Hoy: {txt}", fecha_hoy(agrupar_lineas(linea_sintetica("Hoy:", txt))), esperado)
    caso("sin etiqueta 'Hoy'", fecha_hoy(agrupar_lineas(linea_sintetica("Vence:", "14/10/2026"))), None)

    print(f"\n{'TODO OK' if not fallas else f'{fallas} FALLA(S)'}")
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    main()

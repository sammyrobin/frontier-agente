"""Prueba SIN LLM de escribir_en_campo: Clientes -> Nombre = "Ramírez" -> Buscar.

Uso (desde agente/):  python scripts/probar_busqueda.py [texto]
Solo filtra una búsqueda: NO crea, edita ni guarda nada en la app. Hace /__reset al inicio.
Imprime cada paso con sus tiempos, las filas resultantes y guarda capturas/busqueda.png.
"""
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from dotenv import load_dotenv
from PIL import Image

from agente.accion import clic_en_texto, escribir_en_campo, observar
from agente.percepcion import Linea, buscar_texto, verificar_tesseract
from agente.vnc import ClienteVNC
from reset import reset

load_dotenv(RAIZ / ".env")


def paso(nombre, res) -> None:
    t = " · ".join(f"{k} {v:.2f} s" for k, v in res.tiempos.items())
    print(f"\n[{'OK' if res.ok else 'ERROR'}] {nombre}: {res.detalle}\n     tiempos: {t}")
    if not res.ok:
        sys.exit(1)


def filas(lineas: list[Linea], debajo_de: int) -> list[str]:
    """Agrupa las líneas sueltas del OCR en filas de tabla (misma altura +-6 px)."""
    grupos: list[list[Linea]] = []
    for ln in sorted((l for l in lineas if l.caja[1] > debajo_de), key=lambda l: l.caja[1]):
        if grupos and abs(ln.caja[1] - grupos[-1][0].caja[1]) <= 6:
            grupos[-1].append(ln)
        else:
            grupos.append([ln])
    return [" | ".join(l.texto for l in sorted(g, key=lambda l: l.caja[0])) for g in grupos]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    texto = sys.argv[1] if len(sys.argv) > 1 else "Ramírez"
    verificar_tesseract()
    codigo, _ = reset()
    print(f"reset: HTTP {codigo}")
    if codigo != 200:
        sys.exit(1)
    vnc = ClienteVNC(os.environ["ESCRITORIO_URL"], os.environ["ESCRITORIO_PASSWORD"])
    try:
        imagen, lineas, _ = observar(vnc)
        for objetivo in ["Comercial", "Maestros", "Clientes"]:
            res = clic_en_texto(vnc, objetivo, imagen, lineas)
            paso(f"clic '{objetivo}'", res)
            imagen, lineas = res.captura_despues, res.lineas_despues

        res = escribir_en_campo(vnc, "Nombre", texto, imagen, lineas)
        paso(f"escribir '{texto}' en Nombre", res)

        # Releer la pantalla tras escribir (el campo cambió) antes de ubicar Buscar.
        imagen, lineas, _ = observar(vnc)
        t = time.perf_counter()
        res = clic_en_texto(vnc, "Buscar", imagen, lineas)
        paso("clic 'Buscar'", res)

        Image.fromarray(res.captura_despues).save(RAIZ / "capturas" / "busqueda.png")
        cab = buscar_texto(res.lineas_despues, "Teléfono") or buscar_texto(res.lineas_despues, "Estado")
        y_cab = cab[0].y if cab else 190
        print(f"\nFilas resultantes (bajo la cabecera y={y_cab}):")
        for f in filas(res.lineas_despues, y_cab - 3):
            print("   ", f)
        print("\nguardada capturas/busqueda.png")
    finally:
        vnc.cerrar()


if __name__ == "__main__":
    main()

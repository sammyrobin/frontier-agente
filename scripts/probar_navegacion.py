"""Prueba de navegación SIN LLM: pantalla inicial -> Comercial -> Maestros -> Clientes.

Uso (desde agente/):  python scripts/probar_navegacion.py
Solo navega: NO crea, edita ni guarda nada en la app. Hace /__reset al inicio.
Guarda capturas/clientes.png, imprime los textos leídos y el tiempo de cada paso.
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

from agente.accion import clic_en_texto, observar
from agente.percepcion import buscar_texto, fecha_hoy, verificar_tesseract
from agente.vnc import ClienteVNC
from reset import reset

load_dotenv(RAIZ / ".env")


def tiempos(t: dict) -> str:
    return " · ".join(f"{k} {v:.2f} s" for k, v in t.items())


def paso(nombre, res) -> None:
    print(f"\n[{'OK' if res.ok else 'ERROR'}] {nombre}: {res.detalle}")
    print(f"     tiempos: {tiempos(res.tiempos)}")
    if not res.ok:
        sys.exit(1)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    verificar_tesseract()

    t = time.perf_counter()
    codigo, _ = reset()
    print(f"1. reset: HTTP {codigo} en {time.perf_counter() - t:.2f} s")
    if codigo != 200:
        sys.exit(1)

    t = time.perf_counter()
    vnc = ClienteVNC(os.environ["ESCRITORIO_URL"], os.environ["ESCRITORIO_PASSWORD"])
    print(f"2. conexión: {time.perf_counter() - t:.2f} s · {vnc.ancho}x{vnc.alto}")
    try:
        imagen, lineas, t_obs = observar(vnc)
        print(f"   observación inicial: {tiempos(t_obs)} · {len(lineas)} líneas · Hoy={fecha_hoy(lineas)}")

        # Ruta real vista en SIGECOM: Comercial abre un menú con submenús
        # "Maestros >" y "Ventas >"; Clientes está dentro de Maestros.
        ruta = ["Comercial", "Maestros", "Clientes"]
        res = None
        for i, objetivo in enumerate(ruta):
            res = clic_en_texto(vnc, objetivo, imagen, lineas)
            paso(f"{3 + i}. clic '{objetivo}'", res)
            imagen, lineas = res.captura_despues, res.lineas_despues
            siguiente = ruta[i + 1] if i + 1 < len(ruta) else None
            if siguiente:
                print("   textos visibles:", " | ".join(ln.texto for ln in lineas))
                if not buscar_texto(lineas, siguiente):
                    print(f"[ERROR] '{siguiente}' no apareció tras '{objetivo}'")
                    sys.exit(1)
                print(f"   verificado: aparece '{siguiente}'")

        destino = RAIZ / "capturas" / "clientes.png"
        Image.fromarray(res.captura_despues).save(destino)
        print(f"\n5. guardada {destino.relative_to(RAIZ)} · textos leídos:")
        for ln in res.lineas_despues:
            x, y, w, h = ln.caja
            print(f"     ({x:4},{y:3}) conf≥{ln.confianza:3.0f}  {ln.texto}")
    finally:
        vnc.cerrar()


if __name__ == "__main__":
    main()

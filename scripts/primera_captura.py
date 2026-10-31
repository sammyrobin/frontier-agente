"""Paso 5: conecta al escritorio, espera pantalla estable y guarda capturas/captura.png.

Uso (desde agente/):  python scripts/primera_captura.py
Lee ESCRITORIO_URL y ESCRITORIO_PASSWORD del entorno (.env); nunca los imprime.
"""
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv
from PIL import Image

from agente.vnc import ClienteVNC

load_dotenv(RAIZ / ".env")

t0 = time.monotonic()
vnc = ClienteVNC(os.environ["ESCRITORIO_URL"], os.environ["ESCRITORIO_PASSWORD"])
print(f"Conectado en {time.monotonic() - t0:.1f} s · pantalla {vnc.ancho}x{vnc.alto}")

try:
    t1 = time.monotonic()
    imagen, estable = vnc.esperar_estable()
    print(f"Pantalla {'estable' if estable else 'NO estable (se agotó el máximo)'} "
          f"en {time.monotonic() - t1:.1f} s")

    # Chequeo rápido: una captura negra o uniforme indica que no llegó el framebuffer
    print(f"Brillo medio {imagen.mean():.0f}/255 · colores distintos en una muestra: "
          f"{len(set(map(tuple, imagen[::20, ::20].reshape(-1, 3))))}")

    destino = RAIZ / "capturas" / "captura.png"
    Image.fromarray(imagen).save(destino)
    print(f"Guardada en {destino.relative_to(RAIZ)}")
finally:
    vnc.cerrar()

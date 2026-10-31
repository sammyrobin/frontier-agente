import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
from agente.vnc import ClienteVNC

load_dotenv()
t0 = time.monotonic()
vnc = ClienteVNC(os.environ["ESCRITORIO_URL"], os.environ["ESCRITORIO_PASSWORD"])
print(f"Conectado en {time.monotonic() - t0:.1f} s")
print(f"Servidor: {vnc.nombre!r} · pantalla {vnc.ancho}x{vnc.alto}")
print(f"Cuadros recibidos: {vnc.actualizaciones}")
vnc.cerrar()

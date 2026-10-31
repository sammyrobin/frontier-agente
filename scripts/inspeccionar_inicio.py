"""Reset + captura de la pantalla inicial: OCR, modal detectado y prueba de cerrar_modal.

Uso (desde agente/):  python scripts/inspeccionar_inicio.py [--sin-reset]
Guarda capturas/inicio.png y capturas/tras_modal.png. No imprime URL, contraseña ni token.
"""
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))
from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")
from PIL import Image

from agente.accion import cerrar_modal, observar
from agente.percepcion import detectar_modal
from agente.vnc import ClienteVNC
from reset import reset

sys.stdout.reconfigure(encoding="utf-8")
if "--sin-reset" not in sys.argv:
    print("reset:", reset()[0])
    time.sleep(3)
vnc = ClienteVNC(os.environ["ESCRITORIO_URL"], os.environ["ESCRITORIO_PASSWORD"])
try:
    img, lineas, _ = observar(vnc)
    Image.fromarray(img).save(RAIZ / "capturas" / "inicio.png")
    print("modal detectado:", detectar_modal(img))
    for ln in lineas:
        print(f"  {ln.caja} {ln.texto}")
    img2, lineas2, informe = cerrar_modal(vnc, img, lineas)
    print("\ninforme cerrar_modal:", informe or "(sin modal)")
    Image.fromarray(img2).save(RAIZ / "capturas" / "tras_modal.png")
    print("modal tras cerrar:", detectar_modal(img2))
    for ln in lineas2:
        print(f"  {ln.caja} {ln.texto}")
finally:
    vnc.cerrar()

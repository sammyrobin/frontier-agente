"""Reinicia la app del escritorio: POST /__reset con Bearer ESCRITORIO_TOKEN.

Uso (desde agente/):  python scripts/reset.py
URL base = ESCRITORIO_URL con wss:// -> https:// y sin /websockify.
Nunca imprime el token ni la URL con credenciales: solo código HTTP y respuesta.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")


def url_base() -> str:
    url = os.environ["ESCRITORIO_URL"]
    url = url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    url = url.split("?", 1)[0].rstrip("/")
    if url.endswith("/websockify"):
        url = url[: -len("/websockify")]
    return url


def llamar(ruta: str, cuerpo: dict | None = None, timeout: float = 30.0) -> tuple[int, str]:
    """POST a ruta del escritorio con el token. Devuelve (código HTTP, texto)."""
    datos = json.dumps(cuerpo or {}).encode()
    req = urllib.request.Request(url_base() + ruta, data=datos, method="POST", headers={
        "Authorization": f"Bearer {os.environ['ESCRITORIO_TOKEN']}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def reset() -> tuple[int, str]:
    return llamar("/__reset")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    codigo, texto = reset()
    print(f"HTTP {codigo}")
    print(texto[:500])
    sys.exit(0 if 200 <= codigo < 300 else 1)

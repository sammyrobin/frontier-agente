"""Filtro de secretos: nada de lo que el agente recibe como credencial sale en el resumen
ni en la traza (contraseña del escritorio, URL del escritorio, tokens, API keys).

Se reemplaza el valor literal y también la versión sin espacios/mayúsculas, por si el LLM
lo reescribe. Nunca se imprime qué secreto coincidió.
"""
from __future__ import annotations

import os
import re

# Variables de entorno que se consideran secretas si existen.
VARIABLES_SECRETAS = ("OPENROUTER_API_KEY", "ESCRITORIO_TOKEN", "ESCRITORIO_PASSWORD",
                      "ESCRITORIO_URL", "AGENTE_TOKEN", "API_TOKEN")
MARCA = "[oculto]"


def secretos_conocidos(extra: list[str] | None = None) -> list[str]:
    valores = [os.environ.get(v, "") for v in VARIABLES_SECRETAS] + list(extra or [])
    out = []
    for v in valores:
        v = (v or "").strip()
        if len(v) < 4:          # un secreto de 1-3 caracteres borraría texto normal
            continue
        out.append(v)
        if "://" in v:          # la URL sin esquema y sin ruta (host) también es secreta
            host = v.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0]
            if len(host) >= 6:
                out.append(host)
    return sorted(set(out), key=len, reverse=True)


def filtrar(texto: str, extra: list[str] | None = None) -> str:
    """Devuelve `texto` sin ningún secreto (comparación sin mayúsculas)."""
    if not texto:
        return texto
    for s in secretos_conocidos(extra):
        texto = re.sub(re.escape(s), MARCA, texto, flags=re.IGNORECASE)
    # Por si el LLM copia una URL de websocket u otra credencial con forma conocida.
    texto = re.sub(r"wss?://\S+", MARCA, texto)
    texto = re.sub(r"\bsk-[A-Za-z0-9_\-]{16,}", MARCA, texto)
    texto = re.sub(r"(?i)bearer\s+\S+", "Bearer " + MARCA, texto)
    return texto

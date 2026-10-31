"""Punto de entrada que usa la API: ejecutar_tarea(tarea, url, password, deadline).

La firma NO cambia (la API depende de ella). Devuelve (estado, resumen) con estado
"terminada" o "fallida". Nunca lanza: cualquier error termina en "fallida" con un resumen
sin secretos. La conexión VNC se cierra siempre.

deadline: instante límite en segundos de time.time() (epoch). Si llega None, 4:40 desde ahora.
"""
from __future__ import annotations

import time
import uuid

from agente.loop import correr
from agente.secretos import filtrar
from agente.vnc import ClienteVNC

DURACION_POR_DEFECTO = 280.0


def ejecutar_tarea(tarea: str, url: str, password: str, deadline: float | None,
                   task_id: str | None = None) -> tuple[str, str]:
    deadline = deadline or (time.time() + DURACION_POR_DEFECTO)
    task_id = task_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    secretos = [password, url]
    vnc = None
    try:
        vnc = ClienteVNC(url, password)
        estado, resumen, _ = correr(vnc, tarea, deadline, task_id)
    except Exception as e:
        estado, resumen = "fallida", f"Error interno del agente ({type(e).__name__}); no completé la tarea."
    finally:
        if vnc is not None:
            try:
                vnc.cerrar()
            except Exception:
                pass
    if estado not in ("terminada", "fallida"):
        estado = "fallida"
    return estado, filtrar(resumen, secretos)

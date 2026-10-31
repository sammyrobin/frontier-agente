"""API del agente (contrato de docs/reto.md).

    GET  /health          -> 200 {"ok": true}
    POST /tasks           -> {"task_id"} enseguida; la tarea va a una cola
    GET  /tasks/{id}      -> {"estado": "en_curso|terminada|fallida", "resumen"}; 404 si no existe

Todas las rutas exigen `Authorization: Bearer <EQUIPO_TOKEN>` (os.environ), comparado con
hmac.compare_digest; sin token o incorrecto -> 401.

Un solo worker (hilo) ejecuta las tareas de a una, en orden de llegada. El deadline de cada
tarea es el instante en que LLEGÓ su POST + 270 s: si espera en cola, su tiempo ya corre.
El worker llama a runner.ejecutar_tarea, que cierra siempre la conexión VNC al terminar.

Nunca se loguean ni se devuelven la contraseña, la URL del escritorio ni tokens: el resumen pasa
por el filtro de secretos y los errores de validación no repiten el cuerpo recibido.

Al importar: si falta EQUIPO_TOKEN o Tesseract no está listo, el proceso no arranca.
"""
from __future__ import annotations

import hmac
import logging
import os
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env", override=False)   # en el servidor ya lo carga systemd (EnvironmentFile)

from agente.percepcion import verificar_tesseract  # noqa: E402
from agente.runner import ejecutar_tarea           # noqa: E402
from agente.secretos import filtrar                # noqa: E402

DURACION_TAREA = 270.0       # s desde que llega el POST
MINIMO_PARA_EMPEZAR = 15.0   # si al salir de la cola queda menos, no se toca el escritorio
RESUMEN_ERROR = "Error interno del agente; no completé la tarea."
RESUMEN_SIN_TIEMPO = "La tarea esperó en cola y se agotó su tiempo antes de empezar; no hice cambios."

log = logging.getLogger("frontier.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ------------------------------------------------------------------ arranque
EQUIPO_TOKEN = os.environ.get("EQUIPO_TOKEN", "").strip()
if len(EQUIPO_TOKEN) < 8:
    raise RuntimeError("EQUIPO_TOKEN no está definido (o es demasiado corto); la API no arranca.")
verificar_tesseract()   # lanza si falta el binario o los modelos -> uvicorn no carga la app
_TOKEN_BYTES = EQUIPO_TOKEN.encode("utf-8")


# ------------------------------------------------------------------ estado
class Escritorio(BaseModel):
    url: str = Field(min_length=1)
    password: str = ""


class NuevaTarea(BaseModel):
    tarea: str = Field(min_length=1)
    escritorio: Escritorio


_tareas: dict[str, dict] = {}          # task_id -> {"estado", "resumen"}
_lock = threading.Lock()
_cola: queue.Queue = queue.Queue()     # (task_id, tarea, url, password, deadline)


def _poner(task_id: str, estado: str, resumen: str) -> None:
    with _lock:
        _tareas[task_id] = {"estado": estado, "resumen": resumen}


def _worker() -> None:
    while True:
        item = _cola.get()
        if item is None:
            return
        task_id, tarea, url, password, deadline = item
        t0 = time.time()
        secretos = [password, url, EQUIPO_TOKEN]
        try:
            if deadline - t0 < MINIMO_PARA_EMPEZAR:
                estado, resumen = "fallida", RESUMEN_SIN_TIEMPO
            else:
                log.info("tarea %s: empieza (le quedan %.0f s)", task_id, deadline - t0)
                estado, resumen = ejecutar_tarea(tarea, url, password, deadline, task_id=task_id)
                if estado not in ("terminada", "fallida"):
                    estado = "fallida"
        except Exception as e:   # el runner no lanza, pero por si acaso: sin traza ni secretos
            log.error("tarea %s: excepción %s", task_id, type(e).__name__)
            estado, resumen = "fallida", RESUMEN_ERROR
        resumen = filtrar(resumen or "", secretos)
        _poner(task_id, estado, resumen)
        log.info("tarea %s: %s en %.1f s", task_id, estado, time.time() - t0)
        _cola.task_done()


@asynccontextmanager
async def _vida(app: FastAPI):
    hilo = threading.Thread(target=_worker, name="worker-tareas", daemon=True)
    hilo.start()
    log.info("API lista (1 worker)")
    yield
    _cola.put(None)


app = FastAPI(lifespan=_vida, docs_url=None, redoc_url=None, openapi_url=None)


# ------------------------------------------------------------------ auth (todas las rutas)
@app.middleware("http")
async def _auth(request: Request, call_next):
    cab = request.headers.get("authorization", "")
    esquema, _, token = cab.partition(" ")
    if esquema.lower() != "bearer" or not hmac.compare_digest(token.strip().encode("utf-8"), _TOKEN_BYTES):
        return JSONResponse({"detail": "no autorizado"}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def _validacion(request: Request, exc: RequestValidationError):
    # Respuesta genérica: el detalle por defecto repetiría el cuerpo (con la contraseña).
    campos = sorted({".".join(str(p) for p in e.get("loc", ())[1:]) for e in exc.errors()})
    return JSONResponse({"detail": "cuerpo inválido", "campos": campos}, status_code=422)


# ------------------------------------------------------------------ rutas
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/tasks")
def crear_tarea(body: NuevaTarea):
    llegada = time.time()
    task_id = uuid.uuid4().hex
    _poner(task_id, "en_curso", "")
    _cola.put((task_id, body.tarea, body.escritorio.url, body.escritorio.password,
               llegada + DURACION_TAREA))
    log.info("tarea %s: en cola (posición %d)", task_id, _cola.qsize())
    return {"task_id": task_id}


@app.get("/tasks/{task_id}")
def ver_tarea(task_id: str):
    with _lock:
        t = _tareas.get(task_id)
        if t is None:
            raise HTTPException(status_code=404, detail="no existe")
        return dict(t)

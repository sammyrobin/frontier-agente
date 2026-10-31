"""Prueba local de la API de punta a punta (sin gastar corridas de evaluación).

Uso (desde agente/):  python scripts/probar_api.py [pruebas/E5-homonimos.json]

1. Reset del escritorio (datos de .env).
2. Levanta uvicorn api.main:app en 127.0.0.1:8787 con un EQUIPO_TOKEN aleatorio.
3. 401 sin token y con token malo, /health 200, 404 de tarea inexistente, 422 sin eco del cuerpo.
4. POST /tasks con la prueba -> task_id (mide que sea < 2 s); GET cada 5 s hasta terminar.
5. POST /__check de la prueba en el escritorio.
6. Revisa que el log del servidor no contenga la contraseña, la URL ni los tokens.
Nunca imprime la URL, la contraseña ni los tokens.
"""
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

from reset import llamar, reset

BASE = "http://127.0.0.1:8787"


def pedir(metodo, ruta, token=None, cuerpo=None, timeout=10):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cab = {"Content-Type": "application/json"}
    if token is not None:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo, headers=cab)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null"), time.time() - t0
    except urllib.error.HTTPError as e:
        cuerpo = e.read()
        try:
            cuerpo = json.loads(cuerpo)
        except Exception:
            cuerpo = cuerpo.decode("utf-8", "replace")[:200]
        return e.code, cuerpo, time.time() - t0


def verificar(nombre, ok):
    print(f"[{'OK ' if ok else 'MAL'}] {nombre}")
    return ok


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    prueba = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else RAIZ / "pruebas/E5-homonimos.json")
                        .read_text(encoding="utf-8"))
    url, password = os.environ["ESCRITORIO_URL"], os.environ["ESCRITORIO_PASSWORD"]
    token = secrets.token_urlsafe(24)
    entorno = dict(os.environ, EQUIPO_TOKEN=token, PYTHONIOENCODING="utf-8")
    log_path = RAIZ / "logs" / "probar_api.log"

    codigo, _ = reset()
    print(f"reset: HTTP {codigo}")
    time.sleep(2.0)

    py = Path(sys.executable)
    with open(log_path, "w", encoding="utf-8") as flog:
        t_arranque = time.time()
        srv = subprocess.Popen([str(py), "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1",
                                "--port", "8787"], cwd=RAIZ, env=entorno, stdout=flog,
                               stderr=subprocess.STDOUT)
        try:
            for _ in range(60):
                time.sleep(0.5)
                try:
                    if pedir("GET", "/health", token)[0] == 200:
                        break
                except Exception:
                    if srv.poll() is not None:
                        print("el servidor no arrancó; ver logs/probar_api.log")
                        return
            print(f"arranque: {time.time() - t_arranque:.1f} s")
            todo = True
            todo &= verificar("401 sin token (/health)", pedir("GET", "/health")[0] == 401)
            todo &= verificar("401 token malo (/health)", pedir("GET", "/health", "x" * 30)[0] == 401)
            todo &= verificar("401 sin token (POST /tasks)",
                              pedir("POST", "/tasks", None, {"tarea": "x", "escritorio": {"url": "u"}})[0] == 401)
            c, b, _ = pedir("GET", "/health", token)
            todo &= verificar(f"/health 200 {b}", c == 200 and b == {"ok": True})
            todo &= verificar("404 tarea inexistente", pedir("GET", "/tasks/nada", token)[0] == 404)
            c, b, _ = pedir("POST", "/tasks", token, {"tarea": "", "escritorio": {"password": "eco-secreto"}})
            todo &= verificar(f"422 cuerpo inválido sin eco ({b})", c == 422 and "eco-secreto" not in json.dumps(b))

            c, b, dt = pedir("POST", "/tasks", token, {"tarea": prueba["instruccion"],
                                                      "escritorio": {"url": url, "password": password}})
            todo &= verificar(f"POST /tasks {c} en {dt:.3f} s (< 2 s)", c == 200 and dt < 2 and "task_id" in b)
            task_id = b["task_id"]
            t0 = time.time()
            while True:
                time.sleep(5)
                c, b, _ = pedir("GET", f"/tasks/{task_id}", token)
                print(f"  t={time.time() - t0:5.0f} s  GET {c} estado={b.get('estado')}")
                if b.get("estado") != "en_curso" or time.time() - t0 > 320:
                    break
            dur = time.time() - t0
            print(f"\n=== {prueba['id']}: {prueba['instruccion']}")
            esperado = prueba.get("estado_esperado")
            todo &= verificar(f"estado {b.get('estado')} (esperado {esperado})", b.get("estado") == esperado)
            print(f"resumen:\n{b.get('resumen')}")
            if prueba.get("respuesta_esperada") is not None:
                print(f"respuesta_esperada: {prueba['respuesta_esperada']}")
            if prueba.get("claves_razon"):
                faltan = [k for k in prueba["claves_razon"] if k not in (b.get("resumen") or "")]
                todo &= verificar(f"claves_razon {prueba['claves_razon']} (faltan {faltan})", not faltan)
            print(f"tiempo de la tarea (POST -> estado final, sondeo cada 5 s): {dur:.0f} s")
            codigo, texto = llamar("/__check", prueba)
            print(f"/__check HTTP {codigo}: {texto[:400]}")
        finally:
            srv.terminate()
            try:
                srv.wait(10)
            except Exception:
                srv.kill()
    contenido = log_path.read_text(encoding="utf-8", errors="replace")
    limpios = all(s not in contenido for s in (password, url, token, os.environ.get("OPENROUTER_API_KEY", "@@")))
    todo &= verificar("el log del servidor no contiene contraseña, URL ni tokens", limpios)
    print("\nRESULTADO:", "todo OK" if todo else "hay fallas")


if __name__ == "__main__":
    main()

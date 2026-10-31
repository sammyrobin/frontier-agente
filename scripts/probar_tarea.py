"""Prueba una tarea de punta a punta: reset -> ejecutar_tarea -> POST /__check.

Uso (desde agente/):  python scripts/probar_tarea.py pruebas/E5-homonimos.json
Imprime estado, resumen, checks, pasos, costo y tiempo. La traza queda en datos/<task_id>.json.
No imprime la URL, la contraseña ni el token.
"""
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

from agente.percepcion import verificar_tesseract
from agente.runner import ejecutar_tarea
from reset import llamar, reset


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    prueba = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    verificar_tesseract()
    codigo, _ = reset()
    print(f"reset: HTTP {codigo}")
    if codigo != 200:
        sys.exit(1)
    time.sleep(2.0)     # el navegador del escritorio se reinicia
    task_id = f"{prueba['id']}-" + time.strftime("%Y%m%d-%H%M%S")
    t0 = time.time()
    estado, resumen = ejecutar_tarea(prueba["instruccion"], os.environ["ESCRITORIO_URL"],
                                     os.environ["ESCRITORIO_PASSWORD"], t0 + 300 - 20, task_id=task_id)
    dur = time.time() - t0
    codigo, texto = llamar("/__check", prueba)
    try:
        check = json.loads(texto)
    except Exception:
        check = {"raw": texto[:300]}
    traza = json.loads((RAIZ / "datos" / f"{task_id}.json").read_text(encoding="utf-8"))

    esperado = prueba.get("estado_esperado")
    print(f"\n=== {prueba['id']}: {prueba['instruccion']}")
    print(f"estado: {estado}  (esperado {esperado}) {'OK' if estado == esperado else 'MAL'}")
    print(f"resumen:\n{resumen}")
    if prueba.get("respuesta_esperada") is not None:
        print(f"respuesta_esperada: {prueba['respuesta_esperada']}")
    if prueba.get("claves_razon"):
        faltan = [c for c in prueba["claves_razon"] if c not in resumen]
        print(f"claves_razon: {prueba['claves_razon']} -> faltan {faltan}")
    print(f"/__check HTTP {codigo}: {json.dumps(check, ensure_ascii=False)}")
    print(f"pasos: {traza['pasos_total']} · llamadas LLM: {traza['llamadas_llm']} · tokens: {traza['tokens']} · "
          f"costo: ${traza['costo']:.4f} · tiempo: {dur:.1f} s")
    print(f"traza: datos/{task_id}.json")
    for p in traza["pasos"]:
        a = {k: v for k, v in p["accion"].items() if k in ("accion", "texto", "etiqueta", "valor", "tecla", "estado") and v}
        print(f"  {p['n']:>2}. [{p['t_total']:5.1f}s llm {p['t_llm']:4.1f}s] {json.dumps(a, ensure_ascii=False)} "
              f"-> {'ok' if p['ok'] else 'ERR'}: {p['resultado'][:160]}")
        if p["accion"].get("razon"):
            print(f"       razón: {str(p['accion']['razon'])[:200]}")


if __name__ == "__main__":
    main()

import json, os, sys, time, urllib.request
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
modelo = sys.argv[1] if len(sys.argv) > 1 else "google/gemini-2.5-flash"
cuerpo = {
    "model": modelo,
    "messages": [
        {"role": "system", "content": "Responde SOLO con JSON valido, sin texto extra."},
        {"role": "user", "content": 'Tarea: abrir la pantalla Clientes. Pantalla: "Archivo Comercial Cartera Herramientas Ayuda". Responde {"accion":"clic","texto":"<texto exacto>"}'},
    ],
}
req = urllib.request.Request(
    "https://openrouter.ai/api/v1/chat/completions",
    data=json.dumps(cuerpo).encode(),
    headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
             "Content-Type": "application/json"},
)
t0 = time.monotonic()
with urllib.request.urlopen(req, timeout=30) as r:
    data = json.load(r)
print(f"Modelo: {modelo} · {time.monotonic() - t0:.1f} s")
print("Respuesta:", data["choices"][0]["message"]["content"])
print("Tokens:", data.get("usage"))

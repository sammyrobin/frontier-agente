# Despliegue (AlmaLinux, usuario `frontier`)

Apache ya hace proxy `https://conqrdev.com/frontier/<ruta>` -> `http://127.0.0.1:8787/<ruta>`.
La app escucha solo en 127.0.0.1:8787, con **un** proceso (`--workers 1`): la cola de tareas vive
en memoria y debe haber un único worker.

## 1. Código y dependencias (como `frontier`)

```bash
sudo -iu frontier
cd ~/agente
git pull
python3.12 -m venv venv            # solo la primera vez
venv/bin/pip install -r requirements.txt
ls tessdata/                       # deben estar spa.traineddata y eng.traineddata (tessdata_fast)
tesseract --version | head -1      # 4.1.1
```

## 2. Variables de entorno: `/home/frontier/agente/.env` (como `frontier`)

Formato `CLAVE=valor`, sin comillas ni `export` (lo lee systemd):

```
EQUIPO_TOKEN=<token del equipo>
OPENROUTER_API_KEY=<key de OpenRouter>
```

```bash
chmod 600 ~/agente/.env
```

Las variables `ESCRITORIO_*` no hacen falta en el servidor: el escritorio llega en cada `POST /tasks`.

## 3. Prueba de arranque manual (como `frontier`, opcional)

```bash
cd ~/agente && set -a && . ./.env && set +a
venv/bin/python -c "import api.main; print('import OK')"
```

Si falta `EQUIPO_TOKEN` o Tesseract/tessdata, falla aquí con un mensaje claro.

## 4. Servicio (como root)

```bash
cp /home/frontier/agente/deploy/frontier.service /etc/systemd/system/frontier.service
systemctl daemon-reload
systemctl enable --now frontier
systemctl status frontier --no-pager
journalctl -u frontier -n 50 --no-pager
```

Tras cada `git pull`: `systemctl restart frontier`.

## 5. Verificación

```bash
TOKEN='<token del equipo>'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/health                         # 401
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/health                        # {"ok":true}
curl -s -H "Authorization: Bearer $TOKEN" https://conqrdev.com/frontier/health                # {"ok":true}
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
     https://conqrdev.com/frontier/tasks/no-existe                                            # 404
```

Los logs (`journalctl -u frontier`) muestran solo task_id, estado y tiempos; nunca la tarea,
la contraseña, la URL del escritorio ni tokens.

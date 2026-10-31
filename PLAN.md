# Plan · 31-oct-2026

Reto: docs/reto.md · Pruebas de práctica: pruebas/ · Diseño: docs/doc-diseno-reto2.pdf

## Hecho
- [x] Repo + .gitignore + GitHub privado (sammyrobin/frontier-agente)
- [x] Python 3.12 + venv
- [x] Tesseract 5.4 + tessdata local (eng, spa, osd)
- [x] agente/vnc.py: conecta, autentica, 1280x800, captura, clic, teclado
- [x] Paso 0: reto y pruebas dentro del repo (docs/reto.md, pruebas/E1..E5) para que viajen con git pull
- [x] Carpetas .claude y docs movidas dentro del repo (antes en C:\hack); deny de Read(.env) verificado
- [x] Paso 5: capturas/captura.png de SIGECOM (scripts/primera_captura.py; conecta 4.1 s, estable 1.1 s)

## Lo que vimos en SIGECOM (captura inicial)
- Barra de título oscura con texto blanco: "SIGECOM · Distribuidora Andina v3.9" y "Hoy: 14/10/2026 · Usuario: operador2".
  → "Hoy" de la app = 14/10/2026 (el sistema dice 31/10). Leerlo por OCR del encabezado.
- Menú superior de texto: Archivo, Comercial, Cartera, Herramientas, Ayuda. "Clientes" no está a la vista (¿dentro de Comercial?).
- El cursor del mouse sale en el framebuffer y puede tapar texto (tapaba "operador2").
- Pista para tareas peligrosas: "Soporte: extensión 214 (fuera de servicio)".

## Siguiente (13:00-14:00) OCR con coordenadas y acciones
- [x] percepcion.py: OCR → palabras/líneas con caja, buscar_texto, fecha_hoy (prueba: scripts/probar_percepcion.py, TODO OK, 1.9 s/captura)
- [x] scripts/reset.py: POST /__reset con Bearer (HTTP 200 {"ok":true})
- [x] accion.py: apartar_mouse, esperar_cambio, clic_en_texto (Resultado estructurado)
- [x] Probar: navegar a Clientes desde un script (scripts/probar_navegacion.py: Comercial > Maestros > Clientes OK)
- [x] Deny de Bash/PowerShell para .env en .claude/settings.json (activo al reiniciar la sesión; probar con prueba_deny/.env); .env.example viaja (excepción al final de .gitignore, verificado con git ls-files)
- [x] OCR en dos pasadas: lee "Buscar" (blanco sobre azul) y "Siguiente"/"Nuevo cliente" (botones con borde). probar_percepcion.py: 25/25 OK
- [x] Velocidad idea 1 (cuerpo x1, zonas oscuras x2): medida, NO acelera (ver tabla); se queda por exactitud
- [x] escribir_en_campo (opción A) + scripts/probar_busqueda.py: Nombre="Ramírez" → Buscar → 9 filas, todas Ramírez
- [x] Las 2 pasadas de Tesseract en paralelo (hilo + proceso aparte): bienvenida 1.97 → 1.16 s, Clientes 4.17 → 3.32 s, mismas líneas. probar_percepcion TODO OK, probar_busqueda OK

## ESTADO al cerrar la sesión (31-oct): percepción + acciones listas, SIN loop todavía
- Hay: vnc.py, percepcion.py (leer_pantalla, buscar_texto, fecha_hoy, detectar_campos, campo_de_etiqueta, leer_zona), accion.py (observar, clic_en_texto con hover, escribir_en_campo con relectura), reset.py y 3 scripts de prueba.
- NO hay: LLM, loop, reglas de código, grafo, API, MySQL, despliegue.

## SIGUIENTE: loop básico con LLM (nueva sesión)
- [ ] agente/loop.py: clasificar → observar → decidir (OpenRouter, solo texto: tarea + OCR + historial) → actuar (clic_en_texto / escribir_en_campo / tecla) → verificar
- [ ] Reglas en código: máx 2 reintentos/paso, bloquear acción repetida en la misma pantalla, corte 4:30, releer antes de "terminada", buscar antes de crear, filtro de secretos
- [ ] Resumen final con el formato (respuesta: …; fallida con datos)
- [ ] Probar con pruebas/E1..E5

## Después del loop básico
- [ ] Combo (Ciudad), ANTES de las 15:00: diseño en respuesta.md del 31-oct (clic, OCR de la lista, buscar_texto, teclado de respaldo, releer la caja, nunca por posición)
- [ ] Mejorar OCR de enlaces (texto azul/subrayado) SIN asumir formato (la evaluación es otra app: nada de regex tipo CL-\d{4}). Síntoma hoy: "1-095", "10032", "cL-0046"; también tildes perdidas en celdas
- [ ] Velocidad idea 2: OCR solo del rectángulo que cambió (diferencia de píxeles antes/después) y reutilizar el resto de las líneas
- [ ] Agrupar filas de tabla (misma y) en el texto para el LLM

## Lo que vimos en Clientes
- Ruta: Comercial (clic) > Maestros (submenú que se abre con HOVER y se cierra si el puntero sale) > Clientes.
- Filtros: Nombre, NIT (campos de texto), Ciudad (combo "Todos"), botones Buscar y Limpiar.
- Aviso: "Busca partes del texto. Distingue tildes: Ramírez no trae Ramirez."
- Botones Nuevo cliente, Exportar. Tabla: Código (enlace CL-xxxx), Razón social o nombre, NIT, Ciudad, Teléfono, Estado (Activo/Inactivo).
- Paginación: Anterior (deshabilitado), Página 1, Siguiente. ~20 filas por página. Muchos nombres casi iguales (Abarrotes Moreno x2, Ramírez/Ramirez).

## 14:00-15:00 Loop con LLM, reglas y grafo
## 15:00 Incidente: la app cambia → re-verificar todo
## 15:00-16:30 Banco de pruebas (reset → tarea → check) y mejoras
## 16:30-17:30 API FastAPI con el contrato
## 17:30-18:00 Despliegue en AlmaLinux (repo a público)
## 18:00 Debrief · 19:00 entrega (por confirmar con organizadores; reto.md dice 20:00) · demo · servidor encendido hasta fin del demo day

## Decisiones tomadas (para el debrief)
- Cliente RFB propio: vncdotool/asyncvnc solo hablan TCP, el escritorio solo wss.
- tessdata_fast: más rápido en CPU débil; texto de pantalla es nítido.
- Python 3.12 (wheels estables para numpy/pillow).
- Reto y pruebas copiados al repo (no movidos): el servidor solo recibe lo que está en git; banco_pruebas.py los envía a /__check.

### OCR (scripts/comparar_ocr.py sobre captura.png, 3 corridas)
| psm | escala | recall | precisión | claves | tiempo |
|-----|--------|--------|-----------|--------|--------|
| 3   | x1     | 77%    | 100%      | 8/10   | 0.8–1.1 s |
| 3   | x2     | 97%    | 94%       | 9/10   | 1.3–1.9 s |
| 11  | x1     | 89%    | 82%       | 8/10   | 0.9–1.1 s |
| 11  | x2     | 97%    | 89%       | 9/10   | 1.3 s |
- Elegido psm 3 x2: x1 no lee el encabezado oscuro (sin fecha "Hoy"); psm 11 mete basura ("14/1", "Hor"). La clave faltante (operador2) la tapaba el cursor → captura_limpia() mueve el mouse a la esquina antes de capturar.
- buscar_texto en cascada: exacta normalizada → contenida (palabra completa) → flexible (ratio ≥ 0.85). Devuelve todas las candidatas ordenadas (homónimos visibles, no se elige a ciegas).
- Destructivas (elimin/borr/anul/cancel): solo coincidencia exacta, y nunca se devuelve una candidata cuya LÍNEA contenga una destructiva si el objetivo no lo es ("cliente" no cae en "Eliminar cliente").
- Normalización: sin acentos, minúsculas, sin puntuación de borde.
- Clic al centro de la FRASE encontrada, no de la línea.
- fecha_hoy: regex dd/mm/aaaa a la derecha de la etiqueta "Hoy", validada con date(); sin etiqueta → None (no adivinar con otra fecha de la pantalla).
- TESSERACT_CMD y TESSDATA_DIR por variable de entorno (AlmaLinux); verificar_tesseract() falla al arrancar si faltan modelos.

### OCR en dos pasadas (13:20-14:00)
- zonas_oscuras: mediana de luminancia por bloques de 8x8 < 128 → bloques vecinos = zona (encabezado, botón azul). Una letra negra no oscurece la mediana de su bloque; un fondo oscuro sí.
- Pasada 1 (cuerpo, x1): zonas oscuras pintadas de blanco + borrado de líneas HORIZONTALES finas (rachas >= 30 px). Con el borde, Tesseract tomaba el botón como imagen ("Siguiente", "Nuevo cliente").
- Pasada 2 (zonas oscuras, x2): cada zona invertida y con el fondo estirado a blanco, apiladas en UN mosaico → una sola llamada a Tesseract; las cajas se devuelven a coordenadas reales.
- Borrar también las verticales dejó a psm 3 sin NINGUNA palabra con el menú abierto (hover de Maestros). Medido en 3 pantallas: solo horizontales pasa las 3. Respaldo: si el cuerpo da < 3 palabras, se relee sin borrar líneas.
- Tiempos (misma corrida, mediana de 4): bienvenida 1.92 s antes → 1.95 s ahora; Clientes 4.70 s → 5.64 s (cuerpo 4.1 + oscuras 1.4). La idea 1 no acelera: Tesseract tarda por cantidad de texto, no por píxeles, y la 2.ª llamada cuesta ~1 s de arranque. Se mantiene porque lee Buscar/Siguiente y conserva más tildes (x1 lee "Rodríguez", x2 "Rodriguez"). Laptop con mucho ruido de medición (±1 s).
- tessedit_do_invert=0 probado: sin ganancia medible → revertido.

### Campos (escribir_en_campo, opción A)
- detectar_campos (sin OCR, 0.1–0.2 s): borde horizontal arriba y abajo con los mismos extremos, 14–40 px de alto, interior BLANCO puro (>= 250; los botones son grises). Descartadas las cajas pegadas a otra (celdas de tabla) y las que contienen otra (recuadro del formulario). Combo = flecha oscura en los últimos ~22 px con franja clara antes.
- campo_de_etiqueta: el más cercano DEBAJO o A LA DERECHA de la etiqueta, a <= 30 px (el título "Clientes" quedaba a 34 px de la caja de Nombre). Más lejos → error, no se adivina.
- Clic, Ctrl+A, escribir el texto DEL ARGUMENTO, apartar puntero, releer SOLO la caja (psm 7, x2, ~0.8 s). Igual → ok; igual salvo tildes → ok con aviso (límite del OCR); distinto → error. Combo → error.
- Etiqueta ambigua ("Nombre" también está en "Razón social o nombre"): mismo desempate que clic_en_texto (etiqueta sola en su línea) + solo cuentan las que tienen caja.
- Hover: el resaltado cambia la lectura del propio elemento ("Maemtros"); ya no cuenta como texto nuevo (se excluye lo que se solapa con el elemento y los símbolos sueltos).

### Acción
- Puntero apartado a una zona de color uniforme elegida mirando la captura (no coordenada de un elemento); se prueba primero cerca de la esquina inferior derecha.
- "Cambió la pantalla" = >0.1 % de píxeles distintos con el puntero en el MISMO lugar antes y después (si no, el propio cursor/hover cuenta como cambio).
- Desempate: si varias candidatas y exactamente una es la línea completa (etiqueta de control) y las demás están dentro de oraciones, se elige esa ("Comercial" del menú vs "comercial." de la bienvenida). Si no, error con la lista (homónimos nunca se eligen solos).
- Submenús por hover: si el clic no cambia la pantalla, se deja el puntero encima y se exige TEXTO NUEVO por OCR (el resaltado no cuenta). No es reintento; luego 1 reintento de clic y error.

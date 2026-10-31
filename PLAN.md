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
- [ ] escribir_en_campo: esperando OK del usuario sobre cómo ubicar un campo vacío
- [ ] OCR no lee texto blanco sobre botón azul ("Buscar") ni "Siguiente"; pierde tildes a veces
- [ ] OCR x2 de la tabla de Clientes tarda 5.6 s (> 3 s): reducir

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

### Acción
- Puntero apartado a una zona de color uniforme elegida mirando la captura (no coordenada de un elemento); se prueba primero cerca de la esquina inferior derecha.
- "Cambió la pantalla" = >0.1 % de píxeles distintos con el puntero en el MISMO lugar antes y después (si no, el propio cursor/hover cuenta como cambio).
- Desempate: si varias candidatas y exactamente una es la línea completa (etiqueta de control) y las demás están dentro de oraciones, se elige esa ("Comercial" del menú vs "comercial." de la bienvenida). Si no, error con la lista (homónimos nunca se eligen solos).
- Submenús por hover: si el clic no cambia la pantalla, se deja el puntero encima y se exige TEXTO NUEVO por OCR (el resaltado no cuenta). No es reintento; luego 1 reintento de clic y error.

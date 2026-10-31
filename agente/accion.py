"""Acción: las "manos" del agente. Ubica elementos por TEXTO (percepcion.py), nunca
por coordenadas fijas, y verifica que la pantalla cambió después de actuar.

Contrato: toda función devuelve Resultado(ok, detalle, captura_despues, ...), nunca
solo True/False; el loop y el grafo usan el detalle y la captura.

Reglas que viven AQUÍ (mecánicas de un solo paso):
  - Antes de capturar se aparta el puntero (tapa texto y activa hover).
  - Varias candidatas -> error con la lista; NO se elige sola (homónimos, E5).
  - Sin candidatas -> error con los textos visibles más parecidos.
  - Un clic sin cambio de pantalla -> 1 reintento; si tampoco, error.
Reglas que NO viven aquí (son del loop): 2 reintentos por paso, bloquear acción
repetida, corte de 4:30.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import numpy as np

from agente.percepcion import (Candidato, Linea, buscar_texto, campo_de_etiqueta, detectar_campos,
                               leer_pantalla, leer_zona, normalizar)

# Fracción de píxeles distintos para decir "la pantalla cambió". El cursor
# parpadeante de un campo cambia ~0.01 %; un menú desplegado, varios %.
UMBRAL_CAMBIO = 0.001


@dataclass
class Resultado:
    ok: bool
    detalle: str
    captura_despues: np.ndarray | None = None
    lineas_despues: list[Linea] | None = None      # OCR de captura_despues (si se hizo)
    candidatas: list[Candidato] = field(default_factory=list)
    cambio: bool = False
    tiempos: dict[str, float] = field(default_factory=dict)  # segundos por etapa


# ---------------- puntero ----------------
def _zona_vacia(imagen: np.ndarray, x: int, y: int, r: int = 12) -> bool:
    """True si el cuadro (2r x 2r) alrededor de (x, y) es de un solo color: sin texto
    ni controles, así el puntero no tapa nada ni activa hover/tooltips."""
    alto, ancho = imagen.shape[:2]
    bloque = imagen[max(0, y - r):min(alto, y + r), max(0, x - r):min(ancho, x + r)]
    return bloque.size > 0 and int(np.ptp(bloque.reshape(-1, 3), axis=0).max()) <= 4


def apartar_mouse(vnc, imagen: np.ndarray | None = None) -> tuple[int, int]:
    """Mueve el puntero a una zona vacía. Se elige mirando la pantalla actual (no es
    una coordenada fija de un elemento): se prueban puntos cerca del borde inferior
    —donde en SIGECOM no hay nada— y se toma el primero de color uniforme.
    Se evita el borde exacto (1 px) porque puede ser el marco de la ventana."""
    w, h = vnc.ancho, vnc.alto
    puntos = [(w - 30, h - 30), (30, h - 30), (w // 2, h - 30), (w - 30, h // 2), (w // 2, h // 2)]
    if imagen is None:
        imagen = vnc.captura()
    for x, y in puntos:
        if _zona_vacia(imagen, x, y):
            vnc.mover(x, y)
            return x, y
    vnc.mover(w - 2, h - 2)  # último recurso: esquina
    return w - 2, h - 2


def diferencia(a: np.ndarray, b: np.ndarray) -> float:
    """Fracción de píxeles distintos entre dos capturas."""
    return float(np.any(a != b, axis=2).mean())


def esperar_cambio(vnc, antes: np.ndarray, maximo: float = 2.5,
                   intervalo: float = 0.2) -> tuple[np.ndarray, bool]:
    """Espera a que la pantalla sea DISTINTA de `antes` y luego estable.
    La app repinta hasta 1 s después del clic: si capturáramos al instante veríamos
    la pantalla vieja y creeríamos que el clic falló. Devuelve (captura, hubo_cambio)."""
    limite = time.monotonic() + maximo
    actual = vnc.captura()
    while diferencia(actual, antes) <= UMBRAL_CAMBIO:
        if time.monotonic() >= limite:
            return actual, False
        time.sleep(intervalo)
        actual = vnc.captura()
    estable, _ = vnc.esperar_estable(maximo=max(1.0, limite - time.monotonic() + 1.0))
    return estable, diferencia(estable, antes) > UMBRAL_CAMBIO


def observar(vnc) -> tuple[np.ndarray, list[Linea], dict[str, float]]:
    """Aparta el puntero, espera pantalla estable y hace OCR. Devuelve tiempos."""
    t0 = time.perf_counter()
    apartar_mouse(vnc)
    imagen, _ = vnc.esperar_estable()
    t1 = time.perf_counter()
    lineas = leer_pantalla(imagen)
    t2 = time.perf_counter()
    return imagen, lineas, {"captura": t1 - t0, "ocr": t2 - t1}


# ---------------- clic por texto ----------------
def parecidos(lineas: list[Linea], objetivo: str, n: int = 5) -> list[str]:
    """Textos visibles más parecidos al objetivo (para explicar un 'no encontrado')."""
    obj = normalizar(objetivo)
    textos = {ln.texto for ln in lineas} | {p.texto for ln in lineas for p in ln.palabras}
    puntuados = sorted(((SequenceMatcher(None, obj, normalizar(t)).ratio(), t) for t in textos), reverse=True)
    return [t for r, t in puntuados[:n] if r >= 0.4]


def _se_solapan(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return (min(a[0] + a[2], b[0] + b[2]) > max(a[0], b[0]) and
            min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1]))


def desempatar(candidatas: list[Candidato], texto: str) -> tuple[list[Candidato], str]:
    """Desempate determinista: un control (menú, botón, etiqueta de campo) está solo
    en su línea; el mismo texto dentro de una oración o encabezado es prosa.
    Solo decide si exactamente UNA candidata es línea completa; si no, las devuelve
    todas y quien llama reporta la ambigüedad (homónimos, E5)."""
    if len(candidatas) > 1:
        solas = [c for c in candidatas if normalizar(c.linea) == normalizar(texto)]
        if len(solas) == 1:
            return solas, f" [desempate: única etiqueta sola en su línea entre {len(candidatas)} candidatas]"
    return candidatas, ""


def clic_en_texto(vnc, texto: str, imagen: np.ndarray | None = None,
                  lineas: list[Linea] | None = None, maximo: float = 2.5) -> Resultado:
    """OCR -> buscar_texto -> clic en el centro de la FRASE -> esperar cambio.
    Si ya se tiene la observación (imagen, lineas) se reutiliza para no repetir OCR."""
    tiempos: dict[str, float] = {}
    if imagen is None or lineas is None:
        imagen, lineas, tiempos = observar(vnc)

    candidatas = buscar_texto(lineas, texto)
    if not candidatas:
        return Resultado(False, f"No encontré '{texto}'. Parecidos visibles: {parecidos(lineas, texto)}",
                         imagen, lineas, tiempos=tiempos)
    candidatas, nota = desempatar(candidatas, texto)
    if len(candidatas) > 1:
        lista = [f"'{c.texto}' @{c.centro} en '{c.linea}'" for c in candidatas]
        return Resultado(False, f"'{texto}' es ambiguo ({len(candidatas)} candidatas): {lista}",
                         imagen, lineas, candidatas, tiempos=tiempos)

    c = candidatas[0]
    textos_antes = {normalizar(ln.texto) for ln in lineas}
    despues = imagen
    for intento in (1, 2):  # 1 reintento como máximo; más reintentos los decide el loop
        t0 = time.perf_counter()
        vnc.clic(*c.centro)
        apartar_mouse(vnc, imagen)  # misma zona que en 'antes': comparación justa, sin hover
        t1 = time.perf_counter()
        despues, cambio = esperar_cambio(vnc, imagen, maximo)
        t2 = time.perf_counter()
        tiempos[f"clic{intento}"] = t1 - t0
        tiempos[f"espera{intento}"] = t2 - t1
        if cambio:
            t3 = time.perf_counter()
            lineas_d = leer_pantalla(despues)
            tiempos["ocr_despues"] = time.perf_counter() - t3
            return Resultado(True, f"Clic en '{c.texto}' @{c.centro} ({c.tipo}); la pantalla cambió"
                             + (" al reintentar" if intento == 2 else "") + nota,
                             despues, lineas_d, [c], True, tiempos)
        if intento == 1:
            # Respaldo para submenús que se abren con hover y se cierran al apartar el
            # puntero (visto en SIGECOM: Comercial > Maestros). Se deja el puntero
            # sobre el elemento y se exige TEXTO NUEVO por OCR: el simple resaltado
            # del elemento no cuenta como cambio. Esto no es un reintento (no hay clic).
            t3 = time.perf_counter()
            vnc.mover(*c.centro)
            hover, _ = vnc.esperar_estable(maximo=2.0)
            lineas_h = leer_pantalla(hover)
            # No cuenta como nuevo: el propio elemento (su lectura cambia al resaltarse:
            # visto "Maestros" -> "Maemtros"), ni símbolos sueltos como ">".
            nuevos = [ln.texto for ln in lineas_h if normalizar(ln.texto) not in textos_antes
                      and normalizar(ln.texto) != normalizar(c.linea)
                      and not _se_solapan(ln.caja, (c.x, c.y, c.w, c.h))
                      and sum(ch.isalnum() for ch in ln.texto) >= 2]
            tiempos["hover"] = time.perf_counter() - t3
            if nuevos:
                return Resultado(True, f"'{c.texto}' @{c.centro} abre contenido con el puntero encima "
                                 f"(submenú); texto nuevo: {nuevos}. El puntero debe quedarse ahí" + nota,
                                 hover, lineas_h, [c], True, tiempos)
    return Resultado(False, f"Clic en '{c.texto}' @{c.centro} sin cambio de pantalla tras 2 intentos",
                     despues, None, [c], False, tiempos)


# ---------------- escribir en un campo ----------------
def _limpiar_lectura(s: str) -> str:
    """Quita el cursor de texto ('|') que el OCR a veces lee al final del campo."""
    return s.replace("|", " ").strip()


def escribir_en_campo(vnc, etiqueta: str, texto: str, imagen: np.ndarray | None = None,
                      lineas: list[Linea] | None = None) -> Resultado:
    """Ubica la caja de texto por su ETIQUETA (encima o a la izquierda; gana la más
    cercana), hace clic, Ctrl+A, escribe y RELEE solo esa caja con OCR.
      - `texto` viene siempre del argumento (la tarea), nunca del OCR.
      - Sin caja detectada -> error claro; no se adivina.
      - Combo -> error: no se escribe en un desplegable (operar_combo, pendiente).
      - Releído distinto -> error (la app concatena si no se seleccionó todo)."""
    tiempos: dict[str, float] = {}
    if imagen is None or lineas is None:
        imagen, lineas, tiempos = observar(vnc)

    t0 = time.perf_counter()
    etiquetas = buscar_texto(lineas, etiqueta)
    if not etiquetas:
        return Resultado(False, f"No encontré la etiqueta '{etiqueta}'. Parecidos visibles: "
                         f"{parecidos(lineas, etiqueta)}", imagen, lineas, tiempos=tiempos)
    campos = detectar_campos(imagen)
    con_caja = []
    motivos = []
    for c in etiquetas:
        campo, porque = campo_de_etiqueta(campos, (c.x, c.y, c.w, c.h))
        motivos.append(f"'{c.linea}' @{c.centro}: {porque}")
        if campo:
            con_caja.append((c, campo))
    tiempos["ubicar_campo"] = time.perf_counter() - t0
    if not con_caja:
        return Resultado(False, f"Etiqueta '{etiqueta}' sin caja de texto detectada: {motivos}. "
                         f"No escribo a ciegas.", imagen, lineas, etiquetas, tiempos=tiempos)
    elegidas, nota = desempatar([c for c, _ in con_caja], etiqueta)
    if len(elegidas) > 1:
        lista = [f"'{c.linea}' @{c.centro} -> caja {k.caja}" for c, k in con_caja]
        return Resultado(False, f"Etiqueta '{etiqueta}' ambigua ({len(lista)} con caja): {lista}",
                         imagen, lineas, elegidas, tiempos=tiempos)
    c, campo = next((c, k) for c, k in con_caja if c is elegidas[0])
    if campo.combo:
        return Resultado(False, f"La caja de '{etiqueta}' {campo.caja} es un desplegable (combo): "
                         f"no se escribe en ella", imagen, lineas, [c], tiempos=tiempos)

    t0 = time.perf_counter()
    vnc.clic(*campo.centro)
    vnc.pulsar("ctrl", "a")      # la app concatena: seleccionar todo antes de escribir
    vnc.escribir(texto)
    apartar_mouse(vnc, imagen)   # el puntero (I) taparía el texto al releer
    despues, _ = vnc.esperar_estable(maximo=2.0)
    tiempos["escribir"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    leido = _limpiar_lectura(leer_zona(despues, campo.interior))
    tiempos["releer"] = time.perf_counter() - t0

    base = f"Campo '{etiqueta}' caja {campo.caja}: escrito {texto!r}, releído {leido!r}"
    if leido == texto:
        return Resultado(True, base + nota, despues, None, [c], True, tiempos)
    if normalizar(leido) == normalizar(texto):
        # El OCR pierde tildes a veces (visto: Rodríguez -> Rodriguez). Lo escrito es el
        # argumento exacto; se avisa para que la verificación final lo confirme.
        return Resultado(True, base + " (coincide salvo tildes/mayúsculas: límite del OCR)" + nota,
                         despues, None, [c], True, tiempos)
    return Resultado(False, base + ": NO coincide" + nota, despues, None, [c], True, tiempos)

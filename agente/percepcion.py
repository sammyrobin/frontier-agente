"""Percepción: captura de pantalla -> texto con cajas (OCR local con Tesseract).

Contrato:
  leer_pantalla(imagen)          -> list[Linea]   (coordenadas en píxeles de la pantalla real)
  buscar_texto(lineas, objetivo) -> list[Candidato] ordenados (vacía si no hay)
  texto_para_llm(lineas)         -> str            (lo único que ve el LLM)
  captura_limpia(vnc)            -> imagen sin el puntero encima del texto
  fecha_hoy(lineas)              -> datetime.date | None  ("Hoy" de la APP, no del sistema)

Rutas configurables por entorno para que funcione igual en Windows y AlmaLinux:
  TESSERACT_CMD  (por defecto: instalación de Windows, o "tesseract" del PATH en Linux)
  TESSDATA_DIR   (por defecto: ./tessdata del repo)
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent

pytesseract.pytesseract.tesseract_cmd = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe" if os.name == "nt" else "tesseract")

TESSDATA_DIR = Path(os.environ.get("TESSDATA_DIR", RAIZ / "tessdata"))
# Tesseract 5 lee los modelos de TESSDATA_PREFIX. Lo fijamos desde TESSDATA_DIR
# en vez de pasar --tessdata-dir: pytesseract parte la línea de comandos distinto
# en Windows y una ruta con espacios se rompe.
os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)

IDIOMAS = "spa+eng"


def verificar_tesseract() -> None:
    """Falla temprano y claro (útil al desplegar): binario y modelos presentes."""
    faltan = [i for i in IDIOMAS.split("+") if not (TESSDATA_DIR / f"{i}.traineddata").exists()]
    if faltan:
        raise RuntimeError(f"Faltan modelos {faltan} en TESSDATA_DIR={TESSDATA_DIR}")
    pytesseract.get_tesseract_version()  # lanza TesseractNotFoundError si no está
# Valores por defecto: se fijan tras comparar en scripts/comparar_ocr.py
PSM = 3
ESCALA = 1           # cuerpo (texto oscuro sobre claro): x1 basta y conserva mejor las tildes
ESCALA_OSCURAS = 2   # zonas oscuras (encabezado, botón azul): invertidas y a x2; ver PLAN.md
UMBRAL_OSCURO = 128  # luminancia mediana de un bloque por debajo de la cual es "fondo oscuro"


# ---------------------------------------------------------------- estructuras
@dataclass
class Palabra:
    texto: str
    x: int
    y: int
    w: int
    h: int
    confianza: float

    @property
    def centro(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass
class Linea:
    palabras: list[Palabra] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)

    @property
    def caja(self) -> tuple[int, int, int, int]:
        return _union(self.palabras)

    @property
    def confianza(self) -> float:
        return min(p.confianza for p in self.palabras)


@dataclass
class Candidato:
    texto: str              # lo que se leyó en pantalla
    tipo: str               # "exacta" | "contenida" | "flexible"
    puntaje: float          # 1.0 exacta/contenida; ratio en flexible
    x: int
    y: int
    w: int
    h: int
    confianza: float        # mínima confianza OCR de las palabras usadas
    linea: str              # línea completa donde apareció (contexto)

    @property
    def centro(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def _union(palabras: list[Palabra]) -> tuple[int, int, int, int]:
    x0 = min(p.x for p in palabras)
    y0 = min(p.y for p in palabras)
    x1 = max(p.x + p.w for p in palabras)
    y1 = max(p.y + p.h for p in palabras)
    return x0, y0, x1 - x0, y1 - y0


# ---------------------------------------------------------------- OCR
def ocr_palabras(imagen: np.ndarray, psm: int = PSM, escala: int = ESCALA) -> list[Palabra]:
    """OCR de la imagen completa. Devuelve palabras con caja en coordenadas originales."""
    img = Image.fromarray(imagen).convert("L")
    if escala != 1:
        img = img.resize((img.width * escala, img.height * escala), Image.LANCZOS)
    datos = pytesseract.image_to_data(
        img, lang=IDIOMAS, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    palabras = []
    for i, texto in enumerate(datos["text"]):
        texto = texto.strip()
        conf = float(datos["conf"][i])
        if not texto or conf < 0:
            continue
        palabras.append(Palabra(
            texto=texto,
            x=round(datos["left"][i] / escala), y=round(datos["top"][i] / escala),
            w=round(datos["width"][i] / escala), h=round(datos["height"][i] / escala),
            confianza=conf))
    return palabras


def agrupar_lineas(palabras: list[Palabra], factor_hueco: float = 1.2) -> list[Linea]:
    """Agrupa por geometría (no por los números de línea de Tesseract, que con
    --psm 11 vienen sueltos). Misma franja vertical + hueco horizontal pequeño
    = misma línea. Un hueco grande la parte: así cada opción de menú queda
    separada aunque estén a la misma altura."""
    # Pasada 1: filas por solapamiento vertical. (Ordenar solo por centro falla:
    # "gestión" tiene descendente y su centro queda más abajo que "comercial.")
    filas: list[list[Palabra]] = []
    for p in sorted(palabras, key=lambda p: p.y):
        for fila in filas:
            y0 = min(q.y for q in fila)
            y1 = max(q.y + q.h for q in fila)
            solape = min(y1, p.y + p.h) - max(y0, p.y)
            if solape >= 0.5 * min(p.h, y1 - y0):
                fila.append(p)
                break
        else:
            filas.append([p])

    # Pasada 2: dentro de cada fila, de izquierda a derecha; un hueco grande parte la línea.
    lineas: list[Linea] = []
    for fila in filas:
        fila.sort(key=lambda p: p.x)
        actual = Linea([fila[0]])
        for p in fila[1:]:
            ult = actual.palabras[-1]
            hueco = p.x - (ult.x + ult.w)
            if hueco <= max(p.h, ult.h) * factor_hueco:
                actual.palabras.append(p)
            else:
                lineas.append(actual)
                actual = Linea([p])
        lineas.append(actual)
    lineas.sort(key=lambda l: (l.caja[1], l.caja[0]))
    return lineas


# ---------------------------------------------------------------- preproceso
def gris(imagen: np.ndarray) -> np.ndarray:
    """RGB -> luminancia float32 (0..255)."""
    return imagen[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)


def zonas_oscuras(g: np.ndarray, bloque: int = 8, umbral: float = UMBRAL_OSCURO,
                  min_w: int = 24, min_h: int = 12) -> list[tuple[int, int, int, int]]:
    """Rectángulos de FONDO oscuro (encabezado, botones de color) donde el texto es
    claro. Tesseract espera texto oscuro sobre claro y ahí falla ("Buscar").
    Se mide la mediana por bloques de 8x8: una letra negra no oscurece la mediana
    de su bloque, un fondo oscuro sí. Bloques vecinos oscuros = una zona; su caja
    se ajusta a las filas/columnas cuya mediana es oscura (bordes exactos)."""
    alto, ancho = g.shape
    gh, gw = alto // bloque, ancho // bloque
    bl = g[:gh * bloque, :gw * bloque].reshape(gh, bloque, gw, bloque).transpose(0, 2, 1, 3)
    oscuro = np.median(bl.reshape(gh, gw, -1), axis=2) < umbral
    visto = np.zeros_like(oscuro)
    rects = []
    for i, j in zip(*np.nonzero(oscuro)):
        if visto[i, j]:
            continue
        pila, visto[i, j] = [(i, j)], True
        i0 = i1 = i
        j0 = j1 = j
        while pila:
            a, c = pila.pop()
            i0, i1, j0, j1 = min(i0, a), max(i1, a), min(j0, c), max(j1, c)
            for na, nc in ((a + 1, c), (a - 1, c), (a, c + 1), (a, c - 1)):
                if 0 <= na < gh and 0 <= nc < gw and oscuro[na, nc] and not visto[na, nc]:
                    visto[na, nc] = True
                    pila.append((na, nc))
        y0, y1 = max(0, (i0 - 1) * bloque), min(alto, (i1 + 2) * bloque)
        x0, x1 = max(0, (j0 - 1) * bloque), min(ancho, (j1 + 2) * bloque)
        sub = g[y0:y1, x0:x1]
        filas = np.nonzero(np.median(sub, axis=1) < umbral)[0]
        cols = np.nonzero(np.median(sub, axis=0) < umbral)[0]
        if len(filas) and len(cols):
            r = (int(x0 + cols[0]), int(y0 + filas[0]),
                 int(cols[-1] - cols[0] + 1), int(filas[-1] - filas[0] + 1))
            if r[2] >= min_w and r[3] >= min_h:
                rects.append(r)
    return rects


def _en_racha(mask: np.ndarray, n: int, eje: int) -> np.ndarray:
    """True donde el píxel pertenece a una racha de >= n Trues seguidos a lo largo de `eje`."""
    m = np.moveaxis(mask, eje, -1).astype(np.int32)
    cero = np.zeros(m.shape[:-1] + (1,), np.int32)
    cs = np.concatenate([cero, np.cumsum(m, axis=-1)], axis=-1)
    llena = (cs[..., n:] - cs[..., :-n]) == n                 # ventana [k, k+n) llena
    cf = np.concatenate([cero, np.cumsum(llena, axis=-1)], axis=-1)
    k = np.arange(m.shape[-1])
    hi = np.minimum(k, llena.shape[-1] - 1) + 1
    lo = np.maximum(k - n + 1, 0)
    return np.moveaxis((cf[..., hi] - cf[..., lo]) > 0, -1, eje)


def quitar_lineas(g: np.ndarray, d: int = 2, contraste: float = 20,
                  largo_h: int = 30, largo_v: int | None = None) -> np.ndarray:
    """Borra líneas finas (bordes de botones, campos y tabla). Con un borde alrededor,
    Tesseract toma el botón como imagen y no lo lee ("Siguiente", "Nuevo cliente").
    Línea = píxel distinto de sus vecinos a +-d px en la perpendicular, en una racha
    recta de >= largo px. Los trazos de letras son más cortos (~10 px) y sobreviven.
    Por defecto SOLO horizontales: borrar ambas dejó a psm 3 sin ninguna palabra con
    un menú abierto (medido en bienvenida, menú con hover y Clientes; ver PLAN.md)."""
    g = g.copy()
    for eje, largo in ((0, largo_h), (1, largo_v)):
        if largo is None:
            continue
        a, c = np.roll(g, d, axis=eje), np.roll(g, -d, axis=eje)
        borde = (np.abs(g - a) > contraste) & (np.abs(g - c) > contraste)
        lin = _en_racha(borde, largo, 1 - eje)
        g[lin] = ((a + c) / 2)[lin]
    return g


def _ocr_gris(g: np.ndarray, psm: int, escala: int) -> dict:
    img = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8))
    if escala != 1:
        img = img.resize((img.width * escala, img.height * escala), Image.LANCZOS)
    return pytesseract.image_to_data(img, lang=IDIOMAS, config=f"--psm {psm}",
                                     output_type=pytesseract.Output.DICT)


def _palabras_de(datos: dict):
    for i, texto in enumerate(datos["text"]):
        texto, conf = texto.strip(), float(datos["conf"][i])
        if texto and conf >= 0:
            yield texto, datos["left"][i], datos["top"][i], datos["width"][i], datos["height"][i], conf


def leer_pantalla(imagen: np.ndarray, psm: int = PSM, escala: int = ESCALA,
                  escala_oscuras: int = ESCALA_OSCURAS, tiempos: dict | None = None) -> list[Linea]:
    """Dos pasadas de OCR sobre la misma captura:
      1. Cuerpo a x`escala`, con las zonas oscuras pintadas de blanco (sin basura ni duplicados).
      2. Zonas oscuras invertidas (texto claro -> oscuro), con el fondo estirado a blanco,
         apiladas en UN mosaico y leídas a x`escala_oscuras` (una sola llamada a Tesseract).
    En ambas se borran las líneas finas antes del OCR. Las cajas vuelven en px reales."""
    t0 = time.perf_counter()
    g = gris(imagen)
    rects = zonas_oscuras(g)
    cuerpo = g.copy()
    for x, y, w, h in rects:
        cuerpo[y:y + h, x:x + w] = 255
    t1 = time.perf_counter()
    datos = list(_palabras_de(_ocr_gris(quitar_lineas(cuerpo), psm, escala)))
    if len(datos) < 3:
        # Respaldo: el análisis de página de psm 3 puede quedarse en blanco tras el
        # preproceso; se repite sin borrar líneas antes que devolver una pantalla vacía.
        datos = list(_palabras_de(_ocr_gris(cuerpo, psm, escala)))
    palabras = [Palabra(t, round(x / escala), round(y / escala), round(w / escala), round(h / escala), c)
                for t, x, y, w, h, c in datos]
    t2 = time.perf_counter()
    if rects:
        m = 10  # margen blanco alrededor de cada pieza del mosaico
        piezas, oy = [], m
        for x, y, w, h in rects:
            inv = 255 - g[y:y + h, x:x + w]
            inv = np.clip(inv * (255.0 / max(float(np.median(inv)), 1.0)), 0, 255)  # fondo -> blanco
            piezas.append((oy, x, y, inv))
            oy += h + 2 * m
        mosaico = np.full((oy, max(w for _, _, w, _ in rects) + 2 * m), 255.0, np.float32)
        for py, _, _, inv in piezas:
            mosaico[py:py + inv.shape[0], m:m + inv.shape[1]] = inv
        mosaico = quitar_lineas(mosaico)
        e = escala_oscuras
        for t, x, y, w, h, c in _palabras_de(_ocr_gris(mosaico, psm, e)):
            cy = (y + h / 2) / e
            for py, rx, ry, inv in piezas:      # a qué pieza pertenece -> coordenadas reales
                if py <= cy < py + inv.shape[0]:
                    palabras.append(Palabra(t, round(rx + x / e - m), round(ry + y / e - py),
                                            round(w / e), round(h / e), c))
                    break
    t3 = time.perf_counter()
    if tiempos is not None:
        tiempos.update(preproceso=t1 - t0, ocr_cuerpo=t2 - t1, ocr_oscuras=t3 - t2)
    return agrupar_lineas(palabras)


@dataclass
class Campo:
    x: int
    y: int
    w: int
    h: int
    combo: bool = False     # tiene flecha a la derecha: es un desplegable, no se escribe en él

    @property
    def caja(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h

    @property
    def interior(self) -> tuple[int, int, int, int]:
        """Caja sin el borde: lo que se relee con OCR tras escribir."""
        return self.x + 2, self.y + 2, self.w - 4, self.h - 4

    @property
    def centro(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def _segmentos(fila: np.ndarray) -> list[tuple[int, int]]:
    """Tramos [x0, x1) de Trues seguidos en un vector booleano."""
    d = np.diff(np.concatenate([[0], fila.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def detectar_campos(imagen: np.ndarray, min_w: int = 40, alto_min: int = 14,
                    alto_max: int = 40) -> list[Campo]:
    """Cajas de texto (y combos) por geometría, sin OCR: un borde horizontal arriba y
    otro abajo con los mismos extremos (+-3 px), separados 14-40 px, con interior
    claro (mediana >= 200). Así se ubica un campo VACÍO, que el OCR no puede ver.
    Combo = interior con trazo oscuro en los últimos ~22 px (la flecha) y una
    franja clara justo antes."""
    g = gris(imagen)
    a, c = np.roll(g, 2, axis=0), np.roll(g, -2, axis=0)
    borde = (np.abs(g - a) > 20) & (np.abs(g - c) > 20)
    lineas_h = _en_racha(borde, min_w, 1)
    segs: list[tuple[int, int, int]] = []          # (y, x0, x1), sin repetir bordes gruesos
    for y in np.nonzero(lineas_h.any(axis=1))[0]:
        for x0, x1 in _segmentos(lineas_h[y]):
            if not any(abs(y - sy) <= 2 and abs(x0 - sx0) <= 3 and abs(x1 - sx1) <= 3 for sy, sx0, sx1 in segs):
                segs.append((int(y), int(x0), int(x1)))
    campos: list[Campo] = []
    for i, (yt, x0, x1) in enumerate(segs):
        abajo = [(yb, bx0, bx1) for yb, bx0, bx1 in segs[i + 1:]
                 if alto_min <= yb - yt <= alto_max and abs(bx0 - x0) <= 3 and abs(bx1 - x1) <= 3]
        if not abajo:
            continue
        yb = min(abajo)[0]                           # el borde inferior más cercano
        interior = g[yt + 2:yb - 1, x0 + 2:x1 - 2]
        # Blanco puro: los botones tienen degradado gris (~235-245) y no son campos.
        if interior.size == 0 or np.median(interior) < 250:
            continue
        flecha = interior[:, -22:-4]
        antes = interior[:, -34:-24]
        combo = bool((flecha < 120).any() and antes.size and (antes > 200).all())
        campos.append(Campo(x0, yt, x1 - x0, yb - yt + 1, combo))
    # Un campo que contiene a otro (el recuadro del formulario) no es un campo.
    campos = [k for k in campos if not any(o is not k and o.x >= k.x and o.y >= k.y and
                                           o.x + o.w <= k.x + k.w and o.y + o.h <= k.y + k.h
                                           for o in campos)]

    # Celdas de tabla: comparten borde con otra caja (arriba/abajo o a los lados).
    # Un campo real está separado de los demás por margen.
    def pegadas(k: Campo, o: Campo) -> bool:
        solape_x = min(k.x + k.w, o.x + o.w) - max(k.x, o.x) > 0
        solape_y = min(k.y + k.h, o.y + o.h) - max(k.y, o.y) > 0
        return ((solape_x and (abs(k.y + k.h - o.y) <= 3 or abs(o.y + o.h - k.y) <= 3)) or
                (solape_y and (abs(k.x + k.w - o.x) <= 3 or abs(o.x + o.w - k.x) <= 3)))
    return [k for k in campos if not any(o is not k and pegadas(k, o) for o in campos)]


def campo_de_etiqueta(campos: list[Campo], etiqueta: tuple[int, int, int, int],
                      max_dist: int = 30) -> tuple[Campo | None, str]:
    """El campo de una etiqueta: el más cercano que esté DEBAJO (empieza bajo la
    etiqueta y se solapa en x) o A LA DERECHA (misma franja vertical). Más lejos de
    max_dist px -> None: mejor un error claro que escribir en el campo equivocado."""
    lx, ly, lw, lh = etiqueta
    opciones = []
    for k in campos:
        if k.y >= ly + lh - 2 and k.x <= lx + lw and k.x + k.w >= lx:            # debajo
            opciones.append((abs(k.y - (ly + lh)) + abs(k.x - lx) / 4, "debajo", k))
        elif k.x >= lx + lw - 2 and k.y <= ly + lh // 2 <= k.y + k.h:          # derecha
            opciones.append((k.x - (lx + lw), "derecha", k))
    opciones = sorted((o for o in opciones if o[0] <= max_dist), key=lambda o: o[0])
    if not opciones:
        return None, f"no hay caja de texto a <= {max_dist} px debajo ni a la derecha de la etiqueta"
    d, donde, k = opciones[0]
    return k, f"caja {k.caja} {donde} de la etiqueta (a {d:.0f} px)"


def leer_zona(imagen: np.ndarray, caja: tuple[int, int, int, int], escala: int = 2) -> str:
    """OCR de UN rectángulo (p. ej. un campo recién escrito): psm 7 = una sola línea.
    Recorte pequeño -> rápido. Si el fondo es oscuro se invierte."""
    x, y, w, h = caja
    g = gris(imagen)[max(0, y):y + h, max(0, x):x + w]
    if g.size == 0:
        return ""
    if np.median(g) < UMBRAL_OSCURO:
        g = 255 - g
    g = np.pad(g, 8, constant_values=float(np.median(g)))
    return " ".join(t for t, *_ in _palabras_de(_ocr_gris(g, 7, escala)))


def captura_limpia(vnc):
    """Aparta el puntero a la esquina inferior derecha antes de capturar para
    que no tape texto. No ubica ningún elemento: solo quita el cursor."""
    vnc.mover(vnc.ancho - 1, vnc.alto - 1)
    return vnc.esperar_estable()


def texto_para_llm(lineas: list[Linea]) -> str:
    """Una línea por renglón: '[n] texto  @x,y'. El LLM responde con el texto
    (o el número) y el código ubica la caja; nunca le pedimos coordenadas."""
    out = []
    for i, ln in enumerate(lineas):
        x, y, w, h = ln.caja
        out.append(f"[{i}] {ln.texto}  @{x + w // 2},{y + h // 2}")
    return "\n".join(out)


# ---------------------------------------------------------------- fecha "Hoy"
_FECHA = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")


def _fecha_valida(texto: str) -> date | None:
    """dd/mm/aaaa -> date, solo si existe de verdad (31/02 o 14/13 -> None)."""
    m = _FECHA.search(texto)
    if not m:
        return None
    d, mes, a = map(int, m.groups())
    try:
        return date(a, mes, d)
    except ValueError:
        return None


def fecha_hoy(lineas: list[Linea]) -> date | None:
    """Fecha que la app llama "Hoy". Se busca la palabra 'Hoy' y la fecha más
    cercana A SU DERECHA en la misma fila (la agrupación puede dejarlas en
    líneas distintas). Sin etiqueta 'Hoy' -> None: no adivinamos con otra
    fecha de la pantalla, y quien llama decide qué hacer."""
    palabras = [p for ln in lineas for p in ln.palabras]
    for hoy in (p for p in palabras if normalizar(p.texto) == "hoy"):
        cy = hoy.y + hoy.h / 2
        derecha = sorted((p for p in palabras
                          if p.x > hoy.x and abs((p.y + p.h / 2) - cy) <= max(p.h, hoy.h) * 0.6),
                         key=lambda p: p.x)
        for p in derecha[:3]:          # la fecha va justo después ("Hoy: 14/10/2026")
            f = _fecha_valida(p.texto)
            if f:
                return f
    return None


# ---------------------------------------------------------------- búsqueda
# Raíces: cubren "Eliminar", "eliminado", "Borrar", "Anular", "Cancelar", "cancelación"...
DESTRUCTIVAS = ("elimin", "borr", "anul", "cancel")
UMBRAL_FLEXIBLE = 0.85


def normalizar(s: str) -> str:
    """minúsculas, sin acentos, sin puntuación en los bordes de cada palabra,
    espacios colapsados. 'Módulos.' -> 'modulos'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    tokens = [t.strip(".,:;()[]{}!?¡¿\"'·-") for t in s.split()]
    return " ".join(t for t in tokens if t)


def es_destructiva(s: str) -> bool:
    return any(t.startswith(DESTRUCTIVAS) for t in normalizar(s).split())


def _ventanas(linea: Linea, tamanos):
    n = len(linea.palabras)
    for k in tamanos:
        if k < 1:
            continue
        for i in range(0, n - k + 1):
            yield linea.palabras[i:i + k]


def _candidato(palabras, linea, tipo, puntaje) -> Candidato:
    x, y, w, h = _union(palabras)
    return Candidato(" ".join(p.texto for p in palabras), tipo, round(puntaje, 3),
                     x, y, w, h, min(p.confianza for p in palabras), linea.texto)


def buscar_texto(lineas: list[Linea], objetivo: str,
                 umbral: float = UMBRAL_FLEXIBLE) -> list[Candidato]:
    """Cascada: exacta normalizada -> contenida -> flexible (umbral alto).
    Se detiene en el primer nivel con resultados y devuelve TODOS los de ese
    nivel ordenados (puntaje, confianza, arriba-abajo). Varias candidatas =
    ambigüedad: decide quien llama, no esta función.

    Seguridad:
      - Objetivo destructivo (eliminar, borrar, anular, cancelar): solo exacta.
      - En los tres niveles se descartan líneas destructivas si el objetivo
        no lo es: buscar "Cliente" nunca debe acabar en "Eliminar cliente".
    """
    obj = normalizar(objetivo)
    if not obj:
        return []
    n = len(obj.split())
    obj_destructivo = es_destructiva(objetivo)

    def ordenar(cs):
        # quitar duplicados de la misma caja
        vistos, unicos = set(), []
        for c in cs:
            clave = (c.x, c.y, c.w, c.h)
            if clave not in vistos:
                vistos.add(clave)
                unicos.append(c)
        return sorted(unicos, key=lambda c: (-c.puntaje, -c.confianza, c.y, c.x))

    # Se revisa la LÍNEA completa, no solo la ventana: "cliente" dentro de
    # "Eliminar cliente" es una coincidencia exacta de la ventana y sería un desastre.
    seguro = lambda c: obj_destructivo or not es_destructiva(c.linea)

    # 1. exacta: una ventana de palabras cuyo texto normalizado es igual
    exactas = [_candidato(v, ln, "exacta", 1.0)
               for ln in lineas for v in _ventanas(ln, [n])
               if normalizar(" ".join(p.texto for p in v)) == obj]
    exactas = [c for c in exactas if seguro(c)]
    if exactas or obj_destructivo:
        return ordenar(exactas)

    # 2. contenida: el objetivo aparece como palabras completas dentro de la
    #    línea (OCR pegó o partió palabras). Caja = ventana mínima que lo contiene.
    patron = re.compile(r"(?<!\w)" + re.escape(obj) + r"(?!\w)")
    contenidas = []
    for ln in lineas:
        if not patron.search(normalizar(ln.texto)):
            continue
        for k in range(1, len(ln.palabras) + 1):
            hallado = [v for v in _ventanas(ln, [k])
                       if patron.search(normalizar(" ".join(p.texto for p in v)))]
            if hallado:
                contenidas += [_candidato(v, ln, "contenida", 1.0) for v in hallado]
                break
    contenidas = [c for c in contenidas if seguro(c)]
    if contenidas:
        return ordenar(contenidas)

    # 3. flexible: parecido de cadenas con ventanas de n-1..n+1 palabras
    flexibles = []
    for ln in lineas:
        for v in _ventanas(ln, [n - 1, n, n + 1]):
            r = SequenceMatcher(None, obj, normalizar(" ".join(p.texto for p in v))).ratio()
            if r >= umbral:
                flexibles.append(_candidato(v, ln, "flexible", r))
    return ordenar([c for c in flexibles if seguro(c)])

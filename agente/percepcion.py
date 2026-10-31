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
ESCALA = 2   # x2: lee el encabezado oscuro (fecha "Hoy"); ver PLAN.md


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


def leer_pantalla(imagen: np.ndarray, psm: int = PSM, escala: int = ESCALA) -> list[Linea]:
    return agrupar_lineas(ocr_palabras(imagen, psm, escala))


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

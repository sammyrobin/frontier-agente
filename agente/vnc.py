"""
Cliente VNC mínimo (protocolo RFB 3.8 / 3.3) sobre websocket, para escritorios
expuestos con websockify (wss://.../websockify).

Por qué propio: vncdotool y asyncvnc solo hablan TCP directo. websockify mete el
mismo flujo RFB dentro de mensajes websocket binarios, que no respetan los
límites de los mensajes RFB, así que leemos todo a través de un buffer.
"""
import struct
import time

import numpy as np
from Crypto.Cipher import DES
from websockets.sync.client import connect

# Keysyms X11 de teclas especiales
TECLAS = {
    "enter": 0xFF0D, "tab": 0xFF09, "esc": 0xFF1B, "backspace": 0xFF08,
    "delete": 0xFFFF, "home": 0xFF50, "end": 0xFF57,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "pageup": 0xFF55, "pagedown": 0xFF56,
    "ctrl": 0xFFE3, "shift": 0xFFE1, "alt": 0xFFE9,
}


class ErrorVNC(Exception):
    pass


class ClienteVNC:
    def __init__(self, url, password, timeout=15.0):
        self._password = password
        self._buf = bytearray()
        self.ws = connect(url, subprotocols=["binary"], max_size=None,
                          open_timeout=timeout)
        self.ancho = self.alto = 0
        self.nombre = ""
        self.fb = None
        self.actualizaciones = 0
        self._handshake()
        # Esperar el primer cuadro completo: sin esto, la primera captura sale negra
        while self.actualizaciones == 0:
            self._procesar_mensaje()

    # ---------------- transporte ----------------
    def _leer(self, n, timeout=15.0):
        while len(self._buf) < n:
            try:
                datos = self.ws.recv(timeout=timeout)
            except TimeoutError:
                raise ErrorVNC(f"timeout esperando {n} bytes del servidor")
            if isinstance(datos, str):
                datos = datos.encode("latin-1")
            self._buf += datos
        salida = bytes(self._buf[:n])
        del self._buf[:n]
        return salida

    def _enviar(self, datos):
        self.ws.send(datos)

    def _leer_razon(self):
        largo = struct.unpack(">I", self._leer(4))[0]
        return self._leer(largo).decode("utf-8", "replace")

    # ---------------- handshake ----------------
    def _respuesta_vnc(self, reto):
        clave = self._password.encode("latin-1")[:8].ljust(8, b"\0")
        # Particularidad de VNC: cada byte de la clave va con los bits invertidos
        clave = bytes(int(f"{b:08b}"[::-1], 2) for b in clave)
        return DES.new(clave, DES.MODE_ECB).encrypt(reto)

    def _handshake(self):
        version = self._leer(12)
        if not version.startswith(b"RFB "):
            raise ErrorVNC(f"no es un servidor RFB: {version!r}")
        v38 = (int(version[4:7]), int(version[8:11])) >= (3, 8)
        self._enviar(b"RFB 003.008\n" if v38 else b"RFB 003.003\n")

        if v38:
            n = self._leer(1)[0]
            if n == 0:
                raise ErrorVNC("el servidor rechazó la conexión: " + self._leer_razon())
            tipos = list(self._leer(n))
            if 2 in tipos:
                tipo = 2          # autenticación VNC con contraseña
            elif 1 in tipos:
                tipo = 1          # sin autenticación
            else:
                raise ErrorVNC(f"tipos de seguridad no soportados: {tipos}")
            self._enviar(bytes([tipo]))
        else:
            tipo = struct.unpack(">I", self._leer(4))[0]
            if tipo == 0:
                raise ErrorVNC("el servidor rechazó la conexión: " + self._leer_razon())

        if tipo == 2:
            self._enviar(self._respuesta_vnc(self._leer(16)))
        if tipo == 2 or v38:
            if struct.unpack(">I", self._leer(4))[0] != 0:
                razon = self._leer_razon() if v38 else ""
                raise ErrorVNC(f"autenticación fallida (¿contraseña correcta?) {razon}")

        self._enviar(b"\x01")  # ClientInit: sesión compartida
        self.ancho, self.alto = struct.unpack(">HH", self._leer(4))
        self._leer(16)  # formato de píxel del servidor; lo reemplazamos abajo
        self.nombre = self._leer(struct.unpack(">I", self._leer(4))[0]).decode("utf-8", "replace")

        # Pedimos 32 bpp little endian: cada píxel llega como B, G, R, X
        self._enviar(struct.pack(">B3xBBBBHHHBBB3x", 0, 32, 24, 0, 1,
                                 255, 255, 255, 16, 8, 0))
        codificaciones = [1, 0, -223]  # CopyRect, Raw, DesktopSize
        self._enviar(struct.pack(">BxH", 2, len(codificaciones))
                     + b"".join(struct.pack(">i", c) for c in codificaciones))
        self.fb = np.zeros((self.alto, self.ancho, 3), dtype=np.uint8)
        self._pedir(incremental=False)

    # ---------------- pantalla ----------------
    def _pedir(self, incremental=True):
        self._enviar(struct.pack(">BBHHHH", 3, int(incremental), 0, 0,
                                 self.ancho, self.alto))

    def _procesar_mensaje(self):
        tipo = self._leer(1)[0]
        if tipo == 0:  # FramebufferUpdate
            self._leer(1)
            n = struct.unpack(">H", self._leer(2))[0]
            for _ in range(n):
                x, y, w, h, cod = struct.unpack(">HHHHi", self._leer(12))
                if cod == 0:  # Raw
                    px = np.frombuffer(self._leer(w * h * 4), dtype=np.uint8).reshape(h, w, 4)
                    self.fb[y:y + h, x:x + w] = px[:, :, 2::-1]  # BGRX -> RGB
                elif cod == 1:  # CopyRect
                    sx, sy = struct.unpack(">HH", self._leer(4))
                    self.fb[y:y + h, x:x + w] = self.fb[sy:sy + h, sx:sx + w].copy()
                elif cod == -223:  # DesktopSize
                    self.ancho, self.alto = w, h
                    self.fb = np.zeros((h, w, 3), dtype=np.uint8)
                else:
                    raise ErrorVNC(f"codificación inesperada: {cod}")
            self.actualizaciones += 1
        elif tipo == 1:  # SetColourMapEntries (no aplica en true color)
            _, _, n = struct.unpack(">BHH", self._leer(5))
            self._leer(n * 6)
        elif tipo == 2:  # Bell
            pass
        elif tipo == 3:  # ServerCutText
            self._leer(3)
            self._leer(struct.unpack(">I", self._leer(4))[0])
        else:
            raise ErrorVNC(f"mensaje desconocido del servidor: {tipo}")

    def _bombear(self, espera):
        """Procesa mensajes hasta que el servidor pase `espera` s sin mandar nada."""
        while True:
            if not self._buf:
                try:
                    datos = self.ws.recv(timeout=espera)
                except TimeoutError:
                    return
                self._buf += datos if isinstance(datos, bytes) else datos.encode("latin-1")
            self._procesar_mensaje()

    def captura(self, espera=0.4):
        """Pide cambios y devuelve la pantalla actual (matriz alto x ancho x RGB)."""
        self._pedir(incremental=True)
        self._bombear(espera)
        return self.fb.copy()

    def esperar_estable(self, intervalo=0.25, maximo=3.0, tolerancia=0.0005):
        """Captura hasta que dos cuadros seguidos sean casi iguales.
        tolerancia = fracción de píxeles distintos permitida (cursor parpadeante)."""
        anterior = self.captura()
        limite = time.monotonic() + maximo
        while time.monotonic() < limite:
            time.sleep(intervalo)
            actual = self.captura()
            if np.any(actual != anterior, axis=2).mean() <= tolerancia:
                return actual, True
            anterior = actual
        return anterior, False

    # ---------------- mouse y teclado ----------------
    def mover(self, x, y, botones=0):
        self._enviar(struct.pack(">BBHH", 5, botones, int(x), int(y)))

    def clic(self, x, y, duracion=0.15, boton=1):
        """boton: 1 izquierdo, 2 central, 4 derecho. 150 ms: la app ignora < 100 ms."""
        self.mover(x, y)
        time.sleep(0.05)
        self.mover(x, y, boton)
        time.sleep(duracion)
        self.mover(x, y, 0)

    def _tecla(self, keysym, abajo):
        self._enviar(struct.pack(">BBxxI", 4, 1 if abajo else 0, keysym))

    def pulsar(self, *teclas):
        """pulsar('enter'), pulsar('ctrl', 'a'): mantiene todas y suelta en orden inverso."""
        syms = [TECLAS.get(t, ord(t) if len(t) == 1 else None) for t in teclas]
        if None in syms:
            raise ValueError(f"tecla desconocida en {teclas}")
        for s in syms:
            self._tecla(s, True)
            time.sleep(0.03)
        for s in reversed(syms):
            self._tecla(s, False)
            time.sleep(0.03)

    def escribir(self, texto):
        for c in texto:
            if c == "\n":
                self.pulsar("enter")
                continue
            cp = ord(c)
            keysym = cp if cp < 256 else 0x01000000 + cp  # á, ñ caben en latin-1
            self._tecla(keysym, True)
            self._tecla(keysym, False)
            time.sleep(0.02)

    def cerrar(self):
        try:
            self.ws.close()
        except Exception:
            pass
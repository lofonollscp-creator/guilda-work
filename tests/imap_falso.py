"""Servidor IMAP falso en memoria, con la semántica que importa para sincronizar: varias
carpetas, UID/UIDVALIDITY, banderas, papelera, UIDPLUS y fallos inyectables. Cada conexión es
una `ConexionIMAP` con la misma interfaz que `imaplib.IMAP4`."""
import imaplib
from email.message import EmailMessage


def crudo(asunto: str, remitente: str = "a@b.com", cuerpo: str = "cuerpo", message_id: str | None = None) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = remitente
    msg["To"] = "yo@ejemplo.com"
    msg["Date"] = "Mon, 13 Jul 2026 09:00:00 +0000"
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(cuerpo)
    return bytes(msg)


class Carpeta:
    def __init__(self, nombre: str, atributos: str = "\\HasNoChildren"):
        self.nombre, self.atributos = nombre, atributos
        self.uidvalidity = 1000
        self.siguiente = 1
        self.modseq = 1                       # HIGHESTMODSEQ de la carpeta (CONDSTORE)
        self.mensajes: dict[int, dict] = {}


class ServidorIMAP:
    def __init__(self, carpetas=("INBOX",), papelera: str | None = None, uidplus: bool = True, cola_fetch: str = "estandar", condstore: bool = False):
        self.carpetas = {n: Carpeta(n) for n in carpetas}
        if papelera:
            self.carpetas[papelera] = Carpeta(papelera, "\\HasNoChildren \\Trash")
        self.uidplus = uidplus
        self.condstore = condstore            # anuncia CONDSTORE/ENABLE, da HIGHESTMODSEQ y entiende CHANGEDSINCE
        self.cola_fetch = cola_fetch          # "estandar": FLAGS en la cabecera; "tras_literal": FLAGS después del literal
        self.registro: list[tuple] = []       # (comando, args) de todo lo que llega
        self.fallar: dict[str, str] = {}      # comando -> "NO" | "abort": hace fallar ese comando
        self.conexiones = 0

    # --- preparar el servidor ---
    def anadir(self, carpeta: str, asunto: str, flags=(), **kw) -> int:
        c = self.carpetas[carpeta]
        uid = c.siguiente
        c.siguiente += 1
        c.modseq += 1
        c.mensajes[uid] = {"crudo": crudo(asunto, **kw), "flags": {f.lower() for f in flags}, "modseq": c.modseq}
        return uid

    def poner_flags(self, carpeta: str, uid: int, *flags: str) -> None:
        self.carpetas[carpeta].mensajes[uid]["flags"] = {f.lower() for f in flags}
        self._tocar(carpeta, uid)

    def _tocar(self, carpeta: str, uid: int) -> None:
        c = self.carpetas[carpeta]
        c.modseq += 1
        c.mensajes[uid]["modseq"] = c.modseq

    def borrar(self, carpeta: str, uid: int) -> None:
        del self.carpetas[carpeta].mensajes[uid]

    def flags(self, carpeta: str, uid: int) -> set[str]:
        return self.carpetas[carpeta].mensajes[uid]["flags"]

    def uids(self, carpeta: str) -> list[int]:
        return sorted(self.carpetas[carpeta].mensajes)

    def carpetas_por_objeto_tocar(self, carpeta, uid: int) -> None:
        carpeta.modseq += 1
        carpeta.mensajes[uid]["modseq"] = carpeta.modseq

    def comandos(self, nombre: str) -> list[tuple]:
        return [a for c, a in self.registro if c == nombre]

    def conexion(self, *args, **kwargs):
        self.conexiones += 1
        return ConexionIMAP(self)


class ConexionIMAP:
    def __init__(self, servidor: ServidorIMAP):
        self.s = servidor
        self.actual: Carpeta | None = None
        self.capabilities = ("IMAP4REV1", "UIDPLUS") if servidor.uidplus else ("IMAP4REV1",)
        if servidor.condstore:
            self.capabilities += ("ENABLE", "CONDSTORE")
        self._condstore_pedido = False
        self._ok: list = [None]

    def _entrada(self, comando: str, *args):
        self.s.registro.append((comando, args))
        modo = self.s.fallar.get(comando)
        if modo == "abort":
            raise imaplib.IMAP4.abort("conexión perdida")
        if modo == "NO":
            return False
        return True

    def login(self, usuario, contrasena):
        return "OK", [b"Logged in"]

    def enable(self, capacidad):
        self._entrada("enable", capacidad)
        if capacidad.upper() == "CONDSTORE" and self.s.condstore:
            self._condstore_pedido = True
            return "OK", [b"CONDSTORE"]
        return "NO", [b"no soportado"]

    def list(self):
        return "OK", [f'({c.atributos}) "/" "{c.nombre}"'.encode() for c in self.s.carpetas.values()]

    def select(self, carpeta, readonly=False):
        nombre = carpeta.strip('"')
        self._entrada("select", nombre)
        if nombre not in self.s.carpetas:
            return "NO", [b"no existe"]
        self.actual = self.s.carpetas[nombre]
        # Como Dovecot: HIGHESTMODSEQ en el SELECT solo si el cliente activó CONDSTORE antes.
        self._ok = [f"[HIGHESTMODSEQ {self.actual.modseq}] Ok".encode()] if self._condstore_pedido else [None]
        return "OK", [str(len(self.actual.mensajes)).encode()]

    def response(self, codigo):
        if codigo == "OK":
            return codigo, self._ok
        if codigo == "UIDVALIDITY" and self.actual:
            return codigo, [str(self.actual.uidvalidity).encode()]
        return codigo, [None]

    def _expandir(self, especificacion: str) -> list[int]:
        existentes = sorted(self.actual.mensajes)
        resultado: set[int] = set()
        for trozo in str(especificacion).split(","):
            if ":" in trozo:
                a, b = trozo.split(":")
                maximo = max(existentes, default=0)
                desde = maximo if a == "*" else int(a)
                hasta = maximo if b == "*" else int(b)
                bajo, alto = sorted((desde, hasta))
                resultado.update(u for u in existentes if bajo <= u <= alto)
                if "*" in (a, b) and existentes:
                    resultado.add(maximo)
            elif trozo.isdigit():
                resultado.add(int(trozo))
        return sorted(u for u in resultado if u in self.actual.mensajes)

    def uid(self, comando, *args):
        if not self._entrada(f"uid_{comando}", *args):
            return "NO", [b"fallo"]
        if comando == "search":
            criterio = args[1:]
            if criterio and criterio[0] == "UID":
                uids = self._expandir(criterio[1])
            else:
                uids = sorted(self.actual.mensajes)
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if comando == "fetch":
            pedidos = self._expandir(args[0])
            if len(args) > 2 and str(args[2]).upper().startswith("(CHANGEDSINCE"):
                if not self._condstore_pedido:
                    return "BAD", [b"CONDSTORE no activado"]
                desde = int(str(args[2]).strip("()").split()[1])
                pedidos = [u for u in pedidos if self.actual.mensajes[u].get("modseq", 0) > desde]
            con_cuerpo = "BODY" in args[1] or "RFC822" in args[1]
            respuesta: list = []
            for n, uid in enumerate(pedidos, 1):
                m = self.actual.mensajes[uid]
                banderas = " ".join(sorted(m["flags"]))
                if con_cuerpo and self.s.cola_fetch == "tras_literal":
                    respuesta.append((f"{n} (UID {uid} BODY[] {{{len(m['crudo'])}}}".encode(), m["crudo"]))
                    respuesta.append(f" FLAGS ({banderas}))".encode())
                elif con_cuerpo:
                    respuesta.append((f"{n} (UID {uid} FLAGS ({banderas}) BODY[] {{{len(m['crudo'])}}}".encode(), m["crudo"]))
                    respuesta.append(b")")
                elif self._condstore_pedido:
                    respuesta.append(f"{n} (UID {uid} MODSEQ ({m.get('modseq', 0)}) FLAGS ({banderas}))".encode())
                else:
                    respuesta.append(f"{n} (UID {uid} FLAGS ({banderas}))".encode())
                if "BODY.PEEK" not in args[1] and con_cuerpo:
                    m["flags"].add("\\seen")  # un FETCH sin PEEK marca el mensaje como leído (eso es lo que NO debemos provocar)
            return "OK", respuesta or [None]
        if comando == "store":
            uid, modo, banderas = int(args[0]), args[1], args[2].strip("()").lower().split()
            if uid in self.actual.mensajes:
                f = self.actual.mensajes[uid]["flags"]
                if modo.startswith("+FLAGS"):
                    f.update(banderas)
                elif modo.startswith("-FLAGS"):
                    f.difference_update(banderas)
                self.s.carpetas_por_objeto_tocar(self.actual, uid)
            return "OK", [b"STORE completed"]
        if comando == "copy":
            uid, destino = int(args[0]), args[1].strip('"')
            if destino not in self.s.carpetas:
                return "NO", [b"[TRYCREATE]"]
            origen = self.actual.mensajes[uid]
            c = self.s.carpetas[destino]
            c.modseq += 1
            c.mensajes[c.siguiente] = {"crudo": origen["crudo"], "flags": set(origen["flags"]), "modseq": c.modseq}
            c.siguiente += 1
            return "OK", [b"COPY completed"]
        if comando == "expunge":
            uid = int(args[0])
            if "\\deleted" in self.actual.mensajes.get(uid, {}).get("flags", set()):
                del self.actual.mensajes[uid]
            return "OK", [b"EXPUNGE completed"]
        raise AssertionError(f"comando IMAP inesperado: {comando}")

    def expunge(self):
        if not self._entrada("expunge"):
            return "NO", [b"fallo"]
        for uid in [u for u, m in self.actual.mensajes.items() if "\\deleted" in m["flags"]]:
            del self.actual.mensajes[uid]
        return "OK", [b"EXPUNGE completed"]

    def logout(self):
        return "BYE", [b"Logout"]

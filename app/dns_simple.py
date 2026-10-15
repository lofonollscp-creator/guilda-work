"""Consultas DNS mínimas (TXT y MX) con la librería estándar, para diagnosticar el correo de un dominio (SPF, DKIM, DMARC, MX) sin añadir dependencias.

Usa los servidores de `/etc/resolv.conf` (UDP, y TCP si la respuesta viene truncada). No valida DNSSEC ni sigue CNAME más allá de lo que ya devuelve el servidor recursivo; para un diagnóstico basta."""
from __future__ import annotations

import random
import socket
import struct

TIPOS = {"A": 1, "MX": 15, "TXT": 16}
_MAX_SALTOS = 20


class ErrorDNS(Exception):
    pass


def servidores_del_sistema(ruta: str = "/etc/resolv.conf") -> list[str]:
    try:
        with open(ruta) as f:
            return [p[1] for p in (l.split() for l in f if l.startswith("nameserver")) if len(p) > 1]
    except OSError:
        return []


def construir_consulta(nombre: str, tipo: str, ident: int | None = None) -> bytes:
    ident = random.randint(0, 0xFFFF) if ident is None else ident
    cabecera = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0)                 # recursión deseada, 1 pregunta
    cuerpo = b""
    for etiqueta in nombre.rstrip(".").split("."):
        try:
            b = etiqueta.encode("idna")
        except UnicodeError:
            raise ErrorDNS("Nombre de dominio no válido.") from None
        if not 0 < len(b) < 64:
            raise ErrorDNS("Nombre de dominio no válido.")
        cuerpo += bytes([len(b)]) + b
    return cabecera + cuerpo + b"\x00" + struct.pack("!HH", TIPOS[tipo], 1)


def _nombre(datos: bytes, pos: int) -> tuple[str, int]:
    """Lee un nombre con compresión; devuelve (nombre, posición tras el nombre en el registro original)."""
    partes, siguiente, saltos = [], None, 0
    while True:
        if pos >= len(datos):
            raise ErrorDNS("Respuesta DNS truncada.")
        n = datos[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            if pos + 1 >= len(datos):
                raise ErrorDNS("Respuesta DNS truncada.")
            if siguiente is None:
                siguiente = pos + 2
            pos = ((n & 0x3F) << 8) | datos[pos + 1]
            saltos += 1
            if saltos > _MAX_SALTOS:
                raise ErrorDNS("Respuesta DNS con un bucle de compresión.")
            continue
        partes.append(datos[pos + 1:pos + 1 + n].decode("ascii", "replace"))
        pos += 1 + n
    return ".".join(partes), (siguiente if siguiente is not None else pos)


def interpretar_respuesta(datos: bytes, ident: int | None = None) -> dict:
    """`{"rcode", "truncada", "respuestas": [{"tipo", "valor"}]}`. TXT: el texto unido; MX: `(prioridad, servidor)`."""
    if len(datos) < 12:
        raise ErrorDNS("Respuesta DNS vacía.")
    i, flags, qd, an, _ns, _ar = struct.unpack("!HHHHHH", datos[:12])
    if ident is not None and i != ident:
        raise ErrorDNS("Respuesta DNS que no corresponde a la consulta.")
    pos = 12
    for _ in range(qd):
        _n, pos = _nombre(datos, pos)
        pos += 4
    respuestas = []
    for _ in range(an):
        _n, pos = _nombre(datos, pos)
        if pos + 10 > len(datos):
            raise ErrorDNS("Respuesta DNS truncada.")
        tipo, _clase, _ttl, largo = struct.unpack("!HHIH", datos[pos:pos + 10])
        pos += 10
        rdata = datos[pos:pos + largo]
        if len(rdata) < largo:
            raise ErrorDNS("Respuesta DNS truncada.")
        if tipo == TIPOS["TXT"]:
            trozos, j = [], 0
            while j < len(rdata):
                n = rdata[j]
                trozos.append(rdata[j + 1:j + 1 + n].decode("utf-8", "replace"))
                j += 1 + n
            respuestas.append({"tipo": "TXT", "valor": "".join(trozos)})
        elif tipo == TIPOS["MX"] and largo >= 3:
            servidor, _ = _nombre(datos, pos + 2)
            respuestas.append({"tipo": "MX", "valor": (struct.unpack("!H", rdata[:2])[0], servidor)})
        pos += largo
    return {"rcode": flags & 0x0F, "truncada": bool(flags & 0x0200), "respuestas": respuestas}


def _consultar(servidor: str, consulta: bytes, ident: int, timeout: float, puerto: int = 53) -> dict:
    with socket.socket(socket.AF_INET6 if ":" in servidor else socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(consulta, (servidor, puerto))
        datos, _ = s.recvfrom(4096)
    r = interpretar_respuesta(datos, ident)
    if r["truncada"]:
        with socket.create_connection((servidor, puerto), timeout=timeout) as s:
            s.sendall(struct.pack("!H", len(consulta)) + consulta)
            largo = struct.unpack("!H", s.recv(2))[0]
            buf = b""
            while len(buf) < largo:
                trozo = s.recv(largo - len(buf))
                if not trozo:
                    break
                buf += trozo
        r = interpretar_respuesta(buf, ident)
    return r


def resolver(nombre: str, tipo: str, servidores: list[str] | None = None, timeout: float = 3.0, puerto: int = 53) -> list:
    """Los valores del tipo pedido (`TXT` → textos, `MX` → `(prioridad, servidor)` por prioridad). Lista vacía si el nombre no existe o no tiene ese registro. `ErrorDNS` si no hay forma de consultar."""
    servidores = servidores if servidores is not None else servidores_del_sistema()
    if not servidores:
        raise ErrorDNS("No hay servidores DNS configurados en esta máquina.")
    ident = random.randint(0, 0xFFFF)
    consulta = construir_consulta(nombre, tipo, ident)
    ultimo = None
    for s in servidores:
        try:
            r = _consultar(s, consulta, ident, timeout, puerto)
        except (OSError, ErrorDNS) as e:
            ultimo = e
            continue
        if r["rcode"] not in (0, 3):
            ultimo = ErrorDNS(f"El servidor DNS {s} respondió con error {r['rcode']}.")
            continue
        valores = [x["valor"] for x in r["respuestas"] if x["tipo"] == tipo]
        return sorted(valores) if tipo == "MX" else valores
    raise ErrorDNS(f"No se pudo consultar el DNS: {ultimo}")

"""Notas de voz del cliente (K7): el cliente graba un mensaje desde el móvil, se pasa a texto y lo ve en el cuadro del mensaje para revisarlo y enviarlo (o corregirlo) antes de que salga.

Es opcional y sale apagado: la enciende el despacho (`voz_cliente`), sabiendo que **el audio sale hacia el proveedor de IA** del despacho para transcribirlo (por ahora, un proveedor de OpenAI o
compatible con su ruta de transcripción). No se guarda el audio: solo llega a la conversación el texto que el cliente envía. Si el despacho ha fijado «nada sale del servidor» o no tiene
un proveedor que transcriba, la función no se ofrece al cliente. Cuenta como consulta de IA del despacho, a nombre de quien lleva al cliente."""
from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request

from . import ia_asistente, ia_despacho, ia_proveedores, ia_uso, portal_compromiso, portal_lectura_previa

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXTO = 2000
MIME = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "aac"}
MODELO = "gpt-4o-mini-transcribe"
TIMEOUT = 60
PROVEEDORES_QUE_TRANSCRIBEN = ("openai",)


def _tipo_base(mime: str | None) -> str:
    return (mime or "").split(";")[0].strip().lower()


def _candidato(cliente) -> tuple[int, dict] | None:
    lector = portal_lectura_previa.lector_de(cliente)
    if lector is None:
        return None
    if ia_despacho.config(cliente["tenant_id"])["ocr_local"] == "solo_local":
        return None                                                        # «nada sale del servidor»: ni un audio llega a un proveedor externo
    for c in ia_asistente.candidatos(lector, "asistente"):
        if c["proveedor"] in PROVEEDORES_QUE_TRANSCRIBEN:
            return lector, c
    return None


def disponible(cliente) -> bool:
    return bool(cliente is not None and portal_compromiso.ajustes(cliente["tenant_id"])["voz_cliente"] and _candidato(cliente) is not None)


def _multipart(campos: dict[str, str], archivo: tuple[str, str, bytes]) -> tuple[bytes, str]:
    limite = "----guilda" + secrets.token_hex(12)
    trozos: list[bytes] = []
    for k, v in campos.items():
        trozos.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    nombre, mime, datos = archivo
    trozos.append(f'--{limite}\r\nContent-Disposition: form-data; name="file"; filename="{nombre}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + datos + b"\r\n")
    trozos.append(f"--{limite}--\r\n".encode())
    return b"".join(trozos), f"multipart/form-data; boundary={limite}"


def transcribir(cliente, audio: bytes, mime: str | None, idioma: str | None = None) -> str:
    """El texto de la nota de voz. `ValueError` con un mensaje apto para el cliente si no se puede (apagado, audio demasiado grande o de otro tipo, el proveedor falla)."""
    if not disponible(cliente):
        raise ValueError("Las notas de voz no están disponibles.")
    tipo = _tipo_base(mime)
    if tipo not in MIME or not audio:
        raise ValueError("Ese audio no se puede leer aquí.")
    if len(audio) > MAX_BYTES:
        raise ValueError("La nota de voz es demasiado larga: grábala más corta.")
    lector, c = _candidato(cliente)
    prov = ia_proveedores.obtener(c["proveedor"])
    base = (c["url_base"] or prov.url_base).rstrip("/")
    campos = {"model": MODELO, "response_format": "json"}
    if idioma in ("es", "ca", "en", "fr"):
        campos["language"] = idioma
    cuerpo, tipo_contenido = _multipart(campos, (f"nota.{MIME[tipo]}", tipo, audio))
    ultimo: str | None = None
    for clave in c["claves"]:
        req = urllib.request.Request(f"{base}/audio/transcriptions", data=cuerpo, method="POST", headers={"Content-Type": tipo_contenido, **({"Authorization": f"Bearer {clave}"} if clave else {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                texto = str(json.loads(resp.read().decode("utf-8")).get("text") or "").strip()
        except urllib.error.HTTPError as e:
            ultimo = f"HTTP {e.code}"
            if e.code in ia_proveedores.CODIGOS_DE_CLAVE:
                continue                                                  # el problema es de esa clave: se prueba la siguiente
            break
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            ultimo = type(e).__name__
            break
        ia_uso.registrar(cliente["tenant_id"], c["proveedor"], MODELO, "voz", c["origen"], None)
        if not texto:
            raise ValueError("No se ha entendido nada en la nota de voz. Inténtalo de nuevo, más cerca del micrófono.")
        return texto[:MAX_TEXTO]
    raise ValueError("No se ha podido pasar la nota de voz a texto. Escribe el mensaje o inténtalo más tarde.")

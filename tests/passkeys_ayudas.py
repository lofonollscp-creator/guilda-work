"""Un autenticador WebAuthn de mentira para probar las passkeys sin navegador: crea credenciales y firma desafíos como lo haría un móvil (ES256, verificación de usuario)."""
import base64
import hashlib
import json
import os
import struct
from urllib.parse import urlsplit

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sin_b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Autenticador:
    def __init__(self, origen=None, rp_id=None, verificacion=True):
        origen = origen or (os.environ.get("GUILDA_URL_PUBLICA", "").strip() or "http://localhost").rstrip("/")      # la dirección pública con la que corren los tests
        rp_id = rp_id or urlsplit(origen).hostname
        self.clave = ec.generate_private_key(ec.SECP256R1())
        self.id = os.urandom(32)
        self.origen, self.rp_id, self.contador, self.uv = origen, rp_id, 0, verificacion

    def _flags(self, con_credencial: bool) -> int:
        return 0x01 | (0x04 if self.uv else 0) | (0x40 if con_credencial else 0)

    def crear(self, opciones: dict) -> dict:
        n = self.clave.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})
        datos = hashlib.sha256(self.rp_id.encode()).digest() + bytes([self._flags(True)]) + struct.pack(">I", self.contador) + b"\x00" * 16 + struct.pack(">H", len(self.id)) + self.id + cose
        cliente = json.dumps({"type": "webauthn.create", "challenge": opciones["challenge"], "origin": self.origen, "crossOrigin": False}).encode()
        return {"id": b64u(self.id), "rawId": b64u(self.id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64u(cliente), "attestationObject": b64u(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": datos})), "transports": ["internal"]}}

    def firmar(self, opciones: dict, origen=None) -> dict:
        self.contador += 1
        datos = hashlib.sha256(self.rp_id.encode()).digest() + bytes([self._flags(False)]) + struct.pack(">I", self.contador)
        cliente = json.dumps({"type": "webauthn.get", "challenge": opciones["challenge"], "origin": origen or self.origen, "crossOrigin": False}).encode()
        firma = self.clave.sign(datos + hashlib.sha256(cliente).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.id), "rawId": b64u(self.id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64u(cliente), "authenticatorData": b64u(datos), "signature": b64u(firma), "userHandle": None}}

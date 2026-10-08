"""CONDSTORE (RFC 7162) en la sincronización IMAP: sin cambios no se relee nada, y los cambios de
banderas de mensajes antiguos se ven en la pasada incremental."""
import imaplib

import pytest

from app import correo, db
from tests.imap_falso import ServidorIMAP
from tests.test_correo_sincronizacion import _estado_de_sincronizacion, _montar, _msg, _sync  # noqa: F401


def _fetch_de_banderas(s):
    return [a for a in s.comandos("uid_fetch") if "BODY" not in a[1]]


def _preparar(monkeypatch, usuario_id, condstore=True, n=6):
    s = ServidorIMAP(condstore=condstore)
    uids = [s.anadir("INBOX", f"Correo {i}") for i in range(n)]
    monkeypatch.setattr(correo, "VENTANA_RECIENTES", 2)
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    return s, cuenta, uids


def test_se_guarda_el_modseq_y_sin_cambios_no_se_releen_banderas(monkeypatch, usuario_id):
    s, cuenta, uids = _preparar(monkeypatch, usuario_id)
    assert db.estado_carpeta_correo(cuenta, "INBOX")["modseq"] == str(s.carpetas["INBOX"].modseq)
    antes = len(_fetch_de_banderas(s))
    assert _sync(usuario_id, cuenta) == {"nuevos": 0}
    assert len(_fetch_de_banderas(s)) == antes                           # nada que releer
    assert ("enable", ("CONDSTORE",)) in s.registro


def test_un_cambio_en_un_mensaje_antiguo_se_ve_sin_esperar_a_la_pasada_completa(monkeypatch, usuario_id):
    s, cuenta, uids = _preparar(monkeypatch, usuario_id)
    guardado = int(db.estado_carpeta_correo(cuenta, "INBOX")["modseq"])
    s.poner_flags("INBOX", uids[0], "\\Seen", "\\Flagged")               # el más antiguo: fuera de la ventana de 2
    assert (_msg(cuenta, uids[0])["leido"], _msg(cuenta, uids[0])["destacado"]) == (0, 0)
    _sync(usuario_id, cuenta)
    assert (_msg(cuenta, uids[0])["leido"], _msg(cuenta, uids[0])["destacado"]) == (1, 1)
    pedido = _fetch_de_banderas(s)[-1]
    assert pedido[0] == "1:*" and pedido[2] == f"(CHANGEDSINCE {guardado})"      # solo lo modificado
    assert db.estado_carpeta_correo(cuenta, "INBOX")["modseq"] == str(s.carpetas["INBOX"].modseq)
    antes = len(_fetch_de_banderas(s))
    _sync(usuario_id, cuenta)
    assert len(_fetch_de_banderas(s)) == antes                           # y ya no vuelve a preguntar


def test_sin_condstore_el_cambio_antiguo_espera_a_la_pasada_completa(monkeypatch, usuario_id):
    s, cuenta, uids = _preparar(monkeypatch, usuario_id, condstore=False)
    assert db.estado_carpeta_correo(cuenta, "INBOX")["modseq"] is None
    s.poner_flags("INBOX", uids[0], "\\Seen")
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uids[0])["leido"] == 0                           # comportamiento de siempre
    assert not [a for a in _fetch_de_banderas(s) if len(a) > 2]
    db.guardar_estado_carpeta_correo(cuenta, "INBOX", ultima_pasada_completa=None)
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uids[0])["leido"] == 1


def test_mensajes_nuevos_y_borrados_siguen_funcionando(monkeypatch, usuario_id):
    s, cuenta, uids = _preparar(monkeypatch, usuario_id)
    nuevo = s.anadir("INBOX", "Recién llegado", flags=("\\Seen",))
    s.borrar("INBOX", uids[-1])
    assert _sync(usuario_id, cuenta) == {"nuevos": 1}
    assert _msg(cuenta, nuevo)["leido"] == 1 and _msg(cuenta, uids[-1]) is None
    assert db.estado_carpeta_correo(cuenta, "INBOX")["modseq"] == str(s.carpetas["INBOX"].modseq)


def test_lo_pendiente_aqui_no_lo_pisa_el_servidor(monkeypatch, usuario_id):
    s, cuenta, uids = _preparar(monkeypatch, usuario_id)
    s.poner_flags("INBOX", uids[0], "\\Seen")                            # el servidor lo ve leído...
    db.encolar_operacion_correo(cuenta, "INBOX", str(uids[0]), "no_leido")      # ...pero aquí se acaba de marcar como no leído
    monkeypatch.setattr(correo, "_aplicar_operaciones", lambda conn, cuenta: {"hechas": 0, "fallidas": 0})
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uids[0])["leido"] == 0


def test_cambio_de_uidvalidity_reinicia_el_modseq(monkeypatch, usuario_id):
    s, cuenta, uids = _preparar(monkeypatch, usuario_id)
    s.carpetas["INBOX"].uidvalidity = 2000
    s.carpetas["INBOX"].modseq = 3                                       # el servidor numera desde cero otra vez
    _sync(usuario_id, cuenta)
    assert db.estado_carpeta_correo(cuenta, "INBOX")["modseq"] == "3" and len(db.uids_existentes_correo(cuenta, "INBOX")) == len(uids)


def test_un_modseq_menor_que_el_guardado_hace_una_lectura_normal(monkeypatch, usuario_id):
    s, cuenta, uids = _preparar(monkeypatch, usuario_id)
    s.carpetas["INBOX"].modseq = 1                                       # buzón restaurado de una copia
    s.poner_flags("INBOX", uids[-1], "\\Seen")
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uids[-1])["leido"] == 1
    assert all(len(a) <= 2 for a in _fetch_de_banderas(s)[1:])           # sin CHANGEDSINCE
    assert db.estado_carpeta_correo(cuenta, "INBOX")["modseq"] == str(s.carpetas["INBOX"].modseq)


def test_si_el_servidor_rechaza_enable_se_sincroniza_como_siempre(monkeypatch, usuario_id):
    s = ServidorIMAP(condstore=True)
    s.fallar["enable"] = "NO"
    uid = s.anadir("INBOX", "Uno")
    cuenta = _montar(monkeypatch, usuario_id, s)
    original = s.conexion

    def conexion_sin_enable(*a, **k):
        c = original()
        c.enable = lambda cap: ("NO", [b"no"])
        return c

    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: conexion_sin_enable())
    s.anadir("INBOX", "Dos")
    assert _sync(usuario_id, cuenta) == {"nuevos": 2}
    assert db.estado_carpeta_correo(cuenta, "INBOX")["modseq"] is None

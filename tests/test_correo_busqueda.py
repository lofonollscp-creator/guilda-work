"""Búsqueda de texto completo del correo (FTS5): resultados, seguridad de la consulta,
mantenimiento del índice, migración de un buzón existente y alternativa sin FTS5."""
import imaplib

import pytest

from app import correo, db
from tests.imap_falso import ServidorIMAP


def _cuenta(usuario_id):
    return db.crear_cuenta_correo(usuario_id, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")


def _m(cuenta, uid, asunto="Asunto", remitente="a@b.com", destinatarios="yo@ejemplo.com", cuerpo="cuerpo", carpeta="INBOX", html=None):
    return db.guardar_mensaje_correo(
        cuenta_id=cuenta, uid=str(uid), asunto=asunto, remitente=remitente, destinatarios=destinatarios,
        fecha="2026-03-10T10:00:00", cuerpo_texto=cuerpo, cuerpo_html=html, carpeta=carpeta,
    )


def _ids(cuenta, texto, **kw):
    return {m["id"] for m in db.listar_mensajes_correo(cuenta, texto=texto, **kw)}


def test_busca_en_asunto_remitente_destinatarios_y_cuerpo(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, asunto="Factura del modelo 303")
    b = _m(c, 2, remitente="Pepe Gestor <pepe@gestoria.com>")
    d = _m(c, 3, destinatarios="Ana <ana@cliente.es>")
    e = _m(c, 4, cuerpo="Adjunto el extracto bancario del trimestre")
    _m(c, 5, asunto="Otra cosa")
    assert _ids(c, "factura") == {a} and _ids(c, "303") == {a}
    assert _ids(c, "pepe@gestoria.com") == {b} and _ids(c, "gestoria") == {b}
    assert _ids(c, "ana@cliente.es") == {d}
    assert _ids(c, "extracto") == {e} and _ids(c, "bancario trimestre") == {e}


def test_sin_acentos_ni_mayusculas_y_por_prefijo(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, asunto="Declaración de la Renta — Gestoría Pérez")
    assert _ids(c, "declaracion") == {a} and _ids(c, "GESTORIA") == {a} and _ids(c, "perez") == {a}
    assert _ids(c, "declar") == {a} and _ids(c, "ges") == {a}
    assert _ids(c, "claracion") == set()      # por prefijo de palabra, no por trozos del medio


def test_todas_las_palabras_y_frases_exactas(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, cuerpo="enviar la factura de marzo al cliente")
    b = _m(c, 2, cuerpo="el cliente pide la factura de abril")
    assert _ids(c, "factura cliente") == {a, b} and _ids(c, "factura marzo") == {a}
    assert _ids(c, '"factura de marzo"') == {a} and _ids(c, '"marzo de factura"') == set()


@pytest.mark.parametrize("texto", ['"', '""', "*", "a OR b", "NEAR(a b)", "(", "a AND", "col:valor", "-x", "'; DROP TABLE correo_mensajes; --", "\\", "^", "{x}"])
def test_ninguna_consulta_rara_rompe_la_busqueda(usuario_id, texto):
    c = _cuenta(usuario_id)
    _m(c, 1, asunto="Normal")
    db.listar_mensajes_correo(c, texto=texto)          # no debe lanzar
    assert db.listar_mensajes_correo(c)                 # y la tabla sigue ahí


def test_los_simbolos_se_buscan_literalmente_con_like(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, cuerpo="descuento del 50% hoy")
    _m(c, 2, cuerpo="descuento del 500 hoy")
    assert _ids(c, "50%") == {a} and _ids(c, "_") == set() and _ids(c, "%") == {a}


def test_combina_con_carpeta_leidos_y_categoria(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, asunto="Informe trimestral")
    b = _m(c, 2, asunto="Informe trimestral", carpeta="Archivo")
    d = _m(c, 3, asunto="Informe anual")
    db.marcar_leido_mensaje_correo(a, True)
    assert _ids(c, "informe") == {a, d} and _ids(c, "informe", carpeta="Archivo") == {b}
    assert _ids(c, "informe", solo_no_leidos=True) == {d}
    otra = _cuenta(usuario_id)
    assert _ids(otra, "informe") == set()              # no cruza cuentas


def test_el_indice_sigue_los_cambios_y_borrados(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, asunto="Uno", cuerpo="palabra-original")
    conn = db.get_connection()
    conn.execute("UPDATE correo_mensajes SET cuerpo_texto = 'texto cambiado nuevo' WHERE id = ?", (a,))
    conn.commit()
    conn.close()
    assert _ids(c, "original") == set() and _ids(c, "cambiado") == {a}
    db.marcar_leido_mensaje_correo(a, True)             # un cambio ajeno al texto no rompe nada
    assert _ids(c, "cambiado") == {a}
    db.eliminar_mensaje_correo(a)
    assert _ids(c, "cambiado") == set()
    db.eliminar_mensajes_correo_por_uid(c, "INBOX", ["99"])


def test_los_correos_solo_html_se_encuentran_por_su_cuerpo(monkeypatch, usuario_id):
    s = ServidorIMAP()
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "Boletín", "news@x.com", "yo@ejemplo.com"
    msg.set_content("x")
    msg.clear_content()
    msg.set_content("<html><body><p>Oferta <b>irrepetible</b> de verano</p></body></html>", subtype="html")
    s.carpetas["INBOX"].mensajes[1] = {"crudo": bytes(msg), "flags": set()}
    s.carpetas["INBOX"].siguiente = 2
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: s.conexion())
    cuenta = correo.guardar_cuenta(usuario_id, nombre="T", protocolo="imap", host="h", puerto=993, usuario="yo@ejemplo.com", contrasena="correcta")
    correo.sincronizar_bandeja(usuario_id, cuenta)
    assert len(_ids(cuenta, "irrepetible")) == 1
    assert "irrepetible" in db.mensaje_correo_por_uid(cuenta, "INBOX", "1")["cuerpo_texto"]


def test_migracion_de_un_buzon_existente_rellena_el_indice_y_el_texto_de_los_html(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, asunto="Antiguo", cuerpo="contenido heredado")
    b = _m(c, 2, asunto="Solo html", cuerpo=None, html="<p>cuerpo <i>escondido</i> en html</p>")
    conn = db.get_connection()
    for t in ("correo_fts_ai", "correo_fts_ad", "correo_fts_au"):
        conn.execute(f"DROP TRIGGER {t}")
    conn.execute("DROP TABLE correo_fts")               # como estaba la base antes de existir el índice
    conn.commit()
    assert db._asegurar_fts_correo(conn) is True
    conn.commit()
    conn.close()
    assert _ids(c, "heredado") == {a} and _ids(c, "escondido") == {b}
    conn = db.get_connection()
    assert db._asegurar_fts_correo(conn) is True        # segunda vez: no rehace nada
    conn.close()
    assert _ids(c, "heredado") == {a}


def test_reconstruir_indice_repara_un_indice_desincronizado(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, cuerpo="importante")
    conn = db.get_connection()
    conn.execute("INSERT INTO correo_fts(correo_fts) VALUES ('delete-all')")
    conn.commit()
    conn.close()
    assert _ids(c, "importante") == set()
    assert db.reconstruir_indice_correo() == 1
    assert _ids(c, "importante") == {a}


def test_sin_fts5_la_busqueda_sigue_funcionando_con_like(usuario_id):
    c = _cuenta(usuario_id)
    a = _m(c, 1, asunto="Presupuesto abril")
    conn = db.get_connection()
    for t in ("correo_fts_ai", "correo_fts_ad", "correo_fts_au"):
        conn.execute(f"DROP TRIGGER {t}")
    conn.execute("DROP TABLE correo_fts")
    conn.commit()
    conn.close()
    assert db.fts_correo_disponible() is False
    assert _ids(c, "presupuesto") == {a}


def test_la_busqueda_usa_el_indice(usuario_id):
    c = _cuenta(usuario_id)
    for i in range(50):
        _m(c, i + 1, asunto=f"Mensaje {i}")
    conn = db.get_connection()
    plan = " ".join(f[3] for f in conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM correo_mensajes WHERE cuenta_id = 1 AND carpeta = 'INBOX' "
        "AND id IN (SELECT rowid FROM correo_fts WHERE correo_fts MATCH '\"mensaje\"*') ORDER BY fecha DESC LIMIT 50"))
    conn.close()
    assert "correo_fts" in plan and "VIRTUAL TABLE INDEX" in plan


def test_consulta_fts_construye_expresiones_seguras():
    assert db.consulta_fts("hola mundo") == '"hola"* "mundo"*'
    assert db.consulta_fts('"frase exacta" resto') == '"frase exacta" "resto"*'
    assert db.consulta_fts('di"ce') == '"di""ce"*'
    assert db.consulta_fts("   ") is None and db.consulta_fts("") is None and db.consulta_fts(None) is None
    assert db.consulta_fts("50%") is None and db.consulta_fts("a_b") is None and db.consulta_fts("--") is None
    assert db.consulta_fts("pepe@x.com") == '"pepe@x.com"*'

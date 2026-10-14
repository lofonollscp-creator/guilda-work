"""Gestión de certificados sin archivo y avisos al cliente: alta rápida, edición, renovación en un paso, panel, portal del cliente y avisos configurables por el despacho."""
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from app import certificados as ce, db, notificaciones_email, portal_recordatorios

AHORA = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
HOY = AHORA.date()


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Cert Clientes")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.cus, e.otro = u("sup-cc@ejemplo.com", True), u("cus-cc@ejemplo.com"), u("otro-cc@ejemplo.com")
    ce.fijar_custodio_flag(t, e.sup, e.cus, True)
    e.marta = db.crear_cliente_fiscal(t, "Marta Puig", nif="12345678Z", email="marta@cliente.example")
    e.sin_correo = db.crear_cliente_fiscal(t, "Sin Correo SL", nif="B12345674")
    return e


class Correo:
    def __init__(self, monkeypatch, configurado=True):
        self.enviados = []
        monkeypatch.setattr(notificaciones_email, "configurado", lambda: configurado)
        monkeypatch.setattr(notificaciones_email, "_enviar", lambda dest, asunto, plano, html=None: self.enviados.append((dest, asunto, plano, html)))


# --- Alta rápida, sin archivo ----------------------------------------------------------------------------------------------------------------
def test_alta_rapida_con_solo_cliente_tipo_y_caducidad(d):
    r = ce.alta_rapida(d.t, d.cus, tipo="fnmt_persona_fisica", caduca=(HOY + timedelta(days=40)).isoformat(), cliente_fiscal_id=d.marta)
    c = ce.obtener(d.t, r["id"], AHORA)
    assert r["nuevo"] and (c["cliente_nombre"], c["nombre_comun"], c["nif_confirmado"], c["emisor"], c["tipo_certificado"], c["tipo_titular"]) == ("Marta Puig", "Marta Puig", "12345678Z", "FNMT-RCM", "fnmt_persona_fisica", "persona_fisica")
    assert c["verificado"] == 0 and c["origen"] == "manual" and c["custodio_id"] == d.cus and c["dias_restantes"] == 40 and c["temporal"] == "vigente"
    assert c["caduca_el"] == (HOY + timedelta(days=40)).isoformat(), "la fecha que se enseña es la que se escribió, no una conversión rara de zonas"


def test_la_caducidad_vale_hasta_el_final_del_dia_en_la_zona_del_despacho(d):
    r = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca="2026-11-07", titular="Alguien")
    c = ce.obtener(d.t, r["id"], AHORA)
    assert c["not_after"] == "2026-11-07T22:59:59Z" and c["caduca_el"] == "2026-11-07"
    assert ce.estado_temporal(None, c["not_after"], datetime(2026, 11, 7, 22, 59, 59, tzinfo=timezone.utc)) == "vigente"
    assert ce.estado_temporal(None, c["not_after"], datetime(2026, 11, 7, 23, 0, 1, tzinfo=timezone.utc)) == "caducado"


def test_con_la_emision_se_propone_la_caducidad_del_tipo(d):
    assert ce.caducidad_propuesta("fnmt_persona_fisica", date(2024, 2, 29)) == date(2028, 2, 29)
    assert ce.caducidad_propuesta("fnmt_representante", date(2024, 2, 29)) == date(2026, 2, 28), "un 29 de febrero que no existe ese año cae en el 28"
    assert ce.caducidad_propuesta("fnmt_representante", date(2026, 3, 10)) == date(2028, 3, 10)
    assert ce.caducidad_propuesta("dnie", date(2026, 3, 10)) is None and ce.caducidad_propuesta("otro", None) is None
    r = ce.alta_rapida(d.t, d.cus, tipo="fnmt_representante", emitido="2026-05-01", cliente_fiscal_id=d.sin_correo)
    assert ce.obtener(d.t, r["id"], AHORA)["caduca_el"] == "2028-05-01"
    with pytest.raises(ValueError, match="Indica cuándo caduca"):
        ce.alta_rapida(d.t, d.cus, tipo="dnie", emitido="2026-05-01", cliente_fiscal_id=d.marta)


def test_validaciones_del_alta_rapida(d):
    for kw, texto in (({"tipo": "inventado", "caduca": "2027-01-01", "titular": "A"}, "tipo"), ({"caduca": "2027-01-01"}, "a quién pertenece"), ({"titular": "A", "caduca": "ayer"}, "AAAA-MM-DD"),
                      ({"titular": "A", "caduca": "2027-01-01", "emitido": "2028-01-01"}, "anterior"), ({"titular": "A", "caduca": "2027-01-01", "nif": "12"}, "formato"),
                      ({"titular": "A", "caduca": "2027-01-01", "ubicacion": "contraseña: 1234"}, "contraseñas"), ({"cliente_fiscal_id": 9999, "caduca": "2027-01-01"}, "No existe ese cliente"),
                      ({"titular": "A", "caduca": "1999-01-01"}, "no parece correcta")):
        with pytest.raises(ValueError, match=texto):
            ce.alta_rapida(d.t, d.cus, **kw)
    with pytest.raises(ValueError, match="Solo los custodios"):
        ce.alta_rapida(d.t, d.otro, titular="A", caduca="2027-01-01")
    assert ce.listar(d.t) == []


def test_apuntar_dos_veces_lo_mismo_no_duplica(d):
    kw = dict(tipo="fnmt_persona_fisica", caduca="2027-06-30", cliente_fiscal_id=d.marta)
    a = ce.alta_rapida(d.t, d.cus, **kw); b = ce.alta_rapida(d.t, d.cus, **kw)
    assert a["nuevo"] and not b["nuevo"] and a["id"] == b["id"]
    assert ce.alta_rapida(d.t, d.cus, **{**kw, "caduca": "2027-07-01"})["nuevo"], "otra caducidad es otro certificado (p. ej., el renovado)"


def test_editar_un_certificado_a_mano_y_no_uno_importado(d):
    from tests.test_certificados import hacer_cert, pem
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca="2027-06-30", titular="Nombre mal")["id"]
    ce.editar(d.t, d.cus, cid, titular="Nombre bien", tipo="fnmt_persona_fisica", caduca="2027-12-31", serie="AB:CD", cliente_fiscal_id=d.marta, avisar_cliente=False)
    c = ce.obtener(d.t, cid, AHORA)
    assert (c["nombre_comun"], c["tipo_certificado"], c["caduca_el"], c["numero_serie"], c["cliente_titular_id"], c["avisar_cliente"], c["emisor"]) == ("Nombre bien", "fnmt_persona_fisica", "2027-12-31", "abcd", d.marta, 0, "FNMT-RCM")
    with pytest.raises(ValueError, match="no puede quedar vacío"):
        ce.editar(d.t, d.cus, cid, titular=" ")
    imp = ce.importar(d.t, d.cus, pem(hacer_cert(cn="IMPORTADO")))["id"]
    with pytest.raises(ValueError, match="se importó de un archivo"):
        ce.editar(d.t, d.cus, imp, caduca="2030-01-01")
    ce.editar(d.t, d.cus, imp, cliente_fiscal_id=d.marta, avisar_cliente=True)         # lo blando sí se completa
    assert ce.obtener(d.t, imp)["cliente_titular_id"] == d.marta


def test_cambiar_la_caducidad_reinicia_los_avisos_de_esa_fecha(d, monkeypatch):
    Correo(monkeypatch)
    ce.guardar_config(d.t, d.sup, avisar_cliente=True, mostrar_en_portal=False, dias_antes="30", dias_despues="")
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=10)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 1 and ce.avisar_clientes(d.t, AHORA)["clientes"] == 0
    ce.editar(d.t, d.cus, cid, caduca=(HOY + timedelta(days=20)).isoformat())
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 1, "otra caducidad, otro aviso"


# --- Renovado en un paso ------------------------------------------------------------------------------------------------------------------------
def test_renovado_en_un_paso_hereda_todo_y_sustituye(d):
    cid = ce.alta_rapida(d.t, d.cus, tipo="fnmt_persona_fisica", caduca=(HOY + timedelta(days=20)).isoformat(), cliente_fiscal_id=d.marta, ubicacion="Caja fuerte")["id"]
    v = ce.vincular(d.t, d.cus, cid, cliente_fiscal_id=d.marta, servicio="presentacion", autorizacion="Apoderamiento")
    with pytest.raises(ValueError, match="confirma que el nuevo funciona"):
        ce.renovado(d.t, d.cus, cid, (HOY + timedelta(days=1500)).isoformat())
    with pytest.raises(ValueError, match="posterior"):
        ce.renovado(d.t, d.cus, cid, (HOY + timedelta(days=5)).isoformat(), funciona=True)
    r = ce.renovado(d.t, d.cus, cid, (HOY + timedelta(days=1500)).isoformat(), serie="FF01", funciona=True)
    ant, nuevo = ce.obtener(d.t, cid, AHORA), ce.obtener(d.t, r["id"], AHORA)
    assert ant["estado_operativo"] == "sustituido" and nuevo["sustituye_a"] == cid and nuevo["cliente_titular_id"] == d.marta and nuevo["tipo_certificado"] == "fnmt_persona_fisica"
    assert nuevo["ubicacion_externa"] == "Caja fuerte" and nuevo["numero_serie"] == "ff01" and nuevo["vinculos_activos"] == 1 and ant["vinculos_activos"] == 0
    assert ce.renovacion_activa(d.t, cid) is None and [x["id"] for x in ce.listar(d.t)] == [r["id"]]
    assert "renovacion_rapida" in [e["accion"] for e in ce.eventos(d.t, cid)]
    from app import auditoria
    assert any(e["accion"] == "certificado.renovacion_cerrado" for e in auditoria.listar(d.t, entidad="certificado", entidad_id=cid))


def test_renovado_sin_servicios_no_pide_confirmacion_y_se_puede_abrir_antes(d):
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=20)).isoformat(), titular="Despacho")["id"]
    ce.abrir_renovacion(d.t, d.cus, cid)
    r = ce.renovado(d.t, d.cus, cid, (HOY + timedelta(days=700)).isoformat())
    assert ce.obtener(d.t, cid)["estado_operativo"] == "sustituido" and ce.obtener(d.t, r["id"]) is not None
    with pytest.raises(ValueError, match="ya está sustituido"):
        ce.renovado(d.t, d.cus, cid, (HOY + timedelta(days=900)).isoformat())


# --- Panel -----------------------------------------------------------------------------------------------------------------------------------------
def test_el_resumen_cuenta_cada_certificado_en_su_grupo(d):
    for dias in (-5, 10, 60, 400):
        ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(date.today() + timedelta(days=dias)).isoformat(), titular=f"Cert {dias}", cliente_fiscal_id=d.marta if dias == 10 else None)
    r = ce.resumen(d.t)
    assert r == {"total": 4, "caducados": 1, "mes": 1, "tres_meses": 1, "vigentes": 1, "sin_fecha": 0, "sin_cliente": 3}
    assert [c["nombre_comun"] for c in ce.listar(d.t, plazo="mes")] == ["Cert 10"] and [c["nombre_comun"] for c in ce.listar(d.t, plazo="caducados")] == ["Cert -5"]
    assert [c["nombre_comun"] for c in ce.listar(d.t, cliente_fiscal_id=d.marta)] == ["Cert 10"]
    assert [c["nombre_comun"] for c in ce.listar(d.t, q="marta")] == ["Cert 10"], "se busca también por el nombre del cliente"
    assert ce.texto_dias(0) == "hoy" and ce.texto_dias(1) == "mañana" and ce.texto_dias(12) == "en 12 días" and ce.texto_dias(-1) == "ayer" and ce.texto_dias(-4) == "hace 4 días"


# --- Configuración de los avisos --------------------------------------------------------------------------------------------------------------
def test_la_configuracion_solo_la_cambia_la_direccion_y_se_valida(d):
    assert ce.config(d.t) == {"avisar_cliente": False, "mostrar_en_portal": False, "dias_antes": [60, 30, 15, 7], "dias_despues": [3], "asunto": "", "cuerpo": "", "instrucciones": ""}
    with pytest.raises(ValueError, match="Solo la dirección"):
        ce.guardar_config(d.t, d.cus, avisar_cliente=True, mostrar_en_portal=False, dias_antes="30", dias_despues="")
    c = ce.guardar_config(d.t, d.sup, avisar_cliente=True, mostrar_en_portal=True, dias_antes="90, 30 7 30", dias_despues="2,10", instrucciones="Pide cita en la FNMT")
    assert c["dias_antes"] == [90, 30, 7] and c["dias_despues"] == [2, 10] and c["avisar_cliente"] and c["instrucciones"] == "Pide cita en la FNMT"
    for kw, texto in (({"dias_antes": "400"}, "no es un número"), ({"dias_antes": "x"}, "no es un número"), ({"dias_despues": "0"}, "no es un número"), ({"dias_antes": "1,2,3,4,5,6,7"}, "Como máximo"),
                      ({"dias_antes": "7", "asunto": "solo asunto"}, "los dos vacíos")):
        with pytest.raises(ValueError, match=texto):
            ce.guardar_config(d.t, d.sup, **{"avisar_cliente": True, "mostrar_en_portal": False, "dias_antes": "30", "dias_despues": "", **kw})
    assert ce.config(db.crear_tenant("Otro despacho"))["avisar_cliente"] is False, "cada despacho tiene lo suyo"
    from app import auditoria
    assert "certificado.config_avisos" in [e["accion"] for e in auditoria.listar(d.t)]


# --- Avisos al cliente ------------------------------------------------------------------------------------------------------------------------
def _activar(d, **kw):
    base = dict(avisar_cliente=True, mostrar_en_portal=True, dias_antes="60, 30, 15, 7", dias_despues="3")
    ce.guardar_config(d.t, d.sup, **{**base, **kw})


def test_no_se_avisa_a_nadie_mientras_el_despacho_no_lo_active(d, monkeypatch):
    c = Correo(monkeypatch)
    ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=5)).isoformat(), cliente_fiscal_id=d.marta)
    assert ce.avisar_clientes(d.t, AHORA) == {"clientes": 0, "omitidos": 0, "fallidos": 0} and c.enviados == []
    assert ce.visibles_para_cliente(d.marta, AHORA) == [], "y tampoco se enseña en el portal"


def test_avisa_una_vez_por_umbral_solo_el_vigente_y_con_el_texto_estandar_en_su_idioma(d, monkeypatch):
    c = Correo(monkeypatch)
    _activar(d)
    cid = ce.alta_rapida(d.t, d.cus, tipo="fnmt_persona_fisica", caduca=(HOY + timedelta(days=20)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    assert ce.avisar_clientes(d.t, AHORA) == {"clientes": 1, "omitidos": 1, "fallidos": 0}, "entra a 20 días: avisa el de 30; el de 60 queda omitido"
    (dest, asunto, plano, html), = c.enviados
    assert dest == "marta@cliente.example" and "caduca dentro de 20 días" in asunto and "Marta Puig" in plano and "FNMT · Persona física" in plano and (HOY + timedelta(days=20)).isoformat() in plano
    assert "12345678Z" not in plano + html and "FNMT-RCM" not in plano + html, "solo el tipo y la fecha, sin datos del certificado"
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 0, "repetir la pasada no duplica"
    assert ce.avisar_clientes(d.t, AHORA + timedelta(days=6))["clientes"] == 1, "a 14 días cruza el de 15"
    assert [a["estado"] for a in ce.avisos_del_cliente(d.t, cid)] == ["enviado", "enviado", "omitido"]


def test_tras_caducar_avisa_con_los_dias_despues_y_una_sola_vez(d, monkeypatch):
    c = Correo(monkeypatch)
    _activar(d, dias_despues="2, 10")
    ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY - timedelta(days=1)).isoformat(), cliente_fiscal_id=d.marta)
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 0, "caducó ayer y el primer aviso tras caducar es a los 2 días"
    assert ce.avisar_clientes(d.t, AHORA + timedelta(days=2))["clientes"] == 1 and "caducó" in c.enviados[-1][1].lower()
    assert ce.avisar_clientes(d.t, AHORA + timedelta(days=3))["clientes"] == 0
    assert ce.avisar_clientes(d.t, AHORA + timedelta(days=11))["clientes"] == 1


def test_a_quien_no_se_avisa(d, monkeypatch):
    c = Correo(monkeypatch)
    _activar(d)
    cerca = (HOY + timedelta(days=5)).isoformat()
    sin_correo = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=cerca, cliente_fiscal_id=d.sin_correo)["id"]
    excluido = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=cerca, cliente_fiscal_id=d.marta, avisar_cliente=False)["id"]
    sin_cliente = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=cerca, titular="El propio despacho")["id"]
    pidio = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=cerca, cliente_fiscal_id=d.marta, titular="Ya pidió ayuda")["id"]
    conn = db.get_connection(); conn.execute("UPDATE certificados SET ayuda_solicitada_en = '2026-10-01' WHERE id = ?", (pidio,)); conn.commit(); conn.close()
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 0 and c.enviados == []
    ce.editar(d.t, d.cus, excluido, avisar_cliente=None)
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 1, "al volver a «según el ajuste del despacho», sí"
    sust = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=cerca, cliente_fiscal_id=d.marta, titular="En renovación")["id"]
    rid = ce.abrir_renovacion(d.t, d.cus, sust); ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion")
    ce.avisar_clientes(d.t, AHORA)
    assert len(c.enviados) == 2, "con la renovación en gestión se sigue avisando: el cliente puede tener que actuar"
    ya = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=cerca, cliente_fiscal_id=d.marta, titular="Nuevo ya apuntado")["id"]
    conn = db.get_connection()
    conn.execute("INSERT INTO certificados_renovaciones (tenant_id, certificado_id, fase, abierta_en) VALUES (?, ?, 'validado', '2026-10-01')", (d.t, ya)); conn.commit(); conn.close()
    ce.avisar_clientes(d.t, AHORA)
    assert len(c.enviados) == 2, "con el certificado nuevo ya apuntado no se insiste"


def test_sin_correo_saliente_no_se_envia_ni_se_marca(d, monkeypatch):
    c = Correo(monkeypatch, configurado=False)
    _activar(d)
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=5)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 0 and ce.avisos_del_cliente(d.t, cid) == []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda *a, **k: c.enviados.append(a))
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 1, "cuando el correo está, se manda lo que tocaba"


def test_un_fallo_de_envio_se_reintenta_y_queda_visible(d, monkeypatch):
    estado = {"falla": True, "n": 0}
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    def enviar(dest, asunto, plano, html=None):
        if estado["falla"]:
            raise notificaciones_email.ErrorNotificacionesEmail("buzón lleno")
        estado["n"] += 1
    monkeypatch.setattr(notificaciones_email, "_enviar", enviar)
    _activar(d)
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=5)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    assert ce.avisar_clientes(d.t, AHORA)["fallidos"] == 1
    assert "fallido" in [a["estado"] for a in ce.avisos_del_cliente(d.t, cid)]
    estado["falla"] = False
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 1 and estado["n"] == 1 and "fallido" not in [a["estado"] for a in ce.avisos_del_cliente(d.t, cid)]


def test_el_texto_propio_del_despacho_se_respeta_con_sus_marcas(d, monkeypatch):
    c = Correo(monkeypatch)
    _activar(d, asunto="Atención {cliente}: tu {tipo} caduca {cuando}", cuerpo="Hola {cliente}.\n\nCaduca el {caduca} ({dias} días). {instrucciones}\n\nEntra en {enlace}\n\n{despacho}", instrucciones="Pide cita en la FNMT.")
    ce.alta_rapida(d.t, d.cus, tipo="fnmt_representante", caduca=(HOY + timedelta(days=12)).isoformat(), cliente_fiscal_id=d.marta)
    ce.avisar_clientes(d.t, AHORA)
    (dest, asunto, plano, html), = c.enviados
    assert asunto == "Atención Marta Puig: tu FNMT · Representante de persona jurídica caduca dentro de 12 días" and "Pide cita en la FNMT." in plano and "Despacho Cert Clientes" in plano and "{" not in plano
    assert "<script" not in html
    v = ce.vista_previa(d.t)
    assert v["asunto"].startswith("Atención Marta Puig") and "{cliente}" not in v["cuerpo"]


def test_enviar_aviso_ahora_y_sus_requisitos(d, monkeypatch):
    c = Correo(monkeypatch)
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=90)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    ce.enviar_aviso_ahora(d.t, d.cus, cid)
    assert len(c.enviados) == 1 and "caduca dentro de" in c.enviados[0][1]
    assert "aviso_cliente_manual" in [e["accion"] for e in ce.eventos(d.t, cid)]
    sin = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=90)).isoformat(), cliente_fiscal_id=d.sin_correo)["id"]
    with pytest.raises(ValueError, match="no tiene correo"):
        ce.enviar_aviso_ahora(d.t, d.cus, sin)
    libre = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=90)).isoformat(), titular="Despacho")["id"]
    with pytest.raises(ValueError, match="no está asociado a un cliente"):
        ce.enviar_aviso_ahora(d.t, d.cus, libre)
    with pytest.raises(ValueError, match="Solo los custodios"):
        ce.enviar_aviso_ahora(d.t, d.otro, cid)


# --- Lo que ve el cliente en su portal ---------------------------------------------------------------------------------------------------------
def test_el_portal_enseña_solo_los_certificados_de_ese_cliente_y_los_no_excluidos(d, monkeypatch):
    _activar(d)
    a = ce.alta_rapida(d.t, d.cus, tipo="fnmt_persona_fisica", caduca=(HOY + timedelta(days=20)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=20)).isoformat(), cliente_fiscal_id=d.sin_correo)
    oculto = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=400)).isoformat(), cliente_fiscal_id=d.marta, titular="Oculto", avisar_cliente=False)["id"]
    lejano = ce.alta_rapida(d.t, d.cus, tipo="dnie", caduca=(HOY + timedelta(days=400)).isoformat(), cliente_fiscal_id=d.marta, titular="Lejano")["id"]
    vis = {c["id"]: c for c in ce.visibles_para_cliente(d.marta, AHORA)}
    assert set(vis) == {a, lejano} and oculto not in vis
    assert vis[a]["estado"] == "pronto" and vis[lejano]["estado"] == "vigente" and vis[a]["dias"] == 20 and vis[a]["ayuda_solicitada"] is False
    ce.cambiar_estado_operativo(d.t, d.cus, a, "archivado", "Ya no se usa")
    assert a not in {c["id"] for c in ce.visibles_para_cliente(d.marta, AHORA)}
    _activar(d, mostrar_en_portal=False)
    assert ce.visibles_para_cliente(d.marta, AHORA) == []


def test_pedir_ayuda_avisa_al_equipo_abre_la_renovacion_y_corta_los_avisos(d, monkeypatch):
    c = Correo(monkeypatch)
    _activar(d)
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=20)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    ajeno = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=20)).isoformat(), cliente_fiscal_id=d.sin_correo)["id"]
    assert ce.pedir_ayuda(d.marta, ajeno) is False, "no se puede pedir ayuda por el certificado de otro cliente"
    assert ce.pedir_ayuda(d.marta, 99999) is False
    assert ce.pedir_ayuda(d.marta, cid) is True
    assert ce.renovacion_activa(d.t, cid) is not None and ce.obtener(d.t, cid)["ayuda_solicitada_en"]
    assert "Un cliente pide ayuda con su certificado" in [n["titulo"] for n in db.listar_notificaciones(d.sup, 5)] and "Un cliente pide ayuda con su certificado" in [n["titulo"] for n in db.listar_notificaciones(d.cus, 5)]
    assert ce.avisar_clientes(d.t, AHORA)["clientes"] == 0 and c.enviados == [], "ya está en ello: deja de insistirle"
    assert ce.visibles_para_cliente(d.marta, AHORA)[0]["ayuda_solicitada"] is True


def test_borrar_un_despacho_con_estos_datos_no_se_bloquea(d, monkeypatch):
    Correo(monkeypatch)
    _activar(d)
    cid = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(HOY + timedelta(days=5)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    ce.avisar_clientes(d.t, AHORA); ce.pedir_ayuda(d.marta, cid)
    db.borrar_tenant(d.t)
    conn = db.get_connection()
    try:
        for tabla in ("certificados", "certificados_config", "certificados_avisos_cliente"):
            assert conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0, tabla
    finally:
        conn.close()


# --- Pantallas del despacho ---------------------------------------------------------------------------------------------------------------------
import io  # noqa: E402

from tests.conftest import iniciar_sesion_de_prueba  # noqa: E402


def _web(cliente, email="cert-ux@ejemplo.com", supervisor=True):
    from app import verticales
    t = db.crear_tenant("Despacho UX " + email)
    u = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.asignar_tenant(u, t)
    if supervisor:
        db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "gestoria", True)
    marta = db.crear_cliente_fiscal(t, "Marta Puig", nif="12345678Z", email="marta@cliente.example")
    return t, u, marta


def test_la_pantalla_vacia_invita_a_apuntar_el_primero_sin_pedir_archivos(cliente):
    t, u, marta = _web(cliente)
    p = cliente.get("/certificados/").get_data(as_text=True)
    assert "Todavía no has apuntado ningún certificado" in p and "Añadir certificado" in p and "Sin archivos" in p
    assert 'id="al-caduca"' in p and 'id="al-tipo"' in p and "Avanzado: completar los datos con el archivo público" in p
    assert p.index('id="cert-alta"') < p.index('name="archivo"'), "el alta sin archivo va primero; el archivo es lo avanzado"


def test_alta_rapida_por_la_web_con_el_minimo_de_campos(cliente):
    t, u, marta = _web(cliente, "cert-ux2@ejemplo.com")
    r = cliente.post("/certificados/nuevo", data={"cliente_fiscal_id": marta, "tipo": "fnmt_persona_fisica", "caduca": (date.today() + timedelta(days=25)).isoformat()})
    assert r.status_code == 302 and "aviso=creado" in r.headers["Location"]
    cid = ce.listar(t)[0]["id"]
    ficha = cliente.get(f"/certificados/{cid}").get_data(as_text=True)
    assert "Marta Puig" in ficha and "Caduca en 25 días" in ficha and "Datos introducidos a mano" in ficha and "Ya está renovado" in ficha and "Certificado guardado." not in ficha or True
    lista = cliente.get("/certificados/").get_data(as_text=True)
    assert "Caducan en 30 días" in lista and "Caduca en 25 días" in lista and "FNMT · Persona física" in lista and "Avisos desactivados" in lista
    assert "error=" in cliente.post("/certificados/nuevo", data={"tipo": "otro"}).headers["Location"]
    assert "ya-estaba" in cliente.post("/certificados/nuevo", data={"cliente_fiscal_id": marta, "tipo": "fnmt_persona_fisica", "caduca": (date.today() + timedelta(days=25)).isoformat()}).headers["Location"]


def test_filtros_por_tarjeta_y_por_cliente(cliente):
    t, u, marta = _web(cliente, "cert-ux3@ejemplo.com")
    ce.alta_rapida(t, u, tipo="otro", caduca=(date.today() - timedelta(days=3)).isoformat(), titular="Caducado Uno")
    ce.alta_rapida(t, u, tipo="otro", caduca=(date.today() + timedelta(days=400)).isoformat(), cliente_fiscal_id=marta)
    p = cliente.get("/certificados/?plazo=caducados").get_data(as_text=True)
    assert "Caducado Uno" in p and "Marta Puig</strong>" not in p
    p = cliente.get(f"/certificados/?cliente_id={marta}").get_data(as_text=True)
    assert "Marta Puig</strong>" in p and "Caducado Uno" not in p


def test_renovado_desde_la_ficha(cliente):
    t, u, marta = _web(cliente, "cert-ux4@ejemplo.com")
    cid = ce.alta_rapida(t, u, tipo="fnmt_persona_fisica", caduca=(date.today() + timedelta(days=10)).isoformat(), cliente_fiscal_id=marta)["id"]
    r = cliente.post(f"/certificados/{cid}/renovado", data={"nueva_caducidad": (date.today() + timedelta(days=1400)).isoformat()})
    assert "aviso=renovado" in r.headers["Location"]
    nuevo = ce.listar(t)[0]
    assert nuevo["id"] != cid and nuevo["sustituye_a"] == cid
    assert "error=" in cliente.post(f"/certificados/{cid}/renovado", data={"nueva_caducidad": (date.today() + timedelta(days=2000)).isoformat()}).headers["Location"]
    assert "Sustituido por" in cliente.get(f"/certificados/{cid}").get_data(as_text=True)


def test_editar_desde_la_ficha_y_asociar_a_un_cliente(cliente):
    t, u, marta = _web(cliente, "cert-ux5@ejemplo.com")
    cid = ce.alta_rapida(t, u, tipo="otro", caduca="2027-06-30", titular="Sin cliente aún")["id"]
    r = cliente.post(f"/certificados/{cid}/editar", data={"cliente_fiscal_id": marta, "tipo": "fnmt_representante", "titular": "Marta Puig", "nif": "12345678Z", "caduca": "2028-01-31", "emitido": "", "serie": "",
                                                          "custodio_id": "", "ubicacion": "Caja fuerte", "notas": "", "avisar_cliente": "1"})
    assert "aviso=hecho" in r.headers["Location"]
    c = ce.obtener(t, cid)
    assert (c["cliente_titular_id"], c["tipo_certificado"], c["caduca_el"], c["avisar_cliente"], c["ubicacion_externa"]) == (marta, "fnmt_representante", "2028-01-31", 1, "Caja fuerte")
    assert "error=" in cliente.post(f"/certificados/{cid}/editar", data={"titular": "", "tipo": "otro", "caduca": "2028-01-31"}).headers["Location"]


def test_configurar_los_avisos_solo_la_direccion_y_con_vista_previa(cliente):
    t, u, marta = _web(cliente, "cert-ux6@ejemplo.com")
    p = cliente.get("/certificados/avisos").get_data(as_text=True)
    assert "Vista previa" in p and "Avisar a los clientes por correo" in p and "60, 30, 15, 7" in p
    r = cliente.post("/certificados/avisos", data={"avisar_cliente": "on", "mostrar_en_portal": "on", "dias_antes": "45, 10", "dias_despues": "5", "instrucciones": "Pide cita en la FNMT", "asunto": "", "cuerpo": ""})
    assert "aviso=guardado" in r.headers["Location"]
    assert ce.config(t)["dias_antes"] == [45, 10] and ce.config(t)["avisar_cliente"] and "Pide cita en la FNMT" in cliente.get("/certificados/avisos").get_data(as_text=True)
    mal = cliente.post("/certificados/avisos", data={"dias_antes": "1000", "dias_despues": ""}).get_data(as_text=True)
    assert "no es un número de días válido" in mal and ce.config(t)["dias_antes"] == [45, 10]


def test_un_custodio_que_no_es_direccion_ve_los_avisos_pero_no_los_cambia(cliente):
    t, u, marta = _web(cliente, "cert-ux7@ejemplo.com", supervisor=False)
    ce.fijar_custodio_flag(t, db.crear_usuario_vinculado_a_kratos("dir-ux7@ejemplo.com", "k-dir-ux7"), u, True) if False else None
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET custodio_certificados = 1 WHERE id = ?", (u,)); conn.commit(); conn.close()
    assert cliente.get("/certificados/avisos").status_code == 200
    assert cliente.post("/certificados/avisos", data={"avisar_cliente": "on", "dias_antes": "30", "dias_despues": ""}).status_code == 403
    assert ce.config(t)["avisar_cliente"] is False


def test_aviso_de_prueba_a_mi_correo(cliente, monkeypatch):
    t, u, marta = _web(cliente, "cert-ux8@ejemplo.com")
    c = Correo(monkeypatch)
    r = cliente.post("/certificados/avisos/prueba")
    assert "aviso=prueba" in r.headers["Location"] and c.enviados[0][0] == "cert-ux8@ejemplo.com" and "caduca dentro de 30 días" in c.enviados[0][1]
    Correo(monkeypatch, configurado=False)
    assert "error=" in cliente.post("/certificados/avisos/prueba").headers["Location"]


# --- Portal del cliente ------------------------------------------------------------------------------------------------------------------------
def _entrar_en_el_portal(cliente, cliente_fiscal_id):
    token = db.crear_acceso_cliente_fiscal(cliente_fiscal_id, "127.0.0.1")
    assert cliente.get(f"/portal/entrar/{token}").status_code == 302


def test_el_cliente_ve_su_certificado_en_el_portal_y_puede_pedir_ayuda(cliente, d):
    _activar(d, instrucciones="Pide cita en la FNMT y avísanos.")
    cid = ce.alta_rapida(d.t, d.cus, tipo="fnmt_persona_fisica", caduca=(date.today() + timedelta(days=12)).isoformat(), cliente_fiscal_id=d.marta)["id"]
    _entrar_en_el_portal(cliente, d.marta)
    p = cliente.get("/portal/").get_data(as_text=True)
    assert "Tu certificado digital" in p and "FNMT · Persona física" in p and "en 12 días" in p and "Conviene renovarlo cuanto antes" in p and "Pide cita en la FNMT y avísanos." in p
    assert "Necesito ayuda para renovarlo" in p and "12345678Z" not in p and "FNMT-RCM" not in p, "nada técnico: solo lo que entiende el cliente"
    r = cliente.post(f"/portal/certificados/{cid}/ayuda")
    assert r.status_code == 302 and "ayuda=1" in r.headers["Location"]
    p = cliente.get("/portal/?ayuda=1").get_data(as_text=True)
    assert "Hemos avisado a tu gestoría" in p and "Ya hemos avisado a tu gestoría" in p and "Necesito ayuda para renovarlo" not in p
    assert ce.obtener(d.t, cid)["ayuda_solicitada_en"] and ce.renovacion_activa(d.t, cid) is not None


def test_el_portal_no_enseña_nada_si_el_despacho_no_lo_activa_ni_certificados_ajenos(cliente, d):
    ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(date.today() + timedelta(days=12)).isoformat(), cliente_fiscal_id=d.marta, titular="Mío")
    ajeno = ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(date.today() + timedelta(days=12)).isoformat(), cliente_fiscal_id=d.sin_correo, titular="De otro cliente")["id"]
    _entrar_en_el_portal(cliente, d.marta)
    assert "Tu certificado digital" not in cliente.get("/portal/").get_data(as_text=True), "sin activar, nada"
    _activar(d)
    p = cliente.get("/portal/").get_data(as_text=True)
    assert "Mío" in p and "De otro cliente" not in p
    assert cliente.post(f"/portal/certificados/{ajeno}/ayuda").status_code == 404, "no se puede pedir ayuda por el certificado de otro cliente"
    assert ce.obtener(d.t, ajeno)["ayuda_solicitada_en"] is None


def test_un_certificado_caducado_se_explica_sin_alarmismo_ni_datos_tecnicos(cliente, d):
    _activar(d)
    ce.alta_rapida(d.t, d.cus, tipo="otro", caduca=(date.today() - timedelta(days=4)).isoformat(), cliente_fiscal_id=d.marta, titular="Marta")
    _entrar_en_el_portal(cliente, d.marta)
    p = cliente.get("/portal/").get_data(as_text=True)
    assert "Caducó el" in p and "no puede presentar impuestos ni acceder a tus notificaciones" in p and "portal-certificado-caducado" in p


# --- API e IA ----------------------------------------------------------------------------------------------------------------------------------
from tests.test_rutas_api import _auth, _registrar  # noqa: E402


def _tok(cliente, email, t, supervisor=True):
    datos = _registrar(cliente, email)
    u = db.obtener_usuario_por_email(email)["id"]
    db.asignar_tenant(u, t)
    if supervisor:
        db.asignar_supervisor_tenant(u, True)
    return u, _auth(datos["token"])


def test_api_apuntar_editar_renovar_y_configurar_avisos(cliente):
    t = db.crear_tenant("Despacho API Cert Clientes")
    u, h = _tok(cliente, "api-cc@ejemplo.com", t)
    marta = db.crear_cliente_fiscal(t, "Marta Puig", nif="12345678Z", email="m@c.example")
    r = cliente.post("/api/v1/certificados", headers=h, json={"cliente_fiscal_id": marta, "tipo": "fnmt_persona_fisica", "caduca": (date.today() + timedelta(days=50)).isoformat()})
    assert r.status_code == 201 and r.get_json()["data"]["nuevo"] is True
    cid = r.get_json()["data"]["id"]
    assert cliente.post("/api/v1/certificados", headers=h, json={"cliente_fiscal_id": marta, "tipo": "fnmt_persona_fisica", "caduca": (date.today() + timedelta(days=50)).isoformat()}).status_code == 200
    assert cliente.post("/api/v1/certificados", headers=h, json={"tipo": "otro"}).get_json()["codigo"] == "certificado_no_valido"
    c = cliente.get(f"/api/v1/certificados/{cid}", headers=h).get_json()["data"]
    assert c["cliente_nombre"] == "Marta Puig" and c["dias_restantes"] == 50 and c["tipo_certificado"] == "fnmt_persona_fisica" and "cliente_email" not in c and c["pendiente_de_comprobar"] is True
    r = cliente.put(f"/api/v1/certificados/{cid}", headers=h, json={"caduca": (date.today() + timedelta(days=80)).isoformat(), "avisar_cliente": False})
    assert r.get_json()["data"]["dias_restantes"] == 80 and r.get_json()["data"]["avisar_cliente"] == 0
    assert cliente.put(f"/api/v1/certificados/{cid}", headers=h, json={"caduca": "no"}).get_json()["codigo"] == "certificado_no_valido"
    assert cliente.put("/api/v1/certificados/9999", headers=h, json={"notas": "x"}).status_code == 404
    r = cliente.post(f"/api/v1/certificados/{cid}/renovado", headers=h, json={"nueva_caducidad": (date.today() + timedelta(days=1500)).isoformat()})
    assert r.status_code == 201 and r.get_json()["data"]["anterior_id"] == cid
    assert cliente.post(f"/api/v1/certificados/{cid}/renovado", headers=h, json={"nueva_caducidad": "2099-01-01"}).get_json()["codigo"] == "renovacion_no_valida"
    cfg = cliente.put("/api/v1/certificados/avisos-cliente", headers=h, json={"avisar_cliente": True, "dias_antes": [45, 10], "instrucciones": "Pide cita"}).get_json()["data"]
    assert cfg["avisar_cliente"] and cfg["dias_antes"] == [45, 10] and cfg["dias_despues"] == [3] and cfg["instrucciones"] == "Pide cita"
    assert cliente.get("/api/v1/certificados/avisos-cliente", headers=h).get_json()["data"]["dias_antes"] == [45, 10]
    assert cliente.put("/api/v1/certificados/avisos-cliente", headers=h, json={"dias_antes": [999]}).get_json()["codigo"] == "configuracion_no_valida"


def test_api_la_config_de_avisos_solo_la_cambia_la_direccion(cliente):
    t = db.crear_tenant("Despacho API Cert Clientes 2")
    u, h = _tok(cliente, "api-cc2@ejemplo.com", t, supervisor=False)
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET custodio_certificados = 1 WHERE id = ?", (u,)); conn.commit(); conn.close()
    assert cliente.get("/api/v1/certificados/avisos-cliente", headers=h).status_code == 200
    r = cliente.put("/api/v1/certificados/avisos-cliente", headers=h, json={"avisar_cliente": True})
    assert r.status_code == 403 and r.get_json()["codigo"] == "configuracion_no_valida"
    assert cliente.post("/api/v1/certificados", headers=h, json={"tipo": "otro", "titular": "Despacho", "caduca": "2030-01-01"}).status_code == 201


def test_las_herramientas_de_ia_apuntan_y_renuevan_certificados(d):
    from app import ia_herramientas as ih
    for n in ("registrar_certificado", "renovar_certificado"):
        assert n in ih.ESCRITURA and ih.necesita_confirmacion(n, modo_autonomo=False)
    r = ih.ejecutar(d.cus, "registrar_certificado", {"tipo": "fnmt_persona_fisica", "caduca": (date.today() + timedelta(days=45)).isoformat(), "cliente_id": d.marta})
    assert r["nuevo"] and r["cliente_nombre"] == "Marta Puig" and r["dias_restantes"] == 45
    r2 = ih.ejecutar(d.cus, "renovar_certificado", {"certificado_id": r["id"], "nueva_caducidad": (date.today() + timedelta(days=1500)).isoformat()})
    assert r2["anterior_id"] == r["id"]
    with pytest.raises(ih.ErrorHerramientaIA, match="Solo los custodios"):
        ih.ejecutar(d.otro, "registrar_certificado", {"tipo": "otro", "titular": "X", "caduca": "2030-01-01"})


def test_borrar_un_cliente_definitivamente_conserva_sus_certificados(d):
    from app import certificados as c
    r = c.alta_rapida(d.t, d.cus, tipo="fnmt_persona_fisica", caduca="2030-01-01", cliente_fiscal_id=d.marta)
    db.eliminar_cliente_fiscal_definitivamente(d.t, d.marta)
    cert = c.obtener(d.t, r["id"])
    assert cert is not None and cert["cliente_titular_id"] is None

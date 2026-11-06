"""Personas con acceso al portal (H1/H2), avisos a medida (F1–F4), sesión recordada y avisos en el móvil (G2/G3)."""
import json
from datetime import date, datetime, timedelta

import pytest

from app import auditoria, db, facturas_contables as fc, facturas_portal, justificantes, notificaciones_email, portal_avisos, portal_personas, portal_push, portal_recordatorios, push, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba


@pytest.fixture
def correo(monkeypatch):
    enviados = []
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://work.ejemplo.com")
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda dest, asunto, cuerpo, html=None: enviados.append((dest, asunto, cuerpo, html)))
    return enviados


def _despacho(nombre="Gestoria P", cliente_email="titular@ejemplo.com", cliente_nombre="Cliente P SL"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"resp-{nombre}@ejemplo.com".replace(" ", ""), "k-" + nombre.replace(" ", ""))
    db.asignar_tenant(u, t)
    verticales.fijar_activo(t, "contabilizacion", True)
    verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, cliente_nombre, nif="B12345678", email=cliente_email)
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET responsable_id = ? WHERE id = ?", (u, c)); conn.commit(); conn.close()
    return t, u, c


def _ficha(c):
    return db.obtener_cliente_fiscal_por_id(c)


def _entrar(http, c, email, extra=""):
    token = db.crear_acceso_cliente_fiscal(c, "127.0.0.1", email=email)
    return http.get(f"/portal/entrar/{token}{extra}")


def _html(http, ruta):
    r = http.get(ruta)
    assert r.status_code == 200, ruta
    return r.get_data(as_text=True)


# --- H1: personas y perfiles ------------------------------------------------------------------------------------------------------------------------

def test_el_titular_es_siempre_acceso_completo_y_el_contacto_tiene_el_perfil_que_se_le_da():
    t, u, c = _despacho()
    ficha = _ficha(c)
    portal_personas.anadir(ficha, "Admin@Ejemplo.com", "Ana", "administracion", por=u)
    assert portal_personas.rol_de(ficha, "titular@ejemplo.com") == "completo"
    assert portal_personas.rol_de(ficha, "admin@ejemplo.com") == "administracion"
    assert portal_personas.rol_de(ficha, "otro@ejemplo.com") is None
    assert portal_personas.rol_de(ficha, None) == "completo", "sesiones anteriores a los contactos: el titular"
    assert [p["email"] for p in portal_personas.listar(ficha)] == ["titular@ejemplo.com", "admin@ejemplo.com"]


@pytest.mark.parametrize("email, rol, esperado", [("no-es-email", "consulta", "email válido"), ("a@b.es", "dios", "Perfil no válido"), ("titular@ejemplo.com", "consulta", "ya es el del titular")])
def test_no_se_da_acceso_con_datos_invalidos(email, rol, esperado):
    t, u, c = _despacho("Gestoria inv")
    with pytest.raises(ValueError, match=esperado):
        portal_personas.anadir(_ficha(c), email, "X", rol)


def test_hay_un_maximo_de_contactos_y_no_se_repiten():
    t, u, c = _despacho("Gestoria max")
    ficha = _ficha(c)
    for i in range(portal_personas.MAX_CONTACTOS):
        portal_personas.anadir(ficha, f"p{i}@ejemplo.com", "", "consulta")
    with pytest.raises(ValueError, match="hasta"):
        portal_personas.anadir(ficha, "uno-mas@ejemplo.com", "", "consulta")
    with pytest.raises(ValueError, match="ya tiene acceso"):
        portal_personas.anadir(ficha, "p0@ejemplo.com", "", "consulta")


def test_quitar_a_un_contacto_le_corta_el_acceso_y_se_le_puede_volver_a_dar():
    t, u, c = _despacho("Gestoria quitar")
    ficha = _ficha(c)
    cid = portal_personas.anadir(ficha, "temp@ejemplo.com", "Temp", "completo")
    assert portal_personas.quitar(ficha, cid) == "temp@ejemplo.com"
    assert portal_personas.rol_de(ficha, "temp@ejemplo.com") is None and portal_personas.clientes_de("temp@ejemplo.com") == []
    portal_personas.anadir(ficha, "temp@ejemplo.com", "Temp", "consulta")
    assert portal_personas.rol_de(ficha, "temp@ejemplo.com") == "consulta"


def test_un_contacto_entra_con_su_email_y_su_sesion_se_corta_si_le_quitan_el_acceso(cliente):
    t, u, c = _despacho("Gestoria sesion")
    ficha = _ficha(c)
    cid = portal_personas.anadir(ficha, "admin@ejemplo.com", "Ana", "administracion")
    r = _entrar(cliente, c, "admin@ejemplo.com")
    assert r.status_code == 302 and r.headers["Location"].endswith("/portal/")
    with cliente.session_transaction() as s:
        assert s["portal_email"] == "admin@ejemplo.com" and s["cliente_fiscal_id"] == c
    assert "Cliente P SL" in _html(cliente, "/portal/")
    portal_personas.quitar(ficha, cid)
    assert cliente.get("/portal/").status_code == 302, "al quitarle el acceso, la siguiente petición lo echa"
    with cliente.session_transaction() as s:
        assert "cliente_fiscal_id" not in s


def test_un_enlace_pedido_por_quien_perdio_el_acceso_no_sirve(cliente):
    t, u, c = _despacho("Gestoria enlace")
    ficha = _ficha(c)
    cid = portal_personas.anadir(ficha, "temp@ejemplo.com", "", "completo")
    token = db.crear_acceso_cliente_fiscal(c, "127.0.0.1", email="temp@ejemplo.com")
    portal_personas.quitar(ficha, cid)
    r = cliente.get(f"/portal/entrar/{token}")
    assert r.status_code == 200 and "caducado" in r.get_data(as_text=True)


def test_el_enlace_de_acceso_se_manda_a_quien_lo_pide_y_solo_una_vez_en_el_cooldown(cliente, correo, monkeypatch):
    t, u, c = _despacho("Gestoria login")
    portal_personas.anadir(_ficha(c), "admin@ejemplo.com", "Ana", "administracion")
    enlaces = []
    monkeypatch.setattr("app.rutas_portal_cliente.enviar_enlace_portal", lambda dest, enlace, **kw: enlaces.append((dest, enlace)))
    assert cliente.post("/portal/entrar", data={"email": "Admin@Ejemplo.com", "recordar": "1"}).status_code == 200
    assert len(enlaces) == 1 and enlaces[0][0] == "admin@ejemplo.com" and "r=1" in enlaces[0][1]
    cliente.post("/portal/entrar", data={"email": "admin@ejemplo.com"})
    assert len(enlaces) == 1, "el cooldown es por persona"
    cliente.post("/portal/entrar", data={"email": "titular@ejemplo.com"})
    assert len(enlaces) == 2, "otra persona de la misma ficha no queda bloqueada"
    cliente.post("/portal/entrar", data={"email": "nadie@ejemplo.com"})
    assert len(enlaces) == 2


# --- H2: varias sociedades con un mismo email ------------------------------------------------------------------------------------------------------

def test_un_email_en_varias_fichas_ve_todas_y_cambia_de_una_a_otra(cliente):
    t, u, c1 = _despacho("Gestoria varias", cliente_email="dueno@ejemplo.com", cliente_nombre="Sociedad Uno SL")
    c2 = crear_cliente_fiscal(t, "Sociedad Dos SL", nif="B87654321", email="dueno@ejemplo.com")
    c3 = crear_cliente_fiscal(t, "Sociedad Tres SL", nif="B11223344", email="otro@ejemplo.com")
    portal_personas.anadir(_ficha(c3), "dueno@ejemplo.com", "", "consulta")
    assert [x["nombre"] for x in portal_personas.clientes_de("dueno@ejemplo.com")] == ["Sociedad Dos SL", "Sociedad Tres SL", "Sociedad Uno SL"]
    _entrar(cliente, c1, "dueno@ejemplo.com")
    html = _html(cliente, "/portal/")
    assert "Sociedad Uno SL" in html and 'name="cliente_id"' in html and "Sociedad Dos SL" in html and "Sociedad Tres SL" in html
    assert cliente.post("/portal/cambiar-titular", data={"cliente_id": c2}).status_code == 302
    assert "Sociedad Dos SL" in _html(cliente, "/portal/")
    assert portal_personas.rol_de(_ficha(c3), "dueno@ejemplo.com") == "consulta"
    cliente.post("/portal/cambiar-titular", data={"cliente_id": c3})
    html3 = _html(cliente, "/portal/")
    assert "Sociedad Tres SL" in html3 and "solo consulta" in _html(cliente, "/portal/cuenta").lower()


def test_no_se_puede_cambiar_a_la_ficha_de_otro(cliente):
    t, u, c1 = _despacho("Gestoria ajena", cliente_email="dueno@ejemplo.com")
    ajena = crear_cliente_fiscal(t, "Ajena SL", nif="B99999999", email="ajeno@ejemplo.com")
    _entrar(cliente, c1, "dueno@ejemplo.com")
    cliente.post("/portal/cambiar-titular", data={"cliente_id": ajena})
    with cliente.session_transaction() as s:
        assert s["cliente_fiscal_id"] == c1
    assert "Ajena SL" not in _html(cliente, "/portal/")


def test_un_enlace_directo_a_otra_sociedad_la_abre(cliente):
    t, u, c1 = _despacho("Gestoria directo", cliente_email="dueno@ejemplo.com", cliente_nombre="Sociedad Uno SL")
    c2 = crear_cliente_fiscal(t, "Sociedad Dos SL", nif="B87654321", email="dueno@ejemplo.com")
    v = db.crear_vencimiento_fiscal(t, c2, "303", "2026-T3", "2026-10-20", usuario_id=u)
    token = db.crear_acceso_cliente_fiscal(c1, "127.0.0.1", email="dueno@ejemplo.com")
    r = cliente.get(f"/portal/entrar/{token}?siguiente=/portal/vencimientos/{v}/documentos&c={c2}")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/portal/vencimientos/{v}/documentos")
    assert cliente.get(f"/portal/vencimientos/{v}/documentos").status_code == 200


def test_la_url_del_correo_lleva_la_ficha(monkeypatch):
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://work.ejemplo.com")
    assert portal_recordatorios.url_portal("/portal/facturas", 7) == "https://work.ejemplo.com/portal/entrar?siguiente=%2Fportal%2Ffacturas&c=7"


# --- Perfiles sobre lo que se puede hacer ------------------------------------------------------------------------------------------------------------

def test_consulta_solo_mira_y_administracion_no_firma_ni_paga_ni_da_la_conformidad(cliente):
    t, u, c = _despacho("Gestoria perfiles")
    ficha = _ficha(c)
    portal_personas.anadir(ficha, "consulta@ejemplo.com", "", "consulta")
    portal_personas.anadir(ficha, "admin@ejemplo.com", "", "administracion")
    f = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "P-1", "tercero_nombre": "Ferretería", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})
    _entrar(cliente, c, "consulta@ejemplo.com")
    assert cliente.get("/portal/facturas").status_code == 200
    r = cliente.post(f"/portal/facturas/{f}/mensajes", data={"texto": "hola"})
    assert r.status_code == 403 and "no puede hacer esto" in r.get_data(as_text=True)
    assert facturas_portal.mensajes(t, f) == []
    assert cliente.post("/portal/preferencias", data={"avisos": "resumen"}).status_code == 302, "sus propios avisos sí"
    with cliente.session_transaction() as s:
        s.clear()
    _entrar(cliente, c, "admin@ejemplo.com")
    assert cliente.post(f"/portal/facturas/{f}/mensajes", data={"texto": "hola"}).status_code == 302
    assert len(facturas_portal.mensajes(t, f)) == 1
    assert cliente.post("/portal/vencimientos/1/pagar").status_code == 403
    assert cliente.post("/portal/declaraciones/1/conformidad", data={"resultado": "ok"}).status_code == 403
    assert cliente.post("/portal/contactos", data={"email": "x@ejemplo.com", "rol": "consulta"}).status_code == 403


def test_administracion_no_ve_firmar_ni_conformidad_en_para_hacer(cliente):
    t, u, c = _despacho("Gestoria hacer")
    portal_personas.anadir(_ficha(c), "admin@ejemplo.com", "", "administracion")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    db.editar_vencimiento_fiscal(t, v, documenso_documento_id="doc-1")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Tienes un documento por firmar" in _html(cliente, "/portal/")
    with cliente.session_transaction() as s:
        s.clear()
    _entrar(cliente, c, "admin@ejemplo.com")
    assert "Tienes un documento por firmar" not in _html(cliente, "/portal/")
    assert cliente.get(f"/portal/vencimientos/{v}/firma").status_code == 403


def test_lo_que_hace_cada_persona_queda_en_la_auditoria_con_su_nombre(cliente):
    t, u, c = _despacho("Gestoria audit")
    portal_personas.anadir(_ficha(c), "admin@ejemplo.com", "", "administracion")
    f = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-10", "numero": "P-1", "tercero_nombre": "Ferretería", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})
    _entrar(cliente, c, "admin@ejemplo.com")
    cliente.post(f"/portal/facturas/{f}/mensajes", data={"texto": "hola"})
    eventos = auditoria.listar(t, entidad="cliente_fiscal", entidad_id=c)
    assert {"portal.entrada", "portal.accion"} <= {e["accion"] for e in eventos}
    assert any(isinstance(e["detalle"], dict) and e["detalle"].get("quien") == "admin@ejemplo.com" and e["detalle"].get("pantalla") == "mensaje_de_factura" for e in eventos)


# --- F2: avisos a medida ----------------------------------------------------------------------------------------------------------------------------------

def test_destinatarios_segun_lo_que_cada_uno_eligio_y_su_perfil():
    t, u, c = _despacho("Gestoria dest")
    ficha = _ficha(c)
    portal_personas.anadir(ficha, "resumen@ejemplo.com", "", "completo")
    portal_personas.anadir(ficha, "urgente@ejemplo.com", "", "administracion")
    portal_personas.anadir(ficha, "consulta@ejemplo.com", "", "consulta")
    portal_personas.fijar_avisos(ficha, "resumen@ejemplo.com", "resumen")
    portal_personas.fijar_avisos(ficha, "urgente@ejemplo.com", "urgente")
    ficha = _ficha(c)
    assert portal_personas.destinatarios(ficha) == ["titular@ejemplo.com", "consulta@ejemplo.com"]
    assert portal_personas.destinatarios(ficha, urgente=True) == ["titular@ejemplo.com", "consulta@ejemplo.com", "urgente@ejemplo.com"]
    assert portal_personas.destinatarios(ficha, accion="decidir") == ["titular@ejemplo.com"]
    assert portal_personas.destinatarios(ficha, urgente=True, accion="subir") == ["titular@ejemplo.com", "urgente@ejemplo.com"]
    assert [p["email"] for p in portal_personas.para_resumen(ficha)] == ["resumen@ejemplo.com"]
    with pytest.raises(ValueError):
        portal_personas.fijar_avisos(ficha, "titular@ejemplo.com", "siempre")


def test_cada_correo_lleva_el_enlace_para_cambiar_los_avisos_y_funciona_sin_entrar(cliente, correo):
    t, u, c = _despacho("Gestoria pie")
    ficha = _ficha(c)
    portal_avisos.correo_directo(ficha, lambda e: notificaciones_email.enviar_respuesta_portal(e, "Hola", "https://work.ejemplo.com/portal/entrar", tenant_id=t))
    destino, asunto, cuerpo, html = correo[0]
    assert destino == "titular@ejemplo.com" and "https://work.ejemplo.com/portal/preferencias/" in cuerpo and "Cambiar los avisos que recibes" in html
    token = cuerpo.split("/portal/preferencias/")[1].split()[0]
    pagina = _html(cliente, f"/portal/preferencias/{token}")
    assert "titular@ejemplo.com" in pagina and "Un resumen cada lunes" in pagina
    r = cliente.post(f"/portal/preferencias/{token}", data={"avisos": "urgente"})
    assert r.status_code == 200 and "Guardado" in r.get_data(as_text=True)
    assert _ficha(c)["portal_avisos"] == "urgente"
    assert cliente.get("/portal/preferencias/token-falso").status_code == 404


def test_el_enlace_de_preferencias_de_quien_perdio_el_acceso_no_vale(cliente):
    t, u, c = _despacho("Gestoria pref2")
    ficha = _ficha(c)
    cid = portal_personas.anadir(ficha, "temp@ejemplo.com", "", "completo")
    token = portal_personas.token_preferencias(c, "temp@ejemplo.com")
    assert cliente.get(f"/portal/preferencias/{token}").status_code == 200
    portal_personas.quitar(ficha, cid)
    assert cliente.get(f"/portal/preferencias/{token}").status_code == 404


def test_las_preferencias_se_cambian_desde_mi_cuenta(cliente):
    t, u, c = _despacho("Gestoria cuenta")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/cuenta")
    assert "Qué avisos quieres recibir" in html and "Personas con acceso" in html
    cliente.post("/portal/preferencias", data={"avisos": "resumen"})
    assert _ficha(c)["portal_avisos"] == "resumen"
    assert 'value="resumen" checked' in _html(cliente, "/portal/cuenta")
    cliente.post("/portal/preferencias", data={"avisos": "x"})
    assert _ficha(c)["portal_avisos"] == "resumen", "una opción inventada no cambia nada"


def test_el_titular_gestiona_personas_desde_su_cuenta(cliente):
    t, u, c = _despacho("Gestoria gestion")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert cliente.post("/portal/contactos", data={"email": "nueva@ejemplo.com", "nombre": "Nueva", "rol": "consulta"}).status_code == 302
    persona = next(p for p in portal_personas.listar(_ficha(c)) if p["email"] == "nueva@ejemplo.com")
    assert persona["rol"] == "consulta" and "Nueva" in _html(cliente, "/portal/cuenta")
    cliente.post(f"/portal/contactos/{persona['id']}/perfil", data={"rol": "completo"})
    assert portal_personas.rol_de(_ficha(c), "nueva@ejemplo.com") == "completo"
    cliente.post(f"/portal/contactos/{persona['id']}/quitar")
    assert portal_personas.rol_de(_ficha(c), "nueva@ejemplo.com") is None


# --- Los avisos existentes respetan lo elegido ------------------------------------------------------------------------------------------------------

def test_el_recordatorio_de_un_vencimiento_llega_solo_a_quien_corresponde(correo):
    t, u, c = _despacho("Gestoria venc")
    ficha = _ficha(c)
    portal_personas.anadir(ficha, "resumen@ejemplo.com", "", "administracion")
    portal_personas.anadir(ficha, "urgente@ejemplo.com", "", "administracion")
    portal_personas.fijar_avisos(ficha, "resumen@ejemplo.com", "resumen")
    portal_personas.fijar_avisos(ficha, "urgente@ejemplo.com", "urgente")
    hoy = datetime(2026, 4, 10, 9, 0)
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T1", (hoy + timedelta(days=7)).strftime("%Y-%m-%d"), usuario_id=u)
    db.crear_vencimiento_fiscal(t, c, "130", "2026-T1", (hoy + timedelta(days=2)).strftime("%Y-%m-%d"), usuario_id=u)
    assert portal_recordatorios.procesar_recordatorios(hoy) == 3
    por_destino = sorted(d for d, *_ in correo)
    assert por_destino == ["titular@ejemplo.com", "titular@ejemplo.com", "urgente@ejemplo.com"], "a 7 días: el titular; a 2 días: el titular y quien eligió «urgente»; el del resumen, ninguno"


# --- F1: aviso al devolver una factura -----------------------------------------------------------------------------------------------------------------

def _factura_del_portal(c, numero="P-1"):
    return fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": "2026-08-10", "numero": numero, "tercero_nombre": "Ferretería Paco", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"})


def test_al_devolver_una_factura_el_cliente_recibe_un_correo_con_el_enlace_a_ella(correo):
    t, u, c = _despacho("Gestoria devolver")
    f = _factura_del_portal(c)
    assert facturas_portal.devolver(t, u, f, "Falta el NIF del proveedor") is True
    destino, asunto, cuerpo, _html_ = correo[-1]
    assert destino == "titular@ejemplo.com" and "Ferretería Paco" in asunto and "Falta el NIF del proveedor" in cuerpo
    assert "siguiente=%2Fportal%2Ffacturas%3Ftrimestre%3D2026-T3" in cuerpo and f"&c={c}" in cuerpo


def test_la_devolucion_respeta_a_quien_solo_quiere_el_resumen_y_no_falla_sin_correo(monkeypatch, correo):
    t, u, c = _despacho("Gestoria devolver2")
    portal_personas.fijar_avisos(_ficha(c), "titular@ejemplo.com", "resumen")
    f = _factura_del_portal(c)
    assert facturas_portal.devolver(t, u, f, "Falta el NIF") is False and correo == []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: False)
    f2 = _factura_del_portal(c, "P-2")
    assert facturas_portal.devolver(t, u, f2, "Falta el NIF") is False, "sin correo saliente la devolución se hace igual"
    assert facturas_portal.devueltas_sin_atender(c)


def test_un_contacto_de_consulta_no_recibe_el_aviso_de_algo_que_solo_puede_decidir_el_titular(correo):
    from app import cierre_trimestre  # noqa: F401
    t, u, c = _despacho("Gestoria decidir")
    portal_personas.anadir(_ficha(c), "consulta@ejemplo.com", "", "consulta")
    from app import justificantes as j
    j._avisar_al_cliente(t, c, 3)
    assert sorted(d for d, *_ in correo) == ["titular@ejemplo.com"], "pedir movimientos del banco es subir: la consulta no puede, no se le avisa"


# --- F3: el resumen de los lunes -------------------------------------------------------------------------------------------------------------------

LUNES = datetime(2026, 11, 2, 8, 30)


def test_el_resumen_semanal_llega_a_quien_lo_eligio_una_vez_por_semana_y_solo_si_hay_algo(correo):
    t, u, c = _despacho("Gestoria resumen")
    portal_personas.fijar_avisos(_ficha(c), "titular@ejemplo.com", "resumen")
    assert portal_avisos.procesar(LUNES)["resumenes"] == 0 and correo == [], "no hay nada pendiente: no se escribe"
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-11-20", usuario_id=u)
    conn = db.get_connection(); conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto del banco' WHERE id = ?", (v,)); conn.commit(); conn.close()
    assert portal_avisos.procesar(LUNES)["resumenes"] == 1
    destino, asunto, cuerpo, _h = correo[0]
    assert destino == "titular@ejemplo.com" and asunto == "Tu resumen semanal" and "Extracto del banco" in cuerpo and "/portal/preferencias/" in cuerpo
    assert portal_avisos.procesar(LUNES + timedelta(days=1))["resumenes"] == 0, "la misma semana no se repite"
    assert portal_avisos.procesar(LUNES + timedelta(days=7))["resumenes"] == 1, "la semana siguiente sí"
    assert portal_avisos.procesar(LUNES + timedelta(days=3))["resumenes"] == 0, "el jueves no se manda resumen"


def test_quien_prefiere_un_correo_por_cada_novedad_no_recibe_el_resumen(correo):
    t, u, c = _despacho("Gestoria resumen2")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-11-20", usuario_id=u)
    conn = db.get_connection(); conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto' WHERE id = ?", (v,)); conn.commit(); conn.close()
    assert portal_avisos.procesar(LUNES)["resumenes"] == 0


def test_un_cliente_fuera_de_los_recordatorios_automaticos_tampoco_recibe_resumen(correo):
    t, u, c = _despacho("Gestoria resumen3")
    portal_personas.fijar_avisos(_ficha(c), "titular@ejemplo.com", "resumen")
    db.editar_cliente_fiscal(t, c, recordatorios_portal=0)
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-11-20", usuario_id=u)
    conn = db.get_connection(); conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto' WHERE id = ?", (v,)); conn.commit(); conn.close()
    assert portal_avisos.procesar(LUNES)["resumenes"] == 0


# --- F4: recordatorios escalonados -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("edad, paso", [(0, None), (2, None), (3, 3), (7, 7), (9, 7), (12, 7), (13, None), (14, 14), (19, 14), (20, None), (40, None)])
def test_que_paso_toca_recordar(edad, paso):
    assert portal_avisos.paso_que_toca(edad) == paso


def _movimiento_pendiente(t, u, c, hace_dias, ahora=LUNES):
    antes = (ahora - timedelta(days=hace_dias)).isoformat(timespec="seconds")
    justificantes.pedir(t, u, c, [{"fecha": "2026-10-01", "importe": -5000, "concepto": "Cargo desconocido"}])
    conn = db.get_connection(); conn.execute("UPDATE justificantes_pendientes SET creado_en = ?", (antes,)); conn.commit(); conn.close()


def test_los_movimientos_sin_explicar_se_recuerdan_a_los_3_7_y_14_dias_sin_repetir(correo):
    t, u, c = _despacho("Gestoria escalon")
    _movimiento_pendiente(t, u, c, 3)
    correo.clear()
    assert portal_avisos.procesar(LUNES)["recordatorios"] == 1
    assert "sigue esperando" in correo[0][1] and "%2Fportal%2Fjustificantes" in correo[0][2]
    assert portal_avisos.procesar(LUNES + timedelta(hours=6))["recordatorios"] == 0, "no se repite el mismo paso"
    assert portal_avisos.procesar(LUNES + timedelta(days=4))["recordatorios"] == 1, "a los 7 días, el segundo"
    assert portal_avisos.procesar(LUNES + timedelta(days=11))["recordatorios"] == 1, "a los 14, el tercero"


def test_al_llegar_a_los_14_dias_tambien_se_avisa_al_equipo_una_vez(correo, monkeypatch):
    t, u, c = _despacho("Gestoria equipo")
    _movimiento_pendiente(t, u, c, 14)
    llamadas = []
    monkeypatch.setattr("app.facturas_contables.avisar_al_equipo", lambda f, titulo, cuerpo, url, datos: llamadas.append((f["id"], titulo, url)))
    portal_avisos.procesar(LUNES)
    portal_avisos.procesar(LUNES + timedelta(hours=6))
    assert len(llamadas) == 1 and llamadas[0][0] == c and "14 días sin contestar" in llamadas[0][1] and llamadas[0][2] == f"/fiscal/clientes/{c}/editar"


def test_lo_que_ya_venia_muy_atrasado_no_se_recuerda_de_golpe(correo):
    t, u, c = _despacho("Gestoria atrasado")
    _movimiento_pendiente(t, u, c, 60)
    correo.clear()
    assert portal_avisos.procesar(LUNES)["recordatorios"] == 0 and correo == []


def test_el_recordatorio_escalonado_no_sale_si_todos_prefieren_el_resumen(correo):
    t, u, c = _despacho("Gestoria escalon2")
    portal_personas.fijar_avisos(_ficha(c), "titular@ejemplo.com", "resumen")
    _movimiento_pendiente(t, u, c, 7)
    correo.clear()
    assert portal_avisos.procesar(LUNES)["recordatorios"] == 0
    assert portal_avisos.procesar(LUNES + timedelta(hours=6))["recordatorios"] == 0 and correo == [] or all("resumen" in a.lower() for _d, a, *_ in correo)


def test_un_documento_enviado_a_firma_se_recuerda_contando_desde_que_se_vio_por_primera_vez(correo):
    t, u, c = _despacho("Gestoria firma")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-11-20", usuario_id=u)
    db.editar_vencimiento_fiscal(t, v, documenso_documento_id="doc-1")
    assert portal_avisos.procesar(LUNES)["recordatorios"] == 0, "recién visto: aún no toca"
    assert portal_avisos.procesar(LUNES + timedelta(days=3))["recordatorios"] == 1
    assert "por firmar" in correo[-1][1] and f"%2Fportal%2Fvencimientos%2F{v}%2Ffirma" in correo[-1][2]
    db.editar_vencimiento_fiscal(t, v, documenso_firmado_en=db.now_iso())
    assert portal_avisos.procesar(LUNES + timedelta(days=7))["recordatorios"] == 0, "firmado: ya no se recuerda"


# --- G2: sesión recordada ------------------------------------------------------------------------------------------------------------------------------

def test_mantener_la_sesion_la_hace_persistente_y_caduca_a_los_30_dias(cliente):
    t, u, c = _despacho("Gestoria recordar")
    _entrar(cliente, c, "titular@ejemplo.com", "?r=1")
    with cliente.session_transaction() as s:
        assert s.permanent is True
        hasta = datetime.fromisoformat(s["portal_hasta"])
    assert timedelta(days=29) < hasta - datetime.now() <= timedelta(days=30)
    assert cliente.get("/portal/").status_code == 200
    with cliente.session_transaction() as s:
        s["portal_hasta"] = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
    assert cliente.get("/portal/").status_code == 302
    with cliente.session_transaction() as s:
        assert "cliente_fiscal_id" not in s


def test_sin_marcar_la_casilla_la_sesion_no_lleva_caducidad_propia(cliente):
    t, u, c = _despacho("Gestoria sin recordar")
    _entrar(cliente, c, "titular@ejemplo.com")
    with cliente.session_transaction() as s:
        assert "portal_hasta" not in s
    assert "Mantener la sesión abierta" in cliente.get("/portal/entrar").get_data(as_text=True)


def test_el_portal_se_puede_instalar_como_app(cliente):
    t, u, c = _despacho("Gestoria pwa")
    _entrar(cliente, c, "titular@ejemplo.com")
    m = cliente.get("/portal/manifest.webmanifest")
    assert m.status_code == 200 and m.mimetype == "application/manifest+json"
    datos = json.loads(m.get_data(as_text=True))
    assert datos["start_url"] == "/portal/" and datos["scope"] == "/portal/" and datos["display"] == "standalone"
    html = _html(cliente, "/portal/")
    assert "/portal/manifest.webmanifest" in html and "sw_registro.js" in html


# --- G3: avisos en el móvil ----------------------------------------------------------------------------------------------------------------------------

SUSCRIPCION = {"endpoint": "https://push.ejemplo.com/abc", "keys": {"p256dh": "clave-publica", "auth": "secreto"}}


@pytest.fixture
def push_activo(monkeypatch):
    enviados = []
    monkeypatch.setattr(push, "VAPID_PUBLICA", "clave-vapid-publica")
    monkeypatch.setattr(push, "VAPID_PRIVADA", "clave-vapid-privada")
    monkeypatch.setattr(push, "_enviar_web", lambda sus, carga: enviados.append((json.loads(sus)["endpoint"], carga)) or True)
    return enviados


def test_una_persona_activa_los_avisos_en_su_dispositivo_y_los_recibe(cliente, push_activo):
    t, u, c = _despacho("Gestoria push")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert cliente.get("/portal/push/clave").get_json() == {"clave": "clave-vapid-publica"}
    assert cliente.post("/portal/push/suscribir", json=SUSCRIPCION).get_json() == {"ok": True}
    assert portal_push.tiene(_ficha(c), "titular@ejemplo.com") == 1
    assert "Activar avisos" in _html(cliente, "/portal/cuenta")
    f = _factura_del_portal(c)
    facturas_portal.devolver(t, u, f, "Falta el NIF")
    assert push_activo and push_activo[0][0] == "https://push.ejemplo.com/abc" and "Ferretería" in push_activo[0][1]["cuerpo"] and push_activo[0][1]["url"].startswith("/portal/facturas")
    assert cliente.post("/portal/push/baja", json={"endpoint": SUSCRIPCION["endpoint"]}).get_json() == {"ok": True}
    assert portal_push.tiene(_ficha(c), "titular@ejemplo.com") == 0


@pytest.mark.parametrize("cuerpo", [{}, {"endpoint": "http://inseguro/x", "keys": {"p256dh": "a", "auth": "b"}}, {"endpoint": "https://x.es/a", "keys": {}}])
def test_suscripciones_invalidas_se_rechazan(cliente, push_activo, cuerpo):
    t, u, c = _despacho("Gestoria push2")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert cliente.post("/portal/push/suscribir", json=cuerpo).status_code == 400


def test_solo_reciben_el_aviso_las_personas_que_pueden_actuar_y_se_borran_las_suscripciones_al_quitar_el_acceso(push_activo):
    t, u, c = _despacho("Gestoria push3")
    ficha = _ficha(c)
    cid = portal_personas.anadir(ficha, "consulta@ejemplo.com", "", "consulta")
    portal_push.suscribir(ficha, "titular@ejemplo.com", {**SUSCRIPCION, "endpoint": "https://push.ejemplo.com/titular"})
    portal_push.suscribir(ficha, "consulta@ejemplo.com", {**SUSCRIPCION, "endpoint": "https://push.ejemplo.com/consulta"})
    assert portal_push.enviar(ficha, "Firma", "Tienes un documento", "/portal/", accion="decidir") == 1
    assert [e for e, _c in push_activo] == ["https://push.ejemplo.com/titular"]
    push_activo.clear()
    assert portal_push.enviar(ficha, "Hola", "x", "/portal/") == 2
    portal_personas.quitar(ficha, cid)
    assert portal_push.tiene(ficha, "consulta@ejemplo.com") == 0


def test_hay_un_maximo_de_dispositivos_por_persona(push_activo):
    t, u, c = _despacho("Gestoria push4")
    ficha = _ficha(c)
    for i in range(portal_push.MAX_SUSCRIPCIONES_POR_PERSONA):
        portal_push.suscribir(ficha, None, {**SUSCRIPCION, "endpoint": f"https://push.ejemplo.com/{i}"})
    with pytest.raises(ValueError, match="varios dispositivos"):
        portal_push.suscribir(ficha, None, {**SUSCRIPCION, "endpoint": "https://push.ejemplo.com/otro"})


def test_sin_claves_vapid_no_se_ofrece_ni_se_envia(cliente, monkeypatch):
    monkeypatch.setattr(push, "VAPID_PUBLICA", "")
    monkeypatch.setattr(push, "VAPID_PRIVADA", "")
    t, u, c = _despacho("Gestoria push5")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Activar avisos" not in _html(cliente, "/portal/cuenta") and cliente.get("/portal/push/clave").get_json() == {"clave": ""}
    assert portal_push.enviar(_ficha(c), "x", "y", "/portal/") == 0

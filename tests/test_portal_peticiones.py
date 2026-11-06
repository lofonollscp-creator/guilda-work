"""Peticiones de documentos de la gestoría a sus clientes (L2): crear, subir desde el portal, revisar, reabrir y recordatorios."""
import io
from datetime import date, datetime, timedelta

import pytest

from app import db, notificaciones_email, portal_avisos, portal_inicio, portal_peticiones as pp
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures
from tests.test_facturas_contables import PDF


def _subir(http, pid, nombre="extracto.pdf", datos=PDF, tipo="application/pdf"):
    return http.post(f"/portal/peticiones/{pid}", data={"archivos": (io.BytesIO(datos), nombre, tipo)}, content_type="multipart/form-data")


def test_crear_valida_titulo_fecha_y_tope():
    t, u, c = _despacho("Pet crear")
    ficha = _ficha(c)
    with pytest.raises(ValueError, match="mínimo 3"):
        pp.crear(ficha, "ab")
    with pytest.raises(ValueError, match="fecha límite"):
        pp.crear(ficha, "Extracto", fecha_limite="mañana")
    ids = [pp.crear(ficha, f"Doc {i}") for i in range(pp.MAX_ABIERTAS)]
    with pytest.raises(ValueError, match="demasiadas"):
        pp.crear(ficha, "Una más")
    pp.cancelar(ficha, ids[0], u)
    pp.crear(ficha, "Ahora sí")


def test_el_listado_pone_primero_lo_pendiente_por_fecha_limite():
    t, u, c = _despacho("Pet orden")
    ficha = _ficha(c)
    lejos = pp.crear(ficha, "Lejos", fecha_limite=(date.today() + timedelta(days=30)).isoformat())
    cerca = pp.crear(ficha, "Cerca", fecha_limite=(date.today() + timedelta(days=2)).isoformat())
    hecha = pp.crear(ficha, "Hecha")
    pp.revisar(ficha, hecha, u)
    vencida = pp.crear(ficha, "Vencida", fecha_limite=(date.today() - timedelta(days=3)).isoformat())
    lista = pp.listar(ficha)
    assert [p["titulo"] for p in lista] == ["Vencida", "Cerca", "Lejos", "Hecha"]
    assert lista[0]["vencida"] and lista[0]["dias"] == -3 and not lista[1]["vencida"]


def test_el_cliente_sube_y_la_peticion_pasa_a_enviada(cliente, correo):
    t, u, c = _despacho("Pet subir")
    pid = pp.crear(_ficha(c), "Extracto del 3T", "El de la cuenta principal", date.today().isoformat(), por=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Extracto del 3T" in _html(cliente, "/portal/peticiones") and "Extracto del 3T" in _html(cliente, f"/portal/peticiones/{pid}")
    r = _subir(cliente, pid)
    assert r.status_code == 302 and "enviado=1" in r.headers["Location"]
    p = pp.obtener(_ficha(c), pid)
    assert p["estado"] == "enviada" and p["enviada_en"] and p["archivos"] == 1
    pagina = _html(cliente, f"/portal/peticiones/{pid}?enviado=1")
    assert "Recibido" in pagina and "extracto.pdf" in pagina
    doc = db.get_connection().execute("SELECT categoria, nombre_archivo FROM cliente_documentos WHERE cliente_fiscal_id = ?", (c,)).fetchone()
    assert doc["categoria"] == "Petición: Extracto del 3T"


def test_se_avisa_al_equipo_cuando_el_cliente_envia(cliente, correo):
    t, u, c = _despacho("Pet aviso")
    pid = pp.crear(_ficha(c), "Escritura", por=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    _subir(cliente, pid)
    notis = db.get_connection().execute("SELECT titulo, cuerpo FROM notificaciones WHERE usuario_id = ?", (u,)).fetchall()
    assert any("Cliente P SL" in n["titulo"] and "Escritura" in n["cuerpo"] for n in notis)


def test_archivos_no_validos_o_en_blanco_se_rechazan_con_mensaje(cliente, correo):
    t, u, c = _despacho("Pet invalidos")
    pid = pp.crear(_ficha(c), "Algo", por=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Solo PDF" in _subir(cliente, pid, "virus.exe", b"MZ" + b"0" * 50, "application/x-msdownload").get_data(as_text=True)
    assert "al menos un archivo" in cliente.post(f"/portal/peticiones/{pid}", data={}, content_type="multipart/form-data").get_data(as_text=True)
    assert pp.obtener(_ficha(c), pid)["estado"] == "pendiente"


def test_una_peticion_cerrada_o_ajena_no_admite_subidas(cliente, correo):
    t, u, c = _despacho("Pet cerrada")
    _t2, _u2, c2 = _despacho("Pet otra", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    cerrada = pp.crear(_ficha(c), "Cerrada", por=u)
    pp.revisar(_ficha(c), cerrada, u)
    ajena = pp.crear(_ficha(c2), "De otro", por=_u2)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "ya no está abierta" in _subir(cliente, cerrada).get_data(as_text=True)
    assert cliente.get(f"/portal/peticiones/{ajena}").status_code == 404 and _subir(cliente, ajena).status_code == 404


def test_el_perfil_de_consulta_ve_pero_no_sube(cliente, correo):
    from app import portal_personas
    t, u, c = _despacho("Pet consulta")
    pid = pp.crear(_ficha(c), "Mirar", por=u)
    portal_personas.anadir(_ficha(c), "mira@ejemplo.com", "Mira", "consulta", por=u)
    _entrar(cliente, c, "mira@ejemplo.com")
    assert "Mirar" in _html(cliente, f"/portal/peticiones/{pid}") and 'type="file"' not in _html(cliente, f"/portal/peticiones/{pid}")
    assert _subir(cliente, pid).status_code == 403


def test_revisar_reabrir_y_cancelar_siguen_la_maquina_de_estados():
    t, u, c = _despacho("Pet estados")
    ficha = _ficha(c)
    pid = pp.crear(ficha, "Doc")
    with pytest.raises(ValueError, match="mínimo 5"):
        pp.reabrir(ficha, pid, u, "no")
    assert pp.reabrir(ficha, pid, u, "Falta la página 2") is False, "pendiente no se puede reabrir"
    assert pp.revisar(ficha, pid, u, "Todo bien") and pp.obtener(ficha, pid)["estado"] == "revisada"
    assert pp.cancelar(ficha, pid, u) is False and pp.revisar(ficha, pid, u) is False
    assert pp.reabrir(ficha, pid, u, "Falta la página 2") and (p := pp.obtener(ficha, pid))["estado"] == "pendiente" and p["nota"] == "Falta la página 2"
    assert pp.cancelar(ficha, pid, u) and pp.obtener(ficha, pid)["estado"] == "cancelada"


def test_aparece_en_lo_que_tienes_que_hacer_y_desaparece_al_enviar(cliente, correo):
    t, u, c = _despacho("Pet inicio")
    pid = pp.crear(_ficha(c), "Certificado de retenciones", fecha_limite=(date.today() + timedelta(days=3)).isoformat(), por=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    inicio = _html(cliente, "/portal/")
    assert "Certificado de retenciones" in inicio and f"/portal/peticiones/{pid}" in inicio
    _subir(cliente, pid)
    assert "Certificado de retenciones" not in _html(cliente, "/portal/")


def test_recordatorios_escalonados_mientras_espera_y_no_cuando_ya_envio(correo):
    t, u, c = _despacho("Pet recordatorio")
    ficha = _ficha(c)
    pid = pp.crear(ficha, "Extracto bancario", por=u)
    conn = db.get_connection(); conn.execute("UPDATE portal_peticiones SET creado_en = ? WHERE id = ?", ((datetime.now() - timedelta(days=8)).isoformat(timespec="seconds"), pid)); conn.commit(); conn.close()
    n = portal_avisos.recordar_esperas(ficha, date.today(), datetime.now())
    assert n == 1 and "Extracto bancario" in correo[-1][1] and f"/portal/peticiones/{pid}" in correo[-1][2].replace("%2F", "/")
    assert portal_avisos.recordar_esperas(ficha, date.today(), datetime.now()) == 0, "el mismo paso no se repite"
    pp.revisar(ficha, pid, u)
    assert portal_avisos.recordar_esperas(ficha, date.today(), datetime.now()) == 0


def test_el_equipo_pide_revisa_y_reabre_desde_la_ficha(cliente, correo):
    t, u, c = _despacho("Pet equipo")
    uid = iniciar_sesion_de_prueba(cliente, "eq-pet@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    r = cliente.post(f"/fiscal/clientes/{c}/peticiones", data={"titulo": "Libro de facturas", "descripcion": "2025", "fecha_limite": "2026-12-31", "avisar": "1"})
    assert r.status_code == 302
    pid = pp.listar(_ficha(c))[0]["id"]
    assert any("Libro de facturas" in m[2] for m in correo), "se avisó al cliente"
    assert "Libro de facturas" in _html(cliente, f"/fiscal/clientes/{c}/editar")
    assert "demasiado corto" not in cliente.post(f"/fiscal/clientes/{c}/peticiones", data={"titulo": "x"}).get_data(as_text=True)
    from app.main import app as flask_app
    web = flask_app.test_client()
    _entrar(web, c, "titular@ejemplo.com")
    _subir(web, pid)
    assert cliente.post(f"/fiscal/clientes/{c}/peticiones/{pid}/reabrir", data={"nota": "Falta el de diciembre"}).status_code == 302
    p = pp.obtener(_ficha(c), pid)
    assert p["estado"] == "pendiente" and p["nota"] == "Falta el de diciembre"
    assert cliente.post(f"/fiscal/clientes/{c}/peticiones/{pid}/inventada").status_code == 404
    _subir(web, pid, "diciembre.pdf", PDF + b"dic")
    assert cliente.post(f"/fiscal/clientes/{c}/peticiones/{pid}/revisar").status_code == 302 and pp.obtener(_ficha(c), pid)["estado"] == "revisada"


def test_el_equipo_de_otro_despacho_no_puede_tocar_las_peticiones(cliente):
    t, u, c = _despacho("Pet aislamiento")
    t2, u2, c2 = _despacho("Pet otro equipo", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    uid = iniciar_sesion_de_prueba(cliente, "eq-otro@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t2); db.asignar_supervisor_tenant(uid, True)
    assert cliente.post(f"/fiscal/clientes/{c}/peticiones", data={"titulo": "Intruso"}).status_code == 404
    assert pp.listar(_ficha(c)) == []

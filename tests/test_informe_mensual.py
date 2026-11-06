"""Informe mensual a la dirección de cada despacho (K8)."""
from datetime import date, datetime

import pytest

from app import auditoria, db, facturas_contables as fc, informe_mensual as im, notificaciones_email, verticales
from app.db_fiscal import crear_cliente_fiscal
from backoffice import cartera
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _despacho(nombre="Gestoria informe"):
    t = db.crear_tenant(nombre)
    direccion = db.crear_usuario_vinculado_a_kratos(f"dir-{nombre}@ejemplo.com".replace(" ", "").lower(), "k-" + nombre.replace(" ", ""))
    db.asignar_tenant(direccion, t)
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (direccion,)); conn.commit(); conn.close()
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Uno SL", nif="B12345678", email="uno@ejemplo.com")
    return t, direccion, c


def _en_mes(tabla, columna, mes, **donde):
    conn = db.get_connection()
    conn.execute(f"UPDATE {tabla} SET {columna} = ?", (f"{mes}-10T10:00:00",))
    conn.commit(); conn.close()


def test_mes_anterior_y_limites():
    assert im.mes_anterior(date(2026, 11, 3)) == "2026-10" and im.mes_anterior(date(2027, 1, 2)) == "2026-12"
    assert im._limites("2026-12") == ("2026-12-01", "2027-01-01")


def test_cuenta_facturas_vencimientos_y_uso_del_portal():
    t, u, c = _despacho()
    fc.subir_desde_portal(c, "recibida", [("a.pdf", "application/pdf", PDF), ("b.pdf", "application/pdf", PDF + b"2")])
    mes = datetime.now().strftime("%Y-%m")                                 # la auditoría es de solo anexado: los eventos de hoy caen en el mes en curso
    auditoria.registrar(t, None, "portal.entrada", "cliente_fiscal", c, {"quien": "uno@ejemplo.com"})
    auditoria.registrar(t, None, "portal.entrada", "cliente_fiscal", c, {"quien": "otra@ejemplo.com"})
    d = im.datos(t, mes, hoy=date.today())
    assert d["facturas"] == {"recibidas": 2, "por_portal": 2, "pendientes": 2, "revisadas": 0}
    assert d["portal"] == {"entradas": 2, "personas": 2}
    assert d["clientes_sin_entrar"]["total"] == 0, "entró hace menos de 60 días"
    assert im.hay_algo_que_contar(d)


def test_clientes_sin_entrar_en_dos_meses():
    t, u, c = _despacho("Gestoria sin entrar")
    crear_cliente_fiscal(t, "Cliente Dos SL", nif="B87654321", email="dos@ejemplo.com")
    d = im.datos(t, "2026-10", hoy=date(2026, 11, 3))
    assert d["clientes_sin_entrar"]["total"] == 2 and d["clientes_sin_entrar"]["nombres"] == ["Cliente Dos SL", "Cliente Uno SL"]


def test_un_despacho_sin_actividad_no_recibe_nada():
    t, u, c = _despacho("Gestoria quieta")
    assert not im.hay_algo_que_contar(im.datos(t, "2026-10", hoy=date(2026, 11, 3)))
    assert cartera.enviar_informe_mensual(t, "2026-10", enviar=lambda *a, **k: pytest.fail("no debía enviarse")) == 0


def test_se_envia_a_la_direccion_con_los_datos():
    t, u, c = _despacho("Gestoria envio")
    fc.subir_desde_portal(c, "recibida", [("a.pdf", "application/pdf", PDF)])
    _en_mes("facturas_contables", "creado_en", "2026-10")
    enviados = []
    n = cartera.enviar_informe_mensual(t, "2026-10", enviar=lambda destino, nombre, etiqueta, d, url, tenant_id=None: enviados.append((destino, nombre, etiqueta, d["facturas"]["recibidas"])))
    assert n == 1 and enviados == [("dir-gestoriaenvio@ejemplo.com", "Gestoria envio", "octubre de 2026", 1)]


def test_el_correo_dice_lo_que_ha_pasado(monkeypatch):
    sal = []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda dest, asunto, cuerpo, html=None: sal.append((dest, asunto, cuerpo)))
    d = {"mes": "2026-10", "facturas": {"recibidas": 12, "por_portal": 9, "pendientes": 3, "revisadas": 9}, "vencimientos": {"presentados": 4, "vencidos": 1, "fuera_plazo": 0},
         "portal": {"entradas": 30, "personas": 6}, "clientes_sin_entrar": {"total": 2, "nombres": ["A SL", "B SL"]}}
    notificaciones_email.enviar_informe_mensual("dir@ejemplo.com", "Gestoria X", "octubre de 2026", d, "https://app.ejemplo.com", tenant_id=None)
    dest, asunto, cuerpo = sal[0]
    assert "octubre de 2026" in asunto and "han entrado 12 (9 por el portal)" in cuerpo and "4 presentados" in cuerpo and "A SL, B SL" in cuerpo and "30 entradas de 6" in cuerpo


def test_el_envio_automatico_esta_apagado_salvo_que_se_active_y_no_repite(monkeypatch):
    t, u, c = _despacho("Gestoria auto")
    fc.subir_desde_portal(c, "recibida", [("a.pdf", "application/pdf", PDF)])
    _en_mes("facturas_contables", "creado_en", "2026-10")
    llamadas = []
    monkeypatch.setattr(notificaciones_email, "enviar_informe_mensual", lambda *a, **k: llamadas.append(a[0]))
    ahora = datetime(2026, 11, 2, 9, 0)
    monkeypatch.delenv("GUILDA_INFORME_MENSUAL", raising=False)
    assert cartera.informes_mensuales_si_toca(ahora) == 0 and llamadas == []
    monkeypatch.setenv("GUILDA_INFORME_MENSUAL", "1")
    assert cartera.informes_mensuales_si_toca(datetime(2026, 11, 20, 9, 0)) == 0, "fuera de los primeros días del mes"
    assert cartera.informes_mensuales_si_toca(datetime(2026, 11, 2, 7, 0)) == 0, "antes de las 8:00"
    primero = cartera.informes_mensuales_si_toca(ahora)
    assert primero >= 1 and "dir-gestoriaauto@ejemplo.com" in llamadas
    assert cartera.informes_mensuales_si_toca(ahora) == 0, "una sola vez por despacho y mes"


def test_envio_manual_desde_la_ficha(bo, monkeypatch):
    t, u, c = _despacho("Gestoria manual")
    fc.subir_desde_portal(c, "recibida", [("a.pdf", "application/pdf", PDF)])
    hoy = date.today()
    mes = im.mes_anterior(hoy)
    _en_mes("facturas_contables", "creado_en", mes)
    llamadas = []
    monkeypatch.setattr(notificaciones_email, "enviar_informe_mensual", lambda *a, **k: llamadas.append(a[0]))
    entrar(bo)
    assert post(bo, f"/tenants/{t}/informe-mensual", mes="").status_code == 302 and llamadas == ["dir-gestoriamanual@ejemplo.com"]
    post(bo, f"/tenants/{t}/informe-mensual", mes="octubre")
    assert len(llamadas) == 1, "un mes mal escrito no envía nada"

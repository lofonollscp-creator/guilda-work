"""Núcleo común (app/nucleo.py): clientes con contactos y etiquetas, expedientes con permisos, plazos, festivos y horas. Todo acotado por despacho."""
from datetime import date, timedelta

import pytest

from app import calendario_plazos as cp
from app import db, nucleo, verticales


def _despacho(nombre="Despacho A", n=2):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    return t, us


# --- clientes y fichas fiscales -----------------------------------------------------------------------------------------------------------
def test_cada_cliente_fiscal_tiene_su_ficha_en_el_nucleo_y_se_mantienen_iguales(usuario_id):
    t, _ = _despacho()
    fid = db.crear_cliente_fiscal(t, "Hijos de Vidal S.L.", nif="B12345678", email="v@ejemplo.com")
    f = db.obtener_cliente_fiscal(t, fid)
    assert f["cliente_id"]
    c = nucleo.obtener_cliente(t, f["cliente_id"])
    assert (c["nombre"], c["nif"], c["email"], c["tipo"], c["cliente_fiscal_id"]) == ("Hijos de Vidal S.L.", "B12345678", "v@ejemplo.com", "empresa", fid)
    db.editar_cliente_fiscal(t, fid, nombre="Vidal e Hijos S.L.", email="nuevo@ejemplo.com")
    assert nucleo.obtener_cliente(t, f["cliente_id"])["nombre"] == "Vidal e Hijos S.L." and nucleo.obtener_cliente(t, f["cliente_id"])["email"] == "nuevo@ejemplo.com"
    nucleo.editar_cliente(t, f["cliente_id"], nombre="Vidal & Hijos", nif="B87654321")
    f2 = db.obtener_cliente_fiscal(t, fid)
    assert (f2["nombre"], f2["nif"]) == ("Vidal & Hijos", "B87654321"), "lo común viaja también a la ficha fiscal"
    db.eliminar_cliente_fiscal(t, fid)
    assert nucleo.obtener_cliente(t, f["cliente_id"])["papelera_en"]
    db.restaurar_cliente_fiscal(t, fid)
    assert nucleo.obtener_cliente(t, f["cliente_id"])["papelera_en"] is None


def test_la_migracion_rellena_los_clientes_fiscales_que_ya_existian(usuario_id):
    t, _ = _despacho()
    conn = db.get_connection()
    conn.execute("INSERT INTO clientes_fiscales (tenant_id, nombre, nif, creado_en) VALUES (?, 'Antiguo', '12345678Z', '2025-01-01T00:00:00')", (t,))
    conn.commit(); conn.close()
    db.init_db()
    conn = db.get_connection()
    f = conn.execute("SELECT cliente_id FROM clientes_fiscales WHERE nombre = 'Antiguo'").fetchone()
    conn.close()
    assert f["cliente_id"] and nucleo.obtener_cliente(t, f["cliente_id"])["tipo"] == "persona"
    db.init_db()            # idempotente
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM clientes WHERE nombre = 'Antiguo'").fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize("nif,tipo", [("B12345678", "empresa"), ("a-1234567-4", "empresa"), ("12345678Z", "persona"), ("X1234567L", "persona"), ("", "persona"), (None, "persona")])
def test_inferir_tipo(nif, tipo):
    assert nucleo.inferir_tipo(nif) == tipo


def test_crear_cliente_con_contactos_y_etiquetas_y_buscar(usuario_id):
    t, (u1, _u2) = _despacho()
    cid = nucleo.crear_cliente(t, "María López", nif="12345678Z", email="m@ejemplo.com", telefono="600 111 222", idioma="ca", responsable_id=u1, etiquetas=["VIP", " renta ", "vip"])
    assert nucleo.etiquetas_de(cid) == ["renta", "vip"]
    k = nucleo.anadir_contacto(t, cid, "Pedro López", cargo="Hijo", email="pedro@ejemplo.com", principal=True)
    nucleo.anadir_contacto(t, cid, "Asesor externo", rol="asesor", principal=True)
    assert [c["nombre"] for c in nucleo.listar_contactos(t, cid)] == ["Asesor externo", "Pedro López"], "solo un contacto principal (el último), primero"
    assert [c["nombre"] for c in nucleo.listar_clientes(t, "pedro@")[0]] == ["María López"], "se encuentra por el email de un contacto"
    assert nucleo.listar_clientes(t, "maria")[1] == 1 and nucleo.listar_clientes(t, "MARÍA LOPEZ")[1] == 1 and nucleo.listar_clientes(t, "lopez")[1] == 1, "sin distinguir acentos ni mayúsculas"
    assert nucleo.listar_clientes(t, "lópez")[1] == 1 and nucleo.listar_clientes(t, etiqueta="vip")[1] == 1 and nucleo.listar_clientes(t, etiqueta="otra")[1] == 0
    assert nucleo.listar_clientes(t, tipo="empresa")[1] == 0
    assert nucleo.eliminar_contacto(t, k) and not nucleo.eliminar_contacto(t, k)
    assert nucleo.etiquetas_del_despacho(t) == [{"etiqueta": "renta", "n": 1}, {"etiqueta": "vip", "n": 1}]


@pytest.mark.parametrize("kw,msg", [({"nombre": " "}, "nombre"), ({"nombre": "x", "tipo": "otro"}, "tipo"), ({"nombre": "x", "idioma": "de"}, "Idioma"), ({"nombre": "x" * 201}, "largo")])
def test_crear_cliente_valida(usuario_id, kw, msg):
    t, _ = _despacho()
    with pytest.raises(ValueError, match=msg):
        nucleo.crear_cliente(t, **kw)


def test_duplicados_y_fusion(usuario_id):
    t, (u1, _) = _despacho()
    a = nucleo.crear_cliente(t, "Ana Ruiz", nif="12345678Z", email="ana@ejemplo.com", etiquetas=["a"])
    b = nucleo.crear_cliente(t, "Ana  Ruiz ", nif="12.345.678-Z".replace(".", ""), etiquetas=["b"])
    assert {c["id"] for c in nucleo.posibles_duplicados(t, nif="12345678-z")} == {a, b}
    assert {c["id"] for c in nucleo.posibles_duplicados(t, email="ANA@ejemplo.com")} == {a}
    assert nucleo.posibles_duplicados(t, nif="12345678Z", excluir_id=a)[0]["id"] == b and nucleo.posibles_duplicados(t) == []
    e = nucleo.crear_expediente(t, u1, b, "Renta 2025")
    nucleo.anadir_contacto(t, b, "Contacto B")
    nucleo.registrar_parte(t, u1, "Llamada", minutos=15, cliente_id=b)
    nucleo.fusionar_clientes(t, a, b)
    assert nucleo.obtener_expediente(t, e, u1)["cliente_id"] == a
    assert [c["nombre"] for c in nucleo.listar_contactos(t, a)] == ["Contacto B"] and nucleo.etiquetas_de(a) == ["a", "b"]
    assert nucleo.listar_partes(t, u1)[0]["cliente_id"] == a
    assert nucleo.obtener_cliente(t, b)["papelera_en"] and "Fusionado" in nucleo.obtener_cliente(t, b)["notas"]
    with pytest.raises(ValueError):
        nucleo.fusionar_clientes(t, a, a)


def test_buscar_expedientes_sin_acentos(usuario_id):
    t, (u1, _) = _despacho()
    c = nucleo.crear_cliente(t, "Sociedad Pérez")
    nucleo.crear_expediente(t, u1, c, "Reclamación de cantidad", referencia="Nº 12/2026")
    assert nucleo.listar_expedientes(t, u1, q="reclamacion")[1] == 1 and nucleo.listar_expedientes(t, u1, q="perez")[1] == 1 and nucleo.listar_expedientes(t, u1, q="12/2026")[1] == 1
    assert nucleo.listar_expedientes(t, u1, q="zzz")[1] == 0


def test_un_despacho_no_ve_ni_toca_lo_del_otro(usuario_id):
    t1, (u1, _) = _despacho("Despacho Uno")
    t2, (u2, _) = _despacho("Despacho Dos")
    c1 = nucleo.crear_cliente(t1, "Cliente de uno")
    x1 = nucleo.crear_expediente(t1, u1, c1, "Asunto uno")
    assert nucleo.obtener_cliente(t2, c1) is None and nucleo.obtener_expediente(t2, x1, u2) is None
    assert nucleo.listar_clientes(t2)[1] == 0 and nucleo.listar_expedientes(t2, u2)[1] == 0
    for accion in (lambda: nucleo.editar_cliente(t2, c1, nombre="Robado"), lambda: nucleo.crear_expediente(t2, u2, c1, "Intruso"),
                   lambda: nucleo.anadir_contacto(t2, c1, "X"), lambda: nucleo.crear_plazo(t2, u2, "P", "2026-12-01", cliente_id=c1),
                   lambda: nucleo.registrar_parte(t2, u2, "t", minutos=5, cliente_id=c1), lambda: nucleo.crear_cliente(t2, "ok", responsable_id=u1)):
        with pytest.raises(ValueError):
            accion()
    assert nucleo.obtener_cliente(t1, c1)["nombre"] == "Cliente de uno"


# --- expedientes ---------------------------------------------------------------------------------------------------------------------------------------
def test_ciclo_de_vida_de_un_expediente_con_linea_de_tiempo(usuario_id):
    t, (u1, u2) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u1, c, "Constitución de sociedad", referencia="EXP-1", descripcion="Alta")
    e = nucleo.obtener_expediente(t, x, u1)
    assert (e["estado"], e["responsable_id"], e["tipo"], e["cliente_nombre"]) == ("abierto", u1, "general", "Cliente")
    nucleo.cambiar_estado_expediente(t, u1, x, "en_curso")
    nucleo.asignar_expediente(t, u1, x, u2)
    nucleo.anotar_expediente(t, u1, x, "Llamado el cliente")
    nucleo.cambiar_estado_expediente(t, u2, x, "cerrado")
    e = nucleo.obtener_expediente(t, x, u1)
    assert e["estado"] == "cerrado" and e["cerrado_en"] and e["responsable_id"] == u2
    nucleo.cambiar_estado_expediente(t, u2, x, "abierto")
    assert nucleo.obtener_expediente(t, x, u1)["cerrado_en"] is None, "reabrir borra la fecha de cierre"
    tipos = [ev["tipo"] for ev in nucleo.linea_de_tiempo(t, u1, x)]
    assert tipos.count("estado") == 3 and "nota" in tipos and "responsable" in tipos and tipos[-1] == "creado"
    with pytest.raises(ValueError):
        nucleo.cambiar_estado_expediente(t, u1, x, "inventado")
    with pytest.raises(ValueError):
        nucleo.crear_expediente(t, u1, c, "x", tipo="causa_judicial")
    nucleo.editar_expediente(t, u1, x, titulo="Constitución S.L.", referencia=" ")
    e = nucleo.obtener_expediente(t, x, u1)
    assert e["titulo"] == "Constitución S.L." and e["referencia"] is None
    nucleo.papelera_expediente(t, u1, x)
    assert nucleo.listar_expedientes(t, u1)[1] == 0 and nucleo.listar_expedientes(t, u1, papelera=True)[1] == 1


def test_un_expediente_confidencial_solo_lo_ven_los_suyos(usuario_id):
    t, (u1, u2, u3) = _despacho("Despacho Conf", 3)
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u1, c, "Asunto reservado", confidencial=True)
    nucleo.crear_plazo(t, u1, "Contestar", "2026-12-01", expediente_id=x)
    nucleo.registrar_parte(t, u1, "Estudio", minutos=60, expediente_id=x)
    assert nucleo.obtener_expediente(t, x, u1) is not None and nucleo.obtener_expediente(t, x, u2) is None
    assert nucleo.listar_expedientes(t, u2)[1] == 0 and nucleo.listar_expedientes(t, u1)[1] == 1
    assert nucleo.listar_plazos(t, u2) == [] and len(nucleo.listar_plazos(t, u1)) == 1
    assert nucleo.listar_partes(t, u2, ver_todo=True) == [] and len(nucleo.listar_partes(t, u1)) == 1
    assert nucleo.listar_expedientes(t, u2, supervisor=True)[1] == 1, "un responsable del despacho sí"
    for accion in (lambda: nucleo.crear_plazo(t, u2, "Colado", "2026-12-01", expediente_id=x), lambda: nucleo.registrar_parte(t, u2, "t", minutos=5, expediente_id=x),
                   lambda: nucleo.anotar_expediente(t, u2, x, "hola"), lambda: nucleo.anadir_miembro(t, u2, x, u3)):
        with pytest.raises(ValueError):
            accion()
    nucleo.anadir_miembro(t, u1, x, u2)
    assert nucleo.obtener_expediente(t, x, u2) is not None and [m["id"] for m in nucleo.miembros_de(x)] == [u2]
    assert nucleo.obtener_expediente(t, x, u3) is None
    nucleo.quitar_miembro(t, u1, x, u2)
    assert nucleo.obtener_expediente(t, x, u2) is None


# --- plazos ---------------------------------------------------------------------------------------------------------------------------------------------
def test_plazos_con_estado_calculado_y_doble_revision(usuario_id):
    t, (u1, u2) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u1, c, "Asunto")
    hoy = date(2026, 10, 13)
    p_venc = nucleo.crear_plazo(t, u1, "Vencido", "2026-10-09", expediente_id=x)
    p_hoy = nucleo.crear_plazo(t, u1, "Hoy", "2026-10-13", cliente_id=c, critico=True)
    p_prox = nucleo.crear_plazo(t, u1, "Próximo", "2026-10-15", expediente_id=x, avisos="3,1")
    p_lejos = nucleo.crear_plazo(t, u1, "Lejano", "2026-12-18", expediente_id=x)
    p_ok = nucleo.crear_plazo(t, u1, "Hecho", "2026-10-01", expediente_id=x)
    nucleo.marcar_cumplido(t, u1, p_ok)
    por_titulo = {p["titulo"]: p for p in nucleo.listar_plazos(t, u1, hoy=hoy)}
    assert {k: v["estado_calculado"] for k, v in por_titulo.items()} == {"Vencido": "vencido", "Hoy": "hoy", "Próximo": "proximo", "Lejano": "en_plazo", "Hecho": "cumplido"}
    assert por_titulo["Próximo"]["cliente_nombre"] == "Cliente" and por_titulo["Próximo"]["dias_restantes"] == 2 and por_titulo["Próximo"]["avisos_fechas"] == ["2026-10-09", "2026-10-14"]
    orden = [p["titulo"] for p in nucleo.listar_plazos(t, u1, hoy=hoy)]
    assert orden == ["Vencido", "Hoy", "Próximo", "Lejano", "Hecho"], "primero los abiertos por fecha y al final los cumplidos"
    assert [p["titulo"] for p in nucleo.listar_plazos(t, u1, hoy=hoy, estado="abiertos")] == ["Vencido", "Hoy", "Próximo", "Lejano"]
    assert [p["titulo"] for p in nucleo.listar_plazos(t, u1, hoy=hoy, estado="vencido")] == ["Vencido"]
    assert [p["titulo"] for p in nucleo.listar_plazos(t, u1, hoy=hoy, hasta="2026-10-15", estado="abiertos")] == ["Vencido", "Hoy", "Próximo"]
    with pytest.raises(ValueError, match="otra persona"):
        nucleo.revisar_plazo(t, u1, p_prox)
    nucleo.revisar_plazo(t, u2, p_prox)
    assert {p["id"]: p["revisado"] for p in nucleo.listar_plazos(t, u1, hoy=hoy)}[p_prox] is True
    nucleo.mover_plazo(t, u1, p_prox, "2026-10-20")
    assert {p["id"]: p["revisado"] for p in nucleo.listar_plazos(t, u1, hoy=hoy)}[p_prox] is False, "cambiar la fecha vuelve a pedir revisión"
    nucleo.marcar_cumplido(t, u1, p_ok, False)
    nucleo.eliminar_plazo(t, u1, p_lejos)
    assert p_lejos not in {p["id"] for p in nucleo.listar_plazos(t, u1)}
    for fecha in ("ayer", "2026-13-01", ""):
        with pytest.raises(ValueError):
            nucleo.crear_plazo(t, u1, "x", fecha)
    with pytest.raises(ValueError):
        nucleo.crear_plazo(t, u1, "x", "2026-10-01", avisos="siete")
    assert x and p_venc and p_hoy


def test_los_plazos_procesales_saltan_agosto_y_los_festivos_del_despacho_cuentan(usuario_id):
    t, (u1, _) = _despacho()
    nucleo.anadir_festivo(t, "2026-10-14", "Fiesta local")
    nucleo.anadir_festivo(t, "2026-10-14", "Fiesta local (corregida)")
    assert [f["nombre"] for f in nucleo.listar_festivos(t, 2026)] == ["Fiesta local (corregida)"]
    gen, proc = nucleo.calendario_del_despacho(t, "general", (2026,)), nucleo.calendario_del_despacho(t, "procesal", (2026,))
    assert not gen.es_habil(date(2026, 10, 14)) and gen.es_habil(date(2026, 8, 12)) and not proc.es_habil(date(2026, 8, 12))
    assert cp.sumar_dias_habiles(date(2026, 10, 13), 1, gen) == date(2026, 10, 15)
    f = nucleo.listar_festivos(t)[0]
    assert nucleo.eliminar_festivo(t, f["id"]) and not nucleo.eliminar_festivo(t, f["id"])
    with pytest.raises(ValueError):
        nucleo.anadir_festivo(t, "mañana", "x")


# --- horas ------------------------------------------------------------------------------------------------------------------------------------------------
def test_importe_de_horas_con_y_sin_bloques():
    assert nucleo.importe_centimos(3600, 12000) == 12000 and nucleo.importe_centimos(1800, 12000) == 6000
    assert nucleo.importe_centimos(7 * 60, 12000, 6) == 2400 and nucleo.importe_centimos(7 * 60, 12000) == 1400, "con bloques de 6 min, 7 min cuentan 12"
    assert nucleo.importe_centimos(0, 12000) == 0 and nucleo.importe_centimos(600, None) == 0 and nucleo.importe_centimos(1, 100) == 0


def test_partes_de_tiempo_resumenes_y_facturacion(usuario_id):
    t, (u1, u2) = _despacho()
    a, b = nucleo.crear_cliente(t, "Cliente A"), nucleo.crear_cliente(t, "Cliente B")
    x = nucleo.crear_expediente(t, u1, a, "Asunto A")
    nucleo.fijar_tarifa_usuario(t, u1, 10000)
    p1 = nucleo.registrar_parte(t, u1, "Estudio del caso", minutos=90, expediente_id=x)            # hereda el cliente del expediente y la tarifa del usuario
    p2 = nucleo.registrar_parte(t, u1, "Reunión interna", minutos=30, facturable=False)
    nucleo.registrar_parte(t, u2, "Escrito", minutos=60, cliente_id=b, tarifa_hora_centimos=20000)
    mios = nucleo.listar_partes(t, u1)
    assert {p["id"] for p in mios} == {p1, p2} and {p["id"]: p["importe_centimos"] for p in mios} == {p1: 15000, p2: 0}
    assert mios[0]["cliente_nombre"] == "Cliente A" or mios[1]["cliente_nombre"] == "Cliente A"
    assert len(nucleo.listar_partes(t, u2)) == 1, "sin ver_todo solo los propios"
    por_cliente = {r["nombre"]: r for r in nucleo.resumen_horas(t, u1, ver_todo=True, agrupar="cliente")}
    assert por_cliente["Cliente A"]["importe_centimos"] == 15000 and por_cliente["Cliente B"]["importe_centimos"] == 20000 and por_cliente["Sin cliente"]["segundos"] == 1800
    assert por_cliente["Sin cliente"]["segundos_facturables"] == 0
    por_user = {r["id"]: r for r in nucleo.resumen_horas(t, u1, ver_todo=True, agrupar="usuario")}
    assert por_user[u1]["segundos"] == 7200 and por_user[u2]["segundos"] == 3600
    assert nucleo.resumen_horas(t, u1, agrupar="expediente")[0]["nombre"] in ("Asunto A", "Sin expediente")
    assert nucleo.resumen_horas(t, u1, ver_todo=True, agrupar="cliente", bloque_minutos=60)[0]["importe_centimos"] >= 15000
    assert len(nucleo.listar_partes(t, u1, ver_todo=True, pendiente_de_facturar=True)) == 2
    assert nucleo.marcar_facturado(t, [p1]) == 1 and nucleo.marcar_facturado(t, [p2]) == 0, "lo no facturable no se factura"
    assert len(nucleo.listar_partes(t, u1, ver_todo=True, pendiente_de_facturar=True)) == 1
    assert not nucleo.eliminar_parte(t, u1, p1) and not nucleo.eliminar_parte(t, u2, p2) and nucleo.eliminar_parte(t, u1, p2)
    for kw in ({"minutos": 0}, {"minutos": 25 * 60}, {"minutos": 5, "fecha": (date.today() + timedelta(days=30)).isoformat()}, {"minutos": 5, "fecha": "ayer"}):
        with pytest.raises(ValueError):
            nucleo.registrar_parte(t, u1, "x", **kw)
    with pytest.raises(ValueError):
        nucleo.registrar_parte(t, u1, " ", minutos=5)
    with pytest.raises(ValueError):
        nucleo.resumen_horas(t, u1, agrupar="color")


def test_borrar_un_despacho_borra_tambien_el_nucleo(usuario_id):
    t, (u1, _) = _despacho()
    c = nucleo.crear_cliente(t, "C", etiquetas=["x"])
    nucleo.anadir_contacto(t, c, "K")
    x = nucleo.crear_expediente(t, u1, c, "X")
    nucleo.crear_plazo(t, u1, "P", "2026-12-01", expediente_id=x)
    nucleo.registrar_parte(t, u1, "t", minutos=5, expediente_id=x)
    nucleo.anadir_festivo(t, "2026-12-01", "F")
    db.crear_cliente_fiscal(t, "Fiscal")
    verticales.fijar_activo(t, "abogados", True)
    db.borrar_tenant(t)
    conn = db.get_connection()
    for tabla in ("clientes", "expedientes", "plazos", "partes_tiempo", "festivos", "cliente_contactos", "tenants_verticales"):
        assert conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0, tabla
    conn.close()


# --- verticales ---------------------------------------------------------------------------------------------------------------------------------------
def test_verticales_por_defecto_extras_y_ajuste_manual(usuario_id):
    t, _ = _despacho()
    assert verticales.activos_de(t) == {"gestoria"} and verticales.activos_de(None) == {"gestoria"}
    extra = db.crear_extra_guilda("Gabinete de abogados", "módulo", 4900)
    conn = db.get_connection(); conn.execute("UPDATE extras_guilda SET vertical_id = 'abogados' WHERE id = ?", (extra,)); conn.commit(); conn.close()
    te = db.activar_extra_tenant(t, extra)
    verticales.invalidar(t)
    assert verticales.activos_de(t) == {"gestoria", "abogados"}
    db.desactivar_extra_tenant(te)
    verticales.invalidar(t)
    assert verticales.activos_de(t) == {"gestoria"}
    verticales.fijar_activo(t, "inmobiliaria", True, activo_hasta="2999-01-01T00:00:00")
    assert verticales.activos_de(t) == {"gestoria", "inmobiliaria"}
    verticales.fijar_activo(t, "inmobiliaria", True, activo_hasta="2000-01-01T00:00:00")
    assert verticales.activos_de(t) == {"gestoria"}, "una prueba caducada deja de valer"
    verticales.fijar_activo(t, "gestoria", False)
    assert verticales.activos_de(t) == set(), "el ajuste manual puede quitar incluso el módulo por defecto"
    verticales.quitar_ajuste_manual(t, "gestoria")
    assert verticales.activos_de(t) == {"gestoria"}
    with pytest.raises(ValueError):
        verticales.fijar_activo(t, "astrologia", True)
    estado = {e["id"]: e for e in verticales.estado_para_backoffice(t)}
    assert list(estado) == ["gestoria"] and estado["gestoria"]["motivo"] == "defecto", "los verticales aún sin pantallas no se ofrecen"


def test_los_verticales_se_guardan_en_memoria_poco_tiempo(usuario_id, monkeypatch):
    t, _ = _despacho()
    verticales.activos_de(t)
    conn = db.get_connection(); conn.execute("INSERT INTO tenants_verticales (tenant_id, vertical_id, activo, creado_en) VALUES (?, 'abogados', 1, '2026-01-01T00:00:00')", (t,)); conn.commit(); conn.close()
    assert verticales.activos_de(t) == {"gestoria"}, "dentro del TTL no se vuelve a consultar"
    monkeypatch.setattr(verticales, "TTL_SEGUNDOS", 0)
    assert verticales.activos_de(t) == {"gestoria", "abogados"}


def test_tipos_de_expediente_segun_los_verticales_activos(usuario_id):
    t, _ = _despacho()
    assert list(verticales.tipos_expediente(t)) == ["general"]
    assert verticales.tipo_de("tipo_retirado") is verticales.TIPO_GENERAL
    assert [e.id for e in verticales.TIPO_GENERAL.estados] == ["abierto", "en_curso", "en_espera", "cerrado"] and verticales.TIPO_GENERAL.inicial == "abierto"


# --- backoffice: módulos de negocio -------------------------------------------------------------------------------------------------------------
def test_el_backoffice_activa_y_desactiva_modulos_de_negocio_y_vincula_extras(tmp_path, monkeypatch):
    from backoffice import auth
    from backoffice.main import create_app
    from tests.test_backoffice_app import CLAVE, entrar, post

    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    auth.crear_admin("jorge", CLAVE, "Jorge")
    bo = create_app(testing=True).test_client()
    entrar(bo)
    t = db.crear_tenant("Despacho BO")
    html = bo.get(f"/tenants/{t}?seccion=modulos").get_data(as_text=True)
    assert "Módulos de negocio" in html and "Gestoría" in html and "Incluido por defecto" in html and "/verticales/inmobiliaria" not in html and "/verticales/abogados" not in html
    post(bo, f"/tenants/{t}/verticales/gestoria")
    assert verticales.activos_de(t, usar_cache=False) == set() and "Ajuste manual" in bo.get(f"/tenants/{t}?seccion=modulos").get_data(as_text=True)
    post(bo, f"/tenants/{t}/verticales/gestoria", accion="auto")
    assert verticales.activos_de(t, usar_cache=False) == {"gestoria"}
    assert post(bo, f"/tenants/{t}/verticales/astrologia").status_code == 400
    # un extra de pago vinculado a un módulo
    post(bo, "/extras", nombre="Pack abogados", descripcion="x", precio="49", vertical_id="abogados")
    extra = next(e for e in db.listar_extras_guilda() if e["nombre"] == "Pack abogados")
    assert extra["vertical_id"] == "abogados"
    post(bo, f"/extras/{extra['id']}/editar", nombre="Pack abogados", descripcion="x", precio="49", vertical_id="")
    assert db.obtener_extra_guilda(extra["id"])["vertical_id"] is None
    post(bo, "/extras", nombre="Malo", descripcion="", precio="1", vertical_id="astrologia")
    assert not any(e["nombre"] == "Malo" for e in db.listar_extras_guilda())

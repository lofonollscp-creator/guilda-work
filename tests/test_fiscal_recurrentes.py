"""Plantillas recurrentes de Guilda Fiscal (app/fiscal_recurrentes.py): alquileres y gastos fijos que se repiten solos."""
import json
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp, fiscal_recurrentes as fr
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba
from tests.escenarios_303 import compra, venta

NIF = "A12345674"
RETENCION = {"modelo": "115", "clave": "", "base": 100000, "pct": 1900, "importe": 19000}


def _despacho(nombre="Despacho recurrentes"):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    director = db.crear_usuario_vinculado_a_kratos(f"{clave}-d@ejemplo.com", f"k-{clave}-d"); db.asignar_tenant(director, t); db.asignar_supervisor_tenant(director, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    fp.guardar_perfil(t, director, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, director, c


def _alquiler(t, u, c, fecha=date(2026, 1, 5)):
    return fn.aprobar_apunte(t, u, c, compra(100000, numero="ALQ-1", fecha=fecha), retencion=RETENCION)


def _numeros(t, u, c):
    return sorted(f["numero"] for f in fn.listar_apuntes(t, u, c))


def test_la_plantilla_mensual_crea_lo_que_toca_una_sola_vez_y_con_la_retencion():
    t, u, c = _despacho()
    ap = _alquiler(t, u, c)
    p = fr.crear(t, u, c, ap["id"], frecuencia="mensual")
    assert p["proxima"] == "2026-02-05" and p["activa"] == 1 and p["generadas"] == 0
    r = fr.generar(tenant_id=t, hoy=date(2026, 4, 10))
    assert r == {"creados": 3, "ya_existian": 0, "errores": 0, "plantillas": 1}
    assert _numeros(t, u, c) == ["ALQ-1", "ALQ-1-202602", "ALQ-1-202603", "ALQ-1-202604"]
    nuevos = [f for f in fn.listar_apuntes(t, u, c) if f["numero"] != "ALQ-1"]
    assert {f["fecha_expedicion"] for f in nuevos} == {"2026-02-05", "2026-03-05", "2026-04-05"} and all(f["retencion_centimos"] == 19000 and f["retencion_modelo"] == "115" for f in nuevos)
    assert fr.generar(tenant_id=t, hoy=date(2026, 4, 10)) == {"creados": 0, "ya_existian": 0, "errores": 0, "plantillas": 0}      # el mismo día no duplica
    assert fr.listar(t, u, c)[0]["generadas"] == 3 and fr.listar(t, u, c)[0]["proxima"] == "2026-05-05"
    r = fr.generar(tenant_id=t, hoy=date(2026, 5, 4))                                                             # aún no ha llegado el 5 de mayo
    assert r["creados"] == 0
    assert fr.generar(tenant_id=t, hoy=date(2026, 5, 5))["creados"] == 1


def test_trimestral_hasta_pausa_y_borrado():
    t, u, c = _despacho("Despacho recurrentes 2")
    ap = _alquiler(t, u, c, fecha=date(2026, 1, 31))
    p = fr.crear(t, u, c, ap["id"], frecuencia="trimestral", hasta="2026-07-31")
    assert p["proxima"] == "2026-04-30"                                                 # febrero y abril tienen menos días: el día se ajusta
    fr.generar(tenant_id=t, hoy=date(2026, 12, 31))
    assert sorted(f["fecha_expedicion"] for f in fn.listar_apuntes(t, u, c)) == ["2026-01-31", "2026-04-30", "2026-07-31"]
    assert fr.listar(t, u, c)[0]["terminada"] is True
    ap2 = fn.aprobar_apunte(t, u, c, compra(50000, numero="GAS-1", fecha=date(2026, 1, 10)))
    p2 = fr.crear(t, u, c, ap2["id"])
    fr.pausar(t, u, c, p2["id"], False)
    assert fr.generar(tenant_id=t, hoy=date(2026, 6, 30))["plantillas"] == 0
    fr.pausar(t, u, c, p2["id"], True)
    assert fr.generar(tenant_id=t, cliente_fiscal_id=c, hoy=date(2026, 3, 15))["creados"] == 2
    fr.borrar(t, u, c, p2["id"])
    assert [x["id"] for x in fr.listar(t, u, c)] == [p["id"]] and len(fn.listar_apuntes(t, u, c)) == 3 + 3
    conn = db.get_connection()
    try:
        acciones = [r[0] for r in conn.execute("SELECT accion FROM auditoria_eventos WHERE tenant_id = ? AND accion LIKE 'fiscal.recurrente.%'", (t,)).fetchall()]
    finally:
        conn.close()
    assert acciones.count("fiscal.recurrente.crear") == 2 and acciones.count("fiscal.recurrente.generar") == 4 and "fiscal.recurrente.pausar" in acciones and "fiscal.recurrente.borrar" in acciones


def test_no_duplica_lo_que_ya_se_repitio_a_mano_y_las_emitidas_siguen_la_serie():
    t, u, c = _despacho("Despacho recurrentes 3")
    ap = _alquiler(t, u, c)
    fn.repetir_apunte(t, u, c, ap["id"], hasta="2026-03", hoy=date(2026, 3, 20))                 # febrero y marzo a mano
    fr.crear(t, u, c, ap["id"])
    r = fr.generar(tenant_id=t, hoy=date(2026, 4, 20))
    assert r["creados"] == 1 and r["ya_existian"] == 2
    emitida = fn.aprobar_apunte(t, u, c, venta(30000, numero="1", fecha=date(2026, 1, 15)))
    fr.crear(t, u, c, emitida["id"])
    fr.generar(tenant_id=t, hoy=date(2026, 3, 20))
    emitidas = sorted(f["numero"] for f in fn.listar_apuntes(t, u, c) if f["libro"] == "E")
    assert len(emitidas) == 3 and len(set(emitidas)) == 3


def test_reglas_de_la_creacion_y_permisos():
    t, u, c = _despacho("Despacho recurrentes 4")
    ap = _alquiler(t, u, c)
    fr.crear(t, u, c, ap["id"])
    with pytest.raises(fr.ErrorFiscal) as e:
        fr.crear(t, u, c, ap["id"])
    assert e.value.codigo == "ya_existe"
    rect = fn.aprobar_apunte(t, u, c, compra(-1000, numero="R-1", tipo_factura="R1", fecha=date(2026, 2, 1)))
    for malo in ({"apunte_id": rect["id"]}, {"apunte_id": ap["id"], "frecuencia": "anual"}, {"apunte_id": ap["id"], "hasta": "2026-01-05"}, {"apunte_id": ap["id"], "hasta": "mañana"}, {"apunte_id": 999999}):
        with pytest.raises(fr.ErrorFiscal):
            fr.crear(t, u, c, **malo)
    lector = db.crear_usuario_vinculado_a_kratos("lector-rec@ejemplo.com", "k-lector-rec"); db.asignar_tenant(lector, t)
    with pytest.raises(fr.ErrorFiscal):
        fr.crear(t, lector, c, ap["id"])
    with pytest.raises(fr.ErrorFiscal):
        fr.generar_de_un_titular(t, lector, c)
    otro_t, otro_u, otro_c = _despacho("Despacho recurrentes 5")
    assert fr.listar(otro_t, otro_u, c) == []                                  # otro despacho no ve nada de esta plantilla ni puede tocarla
    with pytest.raises(fr.ErrorFiscal):
        fr.pausar(otro_t, otro_u, c, fr.listar(t, u, c)[0]["id"], False)
    with pytest.raises(fr.ErrorFiscal):
        fr.pausar(t, u, c, 999999, False)


def test_si_quien_la_creo_ya_no_puede_aprobar_la_plantilla_no_avanza_y_avisa():
    t, u, c = _despacho("Despacho recurrentes 6")
    ap = _alquiler(t, u, c)
    fr.crear(t, u, c, ap["id"])
    otro = db.crear_usuario_vinculado_a_kratos("otro-rec@ejemplo.com", "k-otro-rec"); db.asignar_tenant(otro, t); db.asignar_supervisor_tenant(otro, True)
    db.asignar_supervisor_tenant(u, False)
    r = fr.generar(tenant_id=t, hoy=date(2026, 3, 20))
    assert r["errores"] == 1 and r["creados"] == 0
    p = fr.listar(t, otro, c)[0]
    assert p["generadas"] == 0 and p["ultimo_error"] and p["proxima"] == "2026-02-05"
    avisos = [n["titulo"] for n in db.listar_notificaciones(u)]
    assert any("no se ha podido generar" in x for x in avisos)
    db.asignar_supervisor_tenant(u, True)
    assert fr.generar(tenant_id=t, hoy=date(2026, 3, 20))["creados"] == 2
    assert fr.listar(t, u, c)[0]["ultimo_error"] is None
    assert any("Apuntes recurrentes generados" in n["titulo"] for n in db.listar_notificaciones(u))


def test_el_script_diario_recorre_todos_los_despachos(capsys):
    import importlib.util
    from pathlib import Path
    despachos = [_despacho("Despacho recurrentes 7"), _despacho("Despacho recurrentes 8")]
    for t, u, c in despachos:
        fr.crear(t, u, c, _alquiler(t, u, c, fecha=date(2026, 1, 5))["id"])
    ruta = Path(fr.__file__).resolve().parent.parent / "scripts" / "generar_apuntes_recurrentes.py"
    espec = importlib.util.spec_from_file_location("generar_apuntes_recurrentes", ruta)
    modulo = importlib.util.module_from_spec(espec); espec.loader.exec_module(modulo)
    modulo.main()
    assert "Apuntes recurrentes creados" in capsys.readouterr().out
    for t, u, c in despachos:
        assert len(fn.listar_apuntes(t, u, c)) > 1
    modulo.main()                                                                 # repetirlo no duplica
    assert "creados: 0" in capsys.readouterr().out
    for t, u, c in despachos:
        assert len({f["numero"] for f in fn.listar_apuntes(t, u, c)}) == len(fn.listar_apuntes(t, u, c))


def test_pantallas_de_las_plantillas(cliente):
    from app import verticales
    uid = iniciar_sesion_de_prueba(cliente, "recweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho recweb")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True); verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Alquiler Web SL", nif=NIF)
    fp.guardar_perfil(t, uid, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    ap = _alquiler(t, uid, c, fecha=date(2026, 1, 5))
    html = cliente.get(f"/guilda-fiscal/{c}/apuntes/{ap['id']}").get_data(as_text=True)
    assert 'id="recurrente-apunte"' in html and "Crear plantilla" in html
    assert "Plantillas recurrentes" in cliente.get(f"/guilda-fiscal/{c}?p_ejercicio=2026&p_periodo=1T").get_data(as_text=True)
    r = cliente.post(f"/guilda-fiscal/{c}/apuntes/{ap['id']}/recurrente", data={"frecuencia": "mensual", "hasta": ""})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/guilda-fiscal/{c}/recurrentes")
    html = cliente.get(f"/guilda-fiscal/{c}/recurrentes").get_data(as_text=True)
    assert "ALQ-1" in html and "Activa" in html and "Generar lo que toca ahora" in html
    duplicada = cliente.post(f"/guilda-fiscal/{c}/apuntes/{ap['id']}/recurrente", data={"frecuencia": "mensual"})
    assert duplicada.status_code == 302 and "error=" in duplicada.headers["Location"]
    pid = fr.listar(t, uid, c)[0]["id"]
    html = cliente.post(f"/guilda-fiscal/{c}/recurrentes", data={"accion": "generar"}).get_data(as_text=True)
    assert "Creados:" in html and len(fn.listar_apuntes(t, uid, c)) >= 2
    assert "En pausa" in cliente.post(f"/guilda-fiscal/{c}/recurrentes", data={"accion": "pausar", "plantilla_id": pid}).get_data(as_text=True)
    assert "Activa" in cliente.post(f"/guilda-fiscal/{c}/recurrentes", data={"accion": "reanudar", "plantilla_id": pid}).get_data(as_text=True)
    assert cliente.post(f"/guilda-fiscal/{c}/recurrentes", data={"accion": "inventada"}).status_code == 400
    cliente.post(f"/guilda-fiscal/{c}/recurrentes", data={"accion": "borrar", "plantilla_id": pid})
    assert fr.listar(t, uid, c) == []

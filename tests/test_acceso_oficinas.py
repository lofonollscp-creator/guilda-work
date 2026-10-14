"""Oficinas, roles y alcance (app/acceso.py): quién ve qué clientes fiscales en la web, la API, la IA y el MCP; concesiones; auditor de solo lectura; todo auditado."""
import pytest

import mcp_tools
from app import acceso, auditoria, db, ia_herramientas as ih

from tests.test_rutas_api import _auth, _registrar


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Oficinas")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.g1, e.g2, e.aud, e.rev, e.coord1, e.sin = u("sup-of@ejemplo.com", True), u("g1-of@ejemplo.com"), u("g2-of@ejemplo.com"), u("aud-of@ejemplo.com"), u("rev-of@ejemplo.com"), u("coord1-of@ejemplo.com"), u("sin-of@ejemplo.com")
    e.a = db.crear_cliente_fiscal(t, "Cliente A (Girona)", nif="B12345674"); e.b = db.crear_cliente_fiscal(t, "Cliente B (Barcelona)", nif="J21938519"); e.c = db.crear_cliente_fiscal(t, "Cliente C (sin oficina)")
    for c in (e.a, e.b, e.c):
        db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20")
    return e


def _como(uid):
    """Ejecuta lo que sigue «como» esa persona, igual que la IA y el MCP (contexto de la herramienta)."""
    class _Ctx:
        def __enter__(self):
            self.tok = mcp_tools._usuario_id_actual.set(uid)
        def __exit__(self, *a):
            mcp_tools._usuario_id_actual.reset(self.tok)
    return _Ctx()


def _nombres(uid):
    with _como(uid):
        return sorted(c["nombre"][:9] for c in db.listar_clientes_fiscales(uid and acceso.db.tenant_de_usuario(uid)["id"]))


def _montar(d):
    d.girona = acceso.crear_oficina(d.t, d.sup, "Girona"); d.bcn = acceso.crear_oficina(d.t, d.sup, "Barcelona")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.a, d.girona); acceso.asignar_cliente_a_oficina(d.t, d.sup, d.b, d.bcn)
    acceso.dar_membresia(d.t, d.sup, d.g1, "gestor", "oficina", d.girona); acceso.dar_membresia(d.t, d.sup, d.g2, "gestor", "oficina", d.bcn)
    acceso.dar_membresia(d.t, d.sup, d.aud, "auditor", "organizacion"); acceso.dar_membresia(d.t, d.sup, d.rev, "revisor_fiscal", "organizacion")
    acceso.dar_membresia(d.t, d.sup, d.coord1, "coordinador", "oficina", d.girona)


def test_sin_oficinas_todo_el_equipo_ve_todo_como_siempre(d):
    for u in (d.sup, d.g1, d.sin):
        assert _nombres(u) == ["Cliente A", "Cliente B", "Cliente C"]


def test_con_oficinas_cada_cual_ve_lo_suyo_y_lo_que_no_tiene_oficina(d):
    _montar(d)
    assert _nombres(d.g1) == ["Cliente A", "Cliente C"] and _nombres(d.g2) == ["Cliente B", "Cliente C"]
    assert _nombres(d.sin) == ["Cliente C"], "sin membresía solo ve lo que aún no tiene oficina"
    for u in (d.sup, d.aud, d.rev):
        assert _nombres(u) == ["Cliente A", "Cliente B", "Cliente C"], "dirección y roles de organización lo ven todo"
    assert _nombres(d.coord1) == ["Cliente A", "Cliente C"]


def test_la_restriccion_cubre_fichas_vencimientos_conteos_documentos_y_papelera(d):
    from app import almacen_documentos as alm
    _montar(d)
    t = d.t
    alm.guardar_de_cliente_fiscal(d.sup, d.b, "balance.pdf", "application/pdf", b"%PDF-1.4 balance")
    db.eliminar_cliente_fiscal(t, d.b)
    db.restaurar_cliente_fiscal(t, d.b)
    with _como(d.g1):
        assert db.obtener_cliente_fiscal(t, d.a) is not None and db.obtener_cliente_fiscal(t, d.b) is None
        assert sorted(v["cliente_nombre"][:9] for v in db.listar_vencimientos_fiscales(t)) == ["Cliente A", "Cliente C"]
        assert db.contar_vencimientos_fiscales(t) == 2 and set(db.vencimientos_por_cliente(t)) == {d.a, d.c}
        venc_b = [v["id"] for v in db.listar_vencimientos_fiscales(t, cliente_fiscal_id=d.b)]
        assert venc_b == [] and db.listar_documentos_cliente(t, d.b) == []
        assert db.obtener_documento_cliente(t, d.b, 1) is None
    with _como(d.sup):
        v = db.listar_vencimientos_fiscales(t, cliente_fiscal_id=d.b)[0]["id"]
        assert db.obtener_documento_cliente(t, d.b, 1) is not None
    with _como(d.g1):
        assert db.obtener_vencimiento_fiscal(t, v) is None
    db.eliminar_cliente_fiscal(t, d.b)
    with _como(d.g1):
        assert "Cliente B (Barcelona)" not in [x["texto"] for x in db.papelera_fiscal(t)], "ni siquiera la papelera revela lo que no puede ver"
    with _como(d.sup):
        assert "Cliente B (Barcelona)" in [x["texto"] for x in db.papelera_fiscal(t)]


def test_las_tareas_del_sistema_sin_actor_no_se_filtran(d):
    _montar(d)
    assert len(db.listar_clientes_fiscales(d.t)) == 3 and len(db.listar_vencimientos_fiscales(d.t)) == 3


def test_la_ia_y_el_mcp_respetan_el_alcance(d):
    _montar(d)
    r = ih.ejecutar(d.g1, "listar_clientes_fiscales", {})
    assert sorted(c["nombre"][:9] for c in r) == ["Cliente A", "Cliente C"]
    assert [v["cliente"][:9] if "cliente" in v else v.get("cliente_nombre", "")[:9] for v in ih.ejecutar(d.g1, "listar_vencimientos_fiscales", {})].count("Cliente B") == 0
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(d.g1, "resumen_cliente_fiscal", {"cliente_id": d.b})


def test_las_concesiones_comparten_un_cliente_con_vigencia_y_se_pueden_retirar(d):
    _montar(d)
    k = acceso.conceder_cliente(d.t, d.sup, d.b, para_usuario_id=d.g1, nivel="lectura")
    assert _nombres(d.g1) == ["Cliente A", "Cliente B", "Cliente C"]
    acceso.revocar_concesion(d.t, d.sup, k)
    assert _nombres(d.g1) == ["Cliente A", "Cliente C"]
    k2 = acceso.conceder_cliente(d.t, d.sup, d.b, oficina_id=d.girona)
    assert _nombres(d.g1) == ["Cliente A", "Cliente B", "Cliente C"] and _nombres(d.coord1) == ["Cliente A", "Cliente B", "Cliente C"], "se comparte con toda la oficina"
    acceso.revocar_concesion(d.t, d.sup, k2)
    acceso.conceder_cliente(d.t, d.sup, d.b, para_usuario_id=d.g1, hasta="2020-01-01")
    assert _nombres(d.g1) == ["Cliente A", "Cliente C"], "una concesión vencida no se reutiliza"
    with pytest.raises(ValueError, match="Indica a una oficina o a una persona"):
        acceso.conceder_cliente(d.t, d.sup, d.b)
    with pytest.raises(ValueError, match="Solo la dirección"):
        acceso.conceder_cliente(d.t, d.g1, d.a, para_usuario_id=d.sin)


def test_una_membresia_de_cliente_y_su_vigencia(d):
    _montar(d)
    m = acceso.dar_membresia(d.t, d.sup, d.sin, "gestor", "cliente", d.b)
    assert _nombres(d.sin) == ["Cliente B", "Cliente C"]
    acceso.revocar_membresia(d.t, d.sup, m)
    assert _nombres(d.sin) == ["Cliente C"]
    acceso.dar_membresia(d.t, d.sup, d.sin, "auditor", "oficina", d.bcn, hasta="2020-01-01")
    assert _nombres(d.sin) == ["Cliente C"], "membresía caducada"
    with pytest.raises(ValueError, match="ya tiene"):
        acceso.dar_membresia(d.t, d.sup, d.g1, "gestor", "oficina", d.girona)


def test_quien_coordina_una_oficina_solo_gobierna_la_suya(d):
    _montar(d)
    acceso.dar_membresia(d.t, d.coord1, d.sin, "gestor", "oficina", d.girona)
    assert _nombres(d.sin) == ["Cliente A", "Cliente C"]
    for args in ((d.sin, "gestor", "oficina", d.bcn), (d.sin, "revisor_fiscal", "organizacion", None), (d.sin, "coordinador", "oficina", d.girona)):
        with pytest.raises(ValueError, match="Solo la dirección"):
            acceso.dar_membresia(d.t, d.coord1, *args)
    with pytest.raises(ValueError, match="Solo la dirección"):
        acceso.crear_oficina(d.t, d.coord1, "Madrid")
    nueva = acceso.crear_oficina(d.t, d.sup, "Tarragona")
    acceso.asignar_cliente_a_oficina(d.t, d.coord1, d.a, None)           # sacarlo de su oficina… a «sin oficina», que sigue siendo suya de origen
    with pytest.raises(ValueError, match="coordina"):
        acceso.asignar_cliente_a_oficina(d.t, d.coord1, d.b, nueva)
    assert acceso.puede_autorizar(d.t, d.rev) and acceso.puede_autorizar(d.t, d.sup) and not acceso.puede_autorizar(d.t, d.g1) and not acceso.puede_autorizar(d.t, d.coord1)


def test_no_se_archiva_una_oficina_con_clientes_y_todo_queda_auditado(d):
    _montar(d)
    with pytest.raises(ValueError, match="reasígnalos"):
        acceso.archivar_oficina(d.t, d.sup, d.girona)
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.a, d.bcn)
    acceso.archivar_oficina(d.t, d.sup, d.girona)
    assert _nombres(d.g1) == ["Cliente C"], "al archivar la oficina se retiran sus membresías"
    acciones = [e["accion"] for e in auditoria.listar(d.t, limite=100)]
    for esperada in ("oficina.crear", "oficina.archivar", "cliente.oficina", "membresia.crear"):
        assert esperada in acciones, esperada


def test_el_auditor_no_puede_escribir_en_el_modulo_fiscal_ni_por_web_ni_por_api(cliente, d):
    from tests.conftest import iniciar_sesion_de_prueba
    _montar(d)
    # API: un token de cada persona (una sola sesión web por test, pero los tokens no tienen ese límite)
    tokens = {}
    for nombre, uid in (("aud", d.aud), ("g1", d.g1)):
        email = db.obtener_usuario(uid)["email"]
        datos = _registrar(cliente, "tok-" + email)
        nuevo = db.obtener_usuario_por_email("tok-" + email)["id"]
        db.asignar_tenant(nuevo, d.t)
        for m in acceso.membresias_vigentes(d.t, uid):
            acceso.dar_membresia(d.t, d.sup, nuevo, m["rol"], m["alcance_tipo"], m["alcance_id"])
        tokens[nombre] = (nuevo, _auth(datos["token"]))
    na, ha = tokens["aud"]; ng, hg = tokens["g1"]
    assert cliente.get("/api/v1/fiscal/clientes", headers=ha).status_code == 200
    r = cliente.post("/api/v1/fiscal/clientes", headers=ha, json={"nombre": "Nuevo del auditor"})
    assert r.status_code == 403 and r.get_json()["codigo"] == "solo_lectura"
    assert cliente.put(f"/api/v1/fiscal/clientes/{d.a}", headers=ha, json={"notas": "x"}).status_code == 403
    assert cliente.post("/api/v1/fiscal/clientes", headers=hg, json={"nombre": "Nuevo del gestor"}).status_code == 201
    visibles = [c["nombre"][:9] for c in cliente.get("/api/v1/fiscal/clientes", headers=hg).get_json()["data"]]
    assert "Cliente B" not in visibles and "Cliente A" in visibles
    assert cliente.get(f"/api/v1/fiscal/clientes/{d.b}", headers=hg).status_code == 404, "no se confirma ni que exista"
    assert cliente.put(f"/api/v1/fiscal/clientes/{d.b}", headers=hg, json={"notas": "x"}).status_code == 404
    assert cliente.get(f"/api/v1/fiscal/clientes/{d.b}/documentos", headers=hg).status_code == 404


def test_la_web_filtra_y_el_auditor_no_escribe(cliente, d):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "web-of@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, d.t)
    _montar(d)
    acceso.dar_membresia(d.t, d.sup, uid, "gestor", "oficina", d.girona)
    pagina = cliente.get("/fiscal/clientes").get_data(as_text=True)
    assert "Cliente A (Girona)" in pagina and "Cliente B (Barcelona)" not in pagina
    assert cliente.get(f"/fiscal/clientes/{d.b}").status_code == 404 and cliente.get(f"/fiscal/clientes/{d.a}", follow_redirects=True).status_code == 200      # (la ficha es una sola: /clientes/<id>)
    assert cliente.get(f"/fiscal/clientes/{d.b}/editar").status_code == 404
    assert cliente.post(f"/fiscal/clientes/{d.b}/eliminar").status_code == 404 or db.obtener_cliente_fiscal(d.t, d.b) is not None
    assert "Cliente B (Barcelona)" not in cliente.get("/fiscal/vencimientos").get_data(as_text=True)
    assert "Cliente B (Barcelona)" not in cliente.get("/fiscal/vencimientos/export.csv").get_data(as_text=True)
    m = acceso.dar_membresia(d.t, d.sup, uid, "auditor", "organizacion")
    acceso.revocar_membresia(d.t, d.sup, [x["id"] for x in acceso.membresias_vigentes(d.t, uid) if x["rol"] == "gestor"][0])
    assert "Cliente B (Barcelona)" in cliente.get("/fiscal/clientes").get_data(as_text=True)
    assert cliente.post("/fiscal/clientes", data={"nombre": "Lo intenta el auditor"}).status_code == 403
    assert len(db.listar_clientes_fiscales(d.t)) == 3


def test_el_buscador_no_deja_buscar_clientes_de_otras_oficinas(d, monkeypatch):
    from app import busqueda
    import base64, json
    monkeypatch.setattr(busqueda, "MEILISEARCH_MASTER_KEY", "clave-de-prueba")
    monkeypatch.setattr(busqueda, "_asegurar_clave_busqueda", lambda: {"uid": "u", "key": "k"})
    capturado = {}
    monkeypatch.setattr(busqueda, "_firmar_jwt", lambda payload, clave: capturado.update(payload) or "jwt")
    busqueda.generar_token_busqueda(d.g1, d.t)
    assert capturado["searchRules"][busqueda.INDICE]["filter"] == f"(usuario_id = {d.g1}) OR tenant_id = {d.t}", "sin oficinas, como siempre"
    _montar(d)
    busqueda.generar_token_busqueda(d.g1, d.t)
    f = capturado["searchRules"][busqueda.INDICE]["filter"]
    assert 'tipo != "cliente_fiscal"' in f and 'tipo != "vencimiento_fiscal"' in f
    busqueda.generar_token_busqueda(d.sup, d.t)
    assert capturado["searchRules"][busqueda.INDICE]["filter"] == f"(usuario_id = {d.sup}) OR tenant_id = {d.t}", "la dirección sigue buscando en todo"

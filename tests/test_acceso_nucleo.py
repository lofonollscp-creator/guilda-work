"""Oficinas y clientes del núcleo (app/acceso.py: condicion_nucleo / restriccion_nucleo): un cliente con ficha fiscal se ve en clientes, expedientes, plazos, horas y documentos
solo desde las oficinas que ven esa ficha; un cliente sin ficha fiscal (o un despacho sin oficinas) lo ve todo el equipo, como hasta ahora."""
import pytest

import mcp_tools
from app import acceso, almacen_documentos as alm, db, nucleo
from tests.conftest import iniciar_sesion_de_prueba


def _como(uid):
    class _Ctx:
        def __enter__(self):
            self.tok = mcp_tools._usuario_id_actual.set(uid)

        def __exit__(self, *a):
            mcp_tools._usuario_id_actual.reset(self.tok)
    return _Ctx()


class _E:
    pass


@pytest.fixture
def d():
    t = db.crear_tenant("Despacho núcleo-oficinas")
    e = _E()
    e.t = t

    def persona(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail)
        db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x

    e.sup, e.g1, e.g2, e.sin = persona("sup-nu@ejemplo.com", True), persona("g1-nu@ejemplo.com"), persona("g2-nu@ejemplo.com"), persona("sin-nu@ejemplo.com")
    ficha = {}
    for clave, nombre, nif in (("a", "Cliente A", "B12345674"), ("b", "Cliente B", "J21938519"), ("c", "Cliente C", "B16406233")):
        fid = db.crear_cliente_fiscal(t, nombre, nif=nif)
        ficha[clave] = fid
        setattr(e, clave, nucleo.obtener_cliente(t, db.obtener_cliente_fiscal(t, fid)["cliente_id"])["id"])   # id del cliente del núcleo
    e.fa, e.fb, e.fc = ficha["a"], ficha["b"], ficha["c"]
    e.n = nucleo.crear_cliente(t, "Cliente N (solo núcleo)")
    for clave in ("a", "b", "c", "n"):
        cid = getattr(e, clave)
        setattr(e, "x" + clave, nucleo.crear_expediente(t, e.sup, cid, f"Expediente {clave.upper()}"))
        nucleo.crear_plazo(t, e.sup, f"Plazo {clave.upper()}", "2030-01-15", cliente_id=cid)
        nucleo.registrar_parte(t, e.sup, f"Horas {clave.upper()}", minutos=30, cliente_id=cid)
    return e


def _montar(d):
    d.girona = acceso.crear_oficina(d.t, d.sup, "Girona")
    d.bcn = acceso.crear_oficina(d.t, d.sup, "Barcelona")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.fa, d.girona)
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.fb, d.bcn)
    acceso.dar_membresia(d.t, d.sup, d.g1, "gestor", "oficina", d.girona)
    acceso.dar_membresia(d.t, d.sup, d.g2, "gestor", "oficina", d.bcn)


def _nombres_clientes(uid):
    """Letras de los clientes («Cliente A», «Cliente N (solo núcleo)»…) que ve esa persona en el listado."""
    with _como(uid):
        return sorted(c["nombre"].split()[1] for c in nucleo.listar_clientes(db.obtener_usuario(uid)["tenant_id"])[0])


def test_sin_oficinas_todo_el_equipo_ve_todos_los_clientes_del_nucleo(d):
    for u in (d.sup, d.g1, d.sin):
        assert _nombres_clientes(u) == ["A", "B", "C", "N"]


def test_con_oficinas_cada_cual_ve_los_clientes_de_sus_oficinas_los_sin_oficina_y_los_que_no_tienen_ficha_fiscal(d):
    _montar(d)
    assert _nombres_clientes(d.g1) == ["A", "C", "N"]
    assert _nombres_clientes(d.g2) == ["B", "C", "N"]
    assert _nombres_clientes(d.sin) == ["C", "N"]
    assert _nombres_clientes(d.sup) == ["A", "B", "C", "N"], "la dirección lo ve todo"


def test_ficha_y_ediciones_de_un_cliente_de_otra_oficina_son_como_si_no_existieran(d):
    _montar(d)
    with _como(d.g1):
        assert nucleo.obtener_cliente(d.t, d.a) is not None
        assert nucleo.obtener_cliente(d.t, d.b) is None
        with pytest.raises(ValueError):
            nucleo.editar_cliente(d.t, d.b, nombre="Intruso")
        with pytest.raises(ValueError):
            nucleo.crear_expediente(d.t, d.g1, d.b, "No debería poder")
        assert nucleo.listar_contactos(d.t, d.b) == []
    with _como(d.g2):
        assert nucleo.obtener_cliente(d.t, d.b) is not None


def test_expedientes_plazos_y_horas_siguen_a_su_cliente(d):
    _montar(d)
    t = d.t
    titulos = lambda uid: sorted(x["titulo"][-1] for x in nucleo.listar_expedientes(t, uid)[0])
    assert titulos(d.g1) == sorted(["A", "C", "N"]) and titulos(d.g2) == sorted(["B", "C", "N"]) and titulos(d.sup) == sorted(["A", "B", "C", "N"])
    assert nucleo.obtener_expediente(t, d.xb, d.g1) is None and nucleo.obtener_expediente(t, d.xb, d.g2) is not None
    plazos = lambda uid: sorted(p["titulo"][-1] for p in nucleo.listar_plazos(t, uid))
    assert plazos(d.g1) == sorted(["A", "C", "N"]) and plazos(d.sup) == sorted(["A", "B", "C", "N"])
    horas = lambda uid: sorted(p["descripcion"][-1] for p in nucleo.listar_partes(t, uid, ver_todo=True))
    assert horas(d.g1) == sorted(["A", "C", "N"]) and horas(d.g2) == sorted(["B", "C", "N"]) and horas(d.sup) == sorted(["A", "B", "C", "N"])


def test_los_plazos_y_horas_de_un_expediente_ajeno_tampoco_se_ven(d):
    _montar(d)
    t = d.t
    nucleo.crear_plazo(t, d.sup, "Plazo del expediente B", "2030-02-01", expediente_id=d.xb)
    nucleo.registrar_parte(t, d.sup, "Horas del expediente B", minutos=10, expediente_id=d.xb)
    assert not any("expediente B" in p["titulo"] for p in nucleo.listar_plazos(t, d.g1))
    assert not any("expediente B" in p["descripcion"] for p in nucleo.listar_partes(t, d.g1, ver_todo=True))
    assert any("expediente B" in p["titulo"] for p in nucleo.listar_plazos(t, d.g2))


def test_documentos_del_cliente_de_otra_oficina_no_se_listan_ni_se_leen_ni_se_suben(d):
    _montar(d)
    res, doc = alm.guardar(d.g2, "b.txt", "text/plain", b"contenido de B", cliente_id=d.b)
    assert res == "ok"
    assert [x["id"] for x in alm.listar(d.t, d.g2, cliente_id=d.b)] == [doc]
    assert alm.listar(d.t, d.g1, cliente_id=d.b) == []
    assert alm.leer(d.t, d.g1, doc) is None and alm.leer(d.t, d.g2, doc) is not None
    assert alm.guardar(d.g1, "intruso.txt", "text/plain", b"otro", cliente_id=d.b)[0] == "cliente"
    assert alm.guardar(d.g1, "intruso.txt", "text/plain", b"otro", expediente_id=d.xb)[0] == "expediente"


def test_etiquetas_y_duplicados_no_filtran_clientes_ajenos(d):
    _montar(d)
    with _como(d.sup):
        conn = db.get_connection(); conn.execute("INSERT INTO cliente_etiquetas (cliente_id, etiqueta) VALUES (?, 'secreta')", (d.b,)); conn.commit(); conn.close()
        assert [e["etiqueta"] for e in nucleo.etiquetas_del_despacho(d.t)] == ["secreta"]
    with _como(d.g1):
        assert nucleo.etiquetas_del_despacho(d.t) == []
        assert nucleo.posibles_duplicados(d.t, nombre="Cliente B") == []
    with _como(d.g2):
        assert [c["id"] for c in nucleo.posibles_duplicados(d.t, nombre="Cliente B")] == [d.b]


def test_compartir_el_cliente_fiscal_con_una_oficina_lo_abre_tambien_en_el_nucleo(d):
    _montar(d)
    with _como(d.g1):
        assert nucleo.obtener_cliente(d.t, d.b) is None
    acceso.conceder_cliente(d.t, d.sup, d.fb, oficina_id=d.girona)
    with _como(d.g1):
        assert nucleo.obtener_cliente(d.t, d.b) is not None
        assert nucleo.obtener_expediente(d.t, d.xb, d.g1) is not None


def test_sin_actor_las_tareas_del_sistema_no_se_filtran(d):
    _montar(d)
    assert len(nucleo.listar_clientes(d.t)[0]) == 4


def test_pantallas_web_de_un_gestor_no_enseñan_ni_abren_clientes_de_otra_oficina(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "web-of@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho web oficinas")
    db.asignar_tenant(uid, t)
    jefe = db.crear_usuario_vinculado_a_kratos("jefe-of@ejemplo.com", "k-jefe-of"); db.asignar_tenant(jefe, t); db.asignar_supervisor_tenant(jefe, True)
    fa, fb = db.crear_cliente_fiscal(t, "Cliente Girona", nif="B12345674"), db.crear_cliente_fiscal(t, "Cliente Barcelona", nif="J21938519")
    ca, cb = (db.obtener_cliente_fiscal(t, f)["cliente_id"] for f in (fa, fb))
    girona, bcn = acceso.crear_oficina(t, jefe, "Girona"), acceso.crear_oficina(t, jefe, "Barcelona")
    acceso.asignar_cliente_a_oficina(t, jefe, fa, girona); acceso.asignar_cliente_a_oficina(t, jefe, fb, bcn)
    acceso.dar_membresia(t, jefe, uid, "gestor", "oficina", girona)
    html = cliente.get("/clientes/").get_data(as_text=True)
    assert "Cliente Girona" in html and "Cliente Barcelona" not in html
    assert cliente.get(f"/clientes/{ca}").status_code == 200
    assert cliente.get(f"/clientes/{cb}").status_code == 404
    assert cliente.get(f"/clientes/{cb}", follow_redirects=False).status_code == 404

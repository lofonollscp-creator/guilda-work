"""Test de regresión: aunque tareas/notas/categorias no tienen columna
tenant_id (ver HOSTING.md y app/db.py -- se filtran por usuario_id, no se
duplicó tenant_id para no quedar obsoleto en una reasignación), el
aislamiento entre tenants tiene que sostenerse igualmente porque cada
consulta ya exige `usuario_id = ?`. Este test lo demuestra en dos capas:
la de BD directamente, y la de ruta (para confirmar que ningún handler
se salta el chequeo de propiedad, ni siquiera adivinando IDs)."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def _crear_tenant_con_usuario(email: str) -> tuple[int, int]:
    """Crea un tenant y un usuario asignado a él (sin pasar por Kratos --
    válido para los tests de capa BD, que no necesitan sesión real)."""
    tenant_id = db.crear_tenant(f"Gestoría {email}")
    usuario_id = db.crear_usuario_vinculado_a_kratos(email, f"kratos-{email}")
    db.asignar_tenant(usuario_id, tenant_id)
    return tenant_id, usuario_id


def test_usuario_de_un_tenant_no_puede_leer_tarea_de_otro():
    _, usuario_a = _crear_tenant_con_usuario("a@ejemplo.com")
    _, usuario_b = _crear_tenant_con_usuario("b@ejemplo.com")

    categoria_a = db.crear_categoria(usuario_a, "Clientes A")
    tarea_a = db.crear_tarea(usuario_a, "Tarea de A", categoria_a, "duracion")

    assert db.obtener_tarea(usuario_a, tarea_a) is not None
    assert db.obtener_tarea(usuario_b, tarea_a) is None


def test_usuario_de_un_tenant_no_puede_editar_ni_borrar_tarea_de_otro():
    _, usuario_a = _crear_tenant_con_usuario("a-editar@ejemplo.com")
    _, usuario_b = _crear_tenant_con_usuario("b-editar@ejemplo.com")

    categoria_a = db.crear_categoria(usuario_a, "Clientes A")
    tarea_a = db.crear_tarea(usuario_a, "Tarea original", categoria_a, "duracion")

    # editar_tarea/eliminar_tarea son no-op silencioso si usuario_id no
    # coincide (WHERE id=? AND usuario_id=? en el UPDATE) -- no lanzan,
    # simplemente no tocan la fila. Se confirma leyendo después con A.
    db.editar_tarea(usuario_b, tarea_a, "Secuestrada por B")
    db.eliminar_tarea(usuario_b, tarea_a)

    tarea_tras_intento = db.obtener_tarea(usuario_a, tarea_a)
    assert tarea_tras_intento is not None
    assert tarea_tras_intento["nombre"] == "Tarea original"
    assert tarea_tras_intento["papelera_en"] is None


def test_usuario_de_un_tenant_no_puede_leer_ni_tocar_nota_de_otro():
    _, usuario_a = _crear_tenant_con_usuario("a-nota@ejemplo.com")
    _, usuario_b = _crear_tenant_con_usuario("b-nota@ejemplo.com")

    nota_a = db.crear_nota(usuario_a, "Nota confidencial de A")

    assert db.obtener_nota(usuario_b, nota_a) is None
    db.editar_nota(usuario_b, nota_a, "Secuestrada por B")
    db.eliminar_nota(usuario_b, nota_a)

    nota_tras_intento = db.obtener_nota(usuario_a, nota_a)
    assert nota_tras_intento is not None
    assert nota_tras_intento["texto"] == "Nota confidencial de A"


def test_usuario_de_un_tenant_no_puede_leer_categoria_de_otro():
    _, usuario_a = _crear_tenant_con_usuario("a-cat@ejemplo.com")
    _, usuario_b = _crear_tenant_con_usuario("b-cat@ejemplo.com")

    categoria_a = db.crear_categoria(usuario_a, "Menú privado de A")

    assert db.obtener_categoria(usuario_b, categoria_a) is None


def test_usuarios_de_tenant_devuelve_solo_los_del_tenant():
    tenant_a, usuario_a = _crear_tenant_con_usuario("a-tenant@ejemplo.com")
    tenant_b, usuario_b = _crear_tenant_con_usuario("b-tenant@ejemplo.com")

    assert db.usuarios_de_tenant(tenant_a) == [usuario_a]
    assert db.usuarios_de_tenant(tenant_b) == [usuario_b]


def test_ruta_editar_tarea_de_otro_usuario_da_404(cliente):
    usuario_a = iniciar_sesion_de_prueba(cliente, "ruta-a@ejemplo.com", "contrasena123")
    categoria_a = db.crear_categoria(usuario_a, "Clientes A")
    tarea_a = db.crear_tarea(usuario_a, "Tarea de A por ruta", categoria_a, "duracion")

    # Segundo cliente/sesión para B -- no se reutiliza `cliente` porque la
    # cookie de sesión de Kratos ya quedaría puesta para A.
    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as cliente_b:
        iniciar_sesion_de_prueba(cliente_b, "ruta-b@ejemplo.com", "contrasena123")

        resp_editar = cliente_b.get(f"/tarea/{tarea_a}/editar")
        assert resp_editar.status_code == 404

        resp_eliminar = cliente_b.post(f"/tarea/{tarea_a}/eliminar")
        assert resp_eliminar.status_code == 404

    # La tarea de A sigue intacta.
    tarea_tras_intentos = db.obtener_tarea(usuario_a, tarea_a)
    assert tarea_tras_intentos is not None
    assert tarea_tras_intentos["papelera_en"] is None


def test_ruta_editar_nota_de_otro_usuario_da_404(cliente):
    usuario_a = iniciar_sesion_de_prueba(cliente, "ruta-nota-a@ejemplo.com", "contrasena123")
    nota_a = db.crear_nota(usuario_a, "Nota de A por ruta")

    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as cliente_b:
        iniciar_sesion_de_prueba(cliente_b, "ruta-nota-b@ejemplo.com", "contrasena123")

        resp_editar = cliente_b.get(f"/nota/{nota_a}/editar")
        assert resp_editar.status_code == 404

        resp_eliminar = cliente_b.post(f"/nota/{nota_a}/eliminar")
        assert resp_eliminar.status_code == 404

    nota_tras_intentos = db.obtener_nota(usuario_a, nota_a)
    assert nota_tras_intentos is not None

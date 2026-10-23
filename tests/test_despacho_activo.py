"""Una persona en varios despachos: el selector del panel de cuenta, el despacho activo de la sesión y los atributos por despacho."""
import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba


def _persona_en_dos_despachos(cliente, email="multi@ejemplo.com"):
    t1, t2 = db.crear_tenant("Alfa Asesores"), db.crear_tenant("Beta Abogados")
    uid = iniciar_sesion_de_prueba(cliente, email, "contraseña-larga-123")
    db.asignar_tenant(uid, t1)
    db.anadir_usuario_a_tenant(uid, t2)
    with cliente.session_transaction() as s:
        s.pop("despachos_usuario", None)                      # la lista de despachos se recuerda un minuto en la sesión: aquí cambia justo después de iniciar sesión
    return uid, t1, t2


def test_quien_tiene_un_solo_despacho_no_ve_selector(cliente):
    t = db.crear_tenant("Solo Uno")
    uid = iniciar_sesion_de_prueba(cliente, "uno@ejemplo.com", "contraseña-larga-123")
    db.asignar_tenant(uid, t)
    html = cliente.get("/").get_data(as_text=True)
    assert "Solo Uno" in html and "/despacho/activo/" not in html


def test_el_selector_cambia_el_despacho_con_el_que_se_trabaja(cliente):
    uid, t1, t2 = _persona_en_dos_despachos(cliente)
    html = cliente.get("/").get_data(as_text=True)
    assert f"/despacho/activo/{t1}" in html and f"/despacho/activo/{t2}" in html
    assert 'icon-rail-perfil-tenant">Alfa Asesores' in html                       # el principal, por defecto
    r = cliente.post(f"/despacho/activo/{t2}")
    assert r.status_code == 302
    html = cliente.get("/").get_data(as_text=True)
    assert 'icon-rail-perfil-tenant">Beta Abogados' in html
    with cliente.session_transaction() as s:
        assert s["tenant_activo"] == t2
    cliente.post(f"/despacho/activo/{t1}")
    assert 'icon-rail-perfil-tenant">Alfa Asesores' in cliente.get("/").get_data(as_text=True)


def test_no_se_puede_activar_un_despacho_ajeno(cliente):
    uid, t1, t2 = _persona_en_dos_despachos(cliente, "ajeno@ejemplo.com")
    otro = db.crear_tenant("Despacho ajeno")
    assert cliente.post(f"/despacho/activo/{otro}").status_code == 403
    with cliente.session_transaction() as s:
        assert "tenant_activo" not in s
    assert 'icon-rail-perfil-tenant">Alfa Asesores' in cliente.get("/").get_data(as_text=True)


def test_si_deja_de_pertenecer_al_despacho_activo_vuelve_al_principal(cliente):
    uid, t1, t2 = _persona_en_dos_despachos(cliente, "salida@ejemplo.com")
    cliente.post(f"/despacho/activo/{t2}")
    db.quitar_usuario_de_tenant(uid, t2)
    assert 'icon-rail-perfil-tenant">Alfa Asesores' in cliente.get("/").get_data(as_text=True)


def test_los_atributos_son_de_cada_despacho(cliente):
    """Ser supervisor en un despacho no lo es en el otro: en el principal mandan los de `usuarios`; en los demás, los de la pertenencia."""
    uid, t1, t2 = _persona_en_dos_despachos(cliente, "roles@ejemplo.com")
    db.fijar_atributos_en_despacho(uid, t1, supervisor_tenant=1)                    # supervisor en su despacho principal
    assert db.atributos_en_despacho(uid, t1)["supervisor_tenant"] == 1 and db.atributos_en_despacho(uid, t2)["supervisor_tenant"] == 0
    assert "Seguridad del despacho" in cliente.get("/").get_data(as_text=True)
    cliente.post(f"/despacho/activo/{t2}")
    assert "Seguridad del despacho" not in cliente.get("/").get_data(as_text=True), "en el otro despacho es un miembro más"
    db.fijar_atributos_en_despacho(uid, t2, supervisor_tenant=1)
    assert "Seguridad del despacho" in cliente.get("/").get_data(as_text=True)
    with pytest.raises(ValueError, match="desconocido"):
        db.fijar_atributos_en_despacho(uid, t2, rol="admin")
    with pytest.raises(ValueError, match="no pertenece"):
        db.fijar_atributos_en_despacho(uid, db.crear_tenant("Otro"), supervisor_tenant=1)

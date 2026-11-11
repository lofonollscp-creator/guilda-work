"""Acceso del equipo (W14): quién tiene la verificación en dos pasos, sin tocar nada y sin romperse si Kratos no contesta."""
from app import db, kratos, seguridad_equipo
from tests.conftest import iniciar_sesion_de_prueba


def _equipo(n=1):
    t = db.crear_tenant(f"Acceso equipo {n}")
    dir_ = db.crear_usuario_vinculado_a_kratos(f"dir{n}@ejemplo.com", f"k-dir{n}")
    con2 = db.crear_usuario_vinculado_a_kratos(f"con2{n}@ejemplo.com", f"k-con2{n}")
    sin2 = db.crear_usuario_vinculado_a_kratos(f"sin2{n}@ejemplo.com", f"k-sin2{n}")
    for u in (dir_, con2, sin2):
        db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(dir_, True)
    return t, dir_, con2, sin2


def test_el_informe_separa_quien_tiene_el_segundo_factor_y_pone_a_la_direccion_primero(monkeypatch):
    t, dir_, con2, sin2 = _equipo()
    por_identidad = {f"k-dir1": {"password"}, "k-con21": {"password", "totp", "lookup_secret"}, "k-sin21": {"password"}}
    monkeypatch.setattr(kratos, "credenciales_de", lambda i: por_identidad[i])
    r = seguridad_equipo.informe(t)
    assert [p["email"] for p in r["personas"]][0] == "dir1@ejemplo.com"                                  # la dirección sin 2FA, lo primero
    estado = {p["email"]: p["segundo_factor"] for p in r["personas"]}
    assert estado == {"dir1@ejemplo.com": False, "con21@ejemplo.com": True, "sin21@ejemplo.com": False}
    assert r["sin_segundo_factor"] == 2 and r["direccion_sin_segundo_factor"] == 1 and r["sin_comprobar"] == 0


def test_si_kratos_no_contesta_la_persona_sale_sin_comprobar_y_no_se_rompe(monkeypatch):
    t, *_ = _equipo(2)
    def cae(i):
        raise RuntimeError("Kratos caído")
    monkeypatch.setattr(kratos, "credenciales_de", cae)
    r = seguridad_equipo.informe(t)
    assert r["sin_comprobar"] == 3 and r["sin_segundo_factor"] == 0 and all(p["segundo_factor"] is None for p in r["personas"])
    monkeypatch.setattr(kratos, "credenciales_de", lambda i: None)                                      # respuesta no válida
    assert seguridad_equipo.informe(t)["sin_comprobar"] == 3


def test_credenciales_de_lee_las_credenciales_que_kratos_devuelve(monkeypatch):
    llamadas = []
    monkeypatch.setattr(kratos, "_peticion", lambda url, **k: llamadas.append(url) or (200, {"credentials": {"password": {}, "totp": {}}}, []))
    assert kratos.credenciales_de("abc") == {"password", "totp"} and "include_credential=totp" in llamadas[0]
    monkeypatch.setattr(kratos, "_peticion", lambda url, **k: (404, {}, []))
    assert kratos.credenciales_de("abc") is None


def test_la_pantalla_la_ve_la_direccion_y_nadie_mas(cliente, monkeypatch):
    u = iniciar_sesion_de_prueba(cliente, "acceso-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Acceso web")
    db.asignar_tenant(u, t)
    monkeypatch.setattr(kratos, "credenciales_de", lambda i: {"password"})
    assert cliente.get("/seguridad/acceso").status_code == 403
    db.asignar_supervisor_tenant(u, True)
    html = cliente.get("/seguridad/acceso").get_data(as_text=True)
    assert "Acceso del equipo" in html and "1 persona de la dirección no tiene la verificación en dos pasos." in html and "acceso-web@ejemplo.com" in html and "Cómo se activa" in html

"""Correo C2: archivar, spam, gestión de carpetas del servidor y respuesta rápida (app/correo.py, app/rutas_correo.py). El servidor IMAP se simula."""
import pytest

from app import correo, db
from app.correo import ErrorCorreo
from tests.conftest import iniciar_sesion_de_prueba


class _Imap:
    def __init__(self, ok=True):
        self.ok, self.llamadas = ok, []

    def _r(self, nombre, *a):
        self.llamadas.append((nombre, *a))
        return ("OK" if self.ok else "NO"), [b""]

    def create(self, *a): return self._r("create", *a)
    def rename(self, *a): return self._r("rename", *a)
    def delete(self, *a): return self._r("delete", *a)
    def logout(self): pass


def _cuenta(cliente, email, carpetas=("INBOX", "Archive", "Junk", "Clientes")):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_carpetas_correo(cuenta, [(n, correo._nombre_visible_carpeta(n)) for n in carpetas])
    return uid, cuenta


def _msg(cuenta, uid="1", carpeta="INBOX"):
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid=uid, asunto="Hola", remitente="ana@b.com", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    if carpeta != "INBOX":
        conn = db.get_connection(); conn.execute("UPDATE correo_mensajes SET carpeta = ? WHERE id = ?", (carpeta, m)); conn.commit(); conn.close()
    return m


def test_buscar_carpeta_especial_por_nombre_sin_depender_del_idioma():
    assert correo.buscar_carpeta_especial(["INBOX", "Archive", "Sent"], "archivo") == "Archive"
    assert correo.buscar_carpeta_especial(["INBOX", "Archivo"], "archivo") == "Archivo"
    assert correo.buscar_carpeta_especial(["INBOX", "[Gmail]/Spam"], "spam") == "[Gmail]/Spam"
    assert correo.buscar_carpeta_especial(["INBOX", "INBOX.Junk"], "spam") == "INBOX.Junk"
    assert correo.buscar_carpeta_especial(["INBOX", "Facturas"], "spam") is None and correo.buscar_carpeta_especial(["INBOX"], "archivo") is None


@pytest.mark.parametrize("malo", ["", "  ", "a/b", 'a"b', "a%b", "a*b", "x" * 101, "a\nb"])
def test_nombres_de_carpeta_no_validos(malo):
    with pytest.raises(ErrorCorreo, match="no es válido"):
        correo._nombre_carpeta_valido(malo)


def test_crear_renombrar_y_eliminar_carpeta_actualizan_servidor_y_cache(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "car-1@ejemplo.com")
    imap = _Imap(); monkeypatch.setattr(correo, "_conectar_imap_cuenta", lambda c: imap)
    assert correo.crear_carpeta(uid, cuenta, "Facturas 2026") == "Facturas 2026"
    assert correo.crear_carpeta(uid, cuenta, "Q1", dentro_de="Facturas 2026") == "Facturas 2026/Q1"
    assert imap.llamadas == [("create", '"Facturas 2026"'), ("create", '"Facturas 2026/Q1"')]
    assert {"Facturas 2026", "Facturas 2026/Q1"} <= {c["nombre"] for c in correo.listar_carpetas(uid, cuenta)}
    m = _msg(cuenta, carpeta="Facturas 2026/Q1")
    assert correo.renombrar_carpeta(uid, cuenta, "Facturas 2026", "Facturas") == "Facturas"
    assert imap.llamadas[-1] == ("rename", '"Facturas 2026"', '"Facturas"')
    assert {"Facturas", "Facturas/Q1"} <= {c["nombre"] for c in correo.listar_carpetas(uid, cuenta)} and "Facturas 2026" not in {c["nombre"] for c in correo.listar_carpetas(uid, cuenta)}
    assert correo.obtener_mensaje(m)["carpeta"] == "Facturas/Q1"
    correo.eliminar_carpeta(uid, cuenta, "Facturas/Q1")
    assert imap.llamadas[-1] == ("delete", '"Facturas/Q1"') and correo.obtener_mensaje(m) is None
    assert "Facturas/Q1" not in {c["nombre"] for c in correo.listar_carpetas(uid, cuenta)}


def test_carpetas_del_sistema_duplicadas_y_servidor_que_rechaza(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "car-2@ejemplo.com")
    imap = _Imap(); monkeypatch.setattr(correo, "_conectar_imap_cuenta", lambda c: imap)
    for sistema in ("INBOX", "Archive", "Junk"):
        with pytest.raises(ErrorCorreo, match="sistema"):
            correo.renombrar_carpeta(uid, cuenta, sistema, "Otra")
        with pytest.raises(ErrorCorreo, match="sistema"):
            correo.eliminar_carpeta(uid, cuenta, sistema)
    with pytest.raises(ErrorCorreo, match="Ya existe"):
        correo.crear_carpeta(uid, cuenta, "Clientes")
    with pytest.raises(ErrorCorreo, match="no existe"):
        correo.eliminar_carpeta(uid, cuenta, "Inventada")
    assert imap.llamadas == []
    imap.ok = False
    with pytest.raises(ErrorCorreo, match="no ha aceptado"):
        correo.crear_carpeta(uid, cuenta, "Nueva")
    assert "Nueva" not in {c["nombre"] for c in correo.listar_carpetas(uid, cuenta)}


def test_las_cuentas_pop3_no_tienen_carpetas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "car-3@ejemplo.com", "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "P", "pop3", "pop.ejemplo.com", 995, "yo@ejemplo.com")
    with pytest.raises(ErrorCorreo, match="POP3"):
        correo.crear_carpeta(uid, cuenta, "X")


def test_archivar_y_spam_mueven_a_la_carpeta_de_la_cuenta(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "car-4@ejemplo.com")
    movidos = []
    monkeypatch.setattr(correo, "mover_mensaje", lambda u, m, c: movidos.append((m, c)))
    m = _msg(cuenta)
    r = cliente.post(f"/correo/{m}/archivar")
    assert r.status_code == 302 and movidos == [(m, "Archive")] and "aviso=" in r.headers["Location"]
    cliente.post(f"/correo/{m}/spam")
    assert movidos[-1] == (m, "Junk")


def test_no_es_spam_devuelve_a_la_bandeja_y_sin_carpeta_avisa(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "car-5@ejemplo.com", carpetas=("INBOX", "Junk"))
    movidos = []
    monkeypatch.setattr(correo, "mover_mensaje", lambda u, m, c: movidos.append((m, c)))
    en_spam = _msg(cuenta, "7", carpeta="Junk")
    cliente.post(f"/correo/{en_spam}/spam")
    assert movidos == [(en_spam, "INBOX")]
    normal = _msg(cuenta, "8")
    r = cliente.post(f"/correo/{normal}/archivar")                      # esta cuenta no tiene carpeta de archivo
    assert "aviso=" in r.headers["Location"] and len(movidos) == 1


def test_ruta_de_carpetas_y_mensajes_ajenos_dan_404(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "car-6@ejemplo.com")
    assert cliente.post("/correo/carpetas/crear", data={"cuenta_id": "99999", "nombre": "X"}).status_code == 404
    assert cliente.post("/correo/99999/archivar").status_code == 404
    imap = _Imap(); monkeypatch.setattr(correo, "_conectar_imap_cuenta", lambda c: imap)
    r = cliente.post("/correo/carpetas/crear", data={"cuenta_id": str(cuenta), "nombre": "Proyectos"})
    assert r.status_code == 302 and "Proyectos" in r.headers["Location"] and ("create", '"Proyectos"') in imap.llamadas
    r = cliente.post("/correo/carpetas/crear", data={"cuenta_id": str(cuenta), "nombre": "a/b"})
    assert "aviso=" in r.headers["Location"] and len(imap.llamadas) == 1


def test_respuesta_rapida_envia_con_texto_y_cita(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "car-7@ejemplo.com")
    conn = db.get_connection(); conn.execute("UPDATE correo_cuentas SET smtp_host = 'smtp.ejemplo.com', smtp_puerto = 587 WHERE id = ?", (cuenta,)); conn.commit(); conn.close()
    db.guardar_preferencias_correo(uid, "normal", True, 50, deshacer_segundos=0)
    enviados = []
    monkeypatch.setattr(correo, "construir_y_enviar", lambda u, c, dest, asunto, cuerpo, **kw: enviados.append((dest, asunto, cuerpo, kw)))
    m = _msg(cuenta)
    r = cliente.post(f"/correo/{m}/respuesta-rapida", data={"cuerpo": "Recibido, gracias."})
    assert r.status_code == 302 and len(enviados) == 1
    dest, asunto, cuerpo, kw = enviados[0]
    assert dest == "ana@b.com" and asunto == "Re: Hola" and "Recibido, gracias." in cuerpo and "escribió" in cuerpo
    r = cliente.post(f"/correo/{m}/respuesta-rapida", data={"cuerpo": "  "})
    assert len(enviados) == 1 and "aviso=" in r.headers["Location"]


def test_la_bandeja_muestra_archivar_gestion_y_respuesta_rapida(cliente):
    uid, cuenta = _cuenta(cliente, "car-8@ejemplo.com")
    conn = db.get_connection(); conn.execute("UPDATE correo_cuentas SET smtp_host = 'smtp.ejemplo.com' WHERE id = ?", (cuenta,)); conn.commit(); conn.close()
    m = _msg(cuenta)
    html = cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    assert "/archivar" in html and "Gestionar carpetas" in html and "correo-respuesta-rapida" in html and 'data-carpeta="Archive"' in html


@pytest.mark.parametrize("nombre,visible", [("INBOX", "Bandeja de entrada"), ("INBOX.Sent", "Enviados"), ("INBOX.Hunter", "Hunter"), ("INBOX.Trash", "Papelera"),
                                            ("Clientes/2026", "2026"), ("[Gmail]/Spam", "Spam"), ("Facturas 2.0", "Facturas 2.0")])
def test_el_nombre_visible_quita_el_prefijo_inbox_de_los_servidores_con_punto(nombre, visible):
    assert correo._nombre_visible_carpeta(nombre) == visible

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


# --- Remitentes bloqueados -----------------------------------------------------------------------------------------------------------------------

def _crudo(de="Spam <spam@malo.test>", asunto="Oferta"):
    from email.message import EmailMessage
    m = EmailMessage(); m["From"], m["To"], m["Subject"], m["Message-ID"] = de, "yo@ejemplo.com", asunto, "<s1@malo.test>"; m.set_content("compra"); return m.as_bytes()


def test_bloquear_remitente_manda_el_mensaje_a_la_papelera_y_recuerda_la_direccion(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "blo-1@ejemplo.com")
    ops = []
    monkeypatch.setattr(correo, "_encolar_y_lanzar", lambda m, op: ops.append((m["id"], op)))
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Oferta", remitente="Spam <Spam@Malo.test>", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    assert correo.bloquear_remitente(uid, m) == "spam@malo.test"
    assert ops == [(m, "eliminar")] and correo.obtener_mensaje(m) is None
    assert [b["patron"] for b in db.listar_bloqueados_correo(uid)] == ["spam@malo.test"]


def test_bloquear_el_dominio_y_los_mensajes_nuevos_van_a_la_papelera_sin_contar_como_no_leidos(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "blo-2@ejemplo.com")
    ops = []
    monkeypatch.setattr(correo, "_encolar_y_lanzar", lambda m, op: ops.append((m["uid"], op)))
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Oferta", remitente="a@malo.test", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    assert correo.bloquear_remitente(uid, m, dominio=True) == "@malo.test"
    fila = db.obtener_cuenta_correo(uid, cuenta)
    assert correo._guardar_mensaje_imap(fila, "INBOX", "20", _crudo(), set()) == (None, True)
    assert ("20", "eliminar") in ops and db.listar_mensajes_correo(cuenta) == []
    # otro remitente, otra carpeta y quien no está bloqueado siguen entrando
    ok, _ = correo._guardar_mensaje_imap(fila, "INBOX", "21", _crudo(de="Ana <ana@bien.test>"), set())
    otra, _ = correo._guardar_mensaje_imap(fila, "Archive", "22", _crudo(), set())
    assert ok is not None and otra is not None


def test_el_bloqueo_es_por_persona_no_de_toda_la_plataforma(cliente):
    uid, cuenta = _cuenta(cliente, "blo-3@ejemplo.com")
    db.bloquear_remitente_correo(uid, "x@malo.test")
    assert db.remitente_bloqueado_correo(uid, "X@malo.test") and not db.remitente_bloqueado_correo(uid + 1, "x@malo.test") and not db.remitente_bloqueado_correo(uid, "y@malo.test")
    assert not db.remitente_bloqueado_correo(uid, None) and not db.remitente_bloqueado_correo(uid, "sin-arroba")


def test_no_se_puede_bloquear_la_propia_direccion_ni_un_mensaje_ajeno(cliente):
    uid, cuenta = _cuenta(cliente, "blo-4@ejemplo.com")
    propio = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Nota", remitente="yo@ejemplo.com", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    with pytest.raises(ErrorCorreo, match="propia"):
        correo.bloquear_remitente(uid, propio)
    with pytest.raises(ErrorCorreo, match="no existe"):
        correo.bloquear_remitente(uid, 99999)
    assert cliente.post("/correo/99999/bloquear").status_code == 404


def test_bloquear_y_desbloquear_desde_la_web(cliente, monkeypatch):
    uid, cuenta = _cuenta(cliente, "blo-5@ejemplo.com")
    monkeypatch.setattr(correo, "_encolar_y_lanzar", lambda m, op: None)
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="Oferta", remitente="a@malo.test", destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="x", cuerpo_html=None)
    assert "/bloquear" in cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    r = cliente.post(f"/correo/{m}/bloquear")
    assert r.status_code == 302 and "aviso=" in r.headers["Location"]
    html = cliente.get("/correo/ajustes").get_data(as_text=True)
    assert "a@malo.test" in html and "Remitentes bloqueados" in html
    (b,) = db.listar_bloqueados_correo(uid)
    cliente.post(f"/correo/ajustes/bloqueados/{b['id']}/eliminar")
    assert db.listar_bloqueados_correo(uid) == []


# --- Vistas globales: destacados y no leídos de todas las carpetas --------------------------------------------------------------------------------

def test_la_vista_global_junta_carpetas_y_deja_fuera_papelera_spam_y_borradores(cliente):
    uid, cuenta = _cuenta(cliente, "glo-1@ejemplo.com", carpetas=("INBOX", "Archive", "Junk", "Trash", "Drafts", "Clientes"))
    def msg(n, carpeta, leido=0, destacado=0):
        m = _msg(cuenta, str(n), carpeta=carpeta)
        conn = db.get_connection(); conn.execute("UPDATE correo_mensajes SET leido = ?, destacado = ? WHERE id = ?", (leido, destacado, m)); conn.commit(); conn.close(); return m
    a, b, c, d = msg(1, "INBOX"), msg(2, "Clientes"), msg(3, "Junk"), msg(4, "Trash")
    e = msg(5, "Archive", leido=1, destacado=1)
    ids = lambda **kw: {x["id"] for x in db.listar_mensajes_correo(cuenta, carpeta="*", **kw)}
    assert ids(solo_no_leidos=True) == {a, b} and ids(solo_destacados=True) == {e}
    assert {x["id"] for x in db.listar_mensajes_correo(cuenta, carpeta="Junk", solo_no_leidos=True)} == {c}      # la carpeta concreta sigue igual


def test_la_bandeja_ofrece_y_muestra_las_vistas_globales(cliente):
    uid, cuenta = _cuenta(cliente, "glo-2@ejemplo.com")
    m = _msg(cuenta, "1", carpeta="Clientes")
    html = cliente.get(f"/correo/?cuenta_id={cuenta}").get_data(as_text=True)
    assert "carpeta=%2A" in html or "carpeta=*" in html
    r = cliente.get(f"/correo/?cuenta_id={cuenta}&carpeta=*&no_leidos=1").get_data(as_text=True)
    assert "Hola" in r and f"mensaje_id={m}" in r

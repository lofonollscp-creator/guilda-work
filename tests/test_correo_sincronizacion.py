"""Sincronización IMAP en ambos sentidos: estado leído/destacado del servidor, borrados,
cambios hechos aquí que se reflejan allí (cola de operaciones), papelera, UIDVALIDITY,
descarga acotada de buzones grandes y salvaguardas."""
import imaplib
from datetime import datetime, timedelta

import pytest

from app import correo, db
from tests.imap_falso import ServidorIMAP


@pytest.fixture(autouse=True)
def _estado_de_sincronizacion(monkeypatch):
    monkeypatch.setattr(correo, "_SIN_SEGUNDO_PLANO", True)   # las operaciones se aplican a mano, de forma determinista
    correo._omitidos.clear()
    yield
    correo._omitidos.clear()


def _montar(monkeypatch, usuario_id, servidor: ServidorIMAP, protocolo: str = "imap") -> int:
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda host, port, timeout=None: servidor.conexion())
    return correo.guardar_cuenta(
        usuario_id, nombre="Trabajo", protocolo=protocolo, host="imap.ejemplo.com", puerto=993,
        usuario="yo@ejemplo.com", contrasena="correcta",
    )


def _sync(usuario_id, cuenta_id):
    return correo.sincronizar_bandeja(usuario_id, cuenta_id)


def _msg(cuenta_id, uid, carpeta="INBOX"):
    return db.mensaje_correo_por_uid(cuenta_id, carpeta, str(uid))


# --- estado que ya trae el servidor ----------------------------------------------------------

def test_los_mensajes_llegan_con_su_estado_y_descargarlos_no_los_marca_como_leidos(monkeypatch, usuario_id):
    s = ServidorIMAP()
    leido = s.anadir("INBOX", "Ya leído", flags=("\\Seen",))
    nuevo = s.anadir("INBOX", "Sin leer")
    destacado = s.anadir("INBOX", "Importante", flags=("\\Flagged",))
    cuenta = _montar(monkeypatch, usuario_id, s)
    assert _sync(usuario_id, cuenta) == {"nuevos": 3}
    assert (_msg(cuenta, leido)["leido"], _msg(cuenta, nuevo)["leido"], _msg(cuenta, destacado)["destacado"]) == (1, 0, 1)
    assert "\\seen" not in s.flags("INBOX", nuevo)   # BODY.PEEK: bajar el correo no lo marca como leído en el servidor
    assert not any("RFC822" in str(a) for a in s.comandos("uid_fetch"))


def test_solo_se_notifica_lo_que_es_nuevo_de_verdad(monkeypatch, usuario_id):
    s = ServidorIMAP()
    for i in range(5):
        s.anadir("INBOX", f"Historial {i}", flags=("\\Seen",))
    cuenta = _montar(monkeypatch, usuario_id, s)
    avisos = []
    monkeypatch.setattr(correo, "_emitir_evento_correo_nuevo", lambda u, c, n: avisos.append(n))
    _sync(usuario_id, cuenta)
    assert avisos == []                      # el historial ya leído no genera "5 correos nuevos"
    s.anadir("INBOX", "Este sí es nuevo")
    s.anadir("INBOX", "Y este", flags=("\\Seen",))
    _sync(usuario_id, cuenta)
    assert avisos == [1]


def test_el_servidor_pone_la_bandera_tras_el_literal_o_en_la_cabecera(monkeypatch, usuario_id):
    for forma in ("estandar", "tras_literal"):
        s = ServidorIMAP(cola_fetch=forma)
        uid = s.anadir("INBOX", f"Forma {forma}", flags=("\\Seen", "\\Flagged"))
        cuenta = _montar(monkeypatch, usuario_id, s)
        _sync(usuario_id, cuenta)
        m = _msg(cuenta, uid)
        assert (m["leido"], m["destacado"]) == (1, 1), forma
        db.eliminar_cuenta_correo(usuario_id, cuenta)


# --- cambios hechos en otro cliente -------------------------------------------------------------

def test_lo_que_se_marca_en_otro_cliente_se_refleja_aqui(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Del móvil")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uid)["leido"] == 0
    s.poner_flags("INBOX", uid, "\\Seen", "\\Flagged")      # lo lee y lo destaca en el móvil
    resumen = correo._sincronizar_imap(db.obtener_cuenta_correo(usuario_id, cuenta))
    assert resumen["estados"] == 1
    assert (_msg(cuenta, uid)["leido"], _msg(cuenta, uid)["destacado"]) == (1, 1)
    s.poner_flags("INBOX", uid)                              # y lo vuelve a dejar sin leer ni destacar
    _sync(usuario_id, cuenta)
    assert (_msg(cuenta, uid)["leido"], _msg(cuenta, uid)["destacado"]) == (0, 0)


def test_lo_que_se_borra_en_el_servidor_desaparece_de_aqui(monkeypatch, usuario_id):
    s = ServidorIMAP()
    a, b, c = (s.anadir("INBOX", f"M{i}") for i in range(3))
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    s.borrar("INBOX", b)
    resumen = correo._sincronizar_imap(db.obtener_cuenta_correo(usuario_id, cuenta))
    assert resumen["borrados"] == 1
    assert _msg(cuenta, b) is None and _msg(cuenta, a) is not None and _msg(cuenta, c) is not None


def test_ventana_de_recientes_y_pasada_completa(monkeypatch, usuario_id):
    """Lo reciente se comprueba en cada pasada; lo antiguo, en la pasada completa de cada hora."""
    monkeypatch.setattr(correo, "VENTANA_RECIENTES", 3)
    s = ServidorIMAP()
    uids = [s.anadir("INBOX", f"M{i}") for i in range(6)]
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    s.borrar("INBOX", uids[0])         # antiguo (fuera de la ventana)
    s.borrar("INBOX", uids[5])         # reciente (dentro)
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uids[5]) is None and _msg(cuenta, uids[0]) is not None
    db.guardar_estado_carpeta_correo(cuenta, "INBOX", ultima_pasada_completa=(datetime.now() - timedelta(hours=2)).isoformat())
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uids[0]) is None


def test_salvaguarda_no_borra_nada_si_la_busqueda_no_cuadra_con_el_servidor(monkeypatch, usuario_id):
    s = ServidorIMAP()
    for i in range(4):
        s.anadir("INBOX", f"M{i}")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    conexion_original = s.conexion

    def conexion_con_busqueda_vacia(*a, **k):
        c = conexion_original()
        buscar = c.uid
        c.uid = lambda comando, *args: ("OK", [b""]) if comando == "search" else buscar(comando, *args)
        return c
    s.conexion = conexion_con_busqueda_vacia
    db.guardar_estado_carpeta_correo(cuenta, "INBOX", ultima_pasada_completa=None)   # fuerza pasada completa
    _sync(usuario_id, cuenta)
    assert len(db.uids_existentes_correo(cuenta, "INBOX")) == 4


# --- cambios hechos aquí hacia el servidor -----------------------------------------------------------

def test_marcar_leido_y_destacar_aqui_llega_al_servidor(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Para leer")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    mensaje = _msg(cuenta, uid)["id"]
    correo.marcar_leido(mensaje, True)
    correo.destacar_mensaje(mensaje, True)
    assert len(db.operaciones_pendientes_correo(cuenta)) == 2
    assert correo.procesar_operaciones_cuenta(cuenta) == {"hechas": 2, "fallidas": 0}
    assert {"\\seen", "\\flagged"} <= s.flags("INBOX", uid)
    assert db.operaciones_pendientes_correo(cuenta) == []
    correo.marcar_leido(mensaje, False)
    correo.destacar_mensaje(mensaje, False)
    correo.procesar_operaciones_cuenta(cuenta)
    assert not ({"\\seen", "\\flagged"} & s.flags("INBOX", uid))


def test_un_cambio_pendiente_no_lo_pisa_la_sincronizacion_de_entrada(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Recién leído aquí")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    mensaje = _msg(cuenta, uid)["id"]
    correo.marcar_leido(mensaje, True)                  # aquí leído, el servidor aún no lo sabe
    correo._sincronizar_carpeta_imap(s.conexion(), db.obtener_cuenta_correo(usuario_id, cuenta), "INBOX")
    assert _msg(cuenta, uid)["leido"] == 1              # no vuelve a "sin leer" por el estado antiguo del servidor
    _sync(usuario_id, cuenta)                           # la sincronización completa aplica primero lo pendiente
    assert "\\seen" in s.flags("INBOX", uid) and _msg(cuenta, uid)["leido"] == 1


def test_marcar_y_desmarcar_seguidos_se_reducen_a_la_ultima_orden(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Indeciso")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    mensaje = _msg(cuenta, uid)["id"]
    for leido in (True, False, True, False):
        correo.marcar_leido(mensaje, leido)
    correo.procesar_operaciones_cuenta(cuenta)
    assert len(s.comandos("uid_store")) == 1 and "\\seen" not in s.flags("INBOX", uid)


def test_eliminar_va_a_la_papelera_del_servidor_y_no_vuelve(monkeypatch, usuario_id):
    s = ServidorIMAP(carpetas=("INBOX",), papelera="Trash")
    uid = s.anadir("INBOX", "Basura")
    otro = s.anadir("INBOX", "Se queda")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    correo.eliminar_mensaje(_msg(cuenta, uid)["id"])
    assert _msg(cuenta, uid) is None
    correo.procesar_operaciones_cuenta(cuenta)
    assert s.uids("INBOX") == [otro]                                    # fuera de la bandeja del servidor
    assert [m["crudo"] for m in s.carpetas["Trash"].mensajes.values()]  # y en la papelera
    assert s.comandos("uid_expunge") == [(str(uid),)]                   # UIDPLUS: solo ese mensaje
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uid) is None and len(db.uids_existentes_correo(cuenta, "INBOX")) == 1


def test_eliminar_sin_uidplus_usa_expunge_y_sin_papelera_borra_de_verdad(monkeypatch, usuario_id):
    s = ServidorIMAP(carpetas=("INBOX",), uidplus=False)
    uid = s.anadir("INBOX", "Adiós")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    correo.eliminar_mensaje(_msg(cuenta, uid)["id"])
    correo.procesar_operaciones_cuenta(cuenta)
    assert s.uids("INBOX") == [] and s.comandos("expunge") and not s.comandos("uid_copy")


def test_el_mensaje_que_se_esta_borrando_no_se_vuelve_a_descargar(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Borrando")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    s.fallar["uid_store"] = "NO"                      # el servidor rechaza el borrado
    correo.eliminar_mensaje(_msg(cuenta, uid)["id"])
    correo.procesar_operaciones_cuenta(cuenta)
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uid) is None                  # la operación sigue pendiente: no reaparece
    assert db.operaciones_pendientes_correo(cuenta)[0]["intentos"] >= 1
    del s.fallar["uid_store"]
    _sync(usuario_id, cuenta)                         # al volver el servidor, se aplica
    assert s.uids("INBOX") == []


def test_una_operacion_que_siempre_falla_pasa_a_error_tras_cinco_intentos(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Terco")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    s.fallar["uid_store"] = "NO"
    correo.marcar_leido(_msg(cuenta, uid)["id"], True)
    for _ in range(db.MAX_INTENTOS_OPERACION_CORREO):
        correo.procesar_operaciones_cuenta(cuenta)
    assert db.operaciones_pendientes_correo(cuenta) == [] and db.contar_operaciones_correo_con_error(usuario_id) == 1


def test_si_la_conexion_se_cae_a_mitad_el_resto_queda_para_despues(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uids = [s.anadir("INBOX", f"M{i}") for i in range(3)]
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    for u in uids:
        correo.marcar_leido(_msg(cuenta, u)["id"], True)
    s.fallar["uid_store"] = "abort"
    correo.procesar_operaciones_cuenta(cuenta)
    assert len(db.operaciones_pendientes_correo(cuenta)) == 3
    del s.fallar["uid_store"]
    correo.procesar_operaciones_cuenta(cuenta)
    assert db.operaciones_pendientes_correo(cuenta) == [] and all("\\seen" in s.flags("INBOX", u) for u in uids)


def test_cuentas_pop3_no_generan_operaciones(monkeypatch, usuario_id):
    cuenta = db.crear_cuenta_correo(usuario_id, "Antigua", "pop3", "pop.ejemplo.com", 995, "yo@ejemplo.com")
    m = db.guardar_mensaje_correo(cuenta_id=cuenta, uid="1", asunto="x", remitente="a@b.com", destinatarios="yo@ejemplo.com",
                                  fecha="2026-03-10T10:00:00", cuerpo_texto="c", cuerpo_html=None)
    correo.marcar_leido(m, True)
    correo.destacar_mensaje(m, True)
    correo.eliminar_mensaje(m)
    assert db.operaciones_pendientes_correo(cuenta) == []


def test_las_reglas_automaticas_tambien_llegan_al_servidor(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Boletín", remitente="news@boletin.com")
    cuenta = _montar(monkeypatch, usuario_id, s)
    db.crear_regla_correo(usuario_id, remitente_patron="news@boletin.com", marcar_leido=True)
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uid)["leido"] == 1 and len(db.operaciones_pendientes_correo(cuenta)) == 1
    correo.procesar_operaciones_cuenta(cuenta)
    assert "\\seen" in s.flags("INBOX", uid)


# --- UIDVALIDITY, descarga acotada y robustez --------------------------------------------------------------

def test_si_cambia_el_uidvalidity_se_vuelve_a_descargar_la_carpeta(monkeypatch, usuario_id):
    s = ServidorIMAP()
    s.anadir("INBOX", "Antes")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    correo.marcar_leido(_msg(cuenta, 1)["id"], True)           # operación pendiente sobre UIDs que van a dejar de valer
    c = s.carpetas["INBOX"]
    c.uidvalidity = 2000
    c.mensajes = {}
    c.siguiente = 1
    s.anadir("INBOX", "Después")
    _sync(usuario_id, cuenta)
    assert [m["asunto"] for m in correo.listar_mensajes(cuenta)] == ["Después"]
    assert db.operaciones_pendientes_correo(cuenta) == []
    assert db.estado_carpeta_correo(cuenta, "INBOX")["uidvalidity"] == "2000"


def test_un_buzon_grande_se_baja_por_tandas_empezando_por_lo_mas_reciente(monkeypatch, usuario_id):
    monkeypatch.setattr(correo, "DESCARGAS_POR_CICLO", 5)
    s = ServidorIMAP()
    for i in range(12):
        s.anadir("INBOX", f"M{i + 1}")
    cuenta = _montar(monkeypatch, usuario_id, s)
    assert _sync(usuario_id, cuenta) == {"nuevos": 5}
    assert sorted(int(u) for u in db.uids_existentes_correo(cuenta, "INBOX")) == [8, 9, 10, 11, 12]   # lo reciente primero
    assert db.estado_carpeta_correo(cuenta, "INBOX")["descarga_pendiente"] == 1
    assert _sync(usuario_id, cuenta) == {"nuevos": 5}
    assert _sync(usuario_id, cuenta) == {"nuevos": 2}
    assert len(db.uids_existentes_correo(cuenta, "INBOX")) == 12 and db.estado_carpeta_correo(cuenta, "INBOX")["descarga_pendiente"] == 0
    assert _sync(usuario_id, cuenta) == {"nuevos": 0}


def test_el_correo_nuevo_se_baja_aunque_haya_historial_pendiente(monkeypatch, usuario_id):
    monkeypatch.setattr(correo, "DESCARGAS_POR_CICLO", 3)
    s = ServidorIMAP()
    for i in range(8):
        s.anadir("INBOX", f"Viejo {i}")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    nuevo = s.anadir("INBOX", "Recién llegado")
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, nuevo) is not None


def test_un_mensaje_que_el_servidor_no_entrega_no_bloquea_la_carpeta(monkeypatch, usuario_id):
    s = ServidorIMAP()
    a = s.anadir("INBOX", "Bueno")
    roto = s.anadir("INBOX", "Roto")
    s.carpetas["INBOX"].mensajes[roto]["crudo"] = b""    # el servidor lo devuelve vacío
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, a) is not None
    _sync(usuario_id, cuenta)
    assert db.estado_carpeta_correo(cuenta, "INBOX")["descarga_pendiente"] == 0
    assert len(s.comandos("uid_fetch")) < 12             # no se reintenta sin parar


def test_borrar_localmente_un_mensaje_con_tarea_enlazada_no_rompe_la_sincronizacion(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "Con tarea")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    mensaje = _msg(cuenta, uid)["id"]
    tarea = db.crear_tarea_outlook(usuario_id, "Seguimiento")
    conn = db.get_connection()
    conn.execute("UPDATE tareas_outlook SET mensaje_correo_id = ? WHERE id = ?", (mensaje, tarea))
    conn.commit()
    conn.close()
    s.borrar("INBOX", uid)
    _sync(usuario_id, cuenta)
    assert _msg(cuenta, uid) is None and db.obtener_tarea_outlook(usuario_id, tarea) is not None


def test_borrar_la_cuenta_borra_sus_operaciones(monkeypatch, usuario_id):
    s = ServidorIMAP()
    uid = s.anadir("INBOX", "X")
    cuenta = _montar(monkeypatch, usuario_id, s)
    _sync(usuario_id, cuenta)
    correo.marcar_leido(_msg(cuenta, uid)["id"], True)
    db.eliminar_cuenta_correo(usuario_id, cuenta)
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM correo_operaciones").fetchone()[0] == 0
    conn.close()


# --- interpretación de las respuestas de FETCH -----------------------------------------------------------------

def test_parsear_fetch_formas_reales():
    dos_lineas = [b"1 (UID 4 FLAGS (\\Seen \\Flagged))", b"2 (UID 9 FLAGS ())"]
    r = correo._parsear_fetch(dos_lineas)
    assert [(x["uid"], x["flags"]) for x in r] == [(4, {"\\seen", "\\flagged"}), (9, set())]
    con_literal = [(b"1 (UID 7 FLAGS (\\Seen) BODY[] {3}", b"abc"), b")", (b"2 (UID 8 BODY[] {3}", b"xyz"), b" FLAGS (\\Flagged))"]
    r = correo._parsear_fetch(con_literal)
    assert [(x["uid"], x["flags"], x["crudo"]) for x in r] == [(7, {"\\seen"}, b"abc"), (8, {"\\flagged"}, b"xyz")]
    assert correo._parsear_fetch([None]) == [] and correo._parsear_fetch([]) == [] and correo._parsear_fetch(None) == []
    mayusculas = [b"3 (uid 12 flags (\\SEEN))"]
    assert correo._parsear_fetch(mayusculas)[0]["flags"] == {"\\seen"}

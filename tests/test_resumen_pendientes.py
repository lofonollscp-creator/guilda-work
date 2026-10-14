"""Resumen diario de pendientes de cada persona (app/resumen_pendientes.py): qué reúne, que no cuente dos veces, que no revele lo protegido,
cuándo se entrega (opt-in, hora, entre semana, una vez al día) y que llegue a la campana y al email."""
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from app import cifrado_despacho as cd
from app import correo, correo_cifrado as cc, db, inmobiliaria, notificaciones_email, nucleo, resumen_pendientes as rp, verticales

HOY = date.today()
FRASE = "una frase de paso larga y segura"


def _a(dias, hora):
    return format_datetime(datetime.combine(HOY - timedelta(days=dias), datetime.min.time()).replace(hour=hora).astimezone())


def _crudo(asunto, de, msgid, fecha=None, en_respuesta_a=None, para="yo@despacho.com"):
    fecha = fecha or _a(0, 8)
    m = EmailMessage()
    m["Subject"], m["From"], m["To"], m["Message-ID"], m["Date"] = asunto, de, para, msgid, fecha
    if en_respuesta_a:
        m["In-Reply-To"] = en_respuesta_a
    m.set_content("cuerpo")
    return bytes(m)


class Equipo:
    def __init__(self):
        self.t = db.crear_tenant("Despacho Resumen")
        self.u = db.crear_usuario_vinculado_a_kratos("resumen@ejemplo.com", "k-resumen")
        db.asignar_tenant(self.u, self.t); db.asignar_supervisor_tenant(self.u, True)
        self.cuenta_id = db.crear_cuenta_correo(self.u, "Trabajo", "imap", "h", 993, "yo@despacho.com")
        self.n = 0

    def recibe(self, asunto="Duda sobre el IVA", de="Marta <marta@cliente.com>", msgid=None, **kw):
        self.n += 1
        cuenta = db.obtener_cuenta_correo(self.u, self.cuenta_id)
        mid, _ = correo._guardar_mensaje_imap(cuenta, "INBOX", str(self.n), _crudo(asunto, de, msgid or f"<m{self.n}@x>", **kw), set())
        return mid

    def envia(self, asunto, en_respuesta_a, msgid, fecha=None):
        fecha = fecha or _a(0, 9)
        self.n += 1
        cuenta = db.obtener_cuenta_correo(self.u, self.cuenta_id)
        correo._guardar_mensaje_imap(cuenta, "Sent", str(self.n), _crudo(asunto, "yo@despacho.com", msgid, fecha, en_respuesta_a, para="marta@cliente.com"), set())


@pytest.fixture
def eq(usuario_id):
    return Equipo()


def test_reune_tareas_visitas_plazos_vencimientos_y_correos(eq):
    verticales.fijar_activo(eq.t, "inmobiliaria", True)
    db.crear_tarea_outlook(eq.u, "Llamar al banco", fecha_vencimiento=HOY.isoformat())
    db.crear_tarea_outlook(eq.u, "Enviar el modelo 111", fecha_vencimiento=(HOY - timedelta(days=5)).isoformat())
    propietario = nucleo.crear_cliente(eq.t, "Propietaria")
    inm, _ = inmobiliaria.crear_inmueble(eq.t, eq.u, propietario, "venta", "Calle Mayor 5", municipio="Girona")
    inmobiliaria.crear_visita(eq.t, eq.u, inm, HOY.isoformat() + "T17:30", visitante="Pere Soler", supervisor=True)
    nucleo.crear_plazo(eq.t, eq.u, "Presentar alegaciones", (HOY + timedelta(days=1)).isoformat(), responsable_id=eq.u, supervisor=True)
    nucleo.crear_plazo(eq.t, eq.u, "Plazo lejano", (HOY + timedelta(days=60)).isoformat(), responsable_id=eq.u, supervisor=True)
    cf = db.crear_cliente_fiscal(eq.t, "Cliente Fiscal SL")
    db.crear_vencimiento_fiscal(eq.t, cf, "303", "3T", (HOY + timedelta(days=2)).isoformat(), usuario_id=eq.u)
    eq.recibe()
    r = rp.reunir(eq.u, HOY)
    assert [t["titulo"] for t in r["tareas_hoy"]] == ["Llamar al banco"], "la tarea automática de la visita no se cuenta dos veces"
    assert [t["titulo"] for t in r["tareas_vencidas"]] == ["Enviar el modelo 111"]
    assert [(v["hora"], v["direccion"], v["visitante"]) for v in r["visitas_hoy"]] == [("17:30", "Calle Mayor 5", "Pere Soler")]
    assert [z["titulo"] for z in r["plazos"]] == ["Presentar alegaciones"] and r["plazos"][0]["estado"] == "proximo"
    assert [(v["modelo"], v["cliente"]) for v in r["vencimientos"]] == [("303", "Cliente Fiscal SL")]
    assert [c["asunto"] for c in r["correos_sin_contestar"]] == ["Duda sobre el IVA"]
    titulo, corto, lineas = rp.redactar(r)
    assert titulo.startswith("Tu día: 6 pendientes") and "1 visitas" in corto
    texto = "\n".join(lineas)
    assert "17:30 · Calle Mayor 5 · Pere Soler" in texto and "mañana" in texto
    assert "1 correo sin contestar" in texto and "Duda sobre el IVA" not in texto, "el correo se resume, no se enumera"


def test_sin_modulo_no_hay_visitas_ni_plazos_de_otros_modulos(eq):
    r = rp.reunir(eq.u, HOY)
    assert r["visitas_hoy"] == [] and rp.total(r) == 0


def test_un_correo_contestado_o_automatico_no_cuenta(eq):
    eq.recibe("Pregunta contestada", msgid="<q1@x>")
    eq.envia("Re: Pregunta contestada", "<q1@x>", "<r1@despacho>")
    eq.recibe("Alta de servicio", de="No Reply <noreply@banco.com>")
    eq.recibe("Sin contestar todavía", de="Joan <joan@x.com>")
    eq.recibe("Antiguo", de="Anna <anna@x.com>", fecha=_a(30, 8))
    assert [c["asunto"] for c in rp.correos_sin_contestar(eq.u, HOY)] == ["Sin contestar todavía"]


def test_el_resumen_no_revela_asunto_ni_remitente_sellados(eq, monkeypatch):
    monkeypatch.setattr(cd, "ARGON2", {"time_cost": 1, "memory_cost": 8, "parallelism": 1})
    cc.olvidar_configuracion(); cc.olvidar(None)
    cd.activar(eq.t, eq.u, FRASE, "estricto")
    cc.activar(eq.t, eq.u, "estricto")
    eq.recibe("Asunto muy reservado QZ7", de="Marta Secreta <marta@secreto.com>")
    cd.bloquear(eq.t)                                    # como en el hilo de fondo: sin la clave del despacho
    r = rp.reunir(eq.u, HOY)
    assert len(r["correos_sin_contestar"]) == 1 and r["correos_sin_contestar"][0]["protegido"]
    titulo, corto, lineas = rp.redactar(r)
    todo = "\n".join([titulo, corto, *lineas])
    assert "1 correo sin contestar" in todo and "QZ7" not in todo and "secreto.com" not in todo and "Marta" not in todo
    _, plano, html = rp.construir_correo(eq.u, r)
    assert "QZ7" not in plano + html and "secreto.com" not in plano + html and "Marta" not in plano + html
    cc.olvidar_configuracion(); cc.olvidar(None)


class _Salida:
    def __init__(self, monkeypatch):
        self.correos = []
        monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
        monkeypatch.setattr(notificaciones_email, "_enviar", lambda d, a, c, h=None: self.correos.append((d, a, c, h)))


def test_entregar_llega_a_la_campana_y_al_email(eq, monkeypatch):
    salida = _Salida(monkeypatch)
    db.crear_tarea_outlook(eq.u, "Llamar al banco", fecha_vencimiento=date.today().isoformat())
    res = rp.entregar(eq.u)
    assert res == {"enviado": True, "email": True, "pendientes": 1}
    assert [n["tipo"] for n in db.listar_notificaciones(eq.u, 5)] == ["resumen_diario"]
    (destino, asunto, plano, html), = salida.correos
    assert destino == "resumen@ejemplo.com" and asunto.startswith("Tu día: 1 pendiente") and "Llamar al banco" in plano and "Llamar al banco" in html


def test_sin_pendientes_no_se_envia_nada(eq, monkeypatch):
    salida = _Salida(monkeypatch)
    assert rp.entregar(eq.u) == {"enviado": False, "motivo": "nada pendiente"}
    assert salida.correos == [] and db.listar_notificaciones(eq.u, 5) == []


def test_sin_email_solo_campana(eq, monkeypatch):
    salida = _Salida(monkeypatch)
    db.crear_tarea_outlook(eq.u, "Algo", fecha_vencimiento="2020-01-01")
    assert rp.entregar(eq.u, por_email=False)["email"] is False and salida.correos == []


def test_solo_se_entrega_a_quien_lo_activo_a_su_hora_entre_semana_y_una_vez(eq, monkeypatch):
    salida = _Salida(monkeypatch)
    otro = db.crear_usuario_vinculado_a_kratos("otro-resumen@ejemplo.com", "k-otro-resumen")
    for u in (eq.u, otro):
        db.crear_tarea_outlook(u, "Pendiente", fecha_vencimiento="2020-01-01")
    db.guardar_perfil_usuario(eq.u, resumen_diario=True, resumen_diario_hora=9, resumen_diario_email=True)
    miercoles = datetime(2026, 10, 14, 8, 30)
    assert rp.entregar_a_quien_toca(miercoles) == 0, "todavía no son las 9"
    assert rp.entregar_a_quien_toca(miercoles.replace(hour=9, minute=5)) == 1, "a su hora, y solo a quien lo activó"
    assert rp.entregar_a_quien_toca(miercoles.replace(hour=11)) == 0, "una vez al día"
    assert [c[0] for c in salida.correos] == ["resumen@ejemplo.com"] and db.listar_notificaciones(otro, 5) == []
    assert rp.entregar_a_quien_toca(datetime(2026, 10, 17, 10, 0)) == 0, "el sábado no"
    assert rp.entregar_a_quien_toca(datetime(2026, 10, 15, 10, 0)) == 1, "al día siguiente, otra vez"


def test_la_hora_se_acota_y_el_perfil_la_guarda(eq):
    db.guardar_perfil_usuario(eq.u, resumen_diario=True, resumen_diario_hora=99, resumen_diario_email=False)
    p = db.obtener_perfil_usuario(eq.u)
    assert (p["resumen_diario"], p["resumen_diario_hora"], p["resumen_diario_email"]) == (1, 20, 0)
    db.guardar_perfil_usuario(eq.u, nombre_mostrado="Ana")
    assert db.obtener_perfil_usuario(eq.u)["resumen_diario"] == 1, "guardar otra cosa no lo apaga"


def test_el_correo_resume_los_mensajes_y_nombra_solo_a_los_importantes(eq):
    for i in range(3):
        eq.recibe(f"Asunto corriente {i}", de=f"Ruido <ruido{i}@x.com>")
    importante = eq.recibe("Urgente: la inspección", de="Marta Puig <marta@cliente.com>")
    conn = db.get_connection(); conn.execute("UPDATE correo_mensajes SET destacado = 1 WHERE id = ?", (importante,)); conn.commit(); conn.close()
    r = rp.reunir(eq.u, HOY)
    assert rp.frase_correos(r["correos_sin_contestar"]) == "4 correos sin contestar · importantes: Marta Puig"
    asunto, plano, html = rp.construir_correo(eq.u, r)
    assert "4 correos sin contestar" in html and "Importantes:" in html and "Marta Puig" in html
    assert "Asunto corriente" not in plano + html and "Urgente: la inspección" not in plano + html and "ruido0@x.com" not in plano + html


def test_el_correo_html_lleva_cifras_secciones_y_escapa(eq):
    db.crear_tarea_outlook(eq.u, "<script>alert(1)</script> Llamar", fecha_vencimiento=HOY.isoformat())
    db.crear_tarea_outlook(eq.u, "Vieja", fecha_vencimiento=(HOY - timedelta(days=2)).isoformat())
    asunto, plano, html = rp.construir_correo(eq.u, rp.reunir(eq.u, HOY))
    assert asunto == "Tu día: 2 pendientes" and "Buenos días" in html and "tareas atrasadas" in html and "tareas para hoy" in html
    assert "<script>" not in html and "&lt;script&gt;" in html and html.count("<table") > 3
    assert plano.startswith("Buenos días") and "Abrir mi día:" in plano


def test_quien_gestiona_ve_las_ausencias_por_aprobar_y_los_demas_no(eq):
    from app import ausencias
    db.asignar_gestor_fichajes(eq.u, True)
    otra = db.crear_usuario_vinculado_a_kratos("pide-resumen@ejemplo.com", "k-pide-resumen"); db.asignar_tenant(otra, eq.t)
    lunes = HOY + timedelta(days=(7 - HOY.weekday()) % 7 or 7)
    ausencias.solicitar(eq.t, otra, "permiso", lunes.isoformat())
    r = rp.reunir(eq.u, HOY)
    assert [x["persona"] for x in r["ausencias_por_aprobar"]] == ["pide-resumen@ejemplo.com"]
    assert "Ausencias por aprobar (1)" in "\n".join(rp.redactar(r)[2]) and "ausencias por aprobar" in rp.construir_correo(eq.u, r)[2]
    assert rp.reunir(otra, HOY)["ausencias_por_aprobar"] == []

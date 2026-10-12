"""Correo cifrado (app/correo_cifrado.py): opcional, con tres niveles, sellado al entrar sin desbloqueo, lectura con clave, búsqueda en memoria, adjuntos, cambio de nivel,
desactivación, rotación, concesiones y paridad entre niveles."""
from email.message import EmailMessage

import pytest

from app import cifrado_despacho as cd
from app import correo, correo_cifrado as cc, db, nucleo

FRASE = "una frase de paso larga y segura"
ASUNTO = "Reclamación del IVA trimestral XJ7"
DE = "Marta Puig <marta@cliente-secreto.com>"
CUERPO = "el cuerpo secreto ZK9 plenilunio del mensaje"
ADJ_NOMBRE = "nomina-QW3.pdf"
ADJ_CONTENIDO = b"%PDF-adjunto-secreto-LM5"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setattr(cd, "ARGON2", {"time_cost": 1, "memory_cost": 8, "parallelism": 1})
    cc.olvidar_configuracion(); cc.olvidar(None)
    yield
    cc.olvidar_configuracion(); cc.olvidar(None)


def crudo(asunto=ASUNTO, de=DE, para="yo@despacho.com", cuerpo=CUERPO, adjunto=True, msgid="<a1@mail.example>", en_respuesta_a=None):
    m = EmailMessage()
    m["Subject"], m["From"], m["To"], m["Message-ID"], m["Date"] = asunto, de, para, msgid, "Mon, 12 Oct 2026 10:00:00 +0200"
    if en_respuesta_a:
        m["In-Reply-To"] = en_respuesta_a
    m.set_content(cuerpo)
    if adjunto:
        m.add_attachment(ADJ_CONTENIDO, maintype="application", subtype="pdf", filename=ADJ_NOMBRE)
    return bytes(m)


class Despacho:
    def __init__(self):
        self.t = db.crear_tenant("Despacho Correo")
        self.u = db.crear_usuario_vinculado_a_kratos("resp-correo@ejemplo.com", "k-resp-correo")
        db.asignar_tenant(self.u, self.t); db.asignar_supervisor_tenant(self.u, True)
        self.cuenta_id = db.crear_cuenta_correo(self.u, "Trabajo", "imap", "h", 993, "yo@despacho.com")
        self.cf = db.crear_cliente_fiscal(self.t, "Cliente Secreto SL")
        self.cat = db.crear_categoria_correo(self.u, "Impuestos", "#336699")
        db.crear_regla_correo(self.u, remitente_patron="marta@cliente-secreto.com", categoria_id=self.cat, cliente_fiscal_id=self.cf)
        self.n = 0

    def entra(self, **kw) -> int:
        self.n += 1
        cuenta = db.obtener_cuenta_correo(self.u, self.cuenta_id)
        mid, _ = correo._guardar_mensaje_imap(cuenta, kw.pop("carpeta", "INBOX"), str(self.n), crudo(**kw), set())
        return mid


def _columnas(mid):
    conn = db.get_connection()
    try:
        return dict(conn.execute("SELECT * FROM correo_mensajes WHERE id = ?", (mid,)).fetchone())
    finally:
        conn.close()


def _con_cifrado(nivel, bloquear=True):
    d = Despacho()
    antes = d.entra(msgid="<antes@x.com>")                 # llega ANTES de activar: se sella al activarlo
    cd.activar(d.t, d.u, FRASE, nivel)
    r = cc.activar(d.t, d.u, nivel)
    despues = d.entra(msgid="<despues@x.com>", asunto="Otro " + ASUNTO)     # llega después, con el despacho desbloqueado
    if bloquear:
        cd.bloquear(d.t)
    return d, antes, despues, r


# --- es opcional ---------------------------------------------------------------------------------------------------------------------------------------
def test_sin_activar_el_correo_va_en_claro_y_nada_cambia(usuario_id):
    d = Despacho()
    mid = d.entra()
    f = _columnas(mid)
    assert f["cifrado"] == 0 and f["asunto"] == ASUNTO and CUERPO in f["cuerpo_texto"] and f["datos"] is None
    assert db.obtener_mensaje_correo(mid)["protegido"] is False
    assert [m["id"] for m in db.listar_mensajes_correo(d.cuenta_id, texto="ZK9")] == [mid]       # índice de texto completo de siempre


def test_para_activar_el_correo_hace_falta_el_cifrado_de_documentos(usuario_id):
    d = Despacho()
    with pytest.raises(ValueError, match="documentos"):
        cc.activar(d.t, d.u)
    cd.activar(d.t, d.u, FRASE)
    cc.activar(d.t, d.u, "medio")
    with pytest.raises(ValueError, match="ya está activado"):
        cc.activar(d.t, d.u)


# --- qué queda en claro según el nivel -----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("nivel,asunto_claro,remitente_claro,asoc_claras", [("laxo", True, True, True), ("medio", False, True, True), ("estricto", False, False, False)])
def test_cada_nivel_deja_en_claro_solo_lo_acordado(usuario_id, nivel, asunto_claro, remitente_claro, asoc_claras):
    d, antes, despues, r = _con_cifrado(nivel)
    assert r["sellados"] == 1
    for mid in (antes, despues):
        f = _columnas(mid)
        assert f["cifrado"] == 1 and f["cifrado_nivel"] == nivel and f["datos"] and f["sobre"]
        assert not f["cuerpo_texto"] and f["cuerpo_html"] is None, "el cuerpo va cifrado en los tres niveles"
        assert bool(f["asunto"]) == asunto_claro and bool(f["remitente"]) == remitente_claro and bool(f["destinatarios"]) == remitente_claro
        assert (f["categoria_id"] is not None and f["cliente_fiscal_id"] is not None) == asoc_claras, "las reglas se aplicaron antes de sellar"
        assert f["fecha"] and f["carpeta"] == "INBOX" and f["leido"] in (0, 1), "fecha, carpeta y leído siempre en claro"
        assert (f["hilo_clave"] or "").startswith("h:") == (nivel != "laxo"), "la clave de conversación no puede delatar el asunto"
    a = db.listar_adjuntos_correo(antes)[0]
    conn = db.get_connection()
    cruda = conn.execute("SELECT * FROM correo_adjuntos WHERE mensaje_id = ?", (antes,)).fetchone()
    conn.close()
    assert cruda["cifrado"] == 1 and ADJ_CONTENIDO not in bytes(cruda["contenido"]) and (cruda["nombre_archivo"] == ADJ_NOMBRE) == (nivel == "laxo")


def test_nada_secreto_queda_en_el_fichero_de_la_base_de_datos(usuario_id):
    d, antes, despues, _ = _con_cifrado("estricto")
    correo_cifrado = cc
    correo_cifrado.vaciar_wal()
    datos = db.DB_PATH.read_bytes()
    wal = db.DB_PATH.with_name(db.DB_PATH.name + "-wal")
    datos += wal.read_bytes() if wal.exists() else b""
    for marca in (b"ZK9", b"XJ7", b"Marta Puig", b"LM5", b"QW3", b"zk9", b"xj7", b"puig", b"plenilunio", b"reclamacion"):
        assert marca not in datos, f"«{marca.decode()}» sigue en claro en el fichero de la base de datos"


def test_nivel_laxo_deja_el_asunto_buscable_pero_no_el_cuerpo(usuario_id):
    d, antes, despues, _ = _con_cifrado("laxo")
    datos = db.DB_PATH.read_bytes()
    assert b"XJ7" in datos and b"ZK9" not in datos


# --- leer ----------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("nivel", ["laxo", "medio", "estricto"])
def test_con_clave_se_lee_todo_y_sin_clave_sale_protegido(usuario_id, nivel):
    d, antes, despues, _ = _con_cifrado(nivel)
    m = db.obtener_mensaje_correo(antes)
    assert m["protegido"] is True and not m["cuerpo_texto"], "bloqueado: no se devuelve el contenido y se dice que está protegido"
    cd.desbloquear(d.t, d.u, FRASE)
    m = db.obtener_mensaje_correo(antes)
    assert m["protegido"] is False and m["asunto"] == ASUNTO and m["remitente"] == DE and CUERPO in m["cuerpo_texto"]
    assert m["categoria_id"] == d.cat and m["cliente_fiscal_id"] == d.cf
    a = db.listar_adjuntos_correo(antes)[0]
    assert a["nombre_archivo"] == ADJ_NOMBRE
    assert db.obtener_adjunto_correo(a["id"])["contenido"] == ADJ_CONTENIDO
    assert cd.accesos_recientes(d.t)[0]["tabla"] in ("correo_adjuntos", "correo")


def test_sin_clave_el_adjunto_no_se_entrega(usuario_id):
    d, antes, _, _ = _con_cifrado("medio")
    aid = db.listar_adjuntos_correo(antes)[0]["id"]
    with pytest.raises(cd.DespachoBloqueado):
        db.obtener_adjunto_correo(aid)
    assert db.listar_adjuntos_correo(antes)[0]["nombre_archivo"] == "" and db.listar_adjuntos_correo(antes)[0]["protegido"]


def test_el_correo_que_llega_con_el_despacho_bloqueado_tambien_se_sella(usuario_id):
    d, antes, _, _ = _con_cifrado("estricto")            # termina bloqueado
    de_madrugada = d.entra(msgid="<noche@x.com>", asunto="Aviso nocturno")
    assert _columnas(de_madrugada)["cifrado"] == 1 and _columnas(de_madrugada)["asunto"] == ""
    cd.desbloquear(d.t, d.u, FRASE)
    assert db.obtener_mensaje_correo(de_madrugada)["asunto"] == "Aviso nocturno"


def test_si_el_sellado_falla_el_mensaje_se_reintenta_en_la_siguiente_sincronizacion(usuario_id, monkeypatch):
    d, antes, _, _ = _con_cifrado("medio", bloquear=False)
    with monkeypatch.context() as m:
        m.setattr(cc, "sellar_mensaje", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fallo simulado")))
        pendiente = d.entra(msgid="<fallo@x.com>")
    assert _columnas(pendiente)["cifrado"] == 2 and CUERPO in _columnas(pendiente)["cuerpo_texto"]
    assert db.listar_mensajes_correo(d.cuenta_id, texto="zk9") and db.obtener_mensaje_correo(pendiente)["protegido"] is False, "mientras está por sellar se lee como un mensaje normal"
    assert cc.sellar_pendientes_de_cuenta(d.cuenta_id) == 1
    assert _columnas(pendiente)["cifrado"] == 1 and not _columnas(pendiente)["cuerpo_texto"]


# --- buscar --------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("nivel", ["laxo", "medio", "estricto"])
def test_buscar_por_cuerpo_asunto_remitente_y_cliente_funciona_en_los_tres_niveles(usuario_id, nivel):
    d, antes, despues, _ = _con_cifrado(nivel, bloquear=False)
    ids = lambda **f: sorted(m["id"] for m in db.listar_mensajes_correo(d.cuenta_id, **f))      # noqa: E731
    assert ids(texto="zk9") == sorted([antes, despues])                       # cuerpo, sin mayúsculas
    assert ids(texto="reclamacion xj7") == sorted([antes, despues])            # sin acentos, todas las palabras
    assert ids(asunto="Otro") == [despues]
    assert ids(remitente="cliente-secreto") == sorted([antes, despues])
    assert ids(texto="inexistente") == []
    assert ids(categoria_id=d.cat) == sorted([antes, despues])
    assert ids(cliente_fiscal_id=d.cf) == sorted([antes, despues])
    assert ids(cliente_fiscal_id=d.cf + 99) == []
    assert sorted(m["id"] for m in db.listar_correos_de_cliente_fiscal(d.cf)) == sorted([antes, despues])
    assert sorted(m["id"] for m in db.correos_de_cliente_para(d.u, d.cf)) == sorted([antes, despues])


def test_buscar_sin_clave_solo_encuentra_lo_que_el_nivel_deja_en_claro(usuario_id):
    d, antes, despues, _ = _con_cifrado("medio")
    assert db.listar_mensajes_correo(d.cuenta_id, texto="zk9") == [], "el cuerpo está cifrado: sin clave no se puede buscar"
    assert sorted(m["id"] for m in db.listar_mensajes_correo(d.cuenta_id, remitente="cliente-secreto")) == sorted([antes, despues])
    assert all(m["protegido"] for m in db.listar_mensajes_correo(d.cuenta_id))


def test_la_busqueda_en_memoria_se_olvida_al_bloquear(usuario_id):
    d, antes, _, _ = _con_cifrado("laxo", bloquear=False)
    db.listar_mensajes_correo(d.cuenta_id, texto="zk9")
    assert cc._memoria.get(d.t)
    cd.bloquear(d.t)
    assert not cc._memoria.get(d.t)


def test_la_ia_sigue_encontrando_el_correo_aunque_ya_no_este_en_el_buscador_externo(usuario_id, monkeypatch):
    import mcp_tools
    from app import busqueda
    indexados = []
    monkeypatch.setattr(busqueda, "indexar_mensaje", lambda *a, **k: indexados.append(a))
    monkeypatch.setattr(busqueda, "buscar_hibrido", lambda *a, **k: [])
    d, antes, _, _ = _con_cifrado("estricto", bloquear=False)
    d.entra(msgid="<nuevo@x.com>")
    assert indexados == [], "el correo de un despacho con correo cifrado no se manda a ningún índice externo"
    monkeypatch.setattr(mcp_tools, "_uid", lambda: d.u)
    r = mcp_tools.buscar_semantico("zk9")
    assert r and r[0]["tipo"] == "mensaje" and "ZK9" in r[0]["texto"]


def test_el_asistente_recibe_un_aviso_claro_si_esta_protegido(usuario_id, monkeypatch):
    import mcp_tools
    d, antes, _, _ = _con_cifrado("laxo")
    monkeypatch.setattr(mcp_tools, "_uid", lambda: d.u)
    m = mcp_tools.leer_correo(antes)
    assert m["protegido"] is True and "protegido" in m["aviso"] and not m["cuerpo_texto"]
    lista = mcp_tools.listar_bandeja_entrada(d.cuenta_id)
    assert lista and all(x["protegido"] and "aviso" in x for x in lista)
    cd.desbloquear(d.t, d.u, FRASE)
    assert CUERPO in mcp_tools.leer_correo(antes)["cuerpo_texto"]


# --- conversaciones ----------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("nivel", ["laxo", "medio", "estricto"])
def test_las_conversaciones_se_siguen_agrupando(usuario_id, nivel):
    d, antes, despues, _ = _con_cifrado(nivel, bloquear=False)
    respuesta = d.entra(asunto="Re: " + ASUNTO, msgid="<resp@x.com>", en_respuesta_a="<antes@x.com>", cuerpo="respuesta")
    mismo_asunto = d.entra(asunto=ASUNTO, msgid="<otro-hilo@x.com>", cuerpo="sin cabeceras de hilo")
    f = {i: _columnas(i)["hilo_clave"] for i in (antes, respuesta, mismo_asunto)}
    assert f[antes] == f[respuesta], "la respuesta hereda el hilo por In-Reply-To"
    assert f[antes] == f[mismo_asunto], "mismo asunto y contraparte: mismo hilo, también con la clave opaca"
    hilo = db.mensajes_del_hilo_correo(d.cuenta_id, f[antes])
    assert {m["id"] for m in hilo} == {antes, respuesta, mismo_asunto}


# --- cambiar de nivel, desactivar, rotar ----------------------------------------------------------------------------------------------------------------------
def test_subir_de_nivel_no_necesita_clave_y_bajar_si(usuario_id):
    d, antes, despues, _ = _con_cifrado("laxo", bloquear=False)
    cd.bloquear(d.t)
    assert cc.cambiar_nivel(d.t, d.u, "estricto") == 2                       # subir: sin clave
    f = _columnas(antes)
    assert f["asunto"] == "" and f["remitente"] == "" and f["categoria_id"] is None and f["cifrado_nivel"] == "estricto" and f["hilo_clave"].startswith("h:")
    with pytest.raises(cd.DespachoBloqueado):
        cc.cambiar_nivel(d.t, d.u, "laxo")
    cd.desbloquear(d.t, d.u, FRASE)
    assert cc.cambiar_nivel(d.t, d.u, "medio") == 2
    f = _columnas(antes)
    assert f["asunto"] == "" and f["remitente"] == DE and f["categoria_id"] == d.cat and f["cliente_fiscal_id"] == d.cf
    assert cc.cambiar_nivel(d.t, d.u, "laxo") == 2
    f = _columnas(antes)
    assert f["asunto"] == ASUNTO and not f["cuerpo_texto"] and f["cifrado"] == 1 and not f["hilo_clave"].startswith("h:")
    assert db.listar_adjuntos_correo(antes)[0]["nombre_archivo"] == ADJ_NOMBRE
    assert [m["id"] for m in db.listar_mensajes_correo(d.cuenta_id, texto="zk9", limite=1)] != []


def test_desactivar_deja_el_correo_exactamente_como_estaba(usuario_id):
    d = Despacho()
    mid = d.entra()
    original = _columnas(mid)
    adj = db.listar_adjuntos_correo(mid)[0]
    cd.activar(d.t, d.u, FRASE)
    cc.activar(d.t, d.u, "estricto")
    assert _columnas(mid)["cifrado"] == 1
    cd.bloquear(d.t)
    with pytest.raises(cd.DespachoBloqueado):
        cc.desactivar(d.t, d.u)
    cd.desbloquear(d.t, d.u, FRASE)
    assert cc.desactivar(d.t, d.u) == 1
    f = _columnas(mid)
    for k in ("asunto", "remitente", "destinatarios", "cc", "cuerpo_texto", "cuerpo_html", "categoria_id", "cliente_fiscal_id", "hilo_clave"):
        assert f[k] == original[k], k
    assert f["cifrado"] == 0 and f["datos"] is None
    a = db.obtener_adjunto_correo(adj["id"])
    assert a["contenido"] == ADJ_CONTENIDO and a["nombre_archivo"] == ADJ_NOMBRE and not a["cifrado"]
    assert cc.estado(d.t)["activo"] is False
    assert d.entra(msgid="<despues-de-desactivar@x.com>") and _columnas(d.n and db.mensaje_correo_por_uid(d.cuenta_id, "INBOX", str(d.n))["id"])["cifrado"] == 0


def test_rotar_la_clave_del_despacho_recifra_el_correo(usuario_id):
    d, antes, despues, _ = _con_cifrado("medio", bloquear=False)
    previo = bytes(_columnas(antes)["datos"])
    cd.rotar_clave(d.t, d.u, FRASE)
    assert bytes(_columnas(antes)["datos"]) != previo
    m = db.obtener_mensaje_correo(antes)
    assert m["asunto"] == ASUNTO and CUERPO in m["cuerpo_texto"]
    assert db.obtener_adjunto_correo(db.listar_adjuntos_correo(antes)[0]["id"])["contenido"] == ADJ_CONTENIDO
    cd.bloquear(d.t)
    cd.desbloquear(d.t, d.u, FRASE)
    assert db.obtener_mensaje_correo(despues)["protegido"] is False


def test_cambiar_la_categoria_en_estricto_exige_la_clave(usuario_id):
    d, antes, _, _ = _con_cifrado("estricto")
    cat2 = db.crear_categoria_correo(d.u, "Otra", "#aa0000")
    with pytest.raises(cd.DespachoBloqueado):
        db.asignar_categoria_correo(d.u, antes, cat2)
    cd.desbloquear(d.t, d.u, FRASE)
    db.asignar_categoria_correo(d.u, antes, cat2)
    assert db.obtener_mensaje_correo(antes)["categoria_id"] == cat2
    assert _columnas(antes)["categoria_id"] is None, "en Estricto la categoría no vuelve a las columnas en claro"


# --- aislamiento y concesiones ----------------------------------------------------------------------------------------------------------------------------
def test_el_correo_de_otro_despacho_no_se_toca(usuario_id):
    d, antes, _, _ = _con_cifrado("estricto", bloquear=False)
    t2 = db.crear_tenant("Otro despacho")
    u2 = db.crear_usuario_vinculado_a_kratos("otro-correo@ejemplo.com", "k-otro-correo"); db.asignar_tenant(u2, t2)
    c2 = db.crear_cuenta_correo(u2, "Mi cuenta", "imap", "h", 993, "otro@x.com")
    mid2, _ = correo._guardar_mensaje_imap(db.obtener_cuenta_correo(u2, c2), "INBOX", "1", crudo(adjunto=False, msgid="<o@x.com>"), set())
    f = _columnas(mid2)
    assert f["cifrado"] == 0 and f["asunto"] == ASUNTO and CUERPO in f["cuerpo_texto"]
    assert [m["id"] for m in db.listar_mensajes_correo(c2, texto="zk9")] == [mid2]
    assert db.listar_mensajes_correo(c2, texto="zk9")[0]["protegido"] is False


def test_una_concesion_de_token_lee_el_correo_con_el_despacho_bloqueado(usuario_id):
    d, antes, _, _ = _con_cifrado("estricto", bloquear=False)
    token = db.crear_token_api(d.u, "integración")
    cd.crear_concesion(d.t, d.u, token, "token", "integración")
    cd.bloquear(d.t)
    assert db.obtener_mensaje_correo(antes)["protegido"] is True
    testigo = cd.fijar_concesion("api", token)
    try:
        m = db.obtener_mensaje_correo(antes)
        assert m["protegido"] is False and CUERPO in m["cuerpo_texto"] and m["asunto"] == ASUNTO
        assert [x["id"] for x in db.listar_mensajes_correo(d.cuenta_id, texto="zk9")] != []
        assert db.obtener_adjunto_correo(db.listar_adjuntos_correo(antes)[0]["id"])["contenido"] == ADJ_CONTENIDO
    finally:
        cd.restablecer_concesion(testigo)
    assert db.obtener_mensaje_correo(antes)["protegido"] is True


# --- paridad: ningún nivel quita funciones (§8.2.1) --------------------------------------------------------------------------------------------------------
def _observar(d, antes, despues):
    """Todo lo que se puede hacer con el correo, reducido a algo comparable."""
    import mcp_tools
    obs = {}
    obs["lista"] = sorted((m["asunto"], m["remitente"], m["destinatarios"], bool(m["leido"])) for m in db.listar_mensajes_correo(d.cuenta_id))
    obs["busca_cuerpo"] = sorted(m["asunto"] for m in db.listar_mensajes_correo(d.cuenta_id, texto="ZK9 plenilunio"))
    obs["busca_asunto"] = [m["asunto"] for m in db.listar_mensajes_correo(d.cuenta_id, asunto="otro")]
    obs["busca_remitente"] = len(db.listar_mensajes_correo(d.cuenta_id, remitente="marta"))
    obs["por_categoria"] = len(db.listar_mensajes_correo(d.cuenta_id, categoria_id=d.cat))
    obs["por_cliente"] = len(db.listar_mensajes_correo(d.cuenta_id, cliente_fiscal_id=d.cf))
    obs["ficha_cliente"] = len(db.listar_correos_de_cliente_fiscal(d.cf))
    m = db.obtener_mensaje_correo(antes)
    obs["abrir"] = (m["asunto"], m["remitente"], m["cuerpo_texto"].strip(), m["categoria_id"] == d.cat, m["cliente_fiscal_id"] == d.cf, m["protegido"])
    obs["hilo"] = len(db.mensajes_del_hilo_correo(d.cuenta_id, m["hilo_clave"])) if m["hilo_clave"] else None
    a = db.listar_adjuntos_correo(antes)[0]
    obs["adjunto"] = (a["nombre_archivo"], db.obtener_adjunto_correo(a["id"])["contenido"])
    obs["ia_leer"] = mcp_tools.leer_correo(antes)["cuerpo_texto"].strip()
    obs["ia_lista"] = len(mcp_tools.listar_bandeja_entrada(d.cuenta_id, texto="ZK9"))
    obs["ia_buscar"] = [r["tipo"] for r in mcp_tools.buscar_semantico("ZK9")]
    return obs


@pytest.mark.parametrize("acceso", ["sesion", "concesion"])
def test_paridad_los_tres_niveles_dan_el_mismo_resultado(usuario_id, monkeypatch, acceso):
    import mcp_tools
    from app import busqueda
    monkeypatch.setattr(busqueda, "buscar_hibrido", lambda *a, **k: [])
    resultados = {}
    for nivel in ("laxo", "medio", "estricto"):
        cc.olvidar_configuracion(); cc.olvidar(None)
        # un despacho distinto por nivel
        d = Despacho.__new__(Despacho)
        d.t = db.crear_tenant(f"Despacho {nivel} {acceso}")
        d.u = db.crear_usuario_vinculado_a_kratos(f"par-{nivel}-{acceso}@ejemplo.com", f"k-par-{nivel}-{acceso}")
        db.asignar_tenant(d.u, d.t); db.asignar_supervisor_tenant(d.u, True)
        d.cuenta_id = db.crear_cuenta_correo(d.u, "T", "imap", "h", 993, "yo@despacho.com")
        d.cf = db.crear_cliente_fiscal(d.t, "Cliente Secreto SL")
        d.cat = db.crear_categoria_correo(d.u, "Impuestos", "#336699")
        db.crear_regla_correo(d.u, remitente_patron="marta@cliente-secreto.com", categoria_id=d.cat, cliente_fiscal_id=d.cf)
        d.n = 0
        antes = d.entra(msgid="<antes@x.com>")
        cd.activar(d.t, d.u, FRASE, nivel); cc.activar(d.t, d.u, nivel)
        despues = d.entra(msgid="<despues@x.com>", asunto="Otro " + ASUNTO)
        monkeypatch.setattr(mcp_tools, "_uid", lambda u=d.u: u)
        if acceso == "sesion":
            resultados[nivel] = _observar(d, antes, despues)
        else:
            token = db.crear_token_api(d.u, "x")
            cd.crear_concesion(d.t, d.u, token, "token", "x")
            cd.bloquear(d.t)
            testigo = cd.fijar_concesion("api", token)
            try:
                resultados[nivel] = _observar(d, antes, despues)
            finally:
                cd.restablecer_concesion(testigo)
        # los dos mensajes anteriores a «hilo» comparten asunto distinto a propósito: lo único que cambia es el nivel
    base = resultados["laxo"]
    assert base["abrir"][0] == ASUNTO and base["abrir"][-1] is False and base["busca_cuerpo"] and base["ia_lista"] == 2
    for nivel in ("medio", "estricto"):
        for clave in base:
            assert resultados[nivel][clave] == base[clave], f"{nivel} difiere de laxo en «{clave}»: {resultados[nivel][clave]!r} != {base[clave]!r}"


# --- el historial del asistente no deja en claro lo que la IA lee de lo cifrado ---------------------------------------------------------------------------
def test_el_historial_del_chat_guarda_sellado_lo_que_la_ia_lee_del_correo(usuario_id):
    d, antes, _, _ = _con_cifrado("laxo", bloquear=False)
    leido = '{"asunto": "%s", "cuerpo_texto": "%s"}' % (ASUNTO, CUERPO)
    db.agregar_mensaje_ia(d.u, "user", contenido="¿Qué dice el correo de Marta?")
    db.agregar_mensaje_ia(d.u, "tool", contenido=leido, tool_call_id="1", nombre_herramienta="leer_correo")
    db.agregar_mensaje_ia(d.u, "tool", contenido='{"tareas": 3}', tool_call_id="2", nombre_herramienta="listar_tareas")
    conn = db.get_connection()
    crudo = {r["nombre_herramienta"]: r["contenido"] for r in conn.execute("SELECT nombre_herramienta, contenido FROM ia_mensajes WHERE rol = 'tool'")}
    conn.close()
    assert crudo["leer_correo"].startswith("enc1:") and "ZK9" not in crudo["leer_correo"], "lo leído del correo va sellado"
    assert crudo["listar_tareas"] == '{"tareas": 3}', "el resto de resultados se queda como siempre"
    assert [m["contenido"] for m in db.listar_mensajes_ia(d.u) if m["rol"] == "tool"][0] == leido, "con clave, el asistente recuerda lo leído"
    cd.bloquear(d.t)
    visto = [m["contenido"] for m in db.listar_mensajes_ia(d.u) if m["rol"] == "tool"]
    assert "ZK9" not in visto[0] and "protegido" in visto[0].lower() and visto[1] == '{"tareas": 3}'


def test_al_activar_se_sella_el_historial_que_ya_habia(usuario_id):
    d = Despacho()
    db.agregar_mensaje_ia(d.u, "tool", contenido="cuerpo ZK9 plenilunio", tool_call_id="1", nombre_herramienta="leer_correo")
    cd.activar(d.t, d.u, FRASE)
    conn = db.get_connection()
    assert conn.execute("SELECT contenido FROM ia_mensajes").fetchone()[0].startswith("enc1:")
    conn.close()
    assert db.listar_mensajes_ia(d.u)[0]["contenido"] == "cuerpo ZK9 plenilunio"
    cd.rotar_clave(d.t, d.u, FRASE)
    assert db.listar_mensajes_ia(d.u)[0]["contenido"] == "cuerpo ZK9 plenilunio", "la rotación de la clave también re-cifra el historial"


def test_sin_cifrado_el_historial_no_cambia(usuario_id):
    d = Despacho()
    db.agregar_mensaje_ia(d.u, "tool", contenido="texto", tool_call_id="1", nombre_herramienta="leer_correo")
    conn = db.get_connection()
    assert conn.execute("SELECT contenido FROM ia_mensajes").fetchone()[0] == "texto"
    conn.close()


# --- concesión de servicio para tareas programadas ------------------------------------------------------------------------------------------------------------
def _respuesta_pendiente(d):
    """Un mensaje enviado del que se espera respuesta (la respuesta llega después de cifrar el correo)."""
    d.entra(carpeta="INBOX", msgid="<propio@x.com>", asunto="Consulta")
    return d.entra(asunto="Re: Consulta", de="Cliente <otra-persona@cliente.example>", msgid="<resp@x.com>", en_respuesta_a="<propio@x.com>", adjunto=False, cuerpo="sí")


def test_sin_concesion_de_servicio_una_tarea_programada_no_ve_lo_cifrado(usuario_id):
    d, antes, _, _ = _con_cifrado("estricto")
    resp = _respuesta_pendiente(d)
    assert cd.estado_servicio(d.t) is None
    with cd.como_servicio(d.t, "seguimientos") as autorizada:
        assert autorizada is False
        assert db.obtener_mensaje_correo(resp)["protegido"] is True
        assert db.respuesta_a_mensaje(d.cuenta_id, "<propio@x.com>", "2000-01-01", {"yo@despacho.com"}) is None, "sin saber quién escribe no se puede decir que sea una respuesta"


def test_con_concesion_de_servicio_la_tarea_ve_lo_cifrado_solo_dentro_de_su_bloque(usuario_id):
    d, antes, _, _ = _con_cifrado("estricto", bloquear=False)
    resp = _respuesta_pendiente(d)
    cd.activar_servicio(d.t, d.u, ["seguimientos"], 30)
    cd.bloquear(d.t)
    assert db.obtener_mensaje_correo(resp)["protegido"] is True
    with cd.como_servicio(d.t, "seguimientos") as autorizada:
        assert autorizada is True
        r = db.respuesta_a_mensaje(d.cuenta_id, "<propio@x.com>", "2000-01-01", {"yo@despacho.com"})
        assert r and r["id"] == resp
        assert cd.canal_actual() == "servicio"
    assert db.obtener_mensaje_correo(resp)["protegido"] is True, "fuera del bloque vuelve a estar protegido"
    with cd.como_servicio(d.t, "otra-tarea") as autorizada:
        assert autorizada is False


def test_la_concesion_de_servicio_caduca_se_revoca_y_cae_con_la_rotacion(usuario_id):
    d, antes, _, _ = _con_cifrado("laxo", bloquear=False)
    with pytest.raises(ValueError):
        cd.activar_servicio(d.t, d.u, ["seguimientos"], 365)
    with pytest.raises(ValueError):
        cd.activar_servicio(d.t, d.u, ["nada"], 10)
    cd.activar_servicio(d.t, d.u, ["seguimientos"], 10)
    conn = db.get_connection()
    conn.execute("UPDATE concesion_servicio SET caduca_en = '2020-01-01T00:00:00'"); conn.commit(); conn.close()
    cd.bloquear(d.t)
    with cd.como_servicio(d.t, "seguimientos") as ok:
        assert ok is False and cd.estado_servicio(d.t)["vigente"] is False
    cd.desbloquear(d.t, d.u, FRASE)
    cd.activar_servicio(d.t, d.u, ["seguimientos"], 10)
    assert cd.revocar_servicio(d.t) and cd.estado_servicio(d.t) is None
    cd.activar_servicio(d.t, d.u, ["seguimientos"], 10)
    cd.rotar_clave(d.t, d.u, FRASE)
    assert cd.estado_servicio(d.t) is None, "la concesión envolvía la clave antigua: tras rotar hay que volver a darla"


def test_activar_la_concesion_de_servicio_exige_el_despacho_desbloqueado(usuario_id):
    d, antes, _, _ = _con_cifrado("laxo")
    with pytest.raises(cd.DespachoBloqueado):
        cd.activar_servicio(d.t, d.u, ["seguimientos"], 10)


def test_si_cambia_el_secreto_del_servidor_la_concesion_de_servicio_no_abre_nada(usuario_id, monkeypatch):
    d, antes, _, _ = _con_cifrado("laxo", bloquear=False)
    cd.activar_servicio(d.t, d.u, ["seguimientos"], 10)
    cd.bloquear(d.t)
    monkeypatch.setenv("GUILDA_SECRET_KEY", "otro-secreto-distinto-" + "y" * 30)
    with cd.como_servicio(d.t, "seguimientos") as ok:
        assert ok is False


def test_pantalla_de_tareas_programadas_solo_para_responsables(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "srv-web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho Servicio Web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    cd.activar(t, uid, FRASE)
    assert "No autorizadas" in cliente.get("/seguridad/cifrado").get_data(as_text=True)
    r = cliente.post("/seguridad/cifrado/servicio", data={"alcances": ["seguimientos"], "dias": "30"}, follow_redirects=True)
    assert "Tareas programadas autorizadas" in r.get_data(as_text=True) and cd.estado_servicio(t)["vigente"]
    r = cliente.post("/seguridad/cifrado/servicio/revocar", follow_redirects=True)
    assert "revocada" in r.get_data(as_text=True) and cd.estado_servicio(t) is None


def test_activar_el_correo_con_un_nivel_distinto_al_de_los_documentos_funciona(usuario_id):
    d = Despacho()
    antes = d.entra(msgid="<antes@x.com>")
    cd.activar(d.t, d.u, FRASE, "medio")                  # los documentos se activaron en Medio...
    r = cc.activar(d.t, d.u, "estricto")                  # ...y el correo se activa subiendo a Estricto
    despues = d.entra(msgid="<despues@x.com>")
    assert r["sellados"] == 1 and cd.estado(d.t)["nivel"] == "estricto"
    for mid in (antes, despues):
        f = _columnas(mid)
        assert f["cifrado"] == 1 and f["cifrado_nivel"] == "estricto" and f["asunto"] == "" and f["remitente"] == ""
    assert sorted(m["id"] for m in db.listar_mensajes_correo(d.cuenta_id, texto="zk9")) == sorted([antes, despues])


def test_la_bandeja_web_busca_en_memoria_con_el_correo_cifrado(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "bandeja-cif@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho Bandeja"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    cuenta_id = db.crear_cuenta_correo(uid, "Trabajo", "imap", "h", 993, "yo@despacho.com")
    cuenta = db.obtener_cuenta_correo(uid, cuenta_id)
    m1, _ = correo._guardar_mensaje_imap(cuenta, "INBOX", "1", crudo(adjunto=False), set())
    m2, _ = correo._guardar_mensaje_imap(cuenta, "INBOX", "2", crudo(asunto="Cita para la firma", de="Notaría <n@notaria.example>", cuerpo="el jueves", adjunto=False, msgid="<2@x>"), set())
    cd.activar(t, uid, FRASE, "medio"); cc.activar(t, uid, "estricto")
    html = cliente.get(f"/correo/?cuenta_id={cuenta_id}&q=ZK9").get_data(as_text=True)
    assert ASUNTO in html and "Cita para la firma" not in html, "con el correo cifrado la búsqueda web devuelve solo lo que coincide"
    todo = cliente.get(f"/correo/?cuenta_id={cuenta_id}").get_data(as_text=True)
    assert ASUNTO in todo and "Cita para la firma" in todo

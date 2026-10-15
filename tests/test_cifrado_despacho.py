"""Cifrado de documentos con la clave del despacho (app/cifrado_despacho.py): primitivas, ciclo completo, bloqueo, recuperación, aislamiento y que no quede nada en claro."""
import json

import pytest

import mcp_tools
from app import almacen_documentos as alm
from app import cifrado_despacho as cd
from app import db, ia_herramientas as ih, nucleo
from tests.conftest import iniciar_sesion_de_prueba

FRASE = "una frase de paso larga y segura"
SECRETO = b"CONTENIDO-MUY-CONFIDENCIAL-9f3a"


@pytest.fixture(autouse=True)
def argon2_rapido(monkeypatch):
    monkeypatch.setattr(cd, "ARGON2", {"time_cost": 1, "memory_cost": 8, "parallelism": 1})
    alm.fijar_cifrador(None)


def _despacho(nombre="Despacho Cif", n=2):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    return t, us


# --- primitivas ------------------------------------------------------------------------------------------------------------------------------------
def test_ida_y_vuelta_y_cada_sellado_es_distinto():
    priv, pub = cd.generar_par()
    c1, s1 = cd.sellar_con_publica(pub, SECRETO)
    c2, s2 = cd.sellar_con_publica(pub, SECRETO)
    assert SECRETO not in c1 and c1 != c2 and s1 != s2
    assert cd.abrir_con_privada(priv, c1, s1) == SECRETO == cd.abrir_con_privada(priv, c2, s2)


def test_clave_equivocada_o_contenido_manipulado_no_se_abren():
    priv, pub = cd.generar_par()
    otra, _ = cd.generar_par()
    c, s = cd.sellar_con_publica(pub, SECRETO)
    with pytest.raises(cd.ContenidoAlterado):
        cd.abrir_con_privada(otra, c, s)
    with pytest.raises(cd.ContenidoAlterado):
        cd.abrir_con_privada(priv, c[:-1] + bytes([c[-1] ^ 1]), s)
    manipulado = json.loads(s)
    manipulado["dek"] = manipulado["n"]
    with pytest.raises(cd.ContenidoAlterado):
        cd.abrir_con_privada(priv, c, json.dumps(manipulado))
    with pytest.raises(cd.ContenidoAlterado):
        cd.abrir_con_privada(priv, c, "no es json")


def test_la_privada_se_protege_con_frase_y_con_recuperacion():
    priv, _ = cd.generar_par()
    p = cd.proteger_con_frase(priv, FRASE)
    assert cd.abrir_con_frase(p, FRASE) == priv
    with pytest.raises(cd.ClaveIncorrecta):
        cd.abrir_con_frase(p, FRASE + "x")
    clave = cd.nueva_clave_de_recuperacion()
    assert len(clave.replace("-", "")) == 40 and clave == clave.upper()
    r = cd.proteger_con_recuperacion(priv, clave)
    assert cd.abrir_con_recuperacion(r, clave) == priv == cd.abrir_con_recuperacion(r, clave.lower().replace("-", " "))
    with pytest.raises(cd.ClaveIncorrecta):
        cd.abrir_con_recuperacion(r, cd.nueva_clave_de_recuperacion())


# --- ciclo completo ---------------------------------------------------------------------------------------------------------------------------------
def test_sin_activar_no_se_cifra_nada(usuario_id):
    t, (u, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    _, did = alm.guardar(u, "a.txt", "text/plain", SECRETO, cliente_id=c)
    assert alm.leer(t, u, did)["cifrado"] == 0 and not cd.esta_activo(t) and cd.estado(t)["activo"] is False


def test_activar_cifra_lo_anterior_y_lo_nuevo_y_solo_se_lee_desbloqueado(usuario_id):
    t, (u, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    _, antes = alm.guardar(u, "antes.txt", "text/plain", SECRETO + b"-antes", cliente_id=c)
    recuperacion = cd.activar(t, u, FRASE, "estricto")
    assert recuperacion and cd.estado(t) == {**cd.estado(t), "activo": True, "desbloqueado": True, "nivel": "estricto", "documentos_sin_cifrar": 0}
    _, despues = alm.guardar(u, "despues.txt", "text/plain", SECRETO + b"-despues", cliente_id=c)
    conn = db.get_connection()
    filas = {f["id"]: f for f in conn.execute("SELECT id, contenido, cifrado, sobre FROM documentos WHERE tenant_id = ?", (t,))}
    conn.close()
    for i in (antes, despues):
        assert filas[i]["cifrado"] == 1 and filas[i]["sobre"] and SECRETO not in bytes(filas[i]["contenido"])
    assert alm.leer(t, u, antes)["contenido"] == SECRETO + b"-antes" and alm.leer(t, u, despues)["contenido"] == SECRETO + b"-despues"
    cd.bloquear(t)
    assert cd.estado(t)["desbloqueado"] is False
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer(t, u, antes)
    alm.guardar(u, "de-madrugada.txt", "text/plain", b"llega con el despacho bloqueado", cliente_id=c)      # escribir no necesita desbloqueo
    assert len(alm.listar(t, u, cliente_id=c)) == 3 and all(d["cifrado"] for d in alm.listar(t, u, cliente_id=c))
    cd.desbloquear(t, u, FRASE)
    assert alm.leer(t, u, antes)["contenido"].endswith(b"-antes")


def test_no_queda_nada_en_claro_en_el_fichero_de_la_base_de_datos(usuario_id):
    t, (u, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    marcador = b"MARCADOR-DE-PRUEBA-" + b"X" * 3000      # grande: ocupa páginas de desbordamiento que el UPDATE libera
    alm.guardar(u, "grande.txt", "text/plain", marcador, cliente_id=c)
    cd.activar(t, u, FRASE)
    contenido_bd = db.DB_PATH.read_bytes()
    wal = db.DB_PATH.with_name(db.DB_PATH.name + "-wal")
    assert b"MARCADOR-DE-PRUEBA-" not in contenido_bd and (not wal.exists() or b"MARCADOR-DE-PRUEBA-" not in wal.read_bytes())


def test_frase_incorrecta_intentos_y_frase_corta(usuario_id):
    t, (u, _) = _despacho()
    with pytest.raises(ValueError, match="al menos"):
        cd.activar(t, u, "corta")
    cd.activar(t, u, FRASE)
    cd.bloquear(t)
    for _ in range(cd.INTENTOS_MAXIMOS):
        with pytest.raises(cd.ClaveIncorrecta):
            cd.desbloquear(t, u, "frase equivocada del todo")
    with pytest.raises(cd.DemasiadosIntentos):
        cd.desbloquear(t, u, FRASE)           # ni la buena vale durante el bloqueo por intentos
    cd.bloquear_todo()
    cd.desbloquear(t, u, FRASE)
    with pytest.raises(ValueError, match="ya está activado"):
        cd.activar(t, u, FRASE)


def test_cambiar_la_frase_y_recuperar_con_la_clave_impresa(usuario_id):
    t, (u, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    recuperacion = cd.activar(t, u, FRASE)
    _, did = alm.guardar(u, "a.txt", "text/plain", SECRETO, cliente_id=c)
    cd.cambiar_frase(t, u, FRASE, "otra frase distinta y larga")
    cd.bloquear(t)
    with pytest.raises(cd.ClaveIncorrecta):
        cd.desbloquear(t, u, FRASE)
    cd.bloquear_todo()
    cd.desbloquear(t, u, "otra frase distinta y larga")
    assert alm.leer(t, u, did)["contenido"] == SECRETO            # los documentos no se re-cifran: solo se re-envuelve la privada
    cd.bloquear(t)
    cd.recuperar(t, u, recuperacion, "frase nueva tras olvidar la otra")
    assert alm.leer(t, u, did)["contenido"] == SECRETO
    cd.bloquear(t)
    with pytest.raises(cd.ClaveIncorrecta):
        cd.recuperar(t, u, "AAAA-BBBB-CCCC", "frase nueva que no vale nada")


def test_el_desbloqueo_caduca(usuario_id, monkeypatch):
    t, (u, _) = _despacho()
    cd.activar(t, u, FRASE)
    assert cd.estado(t)["desbloqueado"]
    reloj = [cd.time.monotonic()]
    monkeypatch.setattr(cd.time, "monotonic", lambda: reloj[0] + cd.TTL_DESBLOQUEO_SEGUNDOS + 1)
    assert cd.estado(t)["desbloqueado"] is False


def test_un_despacho_no_toca_al_otro(usuario_id):
    t1, (u1, _) = _despacho("Despacho Uno")
    t2, (u2, _) = _despacho("Despacho Dos")
    c1, c2 = nucleo.crear_cliente(t1, "C1"), nucleo.crear_cliente(t2, "C2")
    cd.activar(t1, u1, FRASE)
    _, d1 = alm.guardar(u1, "uno.txt", "text/plain", SECRETO, cliente_id=c1)
    _, d2 = alm.guardar(u2, "dos.txt", "text/plain", b"en claro", cliente_id=c2)
    assert alm.leer(t2, u2, d2)["cifrado"] == 0 and cd.estado(t2)["activo"] is False
    assert alm.leer(t2, u2, d1) is None
    cd.bloquear(t1)
    assert alm.leer(t2, u2, d2)["contenido"] == b"en claro"       # bloquear uno no afecta al otro
    with pytest.raises(ValueError):
        cd.desbloquear(t2, u2, FRASE)                             # el otro despacho no tiene cifrado: nada que desbloquear


def test_los_accesos_a_contenido_cifrado_quedan_registrados(usuario_id):
    t, (u, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    _, did = alm.guardar(u, "a.txt", "text/plain", SECRETO, cliente_id=c)
    alm.leer(t, u, did)
    assert cd.accesos_recientes(t) == []           # sin cifrado no se registra
    cd.activar(t, u, FRASE)
    alm.leer(t, u, did)
    alm.leer(t, u, did, via="asistente")
    alm.leer_sin_usuario(t, did)
    a = cd.accesos_recientes(t)
    assert [x["via"] for x in a] == ["enlace", "asistente", "persona"] and a[0]["usuario_id"] is None and a[2]["usuario_id"] == u and a[0]["nombre_archivo"] == "a.txt"


def test_una_fila_manipulada_se_detecta(usuario_id):
    t, (u, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    cd.activar(t, u, FRASE)
    _, did = alm.guardar(u, "a.txt", "text/plain", SECRETO, cliente_id=c)
    conn = db.get_connection()
    ct = bytes(conn.execute("SELECT contenido FROM documentos WHERE id = ?", (did,)).fetchone()[0])
    conn.execute("UPDATE documentos SET contenido = ? WHERE id = ?", (ct[:-2] + b"\x00\x00", did))
    conn.commit()
    conn.close()
    with pytest.raises(cd.ContenidoAlterado):
        alm.leer(t, u, did)


# --- IA y MCP ---------------------------------------------------------------------------------------------------------------------------------------
def test_la_ia_lee_desbloqueado_y_explica_si_esta_bloqueado(usuario_id):
    t, (u, _) = _despacho()
    c = nucleo.crear_cliente(t, "Cliente")
    cd.activar(t, u, FRASE)
    _, did = alm.guardar(u, "nota.txt", "text/plain", "Acta de la reunión: ñ".encode(), cliente_id=c)
    _, pdf = alm.guardar(u, "escritura.pdf", "application/pdf", b"%PDF-1.4 x", cliente_id=c)
    lista = ih.ejecutar(u, "listar_documentos_despacho", {"cliente_id": c})
    assert {d["nombre_archivo"] for d in lista["documentos"]} == {"nota.txt", "escritura.pdf"} and "aviso" not in lista
    assert ih.ejecutar(u, "leer_documento_despacho", {"documento_id": did})["texto"] == "Acta de la reunión: ñ"
    with pytest.raises(ih.ErrorHerramientaIA, match="solo se puede leer como texto"):
        ih.ejecutar(u, "leer_documento_despacho", {"documento_id": pdf})
    assert [x["via"] for x in cd.accesos_recientes(t)][0] == "asistente"
    cd.bloquear(t)
    assert "bloqueado" in ih.ejecutar(u, "listar_documentos_despacho", {"cliente_id": c})["aviso"]
    with pytest.raises(ih.ErrorHerramientaIA, match="protegidos"):
        ih.ejecutar(u, "leer_documento_despacho", {"documento_id": did})


def test_la_ia_no_lee_documentos_de_otro_despacho(usuario_id):
    t1, (u1, _) = _despacho("Despacho IA1")
    t2, (u2, _) = _despacho("Despacho IA2")
    c = nucleo.crear_cliente(t1, "C")
    _, did = alm.guardar(u1, "a.txt", "text/plain", b"secreto", cliente_id=c)
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u2, "leer_documento_despacho", {"documento_id": did})


def test_son_herramientas_de_lectura():
    for n in ("listar_documentos_despacho", "leer_documento_despacho"):
        assert n in ih.LECTURA and any(t.__name__ == n for t in mcp_tools.TOOLS)


# --- pantallas --------------------------------------------------------------------------------------------------------------------------------------
def _sesion(cliente, correo, supervisor=True):
    uid = iniciar_sesion_de_prueba(cliente, correo, "contrasena123")
    t = db.crear_tenant("Despacho Rutas Cif")
    db.asignar_tenant(uid, t)
    if supervisor:
        db.asignar_supervisor_tenant(uid, True)
    return uid, t


def test_solo_un_responsable_gestiona_el_cifrado(cliente):
    _sesion(cliente, "cif-normal@ejemplo.com", supervisor=False)
    assert cliente.get("/seguridad/cifrado").status_code == 403
    assert cliente.post("/seguridad/cifrado/activar", data={"frase": FRASE, "frase2": FRASE, "entendido": "1"}).status_code == 403


def test_activar_desde_la_pantalla_enseña_la_clave_una_sola_vez(cliente):
    uid, t = _sesion(cliente, "cif-activar@ejemplo.com")
    html = cliente.get("/seguridad/cifrado").get_data(as_text=True)
    assert "Activar el cifrado" in html
    r = cliente.post("/seguridad/cifrado/activar", data={"frase": FRASE, "frase2": "otra", "entendido": "1"}, follow_redirects=True)
    assert "no coinciden" in r.get_data(as_text=True) and not cd.esta_activo(t)
    r = cliente.post("/seguridad/cifrado/activar", data={"frase": FRASE, "frase2": FRASE}, follow_redirects=True)
    assert "no se pueden recuperar" in r.get_data(as_text=True) and not cd.esta_activo(t)
    r = cliente.post("/seguridad/cifrado/activar", data={"frase": FRASE, "frase2": FRASE, "entendido": "1", "nivel": "estricto"})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store" and "Guarda tu clave de recuperación" in r.get_data(as_text=True)
    assert cd.estado(t)["nivel"] == "estricto"
    despues = cliente.get("/seguridad/cifrado").get_data(as_text=True)
    assert "Guarda tu clave" not in despues and "Desbloqueado" in despues


def test_documento_cifrado_con_el_despacho_bloqueado_da_423_con_explicacion(cliente):
    uid, t = _sesion(cliente, "cif-423@ejemplo.com")
    c = nucleo.crear_cliente(t, "Cliente")
    cd.activar(t, uid, FRASE)
    _, did = alm.guardar(uid, "a.txt", "text/plain", SECRETO, cliente_id=c)
    assert cliente.get(f"/clientes/{c}/documentos/{did}").data == SECRETO
    cliente.post("/seguridad/cifrado/bloquear")
    r = cliente.get(f"/clientes/{c}/documentos/{did}")
    assert r.status_code == 423 and "Documentos protegidos" in r.get_data(as_text=True) and SECRETO not in r.data
    r = cliente.post("/seguridad/cifrado/desbloquear", data={"frase": "incorrecta incorrecta"}, follow_redirects=True)
    assert "Frase incorrecta" in r.get_data(as_text=True) and cliente.get(f"/clientes/{c}/documentos/{did}").status_code == 423
    cliente.post("/seguridad/cifrado/desbloquear", data={"frase": FRASE})
    assert cliente.get(f"/clientes/{c}/documentos/{did}").data == SECRETO


def test_el_enlace_publico_de_un_cliente_tampoco_filtra_con_el_despacho_bloqueado(usuario_id):
    t, (u, _) = _despacho("Despacho Enlace")
    c = nucleo.crear_cliente(t, "Cliente")
    cd.activar(t, u, FRASE)
    _, did = alm.guardar(u, "a.txt", "text/plain", SECRETO, cliente_id=c)
    cd.bloquear(t)
    with pytest.raises(cd.DespachoBloqueado):
        alm.leer_sin_usuario(t, did)


def test_el_enlace_publico_con_el_despacho_bloqueado_da_423_y_no_500(cliente):
    import re
    from app.main import app
    from tests.test_rutas_abogados import _asunto, _con_bufete
    uid, t = _con_bufete(cliente)
    c, x = _asunto(t, uid, "Asunto cifrado")
    cd.activar(t, uid, FRASE)
    _, d1 = alm.guardar(uid, "demanda.pdf", "application/pdf", b"%PDF demanda", expediente_id=x)
    cliente.post(f"/abogados/expedientes/{x}/documentos/{d1}/compartir", data={"compartido": "1"})
    token = re.search(r'id="enlace-cliente">([^<]+)<', cliente.post(f"/abogados/expedientes/{x}/enlaces", data={"dias": "10"}).get_data(as_text=True)).group(1).rsplit("/", 1)[1]
    anonimo = app.test_client()
    assert anonimo.get(f"/asunto/{token}/documentos/{d1}").data == b"%PDF demanda"       # desbloqueado: el cliente lo descarga
    cd.bloquear(t)
    r = anonimo.get(f"/asunto/{token}/documentos/{d1}")
    assert r.status_code == 423 and b"%PDF demanda" not in r.data
    assert anonimo.get(f"/asunto/{token}").status_code == 200              # la página en sí (sin contenido cifrado) sigue funcionando


# --- RGPD: exportar y vaciar la papelera --------------------------------------------------------------------------------------------------------------
def test_exportar_los_datos_de_un_cliente_respeta_la_visibilidad(usuario_id):
    from app import rgpd
    t, (u1, u2) = _despacho("Despacho Rgpd")
    c = nucleo.crear_cliente(t, "Carmen Soler", nif="12345678Z", email="c@ejemplo.com")
    nucleo.anadir_contacto(t, c, "Su hijo", email="h@ejemplo.com")
    abierto = nucleo.crear_expediente(t, u1, c, "Asunto abierto")
    reservado = nucleo.crear_expediente(t, u1, c, "Asunto reservado", confidencial=True)
    nucleo.registrar_parte(t, u1, "Estudio", minutos=30, expediente_id=reservado)
    alm.guardar(u1, "dni.pdf", "application/pdf", b"%PDF dni", cliente_id=c)
    todo = rgpd.exportar_cliente(t, u1, True, c)
    assert todo["cliente"]["nif"] == "12345678Z" and {x["titulo"] for x in todo["expedientes"]} == {"Asunto reservado", "Asunto abierto"}
    assert todo["contactos"][0]["nombre"] == "Su hijo" and todo["documentos"][0]["nombre_archivo"] == "dni.pdf" and "contenido" not in todo["documentos"][0]
    sin = rgpd.exportar_cliente(t, u2, False, c)
    assert [x["titulo"] for x in sin["expedientes"]] == ["Asunto abierto"] and sin["horas"] == []
    assert rgpd.exportar_cliente(t + 99, u1, True, c) is None
    assert [r["tipo"] for r in rgpd.registro(t)] == ["exportacion", "exportacion"]


def test_vaciar_la_papelera_borra_lo_antiguo_con_constancia(usuario_id):
    from app import rgpd
    t, (u, _) = _despacho("Despacho Papelera")
    c = nucleo.crear_cliente(t, "Cliente")
    _, d1 = alm.guardar(u, "viejo.txt", "text/plain", b"viejo", cliente_id=c)
    _, d2 = alm.guardar(u, "reciente.txt", "text/plain", b"reciente", cliente_id=c)
    _, d3 = alm.guardar(u, "vivo.txt", "text/plain", b"vivo", cliente_id=c)
    alm.eliminar(t, u, d1)
    alm.eliminar(t, u, d2)
    conn = db.get_connection()
    conn.execute("UPDATE documentos SET papelera_en = '2020-01-01T00:00:00.000000' WHERE id = ?", (d1,))
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):
        rgpd.vaciar_papelera(t, u, 7)
    assert rgpd.vaciar_papelera(t, u, 90) == {"documentos": 1, "plazos": 0, "partes_tiempo": 0, "trabajadores_cliente": 0, "contactos": 0}
    conn = db.get_connection()
    ids = {f[0] for f in conn.execute("SELECT id FROM documentos WHERE tenant_id = ?", (t,))}
    conn.close()
    assert ids == {d2, d3}, "queda lo reciente de la papelera y lo que está vivo"
    assert rgpd.vaciar_papelera(t, u, 0)["documentos"] == 1
    assert rgpd.registro(t)[0]["tipo"] == "vaciado" and "documentos=1" in rgpd.registro(t)[0]["detalle"]


def test_la_papelera_de_un_despacho_no_vacia_la_de_otro(usuario_id):
    from app import rgpd
    t1, (u1, _) = _despacho("Despacho P1")
    t2, (u2, _) = _despacho("Despacho P2")
    c2 = nucleo.crear_cliente(t2, "C")
    _, d = alm.guardar(u2, "a.txt", "text/plain", b"a", cliente_id=c2)
    alm.eliminar(t2, u2, d)
    assert rgpd.vaciar_papelera(t1, u1, 0)["documentos"] == 0
    assert rgpd.vaciar_papelera(t2, u2, 0)["documentos"] == 1


def test_pantallas_de_privacidad_solo_para_responsables(cliente):
    uid, t = _sesion(cliente, "rgpd-resp@ejemplo.com")
    c = nucleo.crear_cliente(t, "Cliente Rgpd")
    assert "Vaciar la papelera" in cliente.get("/seguridad/privacidad").get_data(as_text=True)
    r = cliente.get(f"/seguridad/clientes/{c}/exportar.json")
    assert r.status_code == 200 and r.mimetype == "application/json" and json.loads(r.data)["cliente"]["nombre"] == "Cliente Rgpd" and r.headers["Cache-Control"] == "no-store"
    assert "Exportar datos (JSON)" in cliente.get(f"/clientes/{c}").get_data(as_text=True)
    assert cliente.get("/seguridad/clientes/99999/exportar.json").status_code == 404
    r = cliente.post("/seguridad/privacidad/vaciar-papelera", data={"dias": "30"}, follow_redirects=True)
    assert "Papelera vaciada" in r.get_data(as_text=True)
    r = cliente.post("/seguridad/privacidad/vaciar-papelera", data={"dias": "3"}, follow_redirects=True)
    assert "plazo válido" in r.get_data(as_text=True)


def test_un_miembro_normal_no_exporta_ni_vacia(cliente):
    uid, t = _sesion(cliente, "rgpd-normal@ejemplo.com", supervisor=False)
    c = nucleo.crear_cliente(t, "Cliente")
    assert cliente.get("/seguridad/privacidad").status_code == 403
    assert cliente.get(f"/seguridad/clientes/{c}/exportar.json").status_code == 403
    assert cliente.post("/seguridad/privacidad/vaciar-papelera", data={"dias": "0"}).status_code == 403
    assert "Exportar datos (JSON)" not in cliente.get(f"/clientes/{c}").get_data(as_text=True)


def test_un_responsable_no_exporta_clientes_de_otro_despacho(cliente):
    uid, t = _sesion(cliente, "rgpd-ajeno@ejemplo.com")
    otro = db.crear_tenant("Otro despacho Rgpd")
    ajeno = nucleo.crear_cliente(otro, "Ajeno")
    assert cliente.get(f"/seguridad/clientes/{ajeno}/exportar.json").status_code == 404

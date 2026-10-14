"""Inventario de certificados X.509 (app/certificados.py): importación segura (nunca claves privadas), dimensiones de estado, instantes exactos, duplicados,
vínculos, renovación con prueba por servicio, riesgos y avisos escalonados sin duplicados ni ráfagas."""
import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from app import certificados as ce, db

AHORA = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
_CLAVES: dict = {}


def _clave(n=0):
    if n not in _CLAVES:
        _CLAVES[n] = ec.generate_private_key(ec.SECP256R1())
    return _CLAVES[n]


def hacer_cert(cn="CLIENTE EJEMPLO", serie_id="IDCES-12345678Z", dias=100, desde=None, hasta=None, ca=False, emisor=None, clave=0, org=None, num=None):
    nombre = [x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    if serie_id:
        nombre.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, serie_id))
    if org:
        nombre.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, org))
        nombre.append(x509.NameAttribute(x509.ObjectIdentifier("2.5.4.97"), "VATES-B12345674"))
    sujeto = x509.Name(nombre)
    emisor_nombre = emisor.subject if emisor is not None else sujeto
    clave_emisor = _clave(clave if emisor is None else 99)
    b = (x509.CertificateBuilder().subject_name(sujeto).issuer_name(emisor_nombre).public_key(_clave(clave).public_key()).serial_number(num or x509.random_serial_number())
         .not_valid_before(desde or (AHORA - timedelta(days=265))).not_valid_after(hasta or (AHORA + timedelta(days=dias))))
    b = b.add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    return b.sign(clave_emisor, hashes.SHA256())


def pem(*certs):
    return b"".join(c.public_bytes(serialization.Encoding.PEM) for c in certs)


def der(c):
    return c.public_bytes(serialization.Encoding.DER)


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Certificados")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False, custodio=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        if custodio:
            ce.fijar_custodio_flag(t, e.sup, x, True)
        return x
    e.sup = u("sup-cert@ejemplo.com", sup=True)
    e.cus = u("cus-cert@ejemplo.com", custodio=True)
    e.otro = u("otro-cert@ejemplo.com")
    e.cf = db.crear_cliente_fiscal(t, "Cliente Fiscal SL")
    return e


# --- Seguridad: nada de claves privadas --------------------------------------------------------------------------------------------------------
def _p12():
    c = hacer_cert()
    return pkcs12.serialize_key_and_certificates(b"x", _clave(0), c, None, serialization.BestAvailableEncryption(b"secreto"))


def _claves_privadas():
    k = _clave(0)
    rsa_k = rsa.generate_private_key(65537, 2048)
    return {
        "pem_pkcs8": k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "pem_cifrada": k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(b"x")),
        "pem_rsa": rsa_k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()),
        "der": k.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "cert_mas_clave": pem(hacer_cert()) + _clave(0).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        "p12": _p12(),
    }


def test_se_rechaza_cualquier_clave_privada_o_contenedor_p12_aunque_cambie_la_extension(d):
    for nombre, datos in _claves_privadas().items():
        assert ce.contiene_clave_privada(datos), nombre
        with pytest.raises(ValueError, match="clave privada|PKCS#12|no guarda claves"):
            ce.importar(d.t, d.cus, datos)
    assert ce.listar(d.t) == [], "no se ha guardado nada"
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM certificados").fetchone()[0] == 0
    finally:
        conn.close()


def test_basura_vacio_enorme_y_asn1_invalido_se_rechazan_sin_romper(d):
    for datos, texto in ((b"", "vacío"), (b"\x30\x82\xff\xff" + b"\x00" * 50, "no es un certificado"), (b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----", "no es un certificado"),
                         (b"hola, esto no es un certificado", "no es un certificado"), (b"A" * (ce.MAX_BYTES + 1), "demasiado grande")):
        with pytest.raises(ValueError, match=texto):
            ce.importar(d.t, d.cus, datos)


def test_un_documento_normal_no_se_confunde_con_una_clave():
    for ok in (b"%PDF-1.4 contrato de arrendamiento", b"Hola, factura n\xc2\xba 12", "BEGIN PUBLIC KEY".encode(), pem(hacer_cert()), der(hacer_cert())):
        assert ce.contiene_clave_privada(ok) is None


# --- Importación y extracción ---------------------------------------------------------------------------------------------------------------------
def test_importar_extrae_huella_fechas_y_sugiere_nif(d):
    c = hacer_cert(cn="MARTA PUIG", serie_id="IDCES-12345678Z", dias=100)
    r = ce.importar(d.t, d.cus, pem(c), ubicacion_externa="Tarjeta en la caja fuerte de Girona")
    assert r["nuevo"] is True
    x = ce.obtener(d.t, r["id"], AHORA)
    assert x["huella_sha256"] == __import__("hashlib").sha256(der(c)).hexdigest() and x["nif_sugerido"] == "12345678Z" and x["tipo_titular_sugerido"] == "persona_fisica"
    assert x["not_after"] == (AHORA + timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ") and x["dias_restantes"] == 100 and x["temporal"] == "vigente" and x["verificado"] == 1
    assert x["nif_confirmado"] is None and x["custodio_id"] == d.cus and "der" not in x
    j = ce.importar(d.t, d.cus, pem(hacer_cert(cn="EMPRESA SL", serie_id=None, org="EMPRESA SL", clave=1)))
    assert ce.obtener(d.t, j["id"], AHORA)["tipo_titular_sugerido"] == "persona_juridica" and ce.obtener(d.t, j["id"], AHORA)["nif_sugerido"] == "B12345674"


def test_importar_dos_veces_o_en_der_y_pem_no_duplica(d):
    c = hacer_cert()
    a = ce.importar(d.t, d.cus, pem(c)); b = ce.importar(d.t, d.sup, der(c))
    assert a["nuevo"] and not b["nuevo"] and a["id"] == b["id"] and len(ce.listar(d.t)) == 1
    otro = db.crear_tenant("Otra asesoría")
    ce_otro = db.crear_usuario_vinculado_a_kratos("sup-otra@ejemplo.com", "k-sup-otra"); db.asignar_tenant(ce_otro, otro); db.asignar_supervisor_tenant(ce_otro, True)
    assert ce.importar(otro, ce_otro, pem(c))["nuevo"], "la unicidad es por asesoría"
    assert ce.obtener(otro, a["id"]) is None and ce.listar(otro)[0]["id"] != a["id"]


def test_varios_certificados_en_un_fichero_identifica_la_hoja_y_no_asume_el_primero(d):
    raiz = hacer_cert("AC RAIZ", serie_id=None, ca=True, clave=5)
    inter = hacer_cert("AC INTERMEDIA", serie_id=None, ca=True, emisor=raiz, clave=6)
    hoja = hacer_cert("MARTA PUIG", emisor=inter, clave=7)
    a = ce.analizar(pem(raiz, inter, hoja))
    assert a["hoja"] == a["certificados"][2]["huella"]
    r = ce.importar(d.t, d.cus, pem(raiz, inter, hoja))
    x = ce.obtener(d.t, r["id"], AHORA)
    assert x["nombre_comun"] == "MARTA PUIG" and [c["es_ca"] for c in x["ruta_cadena"]] == [True, True] and x["es_ca"] == 0
    dos = pem(hacer_cert("UNO", clave=8), hacer_cert("DOS", clave=9))
    with pytest.raises(ce.EleccionRequerida) as e:
        ce.importar(d.t, d.cus, dos)
    assert len(e.value.candidatos) == 2
    elegida = e.value.candidatos[1]["huella"]
    assert ce.obtener(d.t, ce.importar(d.t, d.cus, dos, huella=elegida)["id"], AHORA)["nombre_comun"] == "DOS"
    with pytest.raises(ValueError, match="ningún certificado"):
        ce.importar(d.t, d.cus, dos, huella="0" * 64)


# --- Estado temporal: instantes exactos (RFC 5280) ------------------------------------------------------------------------------------------
def test_los_extremos_de_validez_son_inclusivos_y_se_mide_al_instante():
    ini, fin = "2026-10-13T10:00:00Z", "2026-10-13T12:00:00Z"
    u = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert ce.estado_temporal(ini, fin, u("2026-10-13T09:59:59Z")) == "todavia_no_vigente"
    assert ce.estado_temporal(ini, fin, u(ini)) == "vigente" and ce.estado_temporal(ini, fin, u(fin)) == "vigente"
    assert ce.estado_temporal(ini, fin, u("2026-10-13T12:00:01Z")) == "caducado"
    assert ce.estado_temporal(None, None) == "desconocido", "sin fechas, no se sabe"
    assert ce.estado_temporal(None, fin, u("2026-10-13T12:00:01Z")) == "caducado" and ce.estado_temporal(None, fin, u("2026-10-13T11:00:00Z")) == "vigente", "apuntado a mano: basta la caducidad"
    assert ce.dias_restantes(fin, u("2026-10-12T12:00:00Z")) == 1 and ce.dias_restantes(fin, u("2026-10-13T13:00:00Z")) == -1


def test_la_hora_local_sale_de_la_zona_de_la_asesoria(d):
    assert ce.hora_local("2026-07-01T10:00:00Z", d.t) == "2026-07-01 12:00 (Europe/Madrid)"
    assert ce.hora_local("2026-01-01T10:00:00Z", d.t) == "2026-01-01 11:00 (Europe/Madrid)"


# --- Dimensiones ---------------------------------------------------------------------------------------------------------------------------
def test_lo_no_comprobado_nunca_aparece_como_correcto(d):
    x = ce.obtener(d.t, ce.importar(d.t, d.cus, pem(hacer_cert()))["id"], AHORA)
    assert (x["cadena"]["resultado"], x["revocacion"]["resultado"], x["clave"]["resultado"]) == ("no_comprobada", "no_comprobada", "no_declarada")
    assert x["cadena"]["comprobado_en"] is None and x["renovacion"] == "sin_iniciar" and x["estado_operativo"] == "inventariado"
    ce.registrar_evaluacion(d.t, d.cus, x["id"], "clave", "declarada_en_medio_autorizado", detalle="Tarjeta criptográfica en la oficina de Girona")
    ce.registrar_evaluacion(d.t, d.cus, x["id"], "cadena", "indeterminada", detalle="No se pudo descargar la AC")
    y = ce.obtener(d.t, x["id"], AHORA)
    assert y["clave"]["resultado"] == "declarada_en_medio_autorizado" and y["clave"]["comprobado_en"] and y["cadena"]["resultado"] == "indeterminada" and y["revocacion"]["resultado"] == "no_comprobada"
    with pytest.raises(ValueError, match="no válidos"):
        ce.registrar_evaluacion(d.t, d.cus, x["id"], "cadena", "perfecto")


def test_permisos_y_secretos(d):
    c = hacer_cert()
    with pytest.raises(ValueError, match="Solo los custodios"):
        ce.importar(d.t, d.otro, pem(c))
    assert ce.puede_gestionar(d.cus, d.t) and ce.puede_gestionar(d.sup, d.t) and not ce.puede_gestionar(d.otro, d.t)
    with pytest.raises(ValueError, match="Solo un supervisor"):
        ce.fijar_custodio_flag(d.t, d.otro, d.otro, True)
    with pytest.raises(ValueError, match="contraseñas"):
        ce.importar(d.t, d.cus, pem(c), ubicacion_externa="USB, contraseña: 1234")
    cid = ce.importar(d.t, d.cus, pem(c))["id"]
    with pytest.raises(ValueError, match="contraseñas"):
        ce.actualizar_datos(d.t, d.cus, cid, notas="el PIN: 0000")
    ce.actualizar_datos(d.t, d.cus, cid, nif_confirmado="12345678z", tipo_titular="representante")
    x = ce.obtener(d.t, cid, AHORA)
    assert (x["nif_confirmado"], x["tipo_titular"], x["version"]) == ("12345678Z", "representante", 2)
    with pytest.raises(ValueError, match="formato"):
        ce.actualizar_datos(d.t, d.cus, cid, nif_confirmado="12")


def test_alta_manual_queda_pendiente_de_comprobar(d):
    r = ce.alta_manual(d.t, d.cus, sujeto="CN=Marta Puig", emisor="CN=AC FNMT", numero_serie="AB:CD:01", not_before="2025-01-01", not_after="2026-12-31", evidencia="Captura del portal del emisor, 13/10/2026")
    x = ce.obtener(d.t, r["id"], AHORA)
    assert x["pendiente_de_comprobar"] and x["origen"] == "manual" and x["temporal"] == "vigente" and x["not_after"] == "2026-12-31T23:59:59Z" and x["numero_serie"] == "abcd01"
    assert not ce.alta_manual(d.t, d.cus, sujeto="CN=Marta Puig", emisor="CN=AC FNMT", numero_serie="abcd01", not_before=None, not_after="2026-12-31", evidencia="x")["nuevo"]
    with pytest.raises(ValueError, match="evidencia"):
        ce.alta_manual(d.t, d.cus, sujeto="a", emisor="b", numero_serie="1", not_before=None, not_after="2026-12-31", evidencia="")


def test_estado_operativo(d):
    cid = ce.importar(d.t, d.cus, pem(hacer_cert()))["id"]
    ce.cambiar_estado_operativo(d.t, d.cus, cid, "autorizado")
    with pytest.raises(ValueError, match="motivo"):
        ce.cambiar_estado_operativo(d.t, d.cus, cid, "suspendido")
    ce.cambiar_estado_operativo(d.t, d.cus, cid, "suspendido", "Sospecha de compromiso")
    with pytest.raises(ValueError, match="no válido"):
        ce.cambiar_estado_operativo(d.t, d.cus, cid, "sustituido", "x")
    caducado = ce.importar(d.t, d.cus, pem(hacer_cert(cn="VIEJO", hasta=datetime(2020, 1, 1, tzinfo=timezone.utc), desde=datetime(2019, 1, 1, tzinfo=timezone.utc), clave=3)))["id"]
    with pytest.raises(ValueError, match="caducado"):
        ce.cambiar_estado_operativo(d.t, d.cus, caducado, "autorizado")
    ce.cambiar_estado_operativo(d.t, d.cus, caducado, "archivado", "Ya no se usa")
    assert [c["id"] for c in ce.listar(d.t)] == [cid] and len(ce.listar(d.t, incluir_archivados=True)) == 2
    assert [e["accion"] for e in ce.eventos(d.t, cid)][:2] == ["estado_suspendido", "estado_autorizado"]


# --- Vínculos y riesgos ----------------------------------------------------------------------------------------------------------------------
def test_vinculos_y_riesgos_de_dependencia(d):
    hoy = AHORA.date()
    cert = ce.importar(d.t, d.cus, pem(hacer_cert(dias=20)))["id"]
    venc = db.crear_vencimiento_fiscal(d.t, d.cf, "303", "3T", (hoy + timedelta(days=45)).isoformat())
    otro_cf = db.crear_cliente_fiscal(d.t, "Sin certificado SL")
    db.crear_vencimiento_fiscal(d.t, otro_cf, "111", "3T", (hoy + timedelta(days=10)).isoformat())
    r = {x["cliente"]: x for x in ce.riesgos(d.t, hoy)}
    assert r["Sin certificado SL"]["tipo"] == "cobertura_desconocida" and r["Cliente Fiscal SL"]["tipo"] == "cobertura_desconocida", "sin mapa de dependencias no es «correcto»"
    ce.vincular(d.t, d.cus, cert, cliente_fiscal_id=d.cf, servicio="presentacion", autorizacion="Apoderamiento firmado el 01/06/2026")
    with pytest.raises(ValueError, match="ya está registrado"):
        ce.vincular(d.t, d.cus, cert, cliente_fiscal_id=d.cf, servicio="presentacion", autorizacion="otra vez")
    with pytest.raises(ValueError, match="autorización"):
        ce.vincular(d.t, d.cus, cert, cliente_fiscal_id=d.cf, servicio="firma", autorizacion=" ")
    r = {x["cliente"]: x for x in ce.riesgos(d.t, hoy)}
    assert r["Cliente Fiscal SL"]["tipo"] == "caduca_antes" and r["Cliente Fiscal SL"]["certificado_id"] == cert and r["Cliente Fiscal SL"]["vencimiento_id"] == venc
    otro = ce.importar(d.t, d.cus, pem(hacer_cert(cn="OTRO", dias=400, clave=4)))["id"]
    ce.vincular(d.t, d.cus, otro, cliente_fiscal_id=d.cf, servicio="presentacion", autorizacion="Apoderamiento")
    assert "Cliente Fiscal SL" not in {x["cliente"] for x in ce.riesgos(d.t, hoy)}, "hay una alternativa vigente"
    ce.cambiar_estado_operativo(d.t, d.cus, otro, "suspendido", "Compromiso")
    assert {x["cliente"]: x for x in ce.riesgos(d.t, hoy)}["Cliente Fiscal SL"]["tipo"] in ("caduca_antes", "sin_alternativa")


# --- Renovación ----------------------------------------------------------------------------------------------------------------------------------
def _renovacion_hasta_validado(d):
    viejo = hacer_cert(cn="MARTA PUIG", dias=20)
    cid = ce.importar(d.t, d.cus, pem(viejo))["id"]
    ce.cambiar_estado_operativo(d.t, d.cus, cid, "autorizado")
    v1 = ce.vincular(d.t, d.cus, cid, cliente_fiscal_id=d.cf, servicio="presentacion", autorizacion="Apoderamiento")
    v2 = ce.vincular(d.t, d.cus, cid, cliente_fiscal_id=d.cf, servicio="acceso_buzon", autorizacion="Apoderamiento")
    rid = ce.abrir_renovacion(d.t, d.cus, cid, titular="Marta Puig")
    ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion")
    nuevo = hacer_cert(cn="MARTA PUIG", dias=1100, clave=11)
    dif = ce.registrar_certificado_nuevo(d.t, d.cus, rid, pem(nuevo))
    ce.avanzar_renovacion(d.t, d.cus, rid, "validado")
    return cid, rid, v1, v2, dif


def test_una_sola_renovacion_activa_y_el_orden_de_las_fases(d):
    cid = ce.importar(d.t, d.cus, pem(hacer_cert(dias=20)))["id"]
    rid = ce.abrir_renovacion(d.t, d.cus, cid)
    with pytest.raises(ValueError, match="en curso"):
        ce.abrir_renovacion(d.t, d.sup, cid)
    for destino in ("validado", "cerrado", "obtenido"):
        with pytest.raises(ValueError, match="No se puede pasar|importar el certificado nuevo"):
            ce.avanzar_renovacion(d.t, d.cus, rid, destino)
    ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion"); ce.avanzar_renovacion(d.t, d.cus, rid, "pendiente_titular"); ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion")
    with pytest.raises(ValueError, match="importar el certificado nuevo"):
        ce.avanzar_renovacion(d.t, d.cus, rid, "obtenido")
    ce.avanzar_renovacion(d.t, d.cus, rid, "cancelada")
    assert ce.renovacion_activa(d.t, cid) is None and ce.abrir_renovacion(d.t, d.cus, cid), "cancelada la anterior, se puede abrir otra"


def test_el_certificado_nuevo_no_borra_el_anterior_y_muestra_diferencias(d):
    cid, rid, v1, v2, dif = _renovacion_hasta_validado(d)
    nuevo_id = dif["nuevo_certificado_id"]
    assert ce.obtener(d.t, cid)["estado_operativo"] == "autorizado" and ce.obtener(d.t, nuevo_id)["sustituye_a"] == cid
    assert {x["campo"] for x in dif["diferencias"]} == {"Válido hasta"}, "misma identidad: solo cambian las fechas"
    otro_nombre = ce.abrir_renovacion(d.t, d.cus, ce.importar(d.t, d.cus, pem(hacer_cert(cn="OTRA PERSONA", serie_id="IDCES-87654321X", dias=30, clave=12)))["id"])
    ce.avanzar_renovacion(d.t, d.cus, otro_nombre, "en_gestion")
    dif2 = ce.registrar_certificado_nuevo(d.t, d.cus, otro_nombre, pem(hacer_cert(cn="SUPLANTADOR", serie_id="IDCES-11111111H", clave=13)))
    assert {"Sujeto", "NIF sugerido"} <= {x["campo"] for x in dif2["diferencias"]}, "una identidad distinta salta a la vista"


def test_una_implantacion_fallida_mantiene_abierta_la_renovacion(d):
    cid, rid, v1, v2, dif = _renovacion_hasta_validado(d)
    with pytest.raises(ValueError, match="sin una prueba correcta"):
        ce.avanzar_renovacion(d.t, d.cus, rid, "implantado")
    ce.registrar_implantacion(d.t, d.cus, rid, v1, "correcta", "Presentación de prueba aceptada")
    ce.registrar_implantacion(d.t, d.cus, rid, v2, "fallida", "El buzón rechaza el certificado")
    with pytest.raises(ValueError, match="1 servicio"):
        ce.avanzar_renovacion(d.t, d.cus, rid, "implantado")
    assert ce.renovacion_activa(d.t, cid)["fase"] == "validado" and ce.obtener(d.t, cid)["estado_operativo"] == "autorizado"
    assert [e["resultado"] for e in ce.estado_implantacion(d.t, rid)] == ["correcta", "fallida"]
    ce.registrar_implantacion(d.t, d.cus, rid, v2, "correcta", "Resuelto con el soporte")
    ce.avanzar_renovacion(d.t, d.cus, rid, "implantado"); ce.avanzar_renovacion(d.t, d.cus, rid, "cerrado")


def test_cerrar_sustituye_el_certificado_y_traslada_los_servicios(d):
    cid, rid, v1, v2, dif = _renovacion_hasta_validado(d)
    for v in (v1, v2):
        ce.registrar_implantacion(d.t, d.cus, rid, v, "correcta")
    ce.avanzar_renovacion(d.t, d.cus, rid, "implantado"); ce.avanzar_renovacion(d.t, d.cus, rid, "cerrado")
    viejo, nuevo = ce.obtener(d.t, cid), ce.obtener(d.t, dif["nuevo_certificado_id"])
    assert viejo["estado_operativo"] == "sustituido" and nuevo["estado_operativo"] == "autorizado" and viejo["vinculos_activos"] == 0 and nuevo["vinculos_activos"] == 2
    assert {v["servicio"] for v in ce.vinculos(d.t, nuevo["id"], solo_activos=True)} == {"presentacion", "acceso_buzon"}
    assert len(ce.vinculos(d.t, cid)) == 2 and all(v["estado"] == "retirado" for v in ce.vinculos(d.t, cid)), "el historial se conserva"
    assert ce.renovacion_activa(d.t, cid) is None and [c["id"] for c in ce.listar(d.t)] == [nuevo["id"]]


def test_sin_servicios_registrados_hay_que_confirmarlo(d):
    cid = ce.importar(d.t, d.cus, pem(hacer_cert(dias=20)))["id"]
    rid = ce.abrir_renovacion(d.t, d.cus, cid); ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion")
    ce.registrar_certificado_nuevo(d.t, d.cus, rid, pem(hacer_cert(dias=900, clave=14)))
    ce.avanzar_renovacion(d.t, d.cus, rid, "validado")
    with pytest.raises(ValueError, match="no tiene servicios registrados"):
        ce.avanzar_renovacion(d.t, d.cus, rid, "implantado")
    ce.avanzar_renovacion(d.t, d.cus, rid, "implantado", confirmar_sin_servicios=True)


def test_el_nuevo_certificado_no_puede_ser_el_mismo(d):
    c = hacer_cert(dias=20)
    cid = ce.importar(d.t, d.cus, pem(c))["id"]
    rid = ce.abrir_renovacion(d.t, d.cus, cid); ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion")
    with pytest.raises(ValueError, match="mismo certificado"):
        ce.registrar_certificado_nuevo(d.t, d.cus, rid, pem(c))


# --- Avisos ----------------------------------------------------------------------------------------------------------------------------------
def _avisos(d, cid=None):
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT umbral, destinatario_id, canal, estado FROM certificados_avisos " + ("WHERE certificado_id = ? " % () if False else ("WHERE certificado_id = %d " % cid if cid else "")) + "ORDER BY umbral DESC, destinatario_id, canal")]
    finally:
        conn.close()


def test_avisa_una_sola_vez_por_umbral_y_no_hace_rafaga_retrospectiva(d):
    # Importado cuando ya faltan 20 días: solo cuenta el umbral vigente (30); los de 90 y 60 se anotan como omitidos
    cid = ce.importar(d.t, d.cus, pem(hacer_cert(dias=20), ))["id"]
    r = ce.revisar_avisos(d.t, AHORA, enviar_correo=False)
    assert r["avisos"] == 1 and r["omitidos"] == 4 and r["fallidos"] == 0, r
    nots = db.listar_notificaciones(d.cus, 5)
    assert [n["tipo"] for n in nots] == ["certificado"] and "20 día" in nots[0]["titulo"]
    assert db.listar_notificaciones(d.sup, 5) == [], "a 30 días solo avisa el custodio"
    assert ce.revisar_avisos(d.t, AHORA, enviar_correo=False)["avisos"] == 0, "repetir la pasada no duplica"
    assert {(a["umbral"], a["estado"]) for a in _avisos(d, cid)} == {(90, "omitido"), (60, "omitido"), (30, "entregado")}


def test_el_escalado_suma_destinatarios_segun_se_acerca_la_caducidad(d):
    gestor = db.crear_usuario_vinculado_a_kratos("gestor-cert@ejemplo.com", "k-gestor-cert"); db.asignar_tenant(gestor, d.t); db.asignar_gestor_fichajes(gestor, True)
    cid = ce.importar(d.t, d.cus, pem(hacer_cert(dias=14)))["id"]
    ce.revisar_avisos(d.t, AHORA, enviar_correo=False)
    assert len(db.listar_notificaciones(gestor, 5)) == 1 and len(db.listar_notificaciones(d.sup, 5)) == 1, "desde 15 días, coordinación"
    despues = AHORA + timedelta(days=7)
    ce.revisar_avisos(d.t, despues, enviar_correo=False)
    assert any(n["titulo"].startswith("Certificado: caduca en 7") for n in db.listar_notificaciones(d.sup, 5)), "a 7 días, dirección"
    caducado = AHORA + timedelta(days=15)
    ce.revisar_avisos(d.t, caducado, enviar_correo=False)
    assert "Certificado caducado" in [n["titulo"] for n in db.listar_notificaciones(d.cus, 10)]


def test_un_certificado_sustituido_deja_de_avisar_y_lo_enviado_se_conserva(d):
    cid = ce.importar(d.t, d.cus, pem(hacer_cert(dias=80)))["id"]
    ce.revisar_avisos(d.t, AHORA, enviar_correo=False)
    antes = len(_avisos(d, cid))
    rid = ce.abrir_renovacion(d.t, d.cus, cid); ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion")
    ce.registrar_certificado_nuevo(d.t, d.cus, rid, pem(hacer_cert(dias=900, clave=15)))
    ce.avanzar_renovacion(d.t, d.cus, rid, "validado"); ce.avanzar_renovacion(d.t, d.cus, rid, "implantado", confirmar_sin_servicios=True); ce.avanzar_renovacion(d.t, d.cus, rid, "cerrado")
    ce.revisar_avisos(d.t, AHORA + timedelta(days=75), enviar_correo=False)
    assert len(_avisos(d, cid)) == antes, "sustituido: no hay más avisos, y los enviados siguen ahí"


def test_la_pasada_abre_sola_la_renovacion_a_60_dias_y_una_sola_vez(d):
    cid = ce.importar(d.t, d.cus, pem(hacer_cert(dias=50)))["id"]
    assert ce.revisar_avisos(d.t, AHORA, enviar_correo=False)["renovaciones"] == 1
    assert ce.revisar_avisos(d.t, AHORA, enviar_correo=False)["renovaciones"] == 0 and ce.renovacion_activa(d.t, cid)["fase"] == "sin_iniciar"
    lejos = ce.importar(d.t, d.cus, pem(hacer_cert(cn="LEJOS", dias=300, clave=16)))["id"]
    ce.revisar_avisos(d.t, AHORA, enviar_correo=False)
    assert ce.renovacion_activa(d.t, lejos) is None


def test_el_correo_no_lleva_datos_del_certificado_y_un_fallo_se_reintenta(d, monkeypatch):
    from app import notificaciones_email
    enviados, fallos = [], [True]
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    def enviar(destino, asunto, plano, html=None):
        if fallos and fallos.pop():
            raise notificaciones_email.ErrorNotificacionesEmail("proveedor caído")
        enviados.append((destino, asunto, plano, html))
    monkeypatch.setattr(notificaciones_email, "_enviar", enviar)
    ce.importar(d.t, d.cus, pem(hacer_cert(cn="MARTA PUIG", dias=20)))
    r = ce.revisar_avisos(d.t, AHORA)
    assert r["fallidos"] == 1 and enviados == []
    assert [a["estado"] for a in _avisos(d) if a["canal"] == "correo" and a["estado"] != "omitido"] == ["fallido"], "el fallo queda visible"
    r = ce.revisar_avisos(d.t, AHORA)
    assert r["fallidos"] == 0 and len(enviados) == 1 and "MARTA" not in enviados[0][2] + (enviados[0][3] or "") and "12345678Z" not in enviados[0][2], "mínimo de información + enlace"
    assert [a["estado"] for a in _avisos(d) if a["canal"] == "correo" and a["estado"] != "omitido"] == ["aceptado_por_proveedor"]


# --- Ninguna puerta de subida guarda una clave privada ------------------------------------------------------------------------------------------
def test_los_documentos_del_despacho_rechazan_claves_privadas_y_p12(d):
    from app import almacen_documentos as alm, nucleo
    cli = nucleo.crear_cliente(d.t, "Cliente Docs")
    for nombre, datos in _claves_privadas().items():
        assert alm.guardar(d.sup, "cosa.bin", "application/octet-stream", datos, cliente_id=cli) == ("clave_privada", None), nombre
        assert alm.guardar_de_cliente_fiscal(d.sup, d.cf, "cosa.bin", "application/octet-stream", datos) == ("clave_privada", None), nombre
    assert alm.guardar(d.sup, "contrato.pdf", "application/pdf", b"%PDF-1.4 contrato", cliente_id=cli)[0] == "ok"
    assert alm.guardar(d.sup, "publico.pem", "application/x-pem-file", pem(hacer_cert()), cliente_id=cli)[0] == "ok", "un certificado público sí es un documento"
    assert [x for x in alm.listar(d.t, d.sup, cliente_id=cli)] and all("PRIVATE" not in str(x) for x in alm.listar(d.t, d.sup, cliente_id=cli))


def test_los_justificantes_de_vencimientos_rechazan_claves_privadas(d):
    v = db.crear_vencimiento_fiscal(d.t, d.cf, "303", "3T", "2026-10-20")
    with pytest.raises(ValueError, match="no se guarda"):
        db.subir_documento_vencimiento(v, "x.pdf", "application/pdf", _p12())
    assert db.subir_documento_vencimiento(v, "x.pdf", "application/pdf", b"%PDF-1.4 justificante") > 0


# --- Pantallas ---------------------------------------------------------------------------------------------------------------------------------
import io  # noqa: E402

from tests.conftest import iniciar_sesion_de_prueba  # noqa: E402


def _web(cliente, email="cert-web@ejemplo.com", supervisor=True, gestoria=True):
    from app import verticales
    t = db.crear_tenant("Despacho Web Certs " + email)
    u = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.asignar_tenant(u, t)
    if supervisor:
        db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "gestoria", gestoria)
    return t, u


def _subir(cliente, datos, nombre="cert.pem", **extra):
    return cliente.post("/certificados/importar", data={"archivo": (io.BytesIO(datos), nombre), **extra}, content_type="multipart/form-data")


def test_importar_por_la_web_y_ver_la_ficha(cliente):
    t, u = _web(cliente)
    assert 'href="/certificados/"' in cliente.get("/fiscal/vencimientos").get_data(as_text=True), "el menú Fiscal enseña «Certificados» a quien puede usarlo"
    assert cliente.get("/certificados/").status_code == 200
    marta = hacer_cert(cn="MARTA PUIG", dias=40)
    r = _subir(cliente, pem(marta), ubicacion="Caja fuerte de Girona")
    assert r.status_code == 302 and "aviso=importado" in r.headers["Location"]
    cid = ce.listar(t)[0]["id"]
    ficha = cliente.get(f"/certificados/{cid}").get_data(as_text=True)
    assert "MARTA PUIG" in ficha and "12345678Z" in ficha and "No comprobada" in ficha and "Caja fuerte de Girona" in ficha and "Cobertura" not in ficha.split("Dónde se usa")[0]
    assert "Todavía no hay servicios registrados" in ficha
    assert "ya-estaba" in _subir(cliente, der(marta)).headers["Location"] and len(ce.listar(t)) == 1
    lista = cliente.get("/certificados/").get_data(as_text=True)
    assert "MARTA PUIG" in lista and "Vigente" in lista


def test_la_web_rechaza_claves_privadas_y_no_guarda_nada(cliente):
    t, u = _web(cliente, "cert-web-priv@ejemplo.com")
    for datos in (_p12(), _claves_privadas()["pem_pkcs8"], _claves_privadas()["cert_mas_clave"]):
        r = _subir(cliente, datos, "cert.pfx")
        assert r.status_code == 302 and "error=" in r.headers["Location"]
    pagina = cliente.get("/certificados/?error=" + "x").get_data(as_text=True)
    assert ce.listar(t) == []
    r = cliente.get(_subir(cliente, _p12()).headers["Location"])
    assert "no guarda claves privadas" in r.get_data(as_text=True)


def test_la_web_pide_elegir_entre_varios_certificados_finales(cliente):
    t, u = _web(cliente, "cert-web-elegir@ejemplo.com")
    dos = pem(hacer_cert("UNO", clave=20), hacer_cert("DOS", clave=21))
    pagina = _subir(cliente, dos).get_data(as_text=True)
    assert "¿Cuál es el certificado del cliente?" in pagina and "UNO" in pagina and "DOS" in pagina and ce.listar(t) == []
    import re
    b64 = re.search(r'name="contenido_b64" value="([^"]+)"', pagina).group(1)
    huella = re.findall(r'name="huella" value="([0-9a-f]+)"', pagina)[1]
    r = cliente.post("/certificados/importar", data={"contenido_b64": b64, "huella": huella})
    assert "aviso=importado" in r.headers["Location"] and [c["nombre_comun"] for c in ce.listar(t)] == ["DOS"]


def test_quien_no_es_custodio_ni_supervisor_no_entra(cliente):
    _web(cliente, "cert-web-nadie@ejemplo.com", supervisor=False)
    assert 'href="/certificados/"' not in cliente.get("/fiscal/vencimientos").get_data(as_text=True)
    assert cliente.get("/certificados/").status_code == 403 and _subir(cliente, pem(hacer_cert())).status_code == 403


def test_sin_el_modulo_de_gestoria_las_pantallas_no_existen(cliente):
    _web(cliente, "cert-web-sin-gestoria@ejemplo.com", gestoria=False)
    assert cliente.get("/certificados/").status_code == 404


def test_flujo_de_renovacion_por_la_web(cliente):
    t, u = _web(cliente, "cert-web-renov@ejemplo.com")
    cf = db.crear_cliente_fiscal(t, "Cliente Web SL")
    cid = ce.importar(t, u, pem(hacer_cert(cn="MARTA PUIG", dias=20)))["id"]
    cliente.post(f"/certificados/{cid}/vinculos", data={"cliente_fiscal_id": cf, "servicio": "presentacion", "autorizacion": "Apoderamiento 2026"})
    assert cliente.post(f"/certificados/{cid}/renovacion", data={"titular": "Marta"}).status_code == 302
    rid = ce.renovacion_activa(t, cid)["id"]
    cliente.post(f"/certificados/renovaciones/{rid}/avanzar", data={"certificado_id": cid, "fase": "en_gestion"})
    r = cliente.post(f"/certificados/renovaciones/{rid}/nuevo", data={"certificado_id": cid, "archivo": (io.BytesIO(pem(hacer_cert(cn="MARTA PUIG", dias=900, clave=22))), "nuevo.pem")}, content_type="multipart/form-data")
    assert "nuevo-recibido" in r.headers["Location"]
    cliente.post(f"/certificados/renovaciones/{rid}/avanzar", data={"certificado_id": cid, "fase": "validado"})
    ficha = cliente.get(f"/certificados/{cid}").get_data(as_text=True)
    assert "Prueba en cada servicio" in ficha and "Sin probar" in ficha
    r = cliente.post(f"/certificados/renovaciones/{rid}/avanzar", data={"certificado_id": cid, "fase": "implantado"})
    assert "error=" in r.headers["Location"]
    vid = ce.vinculos(t, cid)[0]["id"]
    cliente.post(f"/certificados/renovaciones/{rid}/implantacion", data={"certificado_id": cid, "vinculo_id": vid, "resultado": "correcta"})
    cliente.post(f"/certificados/renovaciones/{rid}/avanzar", data={"certificado_id": cid, "fase": "implantado"})
    cliente.post(f"/certificados/renovaciones/{rid}/avanzar", data={"certificado_id": cid, "fase": "cerrado"})
    assert ce.obtener(t, cid)["estado_operativo"] == "sustituido" and [c["nombre_comun"] for c in ce.listar(t)] == ["MARTA PUIG"]
    assert "Sustituido por" in cliente.get(f"/certificados/{cid}").get_data(as_text=True)


def test_un_despacho_no_ve_los_certificados_de_otro(cliente):
    t, u = _web(cliente, "cert-web-b@ejemplo.com")
    otro = db.crear_tenant("Otra asesoría con certificados")
    sup = db.crear_usuario_vinculado_a_kratos("sup-otra-cert@ejemplo.com", "k-sup-otra-cert"); db.asignar_tenant(sup, otro); db.asignar_supervisor_tenant(sup, True)
    ajeno = ce.importar(otro, sup, pem(hacer_cert("CLIENTE AJENO SL", serie_id=None, clave=30)))["id"]
    assert cliente.get(f"/certificados/{ajeno}").status_code == 404
    assert "AJENO" not in cliente.get("/certificados/").get_data(as_text=True)
    assert "error=" in cliente.post(f"/certificados/{ajeno}/estado", data={"nuevo": "autorizado"}).headers["Location"]
    assert ce.obtener(otro, ajeno)["estado_operativo"] == "inventariado"


# --- API ---------------------------------------------------------------------------------------------------------------------------------------
from tests.test_rutas_api import _auth, _registrar  # noqa: E402


def _tok(cliente, email, t, supervisor=True):
    datos = _registrar(cliente, email)
    u = db.obtener_usuario_por_email(email)["id"]
    db.asignar_tenant(u, t)
    if supervisor:
        db.asignar_supervisor_tenant(u, True)
    return u, _auth(datos["token"])


def test_api_importar_listar_y_riesgos(cliente):
    t = db.crear_tenant("Despacho API Certs")
    u, h = _tok(cliente, "api-cert@ejemplo.com", t)
    c = hacer_cert(cn="MARTA PUIG", dias=45)
    r = cliente.post("/api/v1/certificados/importar", headers=h, json={"contenido_base64": base64.b64encode(pem(c)).decode(), "ubicacion": "Caja fuerte"})
    assert r.status_code == 201 and r.get_json()["data"]["nuevo"] is True
    cid = r.get_json()["data"]["id"]
    r2 = cliente.post("/api/v1/certificados/importar", headers=h, json={"contenido_base64": base64.b64encode(der(c)).decode()})
    assert r2.status_code == 200 and r2.get_json()["data"] == {"id": cid, "nuevo": False, "huella": r.get_json()["data"]["huella"]}
    lista = cliente.get("/api/v1/certificados", headers=h).get_json()["data"]
    assert [x["id"] for x in lista] == [cid] and lista[0]["temporal"] == "vigente" and lista[0]["cadena"]["resultado"] == "no_comprobada" and "der" not in lista[0] and "tenant_id" not in lista[0]
    assert cliente.get(f"/api/v1/certificados/{cid}", headers=h).get_json()["data"]["nif_sugerido"] == "12345678Z"
    assert cliente.get("/api/v1/certificados?temporal=caducado", headers=h).get_json()["data"] == []
    cf = db.crear_cliente_fiscal(t, "Cliente API SL"); db.crear_vencimiento_fiscal(t, cf, "303", "3T", (date.today() + timedelta(days=10)).isoformat())
    assert cliente.get("/api/v1/certificados/riesgos", headers=h).get_json()["data"][0]["tipo"] == "cobertura_desconocida"
    assert cliente.post(f"/api/v1/certificados/{cid}/renovaciones", headers=h, json={"titular": "Marta"}).status_code == 201
    assert cliente.post(f"/api/v1/certificados/{cid}/renovaciones", headers=h, json={}).status_code == 409


def test_api_rechaza_claves_privadas_y_pide_elegir(cliente):
    t = db.crear_tenant("Despacho API Certs 2")
    u, h = _tok(cliente, "api-cert2@ejemplo.com", t)
    for datos in (_p12(), _claves_privadas()["pem_pkcs8"]):
        r = cliente.post("/api/v1/certificados/importar", headers=h, json={"contenido_base64": base64.b64encode(datos).decode()})
        assert r.status_code == 400 and r.get_json()["codigo"] == "certificado_no_valido"
    assert cliente.post("/api/v1/certificados/importar", headers=h, json={"contenido_base64": "###"}).get_json()["codigo"] == "certificado_no_valido"
    dos = pem(hacer_cert("UNO", clave=40), hacer_cert("DOS", clave=41))
    r = cliente.post("/api/v1/certificados/importar", headers=h, json={"contenido_base64": base64.b64encode(dos).decode()})
    assert r.status_code == 409 and r.get_json()["codigo"] == "eleccion_requerida" and len(r.get_json()["candidatos"]) == 2
    huella = r.get_json()["candidatos"][0]["huella"]
    assert cliente.post("/api/v1/certificados/importar", headers=h, json={"contenido_base64": base64.b64encode(dos).decode(), "huella": huella}).status_code == 201
    assert len(ce.listar(t)) == 1


def test_api_solo_para_custodios_y_supervisores(cliente):
    t = db.crear_tenant("Despacho API Certs 3")
    u, h = _tok(cliente, "api-cert3@ejemplo.com", t, supervisor=False)
    assert cliente.get("/api/v1/certificados", headers=h).status_code == 403
    assert cliente.post("/api/v1/certificados/importar", headers=h, json={"contenido_base64": base64.b64encode(pem(hacer_cert())).decode()}).status_code == 403


# --- IA y MCP ----------------------------------------------------------------------------------------------------------------------------------
def test_las_herramientas_de_ia_leen_certificados_solo_a_quien_corresponde(d):
    from app import ia_herramientas as ih
    for n in ("listar_certificados", "riesgos_de_certificados"):
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
    ce.importar(d.t, d.cus, pem(hacer_cert(cn="MARTA PUIG", dias=30)))
    r = ih.ejecutar(d.cus, "listar_certificados", {})
    assert [c["nombre_comun"] for c in r] == ["MARTA PUIG"] and r[0]["cadena"] == "no_comprobada" and r[0]["revocacion"] == "no_comprobada" and "der" not in r[0]
    assert ih.ejecutar(d.sup, "listar_certificados", {"temporal": "caducado"}) == []
    db.crear_vencimiento_fiscal(d.t, d.cf, "303", "3T", (date.today() + timedelta(days=5)).isoformat())
    assert ih.ejecutar(d.cus, "riesgos_de_certificados", {})[0]["tipo"] == "cobertura_desconocida"
    with pytest.raises(ih.ErrorHerramientaIA, match="Solo los custodios"):
        ih.ejecutar(d.otro, "listar_certificados", {})


def test_borrar_un_despacho_con_certificados_renovaciones_y_vinculos_no_se_bloquea(d):
    cid = ce.importar(d.t, d.cus, pem(hacer_cert(dias=20)))["id"]
    v = ce.vincular(d.t, d.cus, cid, cliente_fiscal_id=d.cf, servicio="presentacion", autorizacion="Apoderamiento")
    rid = ce.abrir_renovacion(d.t, d.cus, cid); ce.avanzar_renovacion(d.t, d.cus, rid, "en_gestion")
    ce.registrar_certificado_nuevo(d.t, d.cus, rid, pem(hacer_cert(dias=900, clave=50))); ce.avanzar_renovacion(d.t, d.cus, rid, "validado")
    ce.registrar_implantacion(d.t, d.cus, rid, v, "correcta")
    ce.revisar_avisos(d.t, AHORA, enviar_correo=False)
    db.borrar_tenant(d.t)
    conn = db.get_connection()
    try:
        for tabla in ("certificados", "certificados_vinculos", "certificados_renovaciones", "certificados_implantaciones", "certificados_evaluaciones", "certificados_avisos", "certificados_eventos"):
            assert conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0, tabla
    finally:
        conn.close()

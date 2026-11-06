"""Almacén de objetos: los contenidos de los documentos viven fuera de la base y se leen y reescriben sin que el resto del código lo note; si el almacén falla, nada se pierde; y el script de migración los lleva, los verifica, los limpia y los devuelve."""
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import almacen_documentos as ad, almacen_objetos as ao, db, nucleo
from app.db_fiscal import crear_cliente_fiscal
from tests.test_correo_expediente import _sembrar as sembrar_correo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migrar_a_objetos as script  # noqa: E402

PDF = b"%PDF-1.4\n" + b"contenido de la factura " * 40


@pytest.fixture
def fuera(tmp_path):
    almacen = ao.AlmacenFichero(tmp_path / "objetos")
    ao.fijar_almacen(almacen)
    yield almacen
    ao.fijar_almacen(None, fijo=False)


@pytest.fixture(autouse=True)
def _sin_almacen_al_terminar():
    yield
    ao.fijar_almacen(None, fijo=False)


def _despacho(nombre="Despacho obj"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"obj-{nombre}@ejemplo.com".replace(" ", ""), "k-" + nombre.replace(" ", ""))
    db.asignar_tenant(u, t)
    c = crear_cliente_fiscal(t, "Cliente Obj SL", nif="B12345678", email="obj@ejemplo.com")
    return t, u, c


def _fila(tabla, fila_id):
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT * FROM {tabla} WHERE id = ?", (fila_id,)).fetchone()
    finally:
        conn.close()


def _registro(tabla, fila_id):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM objetos_almacenados WHERE tabla = ? AND fila_id = ?", (tabla, fila_id)).fetchone()
    finally:
        conn.close()


# --- Los almacenes ------------------------------------------------------------------------------------------------------------------------------------

def test_el_almacen_de_ficheros_guarda_lee_lista_y_borra(tmp_path):
    a = ao.AlmacenFichero(tmp_path)
    a.poner("t1/cliente_documentos/5-abc", b"datos", "application/pdf")
    assert a.leer("t1/cliente_documentos/5-abc") == b"datos" and a.tamano("t1/cliente_documentos/5-abc") == 5 and a.tamano("t1/no-existe") is None
    assert [k for k, *_ in a.listar("t1/")] == ["t1/cliente_documentos/5-abc"] and a.listar("t9/") == []
    assert not list(tmp_path.rglob("*.tmp")), "no queda ningún temporal"
    a.borrar("t1/cliente_documentos/5-abc")
    a.borrar("t1/cliente_documentos/5-abc")
    assert a.tamano("t1/cliente_documentos/5-abc") is None


@pytest.mark.parametrize("clave", ["../fuera", "/absoluta", "a/../../b", "con espacio", "", "a" * 600, "a\x00b"])
def test_las_claves_peligrosas_se_rechazan(tmp_path, clave):
    with pytest.raises(ao.ErrorAlmacenObjetos):
        ao.AlmacenFichero(tmp_path).poner(clave, b"x")


def test_leer_algo_que_no_existe_es_un_error_claro(tmp_path):
    with pytest.raises(ao.ErrorAlmacenObjetos):
        ao.AlmacenFichero(tmp_path).leer("t1/x")


class _ClienteS3Falso:
    """Lo mínimo del SDK de MinIO que usa AlmacenS3."""
    def __init__(self):
        self.objetos, self.llamadas = {}, []

    def put_object(self, bucket, nombre, datos, longitud, content_type=None, retention=None):
        self.llamadas.append(("put", bucket, nombre, longitud, content_type, retention))
        self.objetos[nombre] = datos.read()

    def get_object(self, bucket, nombre):
        if nombre not in self.objetos:
            raise _ErrorS3("NoSuchKey")
        cuerpo = self.objetos[nombre]
        return type("R", (), {"read": lambda s: cuerpo, "close": lambda s: None, "release_conn": lambda s: None})()

    def stat_object(self, bucket, nombre):
        if nombre not in self.objetos:
            raise _ErrorS3("NoSuchKey")
        return type("S", (), {"size": len(self.objetos[nombre])})()

    def remove_object(self, bucket, nombre):
        self.objetos.pop(nombre, None)

    def list_objects(self, bucket, prefix="", recursive=True):
        return [type("O", (), {"object_name": k, "size": len(v), "last_modified": datetime(2026, 1, 1, tzinfo=timezone.utc), "is_dir": False})() for k, v in sorted(self.objetos.items()) if k.startswith(prefix)]


class _ErrorS3(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def test_el_almacen_s3_usa_prefijo_y_bloqueo_de_borrado():
    cliente = _ClienteS3Falso()
    a = ao.AlmacenS3("bucket", "k", "s", prefijo="guilda/", retencion_dias=2200, retencion_modo="compliance", cliente=cliente)
    a.poner("t1/documentos/7-abc", b"hola", "application/pdf")
    _, bucket, nombre, longitud, mime, retencion = cliente.llamadas[0]
    assert (bucket, nombre, longitud, mime) == ("bucket", "guilda/t1/documentos/7-abc", 4, "application/pdf")
    assert retencion.mode == "COMPLIANCE" and (retencion.retain_until_date - datetime.now(timezone.utc)).days >= 2198
    assert a.leer("t1/documentos/7-abc") == b"hola" and a.tamano("t1/documentos/7-abc") == 4 and a.tamano("t1/otro") is None
    assert a.listar("t1/") == [("t1/documentos/7-abc", 4, datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())]
    a.borrar("t1/documentos/7-abc")
    assert a.tamano("t1/documentos/7-abc") is None


def test_sin_retencion_no_se_manda_bloqueo():
    cliente = _ClienteS3Falso()
    ao.AlmacenS3("b", "k", "s", cliente=cliente).poner("t1/x/1-a", b"x")
    assert cliente.llamadas[0][5] is None


def test_un_fallo_del_sdk_sale_como_error_del_almacen():
    class Roto(_ClienteS3Falso):
        def put_object(self, *a, **k):
            raise ConnectionError("sin red")
    with pytest.raises(ao.ErrorAlmacenObjetos, match="sin red"):
        ao.AlmacenS3("b", "k", "s", cliente=Roto()).poner("t1/x/1-a", b"x")


def test_la_configuracion_se_lee_del_entorno(monkeypatch, tmp_path):
    for v in ("GUILDA_OBJETOS", "GUILDA_OBJETOS_DIR", "GUILDA_S3_BUCKET", "GUILDA_S3_ACCESS_KEY", "GUILDA_S3_SECRET_KEY"):
        monkeypatch.delenv(v, raising=False)
    ao.fijar_almacen(None, fijo=False)
    assert ao.almacen() is None and not ao.activo()
    monkeypatch.setenv("GUILDA_OBJETOS", "fichero")
    ao.fijar_almacen(None, fijo=False)
    with pytest.raises(ao.ErrorAlmacenObjetos, match="GUILDA_OBJETOS_DIR"):
        ao.almacen()
    monkeypatch.setenv("GUILDA_OBJETOS_DIR", str(tmp_path))
    ao.fijar_almacen(None, fijo=False)
    assert isinstance(ao.almacen(), ao.AlmacenFichero)
    monkeypatch.setenv("GUILDA_OBJETOS", "s3")
    ao.fijar_almacen(None, fijo=False)
    with pytest.raises(ao.ErrorAlmacenObjetos, match="GUILDA_S3_BUCKET"):
        ao.almacen()
    for v, valor in (("GUILDA_S3_BUCKET", "b"), ("GUILDA_S3_ACCESS_KEY", "k"), ("GUILDA_S3_SECRET_KEY", "s"), ("GUILDA_S3_RETENCION_DIAS", "2200")):
        monkeypatch.setenv(v, valor)
    ao.fijar_almacen(None, fijo=False)
    a = ao.almacen()
    assert isinstance(a, ao.AlmacenS3) and a.retencion_dias == 2200 and a.bucket == "b"
    monkeypatch.setenv("GUILDA_OBJETOS", "ftp")
    ao.fijar_almacen(None, fijo=False)
    with pytest.raises(ao.ErrorAlmacenObjetos, match="desconocido"):
        ao.almacen()


# --- Lo nuevo va al almacén y se lee igual ------------------------------------------------------------------------------------------------------

def test_un_documento_del_expediente_fiscal_nuevo_vive_fuera_y_se_lee_igual(fuera):
    t, u, c = _despacho("Despacho a")
    assert ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura") == ("ok", 1)
    fila = _fila("cliente_documentos", 1)
    assert bytes(fila["contenido"]) == b"" and fila["tamano_bytes"] == len(PDF) and fila["hash_sha256"] == hashlib.sha256(PDF).hexdigest()
    r = _registro("cliente_documentos", 1)
    assert r["tenant_id"] == t and r["tamano_bytes"] == len(PDF) and r["almacen"] == "fichero" and r["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert r["clave"] == f"t{t}/cliente_documentos/1-{r['sha256'][:12]}" and fuera.leer(r["clave"]) == PDF
    assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF
    assert ao.resumen() == {"cliente_documentos": {"objetos": 1, "bytes": len(PDF)}}


def test_un_documento_del_nucleo_vive_fuera_y_se_lee_igual(fuera):
    t, u, c = _despacho("Despacho b")
    cliente_nucleo = nucleo.crear_cliente(t, "Cliente núcleo")
    assert ad.guardar(u, "contrato.pdf", "application/pdf", PDF, cliente_id=cliente_nucleo) == ("ok", 1)
    assert bytes(_fila("documentos", 1)["contenido"]) == b"" and _registro("documentos", 1) is not None
    assert ad.leer(t, u, 1)["contenido"] == PDF


def test_un_documento_de_un_modelo_vive_fuera_y_se_lee_por_el_mismo_camino(fuera):
    t, u, c = _despacho("Despacho c")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    doc = db.subir_documento_vencimiento(v, "extracto.pdf", "application/pdf", PDF)
    assert not _fila("vencimientos_fiscales_documentos", doc)["contenido"] and _registro("vencimientos_fiscales_documentos", doc)["tenant_id"] == t
    assert db.contenido_documento_vencimiento(db.obtener_documento_vencimiento(doc)) == PDF


def test_un_adjunto_de_correo_nuevo_vive_fuera_y_se_lee_igual(fuera):
    uid = db.crear_usuario_vinculado_a_kratos("corr-obj@ejemplo.com", "k-corr-obj")
    _u, tenant, _cli, mid = sembrar_correo(uid, "corr-obj@ejemplo.com", [("a.pdf", "application/pdf", PDF)])
    adj = db.listar_adjuntos_correo(mid)[0]["id"] if hasattr(db, "listar_adjuntos_correo") else 1
    assert not _fila("correo_adjuntos", adj)["contenido"] and _registro("correo_adjuntos", adj)["tenant_id"] == tenant
    assert bytes(db.obtener_adjunto_correo(adj)["contenido"]) == PDF


def test_sin_almacen_todo_sigue_en_la_base():
    t, u, c = _despacho("Despacho d")
    ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")
    assert bytes(_fila("cliente_documentos", 1)["contenido"]) == PDF and _registro("cliente_documentos", 1) is None
    assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF


def test_si_el_almacen_falla_el_contenido_se_queda_en_la_base(tmp_path):
    class Roto(ao.AlmacenFichero):
        def poner(self, clave, datos, tipo_mime=None):
            raise ao.ErrorAlmacenObjetos("sin conexión")
    ao.fijar_almacen(Roto(tmp_path))
    t, u, c = _despacho("Despacho e")
    assert ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")[0] == "ok"
    assert bytes(_fila("cliente_documentos", 1)["contenido"]) == PDF and _registro("cliente_documentos", 1) is None
    assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF


def test_si_el_almacen_no_confirma_el_tamano_no_se_vacia_la_base(tmp_path):
    class Mentiroso(ao.AlmacenFichero):
        def tamano(self, clave):
            return 1
    ao.fijar_almacen(Mentiroso(tmp_path))
    t, u, c = _despacho("Despacho f")
    ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")
    assert bytes(_fila("cliente_documentos", 1)["contenido"]) == PDF and _registro("cliente_documentos", 1) is None


def test_un_objeto_manipulado_no_se_entrega(fuera):
    t, u, c = _despacho("Despacho g")
    ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")
    clave = _registro("cliente_documentos", 1)["clave"]
    fuera.poner(clave, PDF + b"manipulado")
    with pytest.raises(ao.ErrorAlmacenObjetos, match="huella"):
        ad.leer_de_cliente_fiscal(t, c, 1)


def test_si_se_quita_la_configuracion_con_objetos_fuera_el_error_es_claro(fuera):
    t, u, c = _despacho("Despacho h")
    ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")
    ao.fijar_almacen(None)
    with pytest.raises(ao.ErrorAlmacenObjetos, match="GUILDA_OBJETOS"):
        ad.leer_de_cliente_fiscal(t, c, 1)


# --- El cifrado del despacho sigue funcionando con el contenido fuera ----------------------------------------------------------------------------

class _Cifrador:
    def sellar(self, tenant_id, contenido):
        return bytes(b ^ 0x5A for b in contenido), "sobre-1"

    def abrir(self, tenant_id, contenido, sobre):
        assert sobre == "sobre-1"
        return bytes(b ^ 0x5A for b in contenido)


def test_sellar_lo_que_ya_estaba_fuera_reescribe_el_objeto_y_se_sigue_leyendo(fuera):
    t, u, c = _despacho("Despacho i")
    ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")
    antes = _registro("cliente_documentos", 1)
    ad.fijar_cifrador(_Cifrador())
    try:
        assert ad.sellar_pendientes(t) == 1
        fila = _fila("cliente_documentos", 1)
        despues = _registro("cliente_documentos", 1)
        assert fila["cifrado"] == 1 and bytes(fila["contenido"]) == b"" and despues["clave"] != antes["clave"]
        assert fuera.leer(despues["clave"]) == bytes(b ^ 0x5A for b in PDF), "en el almacén solo hay datos sellados"
        assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF
    finally:
        ad.fijar_cifrador(None)


def test_un_documento_nuevo_con_el_cifrado_activo_sube_ya_sellado(fuera):
    ad.fijar_cifrador(_Cifrador())
    try:
        t, u, c = _despacho("Despacho j")
        ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")
        assert fuera.leer(_registro("cliente_documentos", 1)["clave"]) == bytes(b ^ 0x5A for b in PDF)
        assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF
    finally:
        ad.fijar_cifrador(None)


def test_rotar_claves_reescribe_en_el_almacen_con_clave_nueva_y_si_falla_no_pierde_el_anterior(fuera):
    ad.fijar_cifrador(_Cifrador())
    try:
        t, u, c = _despacho("Despacho k")
        ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "factura.pdf", "application/pdf", PDF, "Factura")
        clave_vieja = _registro("cliente_documentos", 1)["clave"]
        with pytest.raises(RuntimeError):
            ad.resellar(t, lambda ct, sobre: bytes(b ^ 0x5A for b in ct), lambda claro: (bytes(b ^ 0x11 for b in claro), "sobre-2"), en_la_misma_transaccion=lambda conn: (_ for _ in ()).throw(RuntimeError("falla")))
        assert _registro("cliente_documentos", 1)["clave"] == clave_vieja and fuera.tamano(clave_vieja) == len(PDF), "la transacción no confirmó: el registro y el objeto anteriores siguen"
        assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF
    finally:
        ad.fijar_cifrador(None)


# --- El script de migración ---------------------------------------------------------------------------------------------------------------------------

def _sembrar_en_la_base():
    """Documentos guardados ANTES de tener almacén (con su contenido en la base)."""
    t, u, c = _despacho("Despacho migrar")
    ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "f1.pdf", "application/pdf", PDF, "Factura")
    ad.guardar_de_cliente_fiscal_sin_usuario(t, c, "f2.pdf", "application/pdf", PDF + b"2", "Factura")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", "2026-10-20", usuario_id=u)
    db.subir_documento_vencimiento(v, "e.pdf", "application/pdf", PDF + b"3")
    cn = nucleo.crear_cliente(t, "Cliente núcleo")
    ad.guardar(u, "c.pdf", "application/pdf", PDF + b"4", cliente_id=cn)
    uid = db.crear_usuario_vinculado_a_kratos("migr-corr@ejemplo.com", "k-migr-corr")
    _u, tc, _cli, mid = sembrar_correo(uid, "migr-corr@ejemplo.com", [("a.pdf", "application/pdf", PDF + b"5")])
    return t, u, c


def test_la_simulacion_cuenta_pero_no_toca_nada(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()
    ao.fijar_almacen(ao.AlmacenFichero(tmp_path / "o"))
    assert script.main(["migrar"]) == 0
    salida = capsys.readouterr().out
    assert "se migrarían 2 filas" in salida and "simulación" in salida
    assert bytes(_fila("cliente_documentos", 1)["contenido"]) == PDF and _registro("cliente_documentos", 1) is None and not list((tmp_path / "o").rglob("*")) if (tmp_path / "o").exists() else True


def test_migrar_lo_existente_vacia_la_base_y_todo_se_sigue_leyendo(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()
    almacen = ao.AlmacenFichero(tmp_path / "o")
    ao.fijar_almacen(almacen)
    assert script.main(["migrar", "--aplicar", "--lote", "2"]) == 0
    for tabla in ("cliente_documentos", "documentos", "vencimientos_fiscales_documentos", "correo_adjuntos"):
        conn = db.get_connection()
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE length(contenido) > 0").fetchone()[0]
        finally:
            conn.close()
        assert n == 0, tabla
    assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF and ad.leer_de_cliente_fiscal(t, c, 2)["contenido"] == PDF + b"2"
    assert ad.leer(t, u, 1)["contenido"] == PDF + b"4"
    assert db.contenido_documento_vencimiento(db.obtener_documento_vencimiento(1)) == PDF + b"3"
    assert bytes(db.obtener_adjunto_correo(1)["contenido"]) == PDF + b"5"
    assert sum(v["objetos"] for v in ao.resumen().values()) == 5
    capsys.readouterr()
    assert script.main(["migrar", "--aplicar"]) == 0 and "0 filas" in capsys.readouterr().out, "repetirlo no hace nada"
    assert script.main(["verificar"]) == 0
    assert script.main(["estado"]) == 0 and "fichero" in capsys.readouterr().out


def test_se_puede_migrar_un_solo_despacho_y_una_sola_tabla(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()
    otro, u2, c2 = _despacho("Despacho otro")
    ad.guardar_de_cliente_fiscal_sin_usuario(otro, c2, "otro.pdf", "application/pdf", PDF + b"9", "Factura")
    ao.fijar_almacen(ao.AlmacenFichero(tmp_path / "o"))
    script.main(["migrar", "--aplicar", "--tablas", "cliente_documentos", "--tenant", str(t)])
    assert _registro("cliente_documentos", 1) is not None and _registro("cliente_documentos", 3) is None, "el otro despacho no se ha tocado"
    assert _registro("documentos", 1) is None, "las demás tablas tampoco"


def test_un_fallo_del_almacen_para_la_migracion_sin_perder_nada(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()

    class Roto(ao.AlmacenFichero):
        def poner(self, clave, datos, tipo_mime=None):
            raise ao.ErrorAlmacenObjetos("sin conexión")
    ao.fijar_almacen(Roto(tmp_path / "o"))
    assert script.main(["migrar", "--aplicar"]) == 1
    assert bytes(_fila("cliente_documentos", 1)["contenido"]) == PDF and ao.resumen() == {}
    assert script.main(["migrar", "--aplicar", "--continuar"]) == 1


def test_no_se_vacia_la_base_si_lo_leido_de_vuelta_no_coincide(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()

    class Corrupto(ao.AlmacenFichero):
        def leer(self, clave):
            return b"corrupto"
    ao.fijar_almacen(Corrupto(tmp_path / "o"))
    assert script.main(["migrar", "--aplicar", "--tablas", "cliente_documentos"]) == 1
    assert bytes(_fila("cliente_documentos", 1)["contenido"]) == PDF and _registro("cliente_documentos", 1) is None


def test_verificar_detecta_objetos_distintos_faltantes_y_filas_vaciadas_sin_objeto(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()
    almacen = ao.AlmacenFichero(tmp_path / "o")
    ao.fijar_almacen(almacen)
    script.main(["migrar", "--aplicar", "--tablas", "cliente_documentos"])
    capsys.readouterr()
    r1, r2 = _registro("cliente_documentos", 1), _registro("cliente_documentos", 2)
    almacen.poner(r1["clave"], b"otra cosa")
    almacen.borrar(r2["clave"])
    conn = db.get_connection(); conn.execute("UPDATE documentos SET contenido = ? WHERE id = 1", (b"",)); conn.commit(); conn.close()
    assert script.main(["verificar"]) == 1
    salida = capsys.readouterr().out
    assert "DISTINTO cliente_documentos #1" in salida and "FALTA cliente_documentos #2" in salida and "SIN CONTENIDO documentos #1" in salida


def test_limpiar_borra_lo_de_filas_que_ya_no_existen_y_los_objetos_sin_registro(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()
    almacen = ao.AlmacenFichero(tmp_path / "o")
    ao.fijar_almacen(almacen)
    script.main(["migrar", "--aplicar", "--tablas", "cliente_documentos"])
    r1 = _registro("cliente_documentos", 1)
    conn = db.get_connection(); conn.execute("DELETE FROM cliente_documentos WHERE id = 1"); conn.commit(); conn.close()
    almacen.poner(f"t{t}/cliente_documentos/99-zzzzzzzzzzzz", b"huerfano")
    almacen.poner(f"t{t}/cliente_documentos/98-yyyyyyyyyyyy", b"huerfano reciente")
    import os
    for k in (f"t{t}/cliente_documentos/99-zzzzzzzzzzzz",):
        os.utime(almacen._ruta(k), (1, 1))
    capsys.readouterr()
    assert script.main(["limpiar", "--antiguedad-min", "60"]) == 0 and "Sobrarían: 2" in capsys.readouterr().out and almacen.tamano(r1["clave"]) is not None, "la simulación no borra"
    assert script.main(["limpiar", "--aplicar", "--antiguedad-min", "60"]) == 0
    assert almacen.tamano(r1["clave"]) is None and almacen.tamano(f"t{t}/cliente_documentos/99-zzzzzzzzzzzz") is None and _registro("cliente_documentos", 1) is None
    assert almacen.tamano(f"t{t}/cliente_documentos/98-yyyyyyyyyyyy") is not None, "lo reciente no se toca"
    assert almacen.tamano(_registro("cliente_documentos", 2)["clave"]) is not None, "lo que sigue en uso se queda"


def test_revertir_devuelve_el_contenido_a_la_base(capsys, tmp_path):
    t, u, c = _sembrar_en_la_base()
    almacen = ao.AlmacenFichero(tmp_path / "o")
    ao.fijar_almacen(almacen)
    script.main(["migrar", "--aplicar"])
    clave = _registro("cliente_documentos", 1)["clave"]
    assert script.main(["revertir", "--tablas", "cliente_documentos"]) == 0 and bytes(_fila("cliente_documentos", 1)["contenido"]) == b"", "sin --aplicar no hace nada"
    assert script.main(["revertir", "--aplicar", "--tablas", "cliente_documentos", "--borrar-objetos"]) == 0
    assert bytes(_fila("cliente_documentos", 1)["contenido"]) == PDF and _registro("cliente_documentos", 1) is None and almacen.tamano(clave) is None
    assert ad.leer_de_cliente_fiscal(t, c, 1)["contenido"] == PDF
    assert _registro("documentos", 1) is not None, "las otras tablas siguen fuera"


def test_no_se_admite_una_tabla_desconocida():
    with pytest.raises(SystemExit):
        script.main(["estado", "--tablas", "usuarios"])

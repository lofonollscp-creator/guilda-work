"""Exportación CSV/PDF/JSON del registro horario (app/fichaje_export.py)
-- sin tests hasta ahora."""
import csv
import io
import json
from datetime import datetime, timedelta

from app import db, fichaje_export


def _usuario(sufijo: str) -> int:
    return db.crear_usuario_vinculado_a_kratos(f"fichaje-export-{sufijo}@ejemplo.com", f"kratos-fichaje-export-{sufijo}")


def _jornada_completa(usuario_id: int, tenant_id: int | None) -> None:
    db.fichar(usuario_id, tenant_id, "entrada")
    db.fichar(usuario_id, tenant_id, "pausa_inicio")
    db.fichar(usuario_id, tenant_id, "pausa_fin")
    db.fichar(usuario_id, tenant_id, "salida")


def test_a_csv_incluye_cabecera_de_empresa_y_una_fila_por_dia():
    tenant_id = db.crear_tenant("Gestoria Fichaje Export")
    usuario_id = _usuario("csv")
    db.asignar_tenant(usuario_id, tenant_id)
    _jornada_completa(usuario_id, tenant_id)

    texto = fichaje_export.a_csv(tenant_id)
    lineas = texto.splitlines()
    assert lineas[0].startswith("# Empresa: Gestoria Fichaje Export")

    # las 3 líneas de cabecera (#) no son CSV -- se parsean el resto
    filas = list(csv.reader(io.StringIO("\n".join(lineas[3:]))))
    assert filas[0] == ["fecha", "trabajador", "dni_nie", "primera_entrada", "ultima_salida", "horas_trabajadas", "horas_pausa"]
    assert len(filas) == 2
    assert filas[1][1] == "fichaje-export-csv@ejemplo.com"


def test_a_csv_reparte_horas_en_turno_que_cruza_medianoche():
    """Bug encontrado en la auditoría de esta sesión (2026-09-30):
    filas_diarias() contabilizaba TODO el turno en el día de la
    salida, dejando el día de la entrada con 0 horas."""
    tenant_id = db.crear_tenant("Gestoria Fichaje Nocturno")
    usuario_id = _usuario("nocturno")
    db.asignar_tenant(usuario_id, tenant_id)

    base = datetime.now() - timedelta(days=3)
    medianoche = datetime(base.year, base.month, base.day)
    entrada_ts = (medianoche - timedelta(hours=1)).isoformat(timespec="seconds")
    salida_ts = (medianoche + timedelta(hours=1)).isoformat(timespec="seconds")
    db.fichar(usuario_id, tenant_id, "entrada", marca_tiempo=entrada_ts)
    db.fichar(usuario_id, tenant_id, "salida", marca_tiempo=salida_ts)

    texto = fichaje_export.a_csv(tenant_id)
    lineas = texto.splitlines()
    filas = list(csv.reader(io.StringIO("\n".join(lineas[3:]))))[1:]
    assert len(filas) == 2

    horas_por_fecha = {f[0]: float(f[5]) for f in filas}
    dia_entrada = (medianoche - timedelta(days=1)).strftime("%Y-%m-%d")
    dia_salida = medianoche.strftime("%Y-%m-%d")
    assert horas_por_fecha[dia_entrada] == 1.0
    assert horas_por_fecha[dia_salida] == 1.0


def test_a_csv_sin_tenant_no_falla():
    usuario_id = _usuario("sin-tenant")
    _jornada_completa(usuario_id, None)
    texto = fichaje_export.a_csv(None)
    assert "Sin tenant" in texto


def test_a_json_incluye_hash_y_datos_de_empresa():
    tenant_id = db.crear_tenant("Gestoria Fichaje JSON")
    usuario_id = _usuario("json")
    db.asignar_tenant(usuario_id, tenant_id)
    _jornada_completa(usuario_id, tenant_id)

    documento = json.loads(fichaje_export.a_json(tenant_id))
    assert documento["empresa"]["nombre"] == "Gestoria Fichaje JSON"
    assert len(documento["eventos"]) == 4
    assert all(e["hash"] for e in documento["eventos"])
    assert {e["tipo"] for e in documento["eventos"]} == {"entrada", "pausa_inicio", "pausa_fin", "salida"}


def test_a_json_filtra_por_usuario():
    tenant_id = db.crear_tenant("Gestoria Fichaje Filtro")
    usuario_a = _usuario("filtro-a")
    usuario_b = _usuario("filtro-b")
    db.asignar_tenant(usuario_a, tenant_id)
    db.asignar_tenant(usuario_b, tenant_id)
    _jornada_completa(usuario_a, tenant_id)
    _jornada_completa(usuario_b, tenant_id)

    documento = json.loads(fichaje_export.a_json(tenant_id, usuario_id=usuario_a))
    assert len(documento["eventos"]) == 4
    assert all(e["trabajador_email"] == "fichaje-export-filtro-a@ejemplo.com" for e in documento["eventos"])


def test_a_pdf_devuelve_bytes_de_un_pdf_valido():
    tenant_id = db.crear_tenant("Gestoria Fichaje PDF")
    usuario_id = _usuario("pdf")
    db.asignar_tenant(usuario_id, tenant_id)
    _jornada_completa(usuario_id, tenant_id)

    contenido = fichaje_export.a_pdf(tenant_id)
    assert isinstance(contenido, bytes)
    assert contenido.startswith(b"%PDF")
    assert len(contenido) > 500


def test_a_pdf_sin_fichajes_no_falla():
    tenant_id = db.crear_tenant("Gestoria Fichaje PDF Vacio")
    contenido = fichaje_export.a_pdf(tenant_id)
    assert contenido.startswith(b"%PDF")

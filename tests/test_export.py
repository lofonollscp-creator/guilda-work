"""Exportación de datos a JSON/CSV/Markdown para análisis por una IA
(app/export.py) -- sin tests hasta ahora."""
import csv
import io
import json
from datetime import datetime, timedelta

from app import db, export


def test_construir_export_incluye_notas_y_tareas(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "Nota suelta", categoria_id=cid)
    tarea_id = db.crear_tarea(usuario_id, "Revisión", cid, "instantanea")

    data = export.construir_export(usuario_id, None, None, None)
    origenes = {r["origen"] for r in data["registros"]}
    assert origenes == {"nota", "tarea"}
    assert data["filtro"] == {"desde": None, "hasta": None, "categoria_id": None}
    assert len(data["registros"]) == 2
    assert tarea_id  # sanity: se creó de verdad


def test_construir_export_filtra_por_categoria(usuario_id):
    cid_a = db.crear_categoria(usuario_id, "Lueira")
    cid_b = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "De Lueira", categoria_id=cid_a)
    db.crear_nota(usuario_id, "De Guilda", categoria_id=cid_b)

    data = export.construir_export(usuario_id, None, None, cid_a)
    assert len(data["registros"]) == 1
    assert data["registros"][0]["texto_o_nombre"] == "De Lueira"


def test_a_json_produce_json_valido(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "Nota", categoria_id=cid)
    texto = export.a_json(usuario_id)
    data = json.loads(texto)
    assert data["registros"][0]["texto_o_nombre"] == "Nota"


def test_a_csv_produce_csv_valido_con_las_columnas_esperadas(usuario_id):
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "Nota CSV", categoria_id=cid)
    texto = export.a_csv(usuario_id)
    filas = list(csv.DictReader(io.StringIO(texto)))
    assert len(filas) == 1
    assert filas[0]["texto_o_nombre"] == "Nota CSV"
    assert filas[0]["origen"] == "nota"


def test_a_markdown_agrupa_por_categoria(usuario_id):
    cid_a = db.crear_categoria(usuario_id, "Lueira")
    cid_b = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "Nota de Lueira", categoria_id=cid_a)
    db.crear_nota(usuario_id, "Nota de Guilda", categoria_id=cid_b)

    texto = export.a_markdown(usuario_id)
    assert "## Guilda" in texto
    assert "## Lueira" in texto
    # orden alfabético de categorías
    assert texto.index("## Guilda") < texto.index("## Lueira")
    assert "Nota de Lueira" in texto


def test_a_markdown_sin_categoria_usa_etiqueta_generica(usuario_id):
    db.crear_nota(usuario_id, "Nota huérfana")
    texto = export.a_markdown(usuario_id)
    assert "## Sin categoría" in texto


def test_generar_resumen_automatico_crea_el_fichero(monkeypatch, tmp_path, usuario_id):
    monkeypatch.setattr(export, "EXPORTS_AUTO_DIR", tmp_path)
    monkeypatch.setattr(db, "usuario_local_id", lambda: usuario_id)
    cid = db.crear_categoria(usuario_id, "Guilda")
    db.crear_nota(usuario_id, "Nota de ayer", categoria_id=cid)

    export.generar_resumen_automatico_si_hace_falta(dias_atras=0)

    ficheros = list(tmp_path.glob("resumen_*.md"))
    assert len(ficheros) == 1
    assert "Registro de actividad" in ficheros[0].read_text(encoding="utf-8")


def test_generar_resumen_automatico_no_lo_regenera_si_ya_existe(monkeypatch, tmp_path, usuario_id):
    monkeypatch.setattr(export, "EXPORTS_AUTO_DIR", tmp_path)
    monkeypatch.setattr(db, "usuario_local_id", lambda: usuario_id)
    tmp_path.mkdir(parents=True, exist_ok=True)
    fecha = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    destino = tmp_path / f"resumen_{fecha}.md"
    destino.write_text("contenido original", encoding="utf-8")

    export.generar_resumen_automatico_si_hace_falta(dias_atras=1)

    assert destino.read_text(encoding="utf-8") == "contenido original"


def test_generar_resumen_automatico_purga_ficheros_viejos(monkeypatch, tmp_path, usuario_id):
    monkeypatch.setattr(export, "EXPORTS_AUTO_DIR", tmp_path)
    monkeypatch.setattr(db, "usuario_local_id", lambda: usuario_id)
    tmp_path.mkdir(parents=True, exist_ok=True)
    viejo = tmp_path / "resumen_2020-01-01.md"
    viejo.write_text("viejo", encoding="utf-8")

    export.generar_resumen_automatico_si_hace_falta(dias_atras=1, mantener_dias=30)

    assert not viejo.exists()


def test_generar_resumen_automatico_ignora_ficheros_con_nombre_raro(monkeypatch, tmp_path, usuario_id):
    monkeypatch.setattr(export, "EXPORTS_AUTO_DIR", tmp_path)
    monkeypatch.setattr(db, "usuario_local_id", lambda: usuario_id)
    tmp_path.mkdir(parents=True, exist_ok=True)
    raro = tmp_path / "resumen_no-es-una-fecha.md"
    raro.write_text("x", encoding="utf-8")

    export.generar_resumen_automatico_si_hace_falta(dias_atras=1)

    assert raro.exists()  # no se toca, no se puede parsear como fecha

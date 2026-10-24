"""Diseño de registro OFICIAL del modelo 303 (ejercicio 2026, versión 1.01): el JSON versionado sale del xlsx de la AEAT y es coherente consigo mismo.

El exportador del 303 (F5 del módulo fiscal) se apoyará en este JSON: ni posiciones ni longitudes se escriben de memoria (docs/plan-modulo-fiscal-alquileres.md §5)."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.fiscal_modelos import disenos_oficiales as d

RAIZ = Path(__file__).resolve().parent.parent
XLSX = RAIZ / "docs" / "fuentes-oficiales" / "aeat" / "DR303e26v101.xlsx"
JSON_VERSIONADO = RAIZ / "app" / "fiscal_modelos" / "disenos" / "303_2026_v101.json"
MANIFIESTO = RAIZ / "docs" / "fuentes-oficiales" / "aeat" / "manifest.json"


@pytest.fixture(scope="module")
def versionado():
    return json.loads(JSON_VERSIONADO.read_text(encoding="utf-8"))


def test_el_json_versionado_se_regenera_igual_desde_el_xlsx_oficial(versionado):
    regenerado = json.loads(json.dumps(d.leer_diseno(XLSX), ensure_ascii=False))
    assert regenerado == versionado, "el diseño versionado no coincide con el xlsx oficial: regenera con scripts/fiscal/extraer_diseno.py"


def test_la_huella_del_xlsx_coincide_con_la_del_manifiesto_y_la_del_json(versionado):
    huella = hashlib.sha256(XLSX.read_bytes()).hexdigest()
    manifiesto = {f["fichero"]: f for f in json.loads(MANIFIESTO.read_text(encoding="utf-8"))}
    assert manifiesto["DR303e26v101.xlsx"]["sha256"] == huella == versionado["origen"]["sha256"]


def test_el_diseno_es_coherente_consigo_mismo(versionado):
    assert d.comprobar(versionado) == []


def test_estructura_conocida_del_fichero_303(versionado):
    totales = {p["hoja"]: p["total_posiciones"] for p in versionado["paginas"]}
    assert totales == {"DP30300": None, "DP30301": 1581, "DP30302": 1900, "DP30303": 1017, "DP30304": 998, "DP30305": 1528, "DP303DID": 823}
    p1 = next(p for p in versionado["paginas"] if p["hoja"] == "DP30301")
    nif = next(c for c in p1["campos"] if c["descripcion"] == "Identificación (1) - NIF")
    assert (nif["pos"], nif["lon"], nif["tipo"]) == (14, 9, "An")
    envoltura = versionado["paginas"][0]["campos"]
    assert [c["contenido"] for c in envoltura[:3]] == ['"<T"', '"303"', '"0"']


def test_indice_de_casillas_un_campo_por_casilla(versionado):
    ix = d.indice_casillas(versionado)
    assert len(ix) == 183 and all(len(v) == 1 for v in ix.values())
    base = ix["150"][0]
    assert (base["hoja"], base["pos"], base["lon"], base["tipo"], base["contenido"]) == ("DP30301", 131, 17, "Num", "15 enteros y 2 decimales")
    assert "Cuota" in ix["152"][0]["descripcion"] and ix["152"][0]["pos"] == 153


def test_comprobar_detecta_un_diseno_roto(versionado):
    roto = copy.deepcopy(versionado)
    roto["paginas"][1]["campos"][6]["pos"] += 1                   # un hueco entre campos
    assert any("debería en" in p for p in d.comprobar(roto))
    roto = copy.deepcopy(versionado)
    roto["paginas"][2]["total_posiciones"] += 5                   # el TOTAL declarado no cuadra
    assert any("TOTAL declarado" in p for p in d.comprobar(roto))

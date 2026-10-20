"""Dependencia `mcp` (SDK del servidor MCP): versión mínima con los parches de seguridad y decisión explícita sobre el recurso del token."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_requirements_mcp_exige_una_version_parcheada_y_se_queda_en_la_rama_1():
    texto = (RAIZ / "requirements-mcp.txt").read_text(encoding="utf-8")
    linea = next(l for l in texto.splitlines() if re.match(r"mcp\s*[<>=~!]", l))
    minimo = re.search(r">=\s*(\d+)\.(\d+)\.(\d+)", linea)
    assert minimo and tuple(map(int, minimo.groups())) >= (1, 30, 0), linea          # 1.29.x tiene avisos de seguridad conocidos
    assert re.search(r"<\s*2(\.0(\.0)?)?\s*$", linea.strip()), "la 2.x cambia la API: migrarla es otra tarea"


def test_el_servidor_remoto_no_deja_sin_decidir_la_validacion_del_recurso_del_token():
    fuente = (RAIZ / "mcp_server_remoto.py").read_text(encoding="utf-8")
    assert re.search(r"validate_token_resource\s*=\s*(True|False)", fuente), "sin valor explícito, el SDK avisa y cambiará el comportamiento en la 3.0"


def test_el_servidor_remoto_se_construye_con_la_version_instalada_sin_avisos_de_obsolescencia():
    import importlib
    import importlib.metadata
    import warnings

    import pytest
    instalada = tuple(int(x) for x in re.findall(r"\d+", importlib.metadata.version("mcp"))[:3])
    if instalada < (1, 30, 0):
        pytest.skip(f"mcp {importlib.metadata.version('mcp')} instalado: actualiza con «pip install -r requirements-mcp.txt» (la versión mínima ya está fijada)")
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        remoto = importlib.import_module("mcp_server_remoto")
    assert remoto.mcp.settings.auth.validate_token_resource is False
    assert len(remoto.mcp._tool_manager.list_tools()) > 100

"""Protección de datos personales antes de enviar texto a la IA (app/anonimizar.py + su uso en app/ia_asistente.py). Carga el detector real (Presidio + spaCy, ≈2 s)."""
import json

import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip(__import__("app.anonimizar", fromlist=["x"]).MODELO_SPACY)

from app import anonimizar, db, ia_asistente as a  # noqa: E402
from tests.test_ia_asistente import _chunks_texto, _encolar_stream, _preparar, _respuesta_texto, _respuesta_tool_calls  # noqa: E402

TEXTO = ("Juan Pérez García (DNI 12345678Z, NIE X1234567L) debe 300 € a Construcciones Vidal SL con CIF B12345674. IBAN ES91 2100 0418 4502 0005 1332, "
         "correo juan.perez@ejemplo.com, móvil +34 612 345 678, fijo 91 123 45 67, vive en Calle Mayor 12, 3º B, Madrid. Tarjeta 4111 1111 1111 1111.")
PERSONALES = ["Juan Pérez García", "12345678Z", "X1234567L", "B12345674", "ES91 2100 0418 4502 0005 1332", "juan.perez@ejemplo.com", "612 345 678", "91 123 45 67", "Calle Mayor 12", "4111 1111 1111 1111"]


@pytest.fixture(autouse=True)
def _activada(monkeypatch):
    monkeypatch.setenv("GUILDA_IA_ANONIMIZAR", "1")


def test_se_protegen_los_datos_personales_y_se_restauran():
    sp = anonimizar.Seudonimizador()
    protegido = sp.proteger(TEXTO)
    for dato in PERSONALES:
        assert dato not in protegido, dato
    assert "Construcciones Vidal SL" in protegido and "Madrid" in protegido and "300 €" in protegido      # lo que no es una persona se queda
    assert sp.restaurar(protegido) == TEXTO


def test_mismo_valor_misma_etiqueta_y_formatos_distintos_del_iban():
    sp = anonimizar.Seudonimizador()
    p = sp.proteger("Pagar a Marta Ruiz. Otra vez Marta Ruiz. IBAN ES9121000418450200051332 y ES91 2100 0418 4502 0005 1332.")
    assert p.count("[PERSONA_1]") == 2 and p.count("[IBAN_1]") == 2 and "[IBAN_2]" not in p


def test_cif_con_digito_de_control_malo_no_se_toca_y_nif_con_letra_mala_tampoco():
    p = anonimizar.Seudonimizador().proteger("Presupuesto B12345679 y 12345678A.")
    assert "[CIF" not in p and "[NIF" not in p


def test_no_hay_envio_ni_cambio_si_esta_desactivada(monkeypatch):
    monkeypatch.setenv("GUILDA_IA_ANONIMIZAR", "0")
    assert anonimizar.Seudonimizador().proteger(TEXTO) == TEXTO


def test_argumentos_json_se_restauran_y_siguen_siendo_json():
    sp = anonimizar.Seudonimizador()
    marca = sp.proteger("Juan Pérez García")
    argumentos = json.dumps({"asunto": f"Llamar a {marca}", "n": 3, "lista": [marca]})
    assert json.loads(sp.restaurar_argumentos(argumentos)) == {"asunto": "Llamar a Juan Pérez García", "n": 3, "lista": ["Juan Pérez García"]}


def test_el_stream_restaura_etiquetas_partidas_entre_trozos():
    sp = anonimizar.Seudonimizador()
    marca = sp.proteger("Juan Pérez García")                    # [PERSONA_1]
    r = anonimizar.RestauradorEnStream(sp)
    salida = "".join([r.alimentar("Hola [PER"), r.alimentar("SONA_1], tu [x"), r.alimentar("] saldo"), r.terminar()])
    assert salida == "Hola Juan Pérez García, tu [x] saldo" and marca == "[PERSONA_1]"


def test_si_el_detector_falla_no_se_envia_nada(monkeypatch, usuario_id):
    _preparar(usuario_id)
    monkeypatch.setattr(anonimizar, "_detectar", lambda texto: (_ for _ in ()).throw(anonimizar.ErrorProteccionDatos("no disponible")))
    enviado = []
    monkeypatch.setattr(a, "_post_json", lambda url, payload, key: enviado.append(payload) or _respuesta_texto("x"))
    with pytest.raises(a.ErrorIA):
        a.procesar_turno(usuario_id, "Hola, soy Juan Pérez")
    assert enviado == []


def test_el_proveedor_no_recibe_datos_personales_y_las_herramientas_si(monkeypatch, usuario_id):
    """Turno completo: el proveedor solo ve etiquetas; la herramienta que pide con etiquetas recibe el dato real; la respuesta vuelve con el dato real."""
    _preparar(usuario_id, modo_autonomo=True)
    payloads, ejecutadas = [], []
    respuestas = [
        _respuesta_tool_calls(("c1", "crear_nota", {"titulo": "Llamar a [PERSONA_1]", "contenido": "NIF [NIF_1]"})),
        _respuesta_texto("Hecho: nota sobre [PERSONA_1] creada."),
    ]
    monkeypatch.setattr(a, "_post_json", lambda url, payload, key: payloads.append(json.dumps(payload, ensure_ascii=False)) or respuestas.pop(0))
    monkeypatch.setattr(a.herramientas, "ejecutar", lambda uid, nombre, args: ejecutadas.append((nombre, args)) or {"ok": True, "nota": "Nota de Juan Pérez García"})
    resultado = a.procesar_turno(usuario_id, "Crea una nota para llamar a Juan Pérez García, NIF 12345678Z")
    assert ejecutadas == [("crear_nota", {"titulo": "Llamar a Juan Pérez García", "contenido": "NIF 12345678Z"})]
    assert resultado["mensajes_nuevos"][-1]["contenido"] == "Hecho: nota sobre Juan Pérez García creada."
    for cuerpo in payloads:
        assert "Juan Pérez" not in cuerpo and "12345678Z" not in cuerpo, cuerpo       # ni en el mensaje, ni en el resultado de la herramienta, ni en el historial
    assert "[PERSONA_1]" in payloads[0] and "[NIF_1]" in payloads[0]


def test_stream_completo_restaura_el_texto_y_no_filtra(monkeypatch, usuario_id):
    _preparar(usuario_id)
    enviados = []

    def falso(url, payload, claves):
        enviados.append(json.dumps(payload, ensure_ascii=False))
        return iter(_chunks_texto("Claro, [PER", "SONA_1] tiene el NIF [NIF", "_1]."))

    monkeypatch.setattr(a, "_post_json_stream_con_fallback", falso)
    eventos = list(a.procesar_turno_stream(usuario_id, "Dime el NIF de Juan Pérez García (12345678Z)"))
    texto = "".join(e["texto"] for e in eventos if e["tipo"] == "delta")
    assert texto == "Claro, Juan Pérez García tiene el NIF 12345678Z."
    assert "Juan Pérez" not in enviados[0] and "12345678Z" not in enviados[0]
    assert [m["contenido"] for m in db.listar_mensajes_ia(usuario_id) if m["rol"] == "assistant"] == ["Claro, Juan Pérez García tiene el NIF 12345678Z."]


def test_completar_texto_protege_y_restaura(monkeypatch, usuario_id):
    _preparar(usuario_id)
    enviados = []
    monkeypatch.setattr(a, "_post_json", lambda url, payload, key: enviados.append(json.dumps(payload, ensure_ascii=False)) or _respuesta_texto("Resumen: [PERSONA_1] reclama una factura."))
    assert a.completar_texto(usuario_id, "Resume el correo", "De: Marta Ruiz <marta@ejemplo.com>. Hola, soy Marta Ruiz.") == "Resumen: Marta Ruiz reclama una factura."
    assert "Marta" not in enviados[0] and "marta@ejemplo.com" not in enviados[0]

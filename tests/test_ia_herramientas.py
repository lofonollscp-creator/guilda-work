"""Tests de app/ia_herramientas.py: el catálogo de herramientas del
Asistente IA y su dispatcher, que reutiliza directamente las funciones ya
definidas en mcp_server.py."""
import pytest

import mcp_tools
from app import db, ia_herramientas as h


def test_catalogo_tiene_las_mismas_69_herramientas_clasificadas():
    # 52 de antes + 16 de la ampliación Drive/CRM/Firmas/Hojas: CRM (6),
    # Drive (4, incluye enviar_archivo_drive_al_chat), Firmas (4, incluye
    # enviar_documento_firmado_al_chat), Hojas solo lectura (2 --
    # hojas_crear_fila NO se registra aquí, decisión explícita del
    # usuario) + 1 del generador de documentos/informes
    # (generar_documento_al_chat).
    nombres = {t["function"]["name"] for t in h.HERRAMIENTAS}
    assert len(nombres) == 69
    assert nombres == (h.LECTURA | h.ESCRITURA | h.SIEMPRE_CONFIRMAR)
    assert not (h.LECTURA & h.ESCRITURA)
    assert not (h.LECTURA & h.SIEMPRE_CONFIRMAR)
    assert not (h.ESCRITURA & h.SIEMPRE_CONFIRMAR)


def test_ejecutar_crear_nota_usa_mcp_server_directamente(usuario_id):
    resultado = h.ejecutar(usuario_id, "crear_nota", {"texto": "creada por el asistente"})
    assert resultado["texto"] == "creada por el asistente"
    notas = [n for n in db.historial(usuario_id) if n["origen"] == "nota"]
    assert len(notas) == 1


def test_ejecutar_herramienta_desconocida_da_error_legible(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "no_existe", {})


def test_ejecutar_propaga_value_error_como_error_de_herramienta(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "editar_nota", {"nota_id": 9999, "texto": "x"})


@pytest.mark.parametrize(
    "nombre,modo_autonomo,esperado",
    [
        ("listar_notas", False, False),
        ("listar_notas", True, False),
        ("crear_nota", False, True),
        ("crear_nota", True, False),
        ("enviar_borrador_correo", True, True),
        ("enviar_borrador_correo", False, True),
    ],
)
def test_necesita_confirmacion(nombre, modo_autonomo, esperado):
    assert h.necesita_confirmacion(nombre, modo_autonomo) is esperado


# --- Calendario fiscal (Fase G2) ----------------------------------------------

def test_tools_fiscales_sin_tenant_dan_error_legible(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA, match="tenant"):
        h.ejecutar(usuario_id, "listar_clientes_fiscales", {})


def test_tools_fiscales_ciclo_completo(usuario_id):
    tenant_id = db.crear_tenant("Gestoria IA Herramientas")
    db.asignar_tenant(usuario_id, tenant_id)

    creado = h.ejecutar(usuario_id, "crear_cliente_fiscal", {"nombre": "Cliente IA", "modelos_fiscales": ["303"]})
    assert creado["nombre"] == "Cliente IA"

    listado = h.ejecutar(usuario_id, "listar_clientes_fiscales", {})
    assert len(listado) == 1

    generado = h.ejecutar(
        usuario_id, "generar_vencimientos_fiscales",
        {"cliente_id": creado["id"], "modelos": ["303"], "anio": 2026},
    )
    assert generado["creados"] == 4

    vencimientos = h.ejecutar(usuario_id, "listar_vencimientos_fiscales", {})
    assert len(vencimientos) == 4

    v_id = vencimientos[0]["id"]
    editado = h.ejecutar(usuario_id, "editar_vencimiento_fiscal", {"vencimiento_id": v_id, "notas": "revisado"})
    assert editado["notas"] == "revisado"

    marcado = h.ejecutar(usuario_id, "marcar_presentado_vencimiento_fiscal", {"vencimiento_id": v_id})
    assert marcado["estado"] == "presentado"

    resumen = h.ejecutar(usuario_id, "resumen_cliente_fiscal", {"cliente_id": creado["id"]})
    assert resumen["total_vencimientos"] == 4
    assert resumen["pendientes"] == 3
    assert resumen["total_documentos"] == 0
    assert resumen["total_mensajes"] == 0


# --- Adjuntos del chat (Fase G2) ----------------------------------------------

def test_leer_adjunto_chat_es_privado_del_usuario(usuario_id):
    otro_usuario_id = db.crear_usuario_vinculado_a_kratos("otro-adjunto@ejemplo.com", "kratos-otro-adjunto")
    adjunto_id = db.crear_adjunto_ia(usuario_id, "datos.csv", "text/csv", b"a,b\n1,2\n")

    resultado = h.ejecutar(usuario_id, "leer_adjunto_chat", {"adjunto_id": adjunto_id})
    assert resultado["nombre_archivo"] == "datos.csv"
    assert "1,2" in resultado["texto"]

    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(otro_usuario_id, "leer_adjunto_chat", {"adjunto_id": adjunto_id})


# --- Tercera ronda de mejoras: plantillas, tareas recurrentes, facturación --

def test_listar_plantillas_correo_tool(usuario_id):
    db.crear_plantilla_correo(usuario_id, "Recordatorio", "Docs pendientes", "Hola, nos falta la factura.")

    resultado = h.ejecutar(usuario_id, "listar_plantillas_correo", {})
    assert len(resultado) == 1
    assert resultado[0]["nombre"] == "Recordatorio"


def test_tareas_recurrentes_tool_ciclo_completo(usuario_id):
    creada = h.ejecutar(
        usuario_id, "crear_tarea_recurrente", {"asunto": "Revisar correo", "periodicidad": "semanal", "dia": 0},
    )
    assert creada["asunto"] == "Revisar correo"
    assert creada["activa"] == 1

    listado = h.ejecutar(usuario_id, "listar_tareas_recurrentes", {})
    assert len(listado) == 1
    assert listado[0]["id"] == creada["id"]


def test_crear_tarea_recurrente_periodicidad_invalida_lanza_error(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "crear_tarea_recurrente", {"asunto": "X", "periodicidad": "diaria", "dia": 0})


def test_facturas_cliente_tool_ciclo_completo(usuario_id, monkeypatch):
    from app import facturascripts

    tenant_id = db.crear_tenant("Gestoria IA Facturas")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_facturascripts(tenant_id, "http://127.0.0.1:8107/", "admin", "clave-admin")
    db.guardar_facturascripts_api_key(tenant_id, "clave-fs")
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente IA Facturas")
    db.editar_cliente_fiscal(tenant_id, cliente_id, facturascripts_cliente_codigo="7")

    monkeypatch.setattr(facturascripts, "listar_facturas", lambda *a, **k: [{"idfactura": 1, "total": 150.5}])
    llamadas = []
    monkeypatch.setattr(
        facturascripts, "crear_factura",
        lambda url, api_key, codigo, lineas: llamadas.append((codigo, lineas)) or {"idfactura": 2},
    )

    listado = h.ejecutar(usuario_id, "listar_facturas_cliente", {"cliente_id": cliente_id})
    assert listado == [{"idfactura": 1, "total": 150.5}]

    creada = h.ejecutar(
        usuario_id, "crear_factura_cliente",
        {"cliente_id": cliente_id, "concepto": "Presentación 303 T1", "importe": 150.5},
    )
    assert creada == {"idfactura": 2}
    assert llamadas == [("7", [{"descripcion": "Presentación 303 T1", "cantidad": 1, "precio": 150.5}])]


def test_listar_facturas_cliente_sin_vincular_lanza_error(usuario_id):
    tenant_id = db.crear_tenant("Gestoria IA Sin Vincular")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Sin Vincular")

    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "listar_facturas_cliente", {"cliente_id": cliente_id})


# --- Ampliación: CRM, Drive, Firmas, Hojas -------------------------------------

def test_crm_tools(usuario_id, monkeypatch):
    monkeypatch.setattr(mcp_tools.espocrm, "listar_leads", lambda **k: [{"id": "1", "name": "Lead X"}])
    llamadas = []
    monkeypatch.setattr(
        mcp_tools.espocrm, "crear_lead",
        lambda nombre, **k: llamadas.append((nombre, k)) or {"id": "2", "name": nombre},
    )

    listado = h.ejecutar(usuario_id, "crm_listar_leads", {"texto": "X"})
    assert listado == [{"id": "1", "name": "Lead X"}]

    creado = h.ejecutar(usuario_id, "crm_crear_lead", {"nombre": "Nuevo Lead", "email": "a@b.com"})
    assert creado["name"] == "Nuevo Lead"
    assert llamadas == [("Nuevo Lead", {"email": "a@b.com", "telefono": "", "empresa": ""})]


def test_drive_listar_y_subir_tools(usuario_id, monkeypatch):
    monkeypatch.setattr(mcp_tools.nextcloud, "listar_archivos", lambda carpeta: [{"nombre": "a.txt"}])
    subidos = []
    monkeypatch.setattr(
        mcp_tools.nextcloud, "subir_archivo",
        lambda ruta, contenido: subidos.append((ruta, contenido)) or {"ok": True},
    )

    listado = h.ejecutar(usuario_id, "drive_listar_archivos", {"carpeta": "Lueira"})
    assert listado == [{"nombre": "a.txt"}]

    h.ejecutar(usuario_id, "drive_subir_archivo", {"ruta": "Lueira/nota.txt", "contenido_texto": "hola"})
    assert subidos == [("Lueira/nota.txt", b"hola")]


def test_enviar_archivo_drive_al_chat_guarda_adjunto_con_origen_asistente(usuario_id, monkeypatch):
    monkeypatch.setattr(mcp_tools.nextcloud, "descargar_archivo", lambda ruta: b"\xff\xd8\xff contenido binario")

    resultado = h.ejecutar(usuario_id, "enviar_archivo_drive_al_chat", {"ruta": "Lueira/foto.jpg"})
    assert resultado["nombre_archivo"] == "foto.jpg"
    assert resultado["tipo_mime"] == "image/jpeg"

    adjunto = db.obtener_adjunto_ia(usuario_id, resultado["adjunto_id"])
    assert adjunto["origen"] == "asistente"
    assert adjunto["contenido"] == b"\xff\xd8\xff contenido binario"


def test_enviar_archivo_al_chat_respeta_el_limite_de_tamano(usuario_id, monkeypatch):
    demasiado_grande = b"x" * (mcp_tools.TAMANO_MAXIMO_ADJUNTO_ASISTENTE_BYTES + 1)
    monkeypatch.setattr(mcp_tools.nextcloud, "descargar_archivo", lambda ruta: demasiado_grande)

    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "enviar_archivo_drive_al_chat", {"ruta": "Lueira/grande.pdf"})


def test_firmas_tools_sin_tenant_dan_error_legible(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA, match="tenant"):
        h.ejecutar(usuario_id, "listar_documentos_firma", {})


def test_firmas_tools_sin_token_documenso_da_error_legible(usuario_id):
    tenant_id = db.crear_tenant("Gestoria IA Firmas Sin Token")
    db.asignar_tenant(usuario_id, tenant_id)

    with pytest.raises(h.ErrorHerramientaIA, match="Documenso"):
        h.ejecutar(usuario_id, "listar_documentos_firma", {})


def test_firmas_tools_ciclo_completo(usuario_id, monkeypatch):
    tenant_id = db.crear_tenant("Gestoria IA Firmas")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_documenso_api_key(tenant_id, "token-documenso")

    monkeypatch.setattr(mcp_tools.documenso, "listar_documentos", lambda api_key, **k: [{"id": "d1"}])
    monkeypatch.setattr(mcp_tools.documenso, "descargar_firmado", lambda api_key, documento_id: b"%PDF-contenido")

    listado = h.ejecutar(usuario_id, "listar_documentos_firma", {})
    assert listado == [{"id": "d1"}]

    resultado = h.ejecutar(usuario_id, "enviar_documento_firmado_al_chat", {"documento_id": "d1"})
    assert resultado["tipo_mime"] == "application/pdf"
    adjunto = db.obtener_adjunto_ia(usuario_id, resultado["adjunto_id"])
    assert adjunto["origen"] == "asistente"
    assert adjunto["contenido"] == b"%PDF-contenido"


def test_hojas_tools_ciclo_completo(usuario_id, monkeypatch):
    tenant_id = db.crear_tenant("Gestoria IA Hojas")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_baserow(tenant_id, 1, "token-baserow")

    monkeypatch.setattr(mcp_tools.baserow, "listar_tablas", lambda api_key: [{"id": 1, "name": "Tabla X"}])
    monkeypatch.setattr(mcp_tools.baserow, "listar_filas", lambda api_key, tabla_id, **k: [{"id": 1}])

    tablas = h.ejecutar(usuario_id, "listar_tablas_hojas", {})
    assert tablas == [{"id": 1, "name": "Tabla X"}]

    filas = h.ejecutar(usuario_id, "listar_filas_hoja", {"tabla_id": 1})
    assert filas == [{"id": 1}]

    # hojas_crear_fila NO está en el catálogo del chat interno (decisión
    # del usuario) -- confirmar que sigue rechazada como desconocida.
    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(usuario_id, "hojas_crear_fila", {"tabla_id": 1, "campos": {}})


# --- Generador de documentos/informes ------------------------------------------

def test_generar_documento_al_chat_cada_formato(usuario_id):
    for formato, firma_magica in [("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK\x03\x04"), ("docx", b"PK\x03\x04"), ("pdf", b"%PDF")]:
        resultado = h.ejecutar(
            usuario_id, "generar_documento_al_chat",
            {"titulo": f"Informe {formato}", "formato": formato, "columnas": ["Nombre", "Importe"],
             "filas": [["Cliente A", 100], ["Cliente B", 200]]},
        )
        assert resultado["nombre_archivo"] == f"Informe {formato}.{formato}"
        adjunto = db.obtener_adjunto_ia(usuario_id, resultado["adjunto_id"])
        assert adjunto["origen"] == "asistente"
        assert adjunto["contenido"].startswith(firma_magica)


def test_generar_documento_al_chat_formato_no_soportado_lanza_error(usuario_id):
    with pytest.raises(h.ErrorHerramientaIA):
        h.ejecutar(
            usuario_id, "generar_documento_al_chat",
            {"titulo": "X", "formato": "txt", "columnas": ["A"], "filas": [["1"]]},
        )

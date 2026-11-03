"""Medición con volumen (X1): 5.000 correos y 2.000 tareas con clientes, comentarios y subtareas, y el tiempo que tardan las pantallas que más se abren. Solo corre con GUILDA_VOLUMEN=1 (tarda): es una
herramienta de revisión, no un test de regresión; el límite es generoso para que solo salte ante un problema real (una consulta por fila, una lista sin paginar)."""
import os
import time

import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba

pytestmark = pytest.mark.skipif(not os.environ.get("GUILDA_VOLUMEN"), reason="GUILDA_VOLUMEN sin definir")
LIMITE_SEGUNDOS = float(os.environ.get("GUILDA_VOLUMEN_LIMITE", 4))


def _sembrar(uid, t):
    cf = [db.crear_cliente_fiscal(t, f"Cliente {i:03d} SL", nif=f"B{10000000 + i}") for i in range(60)]
    cuenta = db.crear_cuenta_correo(uid, "info@despacho.es", "imap", "imap.ejemplo.com", 993, "info@despacho.es")
    conn = db.get_connection()
    try:
        for i in range(5000):
            conn.execute("INSERT INTO correo_mensajes (cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, descargado_en, leido, hilo_clave, cliente_fiscal_id) "
                         "VALUES (?, 'INBOX', ?, ?, ?, 'info@despacho.es', ?, ?, ?, ?, ?, ?)",
                         (cuenta, f"u{i}", f"Asunto número {i} sobre el modelo 303", f"persona{i % 200}@ejemplo.com", f"2026-10-{1 + i % 28:02d}T10:{i % 60:02d}:00", "Texto del correo " * 20, "2026-11-01T00:00:00", i % 3 == 0, f"h{i // 3}", cf[i % 60] if i % 4 == 0 else None))
        for i in range(2000):
            cur = conn.execute("INSERT INTO tareas_outlook (usuario_id, asunto, cuerpo, estado, prioridad, fecha_vencimiento, cliente_fiscal_id, creada_en, actualizada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (uid, f"Tarea {i} del modelo {100 + i % 30}", "Descripción " * 10, ["no_iniciada", "en_progreso", "esperando"][i % 3], ["alta", "normal", "baja"][i % 3], f"2026-{11 + i % 2:02d}-{1 + i % 28:02d}", cf[i % 60], "2026-10-01T00:00:00", "2026-10-01T00:00:00"))
            if i % 5 == 0:
                conn.execute("INSERT INTO tarea_comentarios (tarea_id, usuario_id, texto, creado_en) VALUES (?, ?, 'Comentario sobre extractos', '2026-10-02T00:00:00')", (cur.lastrowid, uid))
                conn.execute("INSERT INTO tarea_checklist (tarea_outlook_id, texto, hecha, orden) VALUES (?, 'Subtarea de revisión', 0, 1)", (cur.lastrowid,))
        conn.commit()
    finally:
        conn.close()
    return cuenta


def test_las_pantallas_principales_aguantan_el_volumen(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "volumen@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho volumen")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    cuenta = _sembrar(uid, t)
    rutas = ["/hoy/", "/", "/tareas/", "/tareas/?agrupar=cliente", "/tareas/?q=extractos", "/tareas/hoy", "/tareas/carga", "/tareas/informes", f"/correo/?cuenta_id={cuenta}",
             f"/correo/?cuenta_id={cuenta}&q=asunto:303", f"/correo/?cuenta_id={cuenta}&no_leidos=1", "/fiscal/panel"]
    lentas = []
    for ruta in rutas:
        inicio = time.monotonic()
        r = cliente.get(ruta)
        dur = time.monotonic() - inicio
        print(f"VOLUMEN {dur:6.2f} s  {r.status_code}  {ruta}  ({len(r.data) // 1024} KB)")
        assert r.status_code in (200, 302), ruta
        if dur > LIMITE_SEGUNDOS:
            lentas.append((ruta, round(dur, 2)))
    assert not lentas, lentas

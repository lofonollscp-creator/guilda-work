"""Alertas de anomalías (W7): cada regla salta cuando toca, no salta cuando no, y explica por qué."""
from datetime import date, timedelta

import pytest

from app import anomalias, db, facturas_contables as fc, verticales

HOY = date(2026, 11, 11)


_N = [0]


def _t():
    _N[0] += 1
    t = db.crear_tenant(f"Anomalías {_N[0]}")
    verticales.fijar_activo(t, "contabilizacion", True)
    return t, db.crear_cliente_fiscal(t, "Cliente Alertas SL", email="a@ejemplo.com")


def _f(c, dias_atras, total="100,00", tipo="recibida", nombre="Proveedor", nif="B11111111", num=None):
    f = (HOY - timedelta(days=dias_atras)).isoformat()
    return fc.crear_desde_portal(c, {"tipo": tipo, "fecha": f, "numero": num or f"N-{dias_atras}-{total}", "tercero_nombre": nombre, "tercero_nif": nif, "total": total, "pct_iva": "21"})


def _tipos(t):
    return [a["tipo"] for a in anomalias.detectar(t, HOY)]


def test_un_cliente_que_dejo_de_subir_facturas_salta_y_uno_regular_no():
    t, c = _t()
    for d in (220, 190, 160, 130, 100):                      # una cada 30 días y la última hace 100 (más del triple del intervalo)
        _f(c, d)
    assert _tipos(t) == ["sin_facturas"]
    a = anomalias.detectar(t, HOY)[0]
    assert a["datos"]["dias_sin"] == 100 and a["datos"]["intervalo_habitual"] == 30
    t2, c2 = _t()
    for d in (90, 60, 30, 5):                                # al día
        _f(c2, d)
    assert "sin_facturas" not in _tipos(t2)


def test_un_cliente_con_pocas_facturas_no_genera_alerta():
    t, c = _t()
    _f(c, 200); _f(c, 150)
    assert _tipos(t) == []


def test_un_gasto_muy_por_encima_de_lo_habitual_salta_con_su_media():
    t, c = _t()
    for i in range(10):
        _f(c, 100 - i * 5, total=f"{100 + i},00", nombre=f"Proveedor {i}", nif=f"B2222222{i}")
    _f(c, 3, total="2500,00", nombre="Reformas Raras", nif="B33333333")
    alertas = [a for a in anomalias.detectar(t, HOY) if a["tipo"] == "gasto_atipico"]
    assert len(alertas) == 1 and alertas[0]["datos"]["importe"] == 250000 and alertas[0]["datos"]["proveedor"] == "Reformas Raras"


def test_un_gasto_normal_o_con_pocas_anteriores_no_salta():
    t, c = _t()
    for i in range(10):
        _f(c, 100 - i * 5, total=f"{100 + i},00", nombre=f"P{i}", nif=f"B2222222{i}")
    _f(c, 3, total="130,00", nombre="Normal", nif="B44444444")
    assert "gasto_atipico" not in _tipos(t)
    t2, c2 = _t()
    for i in range(3):
        _f(c2, 50 - i, total="100,00", nombre=f"P{i}", nif=f"B5555555{i}")
    _f(c2, 2, total="5000,00", nombre="Grande", nif="B66666666")
    assert "gasto_atipico" not in _tipos(t2)                 # sin histórico suficiente no se opina


def test_dos_facturas_iguales_cercanas_son_posible_duplicado():
    t, c = _t()
    _f(c, 10, total="250,00", num="A-1")
    _f(c, 9, total="250,00", num="A-2")
    _f(c, 8, total="250,00", nombre="Otro", nif="B77777777", num="A-3")        # otro proveedor: no cuenta
    d = [a for a in anomalias.detectar(t, HOY) if a["tipo"] == "duplicada"]
    assert len(d) == 1 and d[0]["severidad"] == "alta"


def test_vencimientos_sin_documentacion_y_vencidos():
    t, c = _t()
    v1 = db.crear_vencimiento_fiscal(t, c, "303", "3T", (HOY + timedelta(days=2)).isoformat())
    v2 = db.crear_vencimiento_fiscal(t, c, "111", "3T", (HOY + timedelta(days=6)).isoformat())
    v3 = db.crear_vencimiento_fiscal(t, c, "115", "3T", (HOY - timedelta(days=4)).isoformat())
    v4 = db.crear_vencimiento_fiscal(t, c, "130", "3T", (HOY + timedelta(days=30)).isoformat())
    conn = db.get_connection()
    for v in (v1, v2, v4):
        conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto del banco' WHERE id = ?", (v,))
    conn.commit(); conn.close()
    por = {(a["tipo"], a["modelo"]): a for a in anomalias.detectar(t, HOY)}
    assert por[("vencimiento_sin_documentos", "303")]["severidad"] == "alta" and por[("vencimiento_sin_documentos", "111")]["severidad"] == "media"
    assert por[("vencido_sin_presentar", "115")]["datos"]["dias"] == 4
    assert ("vencimiento_sin_documentos", "130") not in por                              # vence en 30 días: todavía no
    db.subir_documento_vencimiento(v1, "extracto.pdf", "application/pdf", b"%PDF-1.4\n%%EOF")
    assert ("vencimiento_sin_documentos", "303") not in {(a["tipo"], a.get("modelo")) for a in anomalias.detectar(t, HOY)}      # ya llegó algo




def test_la_pantalla_de_alertas_las_enseña_con_su_explicacion(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    t = db.crear_tenant("Anomalías web")
    u = iniciar_sesion_de_prueba(cliente, "alertas-web@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t)
    c = db.crear_cliente_fiscal(t, "Cliente Web SL", email="w@ejemplo.com")
    v = db.crear_vencimiento_fiscal(t, c, "303", "3T", (date.today() - timedelta(days=3)).isoformat())
    html = cliente.get("/fiscal/alertas").get_data(as_text=True)
    assert "Modelo 303 de Cliente Web SL sin presentar" in html and "La fecha límite pasó hace 3 días." in html and f"/fiscal/vencimientos/{v}/editar" in html
    db.eliminar_vencimiento_fiscal(t, v) if hasattr(db, "eliminar_vencimiento_fiscal") else None


def test_una_alerta_se_convierte_en_tarea_una_sola_vez(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    t = db.crear_tenant("Anomalías tarea")
    u = iniciar_sesion_de_prueba(cliente, "alertas-tarea@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t)
    c = db.crear_cliente_fiscal(t, "Cliente Tarea SL", email="t@ejemplo.com")
    v = db.crear_vencimiento_fiscal(t, c, "303", "3T", (date.today() - timedelta(days=3)).isoformat())
    html = cliente.get("/fiscal/alertas").get_data(as_text=True)
    import re
    clave = re.search(r'name="clave" value="([^"]+)"', html).group(1)
    assert clave == f"vencido_sin_presentar:{c}:{v}"
    for _ in range(2):                                                                    # pulsar dos veces no duplica
        r = cliente.post("/fiscal/alertas/tarea", data={"clave": clave})
        assert r.status_code == 302 and "aviso=tarea" in r.headers["Location"]
    conn = db.get_connection()
    n = conn.execute("SELECT COUNT(*) FROM tareas_outlook WHERE usuario_id = ? AND asunto = 'Modelo 303 de Cliente Tarea SL sin presentar'", (u,)).fetchone()[0]
    conn.close()
    assert n == 1
    assert "aviso=resuelta" in cliente.post("/fiscal/alertas/tarea", data={"clave": "duplicada:1:1"}).headers["Location"]


def _con_iva(c, hoy, cuotas_previas, actual, tipo="emitida"):
    """Una factura por trimestre con la cuota de IVA indicada (la base no importa para esta regla)."""
    from app import anomalias as an
    y, q = an._trimestre(hoy)
    creadas = []
    for i, cuota in enumerate(list(cuotas_previas) + [actual]):
        qq, yy = q - len(cuotas_previas) + i, y
        while qq <= 0:
            qq, yy = qq + 4, yy - 1
        d = date(yy, 3 * qq - 1, 15).isoformat() if i < len(cuotas_previas) else (hoy - timedelta(days=1)).isoformat()
        creadas.append((fc.crear_desde_portal(c, {"tipo": tipo, "fecha": d, "numero": f"I-{i}", "tercero_nombre": "Cliente final", "tercero_nif": "B22222222", "total": "100,00", "pct_iva": "21"}), cuota))
    conn = db.get_connection()
    for f, cuota in creadas:
        conn.execute("UPDATE facturas_contables_lineas SET cuota_iva = ? WHERE factura_id = ?", (cuota, f))
    conn.commit(); conn.close()


def test_el_iva_que_se_sale_de_lo_habitual_salta_y_uno_normal_no():
    hoy = date(2026, 11, 20)                                                         # al 80 % del 4T
    t, c = _t()
    _con_iva(c, hoy, [100000, 110000, 95000, 105000], 1000)                          # media 1.025 €, esperado ~557 €, lleva 10 €
    a = [x for x in anomalias.detectar(t, hoy) if x["tipo"] == "iva_desviado"]
    assert len(a) == 1 and a[0]["datos"]["real"] == 1000 and a[0]["datos"]["media"] == 102500
    t2, c2 = _t()
    _con_iva(c2, hoy, [100000, 110000, 95000, 105000], 80000)
    assert "iva_desviado" not in [x["tipo"] for x in anomalias.detectar(t2, hoy)]
    t3, c3 = _t()
    _con_iva(c3, hoy, [10000, 12000, 9000, 11000], 0)                                # IVA medio de 100 €: demasiado pequeño para opinar
    assert "iva_desviado" not in [x["tipo"] for x in anomalias.detectar(t3, hoy)]


def test_un_cliente_con_documentos_pedidos_que_no_entra_al_portal_salta():
    from app import portal_peticiones
    t, c = _t()
    ficha = db.obtener_cliente_fiscal_por_id(c)
    portal_peticiones.crear(ficha, "Extracto del banco", "En PDF")
    assert "sin_entrar_portal" in [a["tipo"] for a in anomalias.detectar(t, HOY)]                            # nunca ha entrado
    conn = db.get_connection()
    conn.execute("INSERT INTO portal_contactos (tenant_id, cliente_fiscal_id, email, nombre, rol, avisos, ultimo_acceso_en, creado_en) VALUES (?, ?, 'x@ejemplo.com', 'X', 'completo', 'todo', ?, '2026-01-01T10:00:00')", (t, c, (HOY - timedelta(days=3)).isoformat() + "T10:00:00"))
    conn.commit(); conn.close()
    assert "sin_entrar_portal" not in [a["tipo"] for a in anomalias.detectar(t, HOY)]                        # entró hace 3 días


def test_un_proveedor_nuevo_con_importe_alto_avisa_una_vez_y_con_importe_bajo_no():
    t, c = _t()
    _f(c, 120, total="80,00", nombre="Habitual", nif="B11111111")
    _f(c, 10, total="2500,00", nombre="Proveedor Nuevo", nif="B99999999")
    _f(c, 8, total="90,00", nombre="Otro Nuevo", nif="B88888888")
    n = [a for a in anomalias.detectar(t, HOY) if a["tipo"] == "proveedor_nuevo"]
    assert len(n) == 1 and n[0]["datos"]["proveedor"] == "Proveedor Nuevo" and n[0]["severidad"] == "baja"
    _f(c, 3, total="2600,00", nombre="Proveedor Nuevo", nif="B99999999", num="N-2")                          # ya no es la primera vez
    assert not [a for a in anomalias.detectar(t, HOY) if a["tipo"] == "proveedor_nuevo"]


def test_los_umbrales_del_despacho_cambian_lo_que_salta_y_se_validan():
    from app import ia_despacho
    t, c = _t()
    for d in (220, 190, 160, 130, 85):                                               # sin facturas desde hace 85 días con intervalo de 30: umbral por intervalo = 90
        _f(c, d)
    assert "sin_facturas" not in _tipos(t)
    assert ia_despacho.umbrales(t)["dias_sin_facturas"] == 45
    ia_despacho.guardar_umbrales(t, {"importe_gasto": 50, "dias_vencimiento": 10})
    u = ia_despacho.umbrales(t)
    assert u["importe_gasto"] == 50 and u["dias_vencimiento"] == 10 and u["iva_desvio_pct"] == 50           # lo no tocado sigue con el de serie
    with pytest.raises(ValueError):
        ia_despacho.guardar_umbrales(t, {"importe_gasto": 1})
    with pytest.raises(ValueError):
        ia_despacho.guardar_umbrales(t, {"dias_vencimiento": "mucho"})
    ia_despacho.guardar_umbrales(t, {})
    assert ia_despacho.umbrales(t) == anomalias.UMBRALES_POR_DEFECTO                                        # guardar sin cambios vuelve a los de serie


def test_el_cache_reutiliza_el_resultado_y_la_deteccion_en_vivo_no():
    t, c = _t()
    db.crear_vencimiento_fiscal(t, c, "303", "3T", (date.today() - timedelta(days=2)).isoformat())
    anomalias._CACHE.clear()
    assert len(anomalias.detectar_cacheado(t)) == 1
    db.crear_vencimiento_fiscal(t, c, "111", "3T", (date.today() - timedelta(days=2)).isoformat())
    assert len(anomalias.detectar_cacheado(t)) == 1 and len(anomalias.detectar(t)) == 2
    anomalias._CACHE.clear()
    assert len(anomalias.detectar_cacheado(t)) == 2


def test_la_direccion_ajusta_los_umbrales_desde_la_pantalla_y_otros_no(cliente):
    from app import ia_despacho
    from tests.conftest import iniciar_sesion_de_prueba
    t = db.crear_tenant("Anomalías umbrales")
    u = iniciar_sesion_de_prueba(cliente, "umbrales@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(u, True)
    html = cliente.get("/fiscal/alertas").get_data(as_text=True)
    assert "Cuándo salta cada alerta" in html and 'name="dias_vencimiento"' in html
    datos = dict(dias_sin_facturas=60, importe_gasto=500, dias_vencimiento=10, iva_desvio_pct=50, dias_sin_entrar=30, importe_proveedor_nuevo=1000)
    assert "aviso=umbrales" in cliente.post("/fiscal/alertas/umbrales", data=datos).headers["Location"]
    assert ia_despacho.umbrales(t)["importe_gasto"] == 500 and ia_despacho.umbrales(t)["dias_vencimiento"] == 10
    assert "error=" in cliente.post("/fiscal/alertas/umbrales", data={**datos, "importe_gasto": 1}).headers["Location"]
    cliente.post("/fiscal/alertas/umbrales", data={"restablecer": "1"})
    assert ia_despacho.umbrales(t) == anomalias.UMBRALES_POR_DEFECTO
    db.asignar_supervisor_tenant(u, False)
    assert cliente.post("/fiscal/alertas/umbrales", data=datos).status_code == 403
    assert "Cuándo salta cada alerta" not in cliente.get("/fiscal/alertas").get_data(as_text=True)


def _certificado(t, c, caduca, servicio="presentacion", estado="autorizado", n=[0]):
    n[0] += 1
    conn = db.get_connection()
    cur = conn.execute("INSERT INTO certificados (tenant_id, huella_sha256, nombre_comun, not_after, estado_operativo, creado_en, actualizado_en) VALUES (?, ?, 'Cert de prueba', ?, ?, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                       (t, f"h{t}-{n[0]}", caduca.isoformat() + "T00:00:00", estado))
    conn.execute("INSERT INTO certificados_vinculos (tenant_id, certificado_id, cliente_fiscal_id, servicio, autorizacion, vigente_desde, estado, creado_en) VALUES (?, ?, ?, ?, 'poder', '2026-01-01', 'activo', '2026-01-01T00:00:00')",
                 (t, cur.lastrowid, c, servicio))
    conn.commit(); conn.close()


def test_un_certificado_que_caduca_pronto_avisa_y_uno_con_alternativa_o_lejano_no():
    t, c = _t()
    _certificado(t, c, HOY + timedelta(days=10))
    a = [x for x in anomalias.detectar(t, HOY) if x["tipo"] == "certificado_caduca"]
    assert len(a) == 1 and a[0]["severidad"] == "alta" and a[0]["datos"]["dias"] == 10 and "caduca en 10 días" in anomalias.texto(a[0])[0]
    _certificado(t, c, HOY + timedelta(days=400))                                                       # otro vigente sobrado: ya no hay riesgo
    assert "certificado_caduca" not in _tipos(t)
    t2, c2 = _t()
    _certificado(t2, c2, HOY + timedelta(days=200))
    assert "certificado_caduca" not in _tipos(t2)                                                       # lejos del horizonte
    t3, c3 = _t()
    _certificado(t3, c3, HOY - timedelta(days=3))
    a = [x for x in anomalias.detectar(t3, HOY) if x["tipo"] == "certificado_caduca"]
    assert a and "caducó el" in anomalias.texto(a[0])[0]                                                # ya caducado
    t4, c4 = _t()
    _certificado(t4, c4, HOY + timedelta(days=5), estado="sustituido")
    _certificado(t4, c4, HOY + timedelta(days=5), servicio="firma")
    assert "certificado_caduca" not in _tipos(t4)                                                       # sustituido o solo para firmar: no cuenta
    t5, c5 = _t()
    _certificado(t5, c5, HOY + timedelta(days=20))
    assert "certificado_caduca" in _tipos(t5)
    from app import ia_despacho
    ia_despacho.guardar_umbrales(t5, {"dias_certificado": 7})
    assert "certificado_caduca" not in [x["tipo"] for x in anomalias.detectar(t5, HOY)]                 # el despacho avisa más tarde


def _con_retencion(c, fecha, cuota="15,00"):
    f = fc.crear_desde_portal(c, {"tipo": "recibida", "fecha": fecha, "numero": f"R-{fecha}", "tercero_nombre": "Abogado", "tercero_nif": "12345678Z", "total": "106,00", "pct_iva": "21"})
    conn = db.get_connection()
    conn.execute("UPDATE facturas_contables_lineas SET pct_retencion = 15, cuota_retencion = 1500 WHERE factura_id = ?", (f,))
    conn.commit(); conn.close()


def test_retenciones_del_trimestre_cerrado_sin_modelo_111_avisan_hasta_que_hay_modelo():
    hoy = date(2026, 10, 10)                                                                            # el tercer trimestre acaba de cerrarse
    t, c = _t()
    _con_retencion(c, "2026-08-20")
    a = [x for x in anomalias.detectar(t, hoy) if x["tipo"] == "retencion_sin_modelo"]
    assert len(a) == 1 and a[0]["periodo"] == "2026-T3" and a[0]["datos"]["retenido"] == 1500 and "111" in anomalias.texto(a[0])[0]
    conn = db.get_connection()
    conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?, ?, '111', '2026-T3', '2026-10-20', 'pendiente', '2026-10-01T00:00:00')", (t, c))
    conn.commit(); conn.close()
    assert "retencion_sin_modelo" not in [x["tipo"] for x in anomalias.detectar(t, hoy)]                # ya existe la obligación
    t2, c2 = _t()
    _con_retencion(c2, "2026-08-20")
    assert "retencion_sin_modelo" not in [x["tipo"] for x in anomalias.detectar(t2, date(2026, 12, 20))]  # pasada la ventana de 60 días
    assert "retencion_sin_modelo" not in [x["tipo"] for x in anomalias.detectar(t2, date(2026, 9, 20))]   # el trimestre aún no ha cerrado
    t3, c3 = _t()
    _f(c3, 5)                                                                                           # una factura sin retención no avisa
    assert "retencion_sin_modelo" not in [x["tipo"] for x in anomalias.detectar(t3, hoy)]

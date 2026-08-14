"""Propuestas de vencimientos fiscales españoles habituales, para el
calendario fiscal (app/rutas_fiscal.py + app/db.py: clientes_fiscales/
vencimientos_fiscales).

Las fechas de aquí son un PUNTO DE PARTIDA orientativo, no vinculante: la
AEAT desplaza la fecha real cuando cae en fin de semana o festivo, y puede
publicar un calendario ligeramente distinto cada año. `anio` es siempre el
año fiscal/periodo que se declara (no el año en que se presenta) -- para
los trimestres/modelos cuyo plazo cae en enero del año siguiente (303/130/
111/115 del T4, 390 anual, 200 anual), la función ya hace ese salto de año
internamente; quien llama solo piensa en "qué año estoy declarando".

No hay motor de recurrencia genérico en Guilda Work (ver HOSTING.md) -- esto
es una función pura que PROPONE filas concretas para que la ruta las
muestre en un formulario editable antes de guardar nada, nunca un cron que
auto-genera y compromete directamente."""

# {mes, dia} del ÚLTIMO día de plazo de cada trimestre. Los modelos T4 caen
# en enero del año SIGUIENTE al periodo declarado -- reflejado aquí mismo,
# no en la función, para que la tabla sea la única fuente de verdad.
MODELOS_TRIMESTRALES = {
    "303": {
        "nombre": "IVA - Declaración trimestral",
        "trimestres": {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 30)},
    },
    "130": {
        "nombre": "IRPF - Pago fraccionado (estimación directa)",
        "trimestres": {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 30)},
    },
    "111": {
        "nombre": "Retenciones IRPF trabajadores/profesionales",
        "trimestres": {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 20)},
    },
    "115": {
        "nombre": "Retenciones alquileres",
        "trimestres": {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 20)},
    },
}

# {mes, dia} del último día de plazo, y si cae en el año siguiente al
# periodo declarado (`anio_siguiente=True`) o en el mismo (`False`).
MODELOS_ANUALES = {
    "390": {"nombre": "IVA - Resumen anual", "mes_dia": (1, 30), "anio_siguiente": True},
    "200": {"nombre": "Impuesto sobre Sociedades", "mes_dia": (7, 25), "anio_siguiente": True},
}


def generar_vencimientos_propuestos(modelos: list[str], anio: int) -> list[dict]:
    """Devuelve propuestas `{modelo, periodo, fecha_limite}` para los
    modelos pedidos en el año fiscal `anio` -- función pura, no toca la
    base de datos. Cada trimestral genera 4 filas (una por trimestre);
    cada anual genera 1. `modelos` con un valor no reconocido se ignora
    silenciosamente (validar en la ruta antes de llamar, no aquí)."""
    propuestas = []
    for modelo in modelos:
        if modelo in MODELOS_TRIMESTRALES:
            for trimestre, (mes, dia) in MODELOS_TRIMESTRALES[modelo]["trimestres"].items():
                anio_fecha = anio + 1 if trimestre == 4 else anio
                propuestas.append({
                    "modelo": modelo,
                    "periodo": f"{anio}-T{trimestre}",
                    "fecha_limite": f"{anio_fecha:04d}-{mes:02d}-{dia:02d}",
                })
        elif modelo in MODELOS_ANUALES:
            info = MODELOS_ANUALES[modelo]
            mes, dia = info["mes_dia"]
            anio_fecha = anio + 1 if info["anio_siguiente"] else anio
            propuestas.append({
                "modelo": modelo,
                "periodo": f"{anio}-anual",
                "fecha_limite": f"{anio_fecha:04d}-{mes:02d}-{dia:02d}",
            })
    propuestas.sort(key=lambda p: p["fecha_limite"])
    return propuestas

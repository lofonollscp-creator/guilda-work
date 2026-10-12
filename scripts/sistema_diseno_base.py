#!/usr/bin/env python3
"""Regenera tests/datos/sistema_diseno_base.json con el recuento actual de controles «de fábrica» (ver PLAN_MAESTRO.md §3.3).
Se ejecuta tras migrar pantallas: la línea base solo puede BAJAR, y tests/test_sistema_diseno.py exige que se actualice cuando baja.
Solo lee texto; no importa la aplicación."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests import sistema_diseno_reglas as r  # noqa: E402

antes = r.cargar_base()
ahora = r.contar()
if antes:
    for regla, por_fichero in ahora.items():
        for fichero, n in por_fichero.items():
            if n > antes.get(regla, {}).get(fichero, 0):
                sys.exit(f"Sube, no baja: {regla} en {fichero} ({antes.get(regla, {}).get(fichero, 0)} → {n}). Arregla la pantalla en vez de subir la línea base.")
r.guardar_base(ahora)
print("Línea base actualizada:", {k: sum(v.values()) for k, v in ahora.items()})

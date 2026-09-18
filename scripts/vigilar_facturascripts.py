"""Vigilante de los contenedores de FacturaScripts (uno por tenant) --
pensado para correr a intervalos cortos vía el timer systemd
deploy/vigilar-facturascripts.timer/.service, NO como hilo dentro de
serve.py.

Motivo: el contenedor `guilda-work-facturascripts-tenant-<id>` ha
desaparecido varias veces en producción (ver bitácora/HOSTING.md) sin
causa raíz confirmada pese a investigarlo a fondo repetidas veces --
en vez de seguir dependiendo de que alguien note el error 111 y repare
a mano (horas de caída cada vez), este script detecta el contenedor
caído y lo reconstruye solo sobre los datos ya existentes
(app/facturascripts.py:reparar_tenant -- no toca la base de datos ni
los ficheros del segundo disco, solo el contenedor en sí).

Uso:
    .venv/bin/python scripts/vigilar_facturascripts.py

No necesita ningún parámetro: recorre todos los tenants con
`facturascripts_url` configurada y, si su contenedor no está en marcha,
lo repara. Idempotente -- si todos los contenedores están bien, no hace
nada. Requiere las mismas variables de entorno que serve.py (lee
/etc/guilda-work.env vía EnvironmentFile=, ver
deploy/vigilar-facturascripts.service)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, facturascripts  # noqa: E402


def main() -> None:
    reparados = 0
    for tenant in db.listar_tenants():
        if not tenant["facturascripts_url"]:
            continue
        tenant_id = tenant["id"]
        if facturascripts.contenedor_activo(tenant_id):
            continue
        print(f"Contenedor de FacturaScripts caído para el tenant {tenant_id} ({tenant['nombre']}) -- reparando...")
        try:
            facturascripts.reparar_tenant(tenant_id)
        except facturascripts.ErrorFacturaScripts as e:
            print(f"No se ha podido reparar el tenant {tenant_id}: {e}")
            continue
        reparados += 1
        print(f"Tenant {tenant_id} ({tenant['nombre']}) reparado.")
    if reparados == 0:
        print("Todos los contenedores de FacturaScripts están en marcha.")


if __name__ == "__main__":
    main()

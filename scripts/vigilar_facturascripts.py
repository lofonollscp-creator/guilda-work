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

Avisa por correo (app/notificaciones_email.py:enviar_alerta_interna)
cada vez que detecta y repara (o falla al reparar) una caída, para que
quede constancia de cuántas veces pasa sin depender de que alguien
revise el log a mano -- best-effort: si el correo falla, se imprime un
aviso y el vigilante sigue igualmente (la reparación del contenedor es
lo importante, no el aviso).

Uso:
    .venv/bin/python scripts/vigilar_facturascripts.py

No necesita ningún parámetro: recorre todos los tenants con
`facturascripts_url` configurada y, si su contenedor no está en marcha,
lo repara. Idempotente -- si todos los contenedores están bien, no hace
nada. Requiere las mismas variables de entorno que serve.py (lee
/etc/guilda-work.env vía EnvironmentFile=, ver
deploy/vigilar-facturascripts.service), más ALERTAS_ADMIN_EMAIL para
los avisos (si no está configurada, los avisos simplemente no se
mandan -- no bloquea la reparación)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, facturascripts, notificaciones_email  # noqa: E402


def _avisar(asunto: str, cuerpo: str) -> None:
    try:
        notificaciones_email.enviar_alerta_interna(asunto, cuerpo)
    except notificaciones_email.ErrorNotificacionesEmail as e:
        print(f"Aviso: no se ha podido enviar el correo de alerta ({e}).")


def main() -> None:
    reparados = 0
    for tenant in db.listar_tenants():
        if not tenant["facturascripts_url"]:
            continue
        tenant_id = tenant["id"]
        if facturascripts.contenedor_activo(tenant_id):
            continue
        hora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"Contenedor de FacturaScripts caído para el tenant {tenant_id} ({tenant['nombre']}) -- reparando...")
        try:
            facturascripts.reparar_tenant(tenant_id)
        except facturascripts.ErrorFacturaScripts as e:
            print(f"No se ha podido reparar el tenant {tenant_id}: {e}")
            _avisar(
                f"[Guilda Work] FacturaScripts caído -- el vigilante NO ha podido repararlo (tenant {tenant['nombre']})",
                "El vigilante automático ha detectado el contenedor de FacturaScripts caído "
                f"para el tenant {tenant_id} ({tenant['nombre']}) a las {hora}, pero NO ha "
                f"podido repararlo solo.\n\nDetalle del error: {e}\n\n"
                "Hace falta intervención manual -- ver app/facturascripts.py:reparar_tenant "
                "y el registro forense /var/log/guilda-work/docker-events.log en el VPS.",
            )
            continue
        reparados += 1
        print(f"Tenant {tenant_id} ({tenant['nombre']}) reparado.")
        _avisar(
            f"[Guilda Work] FacturaScripts se cayó y se ha reparado solo (tenant {tenant['nombre']})",
            "El vigilante automático ha detectado el contenedor de FacturaScripts caído "
            f"para el tenant {tenant_id} ({tenant['nombre']}) a las {hora} y lo ha reparado "
            "solo, sin intervención manual.\n\n"
            "No hace falta ninguna acción -- este aviso es solo para llevar la cuenta de "
            "cuántas veces pasa, dado que todavía no se ha identificado la causa raíz "
            "(ver la bitácora del proyecto).",
        )
    if reparados == 0:
        print("Todos los contenedores de FacturaScripts están en marcha.")


if __name__ == "__main__":
    main()

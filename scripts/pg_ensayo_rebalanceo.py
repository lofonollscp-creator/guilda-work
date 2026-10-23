#!/usr/bin/env python3
"""Tráfico de aplicación MIENTRAS Citus reequilibra fragmentos (fase 9): demuestra que añadir un nodo no corta el servicio ni pierde escrituras.

  scripts/pg_ensayo_rebalanceo.py --url postgresql://guilda:ensayo@127.0.0.1:55432/gw_carga --base gw_carga

Con la base de `scripts/probar.sh --carga --motor postgres …` (gw_carga) ya preparada y el worker unido (`scripts/pg_ensayo_worker.sh unir gw_carga`):
 1. N hilos, cada uno con el rol de la aplicación y un despacho, leen y escriben sin parar (SET LOCAL app.tenant_id, como la aplicación);
 2. a los 5 s el coordinador inicia el reequilibrado (citus_rebalance_start) y se espera a que acabe;
 3. se muestran errores y latencias antes / durante / después, y se comprueba que NO se ha perdido ninguna escritura confirmada."""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import threading
import time
import uuid

import psycopg
from psycopg.conninfo import make_conninfo

CLAVE_APP = "carga-app"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="superusuario, con la base (gw_carga)")
    ap.add_argument("--base", required=True)
    ap.add_argument("--accion", choices=("reequilibrar", "drenar"), default="reequilibrar", help="qué hace el coordinador mientras hay tráfico")
    ap.add_argument("--hilos", type=int, default=12)
    ap.add_argument("--antes", type=float, default=5.0)
    ap.add_argument("--despues", type=float, default=5.0)
    args = ap.parse_args()
    admin = psycopg.connect(args.url, autocommit=True)
    despachos = [(t, u) for t, u in admin.execute("SELECT DISTINCT u.tenant_id, u.id FROM usuarios u WHERE u.tenant_id > 0 ORDER BY 1, 2").fetchall()]
    if not despachos:
        print("la base no tiene personas con despacho: prepárala con scripts/probar.sh --carga --motor postgres")
        return 2
    marca = uuid.uuid4().hex[:8]
    url_app = make_conninfo(args.url, user="guilda_app", password=CLAVE_APP)
    estado = {"fase": "antes"}
    medidas = {"antes": [], "durante": [], "despues": []}
    errores: dict[str, list[str]] = {"antes": [], "durante": [], "despues": []}
    confirmadas: list[tuple[int, str]] = []
    cerrojo = threading.Lock()
    parar = threading.Event()

    def hilo(i: int):
        tenant, usuario = despachos[i % len(despachos)]
        n = 0
        with psycopg.connect(url_app, autocommit=True) as c:
            while not parar.is_set():
                n += 1
                fase = estado["fase"]
                t0 = time.perf_counter()
                try:
                    with c.transaction():
                        c.execute("SET LOCAL citus.propagate_set_commands = 'local'")
                        c.execute(f"SET LOCAL app.tenant_id = '{int(tenant)}'")
                        c.execute(f"SET LOCAL app.usuario_id = '{int(usuario)}'")
                        if n % 3 == 0:
                            texto = f"rebalanceo {marca} {i}-{n}"
                            c.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (%s, %s, %s, 'x')", (tenant, usuario, texto))
                        else:
                            c.execute("SELECT count(*), max(id) FROM tareas_outlook WHERE tenant_id = %s AND usuario_id = %s", (tenant, usuario)).fetchone()
                    if n % 3 == 0:
                        with cerrojo:
                            confirmadas.append((tenant, texto))
                    with cerrojo:
                        medidas[fase].append((time.perf_counter() - t0) * 1000)
                except Exception as e:                                                                      # noqa: BLE001
                    with cerrojo:
                        errores[fase].append(f"{type(e).__name__}: {str(e).splitlines()[0][:100]}")
                time.sleep(0.01)

    hilos = [threading.Thread(target=hilo, args=(i,), daemon=True) for i in range(args.hilos)]
    for h in hilos:
        h.start()
    time.sleep(args.antes)
    estado["fase"] = "durante"
    t0 = time.monotonic()
    r = subprocess.run([str(__import__("pathlib").Path(__file__).with_name("pg_ensayo_worker.sh")), args.accion, args.base], capture_output=True, text=True)
    segundos = time.monotonic() - t0
    estado["fase"] = "despues"
    print(r.stdout.strip() or r.stderr.strip())
    time.sleep(args.despues)
    parar.set()
    for h in hilos:
        h.join(10)

    print(f"\nreequilibrado: {segundos:.1f} s · {len(despachos)} personas/despachos repartidos entre {args.hilos} hilos")
    print(f"{'fase':8s} {'operaciones':>12s} {'errores':>8s} {'mediana':>9s} {'p95':>8s} {'máx':>8s}")
    for fase in ("antes", "durante", "despues"):
        v = medidas[fase]
        if v:
            p95 = statistics.quantiles(v, n=20)[18] if len(v) >= 20 else max(v)
            print(f"{fase:8s} {len(v):12d} {len(errores[fase]):8d} {statistics.median(v):7.1f}ms {p95:6.0f}ms {max(v):6.0f}ms")
        else:
            print(f"{fase:8s} {0:12d} {len(errores[fase]):8d}")
    distintos = sorted({e for lista in errores.values() for e in lista})
    if distintos:
        print("errores distintos:", *distintos[:8], sep="\n  ")
    perdidas = 0
    for tenant, texto in confirmadas:
        if admin.execute("SELECT 1 FROM notas WHERE tenant_id = %s AND texto = %s", (tenant, texto)).fetchone() is None:
            perdidas += 1
    print(f"escrituras confirmadas: {len(confirmadas)} · perdidas: {perdidas}")
    admin.execute("DELETE FROM notas WHERE texto LIKE %s", (f"rebalanceo {marca}%",))
    return 0 if perdidas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""Acceso a los datos de Guilda Work desde la línea de comandos.

Pensado para que un agente de IA con acceso a esta carpeta (Claude Code,
Codex CLI, etc.) pueda leer el registro de actividad sin pasar por la
interfaz web ni necesitar el servidor Flask arrancado.

Ejemplos:
    python cli.py menus
    python cli.py export --formato json
    python cli.py export --formato md --desde 2026-07-01 --hasta 2026-07-10
    python cli.py export --formato csv --menu Guilda > exports/guilda.csv
    python cli.py demo
    python cli.py backup
    python cli.py crear-tenant "Lueira"
    python cli.py listar-tenants
    python cli.py asignar-tenant persona@ejemplo.com Lueira
"""
import argparse
import sys

from app import db, export


def _resolver_menu_id(usuario_id: int, nombre_o_id: str | None) -> int | None:
    if not nombre_o_id:
        return None
    if nombre_o_id.isdigit():
        return int(nombre_o_id)
    for c in db.listar_categorias(usuario_id):
        if c["nombre"].lower() == nombre_o_id.lower():
            return c["id"]
    disponibles = ", ".join(c["nombre"] for c in db.listar_categorias(usuario_id))
    print(f"Menú '{nombre_o_id}' no encontrado. Disponibles: {disponibles}", file=sys.stderr)
    sys.exit(1)


def cmd_menus(args):
    usuario_id = db.usuario_local_id()
    for c in db.listar_categorias(usuario_id):
        print(f"{c['id']}\t{c['nombre']}\t{c['color'] or ''}")


def cmd_export(args):
    usuario_id = db.usuario_local_id()
    menu_id = _resolver_menu_id(usuario_id, args.menu)
    if args.formato == "csv":
        contenido = export.a_csv(usuario_id, args.desde, args.hasta, menu_id)
    elif args.formato == "md":
        contenido = export.a_markdown(usuario_id, args.desde, args.hasta, menu_id)
    else:
        contenido = export.a_json(usuario_id, args.desde, args.hasta, menu_id)

    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as f:
            f.write(contenido)
        print(f"Escrito en {args.salida}", file=sys.stderr)
    else:
        print(contenido)


def _categoria_o_crear(usuario_id: int, nombre: str, color: str) -> int:
    """Reutiliza el menú si ya existe uno con ese nombre (evita chocar con la
    restricción UNIQUE al volver a ejecutar `demo --forzar`)."""
    for c in db.listar_categorias(usuario_id):
        if c["nombre"] == nombre:
            return c["id"]
    return db.crear_categoria(usuario_id, nombre, color)


def cmd_demo(args):
    usuario_id = db.usuario_local_id()
    if db.listar_categorias(usuario_id) and not args.forzar:
        print(
            "Ya hay menús creados. Usa --forzar si quieres añadir datos de ejemplo de todas formas.",
            file=sys.stderr,
        )
        sys.exit(1)

    lueira = _categoria_o_crear(usuario_id, "Lueira", "#4a90d9")
    guilda = _categoria_o_crear(usuario_id, "Guilda", "#e0a83a")

    db.crear_nota(usuario_id, "Atendido cliente X (consulta sobre reserva)", categoria_id=lueira)
    db.crear_nota(usuario_id, "Llamada a cliente Y", categoria_id=lueira)
    db.crear_nota(usuario_id, "Recibido correo de cliente Z, contestado", categoria_id=lueira)
    db.crear_plantilla(lueira, "Llamada a cliente")

    db.crear_nota(usuario_id, "Avance en desarrollo de la exportación", categoria_id=guilda)
    tarea_id = db.crear_tarea(usuario_id, "Proceso de despliegue", guilda, "duracion")
    db.finalizar_tarea(usuario_id, tarea_id)
    db.crear_tarea(usuario_id, "Reunión rápida con el equipo", lueira, "instantanea")
    db.crear_plantilla(guilda, "Avance en desarrollo")

    print("Datos de ejemplo creados: menús 'Lueira' y 'Guilda' con notas, eventos, una tarea y frases favoritas.")


def cmd_backup(args):
    db.hacer_backup_si_hace_falta()
    print(f"Copia de seguridad al día en {db.BACKUPS_DIR}")


def cmd_crear_tenant(args):
    try:
        tenant_id = db.crear_tenant(args.nombre)
    except Exception as e:
        print(f"No se ha podido crear el tenant '{args.nombre}': {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Tenant '{args.nombre}' creado (id {tenant_id}).")


def cmd_listar_tenants(args):
    for t in db.listar_tenants():
        print(f"{t['id']}\t{t['nombre']}")


def cmd_asignar_tenant(args):
    usuario = db.obtener_usuario_por_email(args.email)
    if usuario is None:
        print(f"No existe ningún usuario con el email '{args.email}'.", file=sys.stderr)
        sys.exit(1)
    tenant = db.obtener_tenant_por_nombre(args.tenant) if not args.tenant.isdigit() else db.obtener_tenant(int(args.tenant))
    if tenant is None:
        print(f"No existe ningún tenant '{args.tenant}'. Usa 'python cli.py crear-tenant {args.tenant}' primero.", file=sys.stderr)
        sys.exit(1)
    db.asignar_tenant(usuario["id"], tenant["id"])
    print(f"{args.email} asignado al tenant '{tenant['nombre']}'.")


def main():
    parser = argparse.ArgumentParser(description="Consulta el registro de actividad de Guilda Work.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_menus = sub.add_parser("menus", help="Lista los menús (categorías) existentes.")
    p_menus.set_defaults(func=cmd_menus)

    p_export = sub.add_parser("export", help="Exporta el histórico de actividad.")
    p_export.add_argument("--formato", choices=["json", "csv", "md"], default="json")
    p_export.add_argument("--desde", help="Fecha inicial YYYY-MM-DD (inclusive).")
    p_export.add_argument("--hasta", help="Fecha final YYYY-MM-DD (inclusive).")
    p_export.add_argument("--menu", help="Nombre o id del menú. Si se omite, incluye todos.")
    p_export.add_argument("--salida", help="Ruta de archivo donde guardar. Si se omite, imprime por stdout.")
    p_export.set_defaults(func=cmd_export)

    p_demo = sub.add_parser("demo", help="Crea menús y datos de ejemplo para pruebas/demos.")
    p_demo.add_argument("--forzar", action="store_true", help="Añade los datos aunque ya existan menús.")
    p_demo.set_defaults(func=cmd_demo)

    p_backup = sub.add_parser("backup", help="Fuerza una copia de seguridad de la base de datos ahora mismo.")
    p_backup.set_defaults(func=cmd_backup)

    p_crear_tenant = sub.add_parser("crear-tenant", help="Crea un tenant (Fase 7c.3).")
    p_crear_tenant.add_argument("nombre")
    p_crear_tenant.set_defaults(func=cmd_crear_tenant)

    p_listar_tenants = sub.add_parser("listar-tenants", help="Lista los tenants existentes.")
    p_listar_tenants.set_defaults(func=cmd_listar_tenants)

    p_asignar_tenant = sub.add_parser("asignar-tenant", help="Asigna un usuario existente a un tenant.")
    p_asignar_tenant.add_argument("email")
    p_asignar_tenant.add_argument("tenant", help="Nombre o id del tenant.")
    p_asignar_tenant.set_defaults(func=cmd_asignar_tenant)

    args = parser.parse_args()
    db.init_db()  # idempotente: por si es la primera vez que se usa la app
    args.func(args)


if __name__ == "__main__":
    main()

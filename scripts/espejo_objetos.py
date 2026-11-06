#!/usr/bin/env python3
"""Espejo local del almacén de objetos (bucket S3), para que Restic lo copie fuera de AWS (ver scripts/backup_objetos_restic.sh).

Solo AÑADE: las claves son inmutables (`t<tenant>/<tabla>/<id>-<sha12>`), así que cada objeto se baja una vez y no se vuelve a tocar; no se borra
nada del espejo aunque el objeto desaparezca del bucket. Cada descarga se comprueba contra el sha12 de la clave antes de dejarla en su sitio.

Variables: las GUILDA_S3_* de /etc/guilda-work.env y GUILDA_OBJETOS_ESPEJO (carpeta de destino, ruta absoluta).
Uso: .venv/bin/python scripts/espejo_objetos.py [--verificar]   (con --verificar vuelve a comprobar también lo que ya estaba en el espejo)
Termina con código 1 si algún objeto falla; escribe un resumen JSON en GUILDA_OBJETOS_ESPEJO_ESTADO si se indica."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from minio import Minio

_CLAVE = re.compile(r"^t\d+/[a-z_]+/\d+-([0-9a-f]{12})$")


def main(argv: list[str]) -> int:
    verificar = "--verificar" in argv
    destino = os.environ.get("GUILDA_OBJETOS_ESPEJO", "")
    bucket, acceso, secreto = (os.environ.get(k, "") for k in ("GUILDA_S3_BUCKET", "GUILDA_S3_ACCESS_KEY", "GUILDA_S3_SECRET_KEY"))
    if not destino.startswith("/") or not (bucket and acceso and secreto):
        print("Faltan GUILDA_OBJETOS_ESPEJO (ruta absoluta) o GUILDA_S3_BUCKET/ACCESS_KEY/SECRET_KEY.", file=sys.stderr)
        return 2
    prefijo = os.environ.get("GUILDA_S3_PREFIJO", "")
    cliente = Minio(os.environ.get("GUILDA_S3_ENDPOINT") or "s3.amazonaws.com", access_key=acceso, secret_key=secreto,
                    region=os.environ.get("GUILDA_S3_REGION") or None, secure=os.environ.get("GUILDA_S3_SECURE", "1") not in ("0", "false", "no"))
    raiz = Path(destino)
    raiz.mkdir(parents=True, exist_ok=True)
    nuevos = ya = 0
    errores: list[str] = []
    for obj in cliente.list_objects(bucket, prefix=prefijo, recursive=True):
        clave = obj.object_name[len(prefijo):] if prefijo else obj.object_name
        m = _CLAVE.match(clave)
        if not m:
            errores.append(f"clave inesperada: {clave}")
            continue
        fichero = raiz / clave
        try:
            if fichero.exists() and not verificar:
                ya += 1
                continue
            r = cliente.get_object(bucket, obj.object_name)
            try:
                datos = r.read()
            finally:
                r.close()
                r.release_conn()
            if hashlib.sha256(datos).hexdigest()[:12] != m.group(1):
                errores.append(f"huella distinta: {clave}")
                continue
            if fichero.exists():
                ya += 1
                continue
            fichero.parent.mkdir(parents=True, exist_ok=True)
            tmp = fichero.with_name(fichero.name + ".parte")
            tmp.write_bytes(datos)
            os.replace(tmp, fichero)
            nuevos += 1
        except Exception as e:  # noqa: BLE001 -- uno que falla no corta a los demás
            errores.append(f"{clave}: {e}")
    resumen = {"fin": datetime.now().astimezone().isoformat(timespec="seconds"), "nuevos": nuevos, "ya_estaban": ya, "errores": errores}
    print(f"Espejo: {nuevos} nuevos, {ya} ya estaban, {len(errores)} con error.")
    for e in errores:
        print("FALLO:", e, file=sys.stderr)
    estado = os.environ.get("GUILDA_OBJETOS_ESPEJO_ESTADO")
    if estado:
        Path(estado).parent.mkdir(parents=True, exist_ok=True)
        Path(estado).write_text(json.dumps(resumen, indent=1))
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

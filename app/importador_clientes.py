"""Importar clientes desde un Excel (.xlsx) o un CSV: leer el archivo, reconocer las columnas, revisar cada fila (errores, duplicados) y crear los clientes.

Va en dos pasos para que nada se cree sin verse antes: `preparar` lee el archivo y lo guarda unos minutos en el servidor (un fichero por importación, privado del despacho y de quien lo subió);
`vista_previa` calcula, con la correspondencia de columnas elegida, qué hará cada fila; `importar` crea los clientes. Cada fila se valida por separado: una fila mala no impide las demás.
Los duplicados (mismo NIF, correo o nombre que un cliente ya existente, o repetidos dentro del propio archivo) se omiten por defecto."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import time
import unicodedata
import zipfile
from datetime import date, datetime
from pathlib import Path

from flask_babel import lazy_gettext as _l

from . import alta_cliente, auditoria, db, nucleo

MAX_BYTES = 5 * 1024 * 1024
MAX_FILAS = 5000
MAX_DESCOMPRIMIDO = 60 * 1024 * 1024      # un .xlsx es un zip: se mira lo que ocuparía abierto antes de abrirlo
VIDA_SEGUNDOS = 2 * 3600

CAMPOS = ("nombre", "nif", "email", "telefono", "direccion", "tipo", "idioma", "origen", "notas", "etiquetas", "pais")
ETIQUETAS_CAMPO = {"nombre": _l("Nombre o razón social"), "nif": _l("NIF / CIF"), "email": _l("Email"), "telefono": _l("Teléfono"), "direccion": _l("Dirección"), "tipo": _l("Tipo (persona o empresa)"), "idioma": _l("Idioma"),
                   "origen": _l("Origen"), "notas": _l("Notas"), "etiquetas": _l("Etiquetas"), "pais": _l("País (gestión fiscal)")}
_SINONIMOS = {
    "nombre": ("nombre", "razonsocial", "cliente", "empresa", "denominacion", "nombrecompleto", "nombreyapellidos", "apellidosynombre", "titular", "name", "nom"),
    "nif": ("nif", "cif", "dni", "nie", "nifcif", "cifnif", "dninifcif", "identificacion", "vat", "taxid"),
    "email": ("email", "correo", "correoelectronico", "mail", "ecorreo", "emailcontacto"),
    "telefono": ("telefono", "tel", "movil", "telefonomovil", "celular", "phone", "telf", "tlf"),
    "direccion": ("direccion", "domicilio", "direccionpostal", "address"),
    "tipo": ("tipo", "tipodecliente", "tipocliente", "personaoempresa", "tipopersona"),
    "idioma": ("idioma", "lengua", "language"),
    "origen": ("origen", "procedencia", "canal", "comoconocio"),
    "notas": ("notas", "observaciones", "comentarios", "comentario", "notes"),
    "etiquetas": ("etiquetas", "tags", "categorias", "grupos", "etiqueta"),
    "pais": ("pais", "country"),
}
_TIPOS = {"persona": "persona", "particular": "persona", "autonomo": "persona", "fisica": "persona", "personafisica": "persona", "empresa": "empresa", "sociedad": "empresa",
          "juridica": "empresa", "personajuridica": "empresa", "sl": "empresa", "sa": "empresa", "slu": "empresa"}
_IDIOMAS = {"es": "es", "castellano": "es", "espanol": "es", "spanish": "es", "ca": "ca", "catalan": "ca", "catala": "ca", "en": "en", "ingles": "en", "english": "en", "fr": "fr", "frances": "fr", "french": "fr"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorImportacion(ValueError):
    """Mensaje legible para quien sube el archivo."""


def _norm(texto) -> str:
    t = unicodedata.normalize("NFD", str(texto or "").strip().lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in t if unicodedata.category(c) != "Mn"))


# --- Leer el archivo ------------------------------------------------------------------------------------------------------------------------------------
def _celda(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))                       # un teléfono o un NIF numérico no debe quedar como «600123456.0»
    if isinstance(v, (datetime, date)):
        return v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
    return str(v).replace("\x00", "").strip()


def _leer_csv(datos: bytes) -> list[list[str]]:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            texto = datos.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErrorImportacion("No se pudo leer el texto del archivo: guárdalo como CSV UTF-8.")
    muestra = texto[:4096]
    primera = muestra.splitlines()[0] if muestra.splitlines() else ""
    delimitador = max(";,\t|", key=primera.count) if any(d in primera for d in ";,\t|") else ";"
    return [[_celda(c) for c in fila] for fila in csv.reader(io.StringIO(texto), delimiter=delimitador)]


def _leer_xlsx(datos: bytes) -> list[list[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPRIMIDO:
                raise ErrorImportacion("El archivo Excel es demasiado grande una vez abierto.")
    except zipfile.BadZipFile:
        raise ErrorImportacion("El archivo no es un Excel (.xlsx) válido. Si es un .xls antiguo, guárdalo como .xlsx o como CSV.") from None
    from openpyxl import load_workbook
    try:
        libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception:
        raise ErrorImportacion("No se pudo abrir el Excel. Prueba a guardarlo de nuevo como .xlsx o como CSV.") from None
    try:
        filas = []
        for fila in libro.worksheets[0].iter_rows(values_only=True):
            filas.append([_celda(c) for c in fila])
            if len(filas) > MAX_FILAS + 1:
                break
        return filas
    finally:
        libro.close()


def leer_archivo(nombre: str, datos: bytes) -> tuple[list[str], list[list[str]]]:
    """(cabeceras, filas) del archivo. `ErrorImportacion` si no se puede leer o no tiene lo mínimo."""
    if not datos:
        raise ErrorImportacion("El archivo está vacío.")
    if len(datos) > MAX_BYTES:
        raise ErrorImportacion("El archivo es demasiado grande (máximo 5 MB).")
    sufijo = Path(nombre or "").suffix.lower()
    if sufijo == ".xlsx":
        filas = _leer_xlsx(datos)
    elif sufijo in (".csv", ".txt", ".tsv"):
        filas = _leer_csv(datos)
    elif sufijo == ".xls":
        raise ErrorImportacion("Los .xls antiguos no se pueden leer: guárdalo como .xlsx o como CSV.")
    else:
        raise ErrorImportacion("Sube un Excel (.xlsx) o un CSV.")
    filas = [f for f in filas if any(c for c in f)]
    if len(filas) < 2:
        raise ErrorImportacion("El archivo necesita una primera fila con los nombres de las columnas y al menos un cliente debajo.")
    if len(filas) - 1 > MAX_FILAS:
        raise ErrorImportacion(f"Demasiados clientes de golpe (máximo {MAX_FILAS}): divide el archivo.")
    cabeceras = filas[0]
    ancho = max(len(f) for f in filas)
    cabeceras = [(cabeceras[i] if i < len(cabeceras) else "") for i in range(ancho)]
    return cabeceras, [[(f[i] if i < len(f) else "") for i in range(ancho)] for f in filas[1:]]


def reconocer_columnas(cabeceras: list[str]) -> dict[int, str]:
    """Qué campo de Guilda Work es cada columna, por el nombre de su cabecera (sin tildes ni mayúsculas). Cada campo se asigna a una sola columna: la primera."""
    asignado: dict[int, str] = {}
    usados: set[str] = set()
    for i, cab in enumerate(cabeceras):
        n = _norm(cab)
        for campo, sinonimos in _SINONIMOS.items():
            if campo not in usados and n in sinonimos:
                asignado[i] = campo
                usados.add(campo)
                break
    return asignado


# --- Un fichero por importación (privado, caduca) ----------------------------------------------------------------------------------------------
def _carpeta() -> Path:
    c = db.DB_PATH.parent / "importaciones"
    c.mkdir(parents=True, exist_ok=True)
    return c


def _limpiar_caducadas() -> None:
    limite = time.time() - VIDA_SEGUNDOS
    for f in _carpeta().glob("*.json"):
        try:
            if f.stat().st_mtime < limite:
                f.unlink()
        except OSError:
            pass


def preparar(tenant_id: int, usuario_id: int, nombre: str, datos: bytes) -> str:
    """Lee el archivo y lo guarda para el siguiente paso. Devuelve el identificador de la importación."""
    cabeceras, filas = leer_archivo(nombre, datos)
    _limpiar_caducadas()
    ident = secrets.token_urlsafe(24)
    ruta = _carpeta() / f"{ident}.json"
    with os.fdopen(os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
        json.dump({"tenant_id": tenant_id, "usuario_id": usuario_id, "nombre": (nombre or "")[:200], "cabeceras": cabeceras, "filas": filas, "creado": time.time()}, f, ensure_ascii=False)
    return ident


def cargar(tenant_id: int, usuario_id: int, ident: str) -> dict | None:
    """La importación preparada, solo para quien la subió y su despacho; None si no existe, caducó o no es suya."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", ident or ""):
        return None
    ruta = _carpeta() / f"{ident}.json"
    try:
        if time.time() - ruta.stat().st_mtime > VIDA_SEGUNDOS:
            ruta.unlink(missing_ok=True)
            return None
        d = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if d.get("tenant_id") == tenant_id and d.get("usuario_id") == usuario_id else None


def descartar(ident: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9_-]{20,64}", ident or ""):
        (_carpeta() / f"{ident}.json").unlink(missing_ok=True)


# --- Revisar cada fila ----------------------------------------------------------------------------------------------------------------------------------
def _fila_a_datos(fila: list[str], correspondencia: dict[int, str]) -> dict:
    d = {c: "" for c in CAMPOS}
    for i, campo in correspondencia.items():
        if i < len(fila) and campo in d and not d[campo]:
            d[campo] = fila[i].strip()
    return d


def _normalizar(d: dict) -> tuple[dict, list[str]]:
    """Los datos listos para crear el cliente y los avisos (algo que se ha descartado porque no valía)."""
    avisos = []
    d = dict(d)
    d["nif"] = re.sub(r"[\s.\-]", "", d["nif"]).upper()
    if d["email"] and not _EMAIL.match(d["email"]):
        avisos.append(f"Email no válido, no se importa: {d['email'][:60]}")
        d["email"] = ""
    d["telefono"] = re.sub(r"[^\d+ ()\-]", "", d["telefono"]).strip()
    tipo = _TIPOS.get(_norm(d["tipo"]), "")
    if d["tipo"] and not tipo:
        avisos.append(f"Tipo no reconocido, se detecta por el NIF: {d['tipo'][:30]}")
    d["tipo"] = tipo
    idioma = _IDIOMAS.get(_norm(d["idioma"]), "")
    if d["idioma"] and not idioma:
        avisos.append(f"Idioma no reconocido, se deja sin indicar: {d['idioma'][:30]}")
    d["idioma"] = idioma
    d["pais"] = d["pais"].strip().upper()[:2]
    d["etiquetas"] = [e.strip() for e in re.split(r"[;,|]", d["etiquetas"]) if e.strip()][:10]
    return d, avisos


def _existentes(tenant_id: int) -> dict[str, dict[str, str]]:
    """Los clientes que ya tiene el despacho, indexados por NIF (sin espacios ni guiones, en mayúsculas), correo y nombre (en minúsculas): se carga una vez en vez de buscar fila a fila
    (con 5.000 filas y 5.000 clientes la búsqueda individual tardaba más de 30 s). Mismo criterio que `nucleo.posibles_duplicados`."""
    indices: dict[str, dict[str, str]] = {"nif": {}, "email": {}, "nombre": {}}
    conn = db.get_connection()
    try:
        for f in conn.execute("SELECT nombre, nif, email FROM clientes WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY id", (tenant_id,)):
            if f["nif"]:
                indices["nif"].setdefault(re.sub(r"[\s.\-]", "", f["nif"]).upper(), f["nombre"])
            if f["email"]:
                indices["email"].setdefault(f["email"].strip().lower(), f["nombre"])
            indices["nombre"].setdefault((f["nombre"] or "").strip().lower(), f["nombre"])
    finally:
        conn.close()
    return indices


def vista_previa(tenant_id: int, importacion: dict, correspondencia: dict[int, str]) -> dict:
    """Qué pasará con cada fila: `nuevo`, `duplicado` (ya existe o se repite en el archivo) o `error`. Devuelve `{filas: [...], cuentas: {...}}`."""
    if "nombre" not in correspondencia.values():
        raise ErrorImportacion("Elige qué columna es el nombre del cliente.")
    existentes = _existentes(tenant_id)
    vistos_nif, vistos_email, vistos_nombre = set(), set(), set()
    filas, cuentas = [], {"nuevo": 0, "duplicado": 0, "error": 0}
    for n, bruta in enumerate(importacion["filas"], start=2):          # la fila 1 es la cabecera: se numera como en Excel
        d, avisos = _normalizar(_fila_a_datos(bruta, correspondencia))
        estado, motivo = "nuevo", ""
        if not d["nombre"]:
            estado, motivo = "error", "Falta el nombre."
        elif len(d["nombre"]) > 200:
            estado, motivo = "error", "El nombre es demasiado largo (máx. 200 caracteres)."
        else:
            clave_nif = d["nif"] or None
            clave_email = d["email"].lower() or None
            clave_nombre = d["nombre"].lower()
            repetido = (clave_nif and clave_nif in vistos_nif) or (clave_email and clave_email in vistos_email) or clave_nombre in vistos_nombre
            if repetido:
                estado, motivo = "duplicado", "Repetido dentro del archivo."
            else:
                existente = existentes["nif"].get(d["nif"]) if d["nif"] else None
                existente = existente or (existentes["email"].get(clave_email) if clave_email else None) or existentes["nombre"].get(clave_nombre)
                if existente:
                    estado, motivo = "duplicado", f"Ya existe: {existente}"
            if clave_nif:
                vistos_nif.add(clave_nif)
            if clave_email:
                vistos_email.add(clave_email)
            vistos_nombre.add(clave_nombre)
        cuentas[estado] += 1
        filas.append({"n": n, "estado": estado, "motivo": motivo, "avisos": avisos, "datos": d})
    return {"filas": filas, "cuentas": cuentas}


# --- Crear ----------------------------------------------------------------------------------------------------------------------------------------------
def importar(tenant_id: int, usuario_id: int, importacion: dict, correspondencia: dict[int, str], *, omitir_duplicados: bool = True, gestion_fiscal: bool = False,
             pais: str = "ES", etiqueta_comun: str | None = None, perfil_tipo: str | None = None, generacion_automatica: bool = False) -> dict:
    """Crea los clientes. Devuelve `{creados, duplicados, errores: [{n, nombre, motivo}], con_gestion_fiscal}`. Una fila que falla no detiene las demás."""
    gestion_fiscal = bool(gestion_fiscal and alta_cliente.gestion_fiscal_disponible(tenant_id))
    previa = vista_previa(tenant_id, importacion, correspondencia)
    etiqueta_comun = (etiqueta_comun or "").strip()[:60]
    resultado = {"creados": 0, "duplicados": 0, "errores": [], "con_gestion_fiscal": 0, "etiqueta": etiqueta_comun}
    for f in previa["filas"]:
        d = f["datos"]
        if f["estado"] == "error":
            resultado["errores"].append({"n": f["n"], "nombre": d["nombre"][:60], "motivo": f["motivo"]})
            continue
        if f["estado"] == "duplicado" and omitir_duplicados:
            resultado["duplicados"] += 1
            continue
        etiquetas = list(d["etiquetas"]) + ([etiqueta_comun] if etiqueta_comun else [])
        try:
            r = alta_cliente.crear_cliente_completo(
                tenant_id, d["nombre"], gestion_fiscal=gestion_fiscal, tipo=d["tipo"] or None, nif=d["nif"] or None, email=d["email"] or None, telefono=d["telefono"] or None,
                direccion=d["direccion"] or None, idioma=d["idioma"] or None, origen=d["origen"] or "Importación", notas=d["notas"] or None, etiquetas=etiquetas,
                pais=(d["pais"] or pais or "ES"), perfil_tipo=(perfil_tipo or None) if gestion_fiscal else None,
                generacion_automatica=bool(generacion_automatica and gestion_fiscal), usuario_id=usuario_id)
        except ValueError as e:
            resultado["errores"].append({"n": f["n"], "nombre": d["nombre"][:60], "motivo": str(e)[:200]})
            continue
        except Exception:
            resultado["errores"].append({"n": f["n"], "nombre": d["nombre"][:60], "motivo": "No se pudo crear (error interno)."})
            continue
        resultado["creados"] += 1
        if r.get("cliente_fiscal_id"):
            resultado["con_gestion_fiscal"] += 1
    auditoria.registrar(tenant_id, usuario_id, "clientes.importados", "cliente", None,
                        {"archivo": importacion.get("nombre"), "creados": resultado["creados"], "duplicados": resultado["duplicados"], "errores": len(resultado["errores"]), "gestion_fiscal": gestion_fiscal})
    return resultado


PLANTILLA_CSV = ("Nombre;NIF;Email;Teléfono;Dirección;Tipo;Idioma;Etiquetas;Notas\n"
                 "Carmen Soler Vidal;12345678Z;carmen@ejemplo.com;600123456;Calle Mayor 1, Madrid;persona;es;autónomo;Cliente desde 2019\n"
                 "Construcciones Mar S.L.;B12345678;admin@construccionesmar.es;912345678;Av. del Puerto 5, Valencia;empresa;es;sociedad;\n")

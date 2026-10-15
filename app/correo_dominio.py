"""Salud del dominio de correo: ¿puede el despacho enviar y recibir sin acabar en spam? Comprueba MX, SPF, DKIM y DMARC con consultas DNS.

Solo diagnostica y recomienda: **no cambia ningún registro**. Los registros DNS son del dominio del despacho y los gestiona quien lo administra. El DKIM depende del selector que use cada proveedor,
así que se prueban los habituales y se admite indicar uno propio. Solo se consultan los dominios de las cuentas de correo de la persona y el dominio de correo del despacho."""
from __future__ import annotations

import re

from . import db, dns_simple

SELECTORES_HABITUALES = ("default", "mail", "dkim", "s1", "s2", "k1", "rsa", "ed", "stalwart", "google", "selector1", "selector2")
_DOMINIO = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
OK, AVISO, ERROR = "ok", "aviso", "error"


def dominio_valido(dominio: str) -> bool:
    return bool(_DOMINIO.match((dominio or "").strip().lower()))


def dominios_de_la_persona(usuario_id: int) -> list[str]:
    """Dominios de las direcciones de sus cuentas y el dominio de correo propio del despacho, sin repetir."""
    dominios: list[str] = []
    for c in db.listar_cuentas_correo(usuario_id):
        d = (c["usuario"] or "").rpartition("@")[2].strip().lower()
        if dominio_valido(d) and d not in dominios:
            dominios.append(d)
    t = db.tenant_de_usuario(usuario_id)
    propio = (t["stalwart_domain_name"] if t is not None and "stalwart_domain_name" in t.keys() else None) or ""
    if dominio_valido(propio) and propio.lower() not in dominios:
        dominios.append(propio.lower())
    return dominios


def _txt(consulta, nombre: str) -> list[str]:
    return consulta(nombre, "TXT")


def comprobar_mx(dominio: str, consulta) -> dict:
    mx = consulta(dominio, "MX")
    if not mx:
        return {"clave": "mx", "titulo": "MX (recepción)", "estado": ERROR, "detalle": "El dominio no tiene registros MX: no puede recibir correo.", "registros": []}
    return {"clave": "mx", "titulo": "MX (recepción)", "estado": OK, "detalle": f"{len(mx)} servidor(es) de correo.", "registros": [f"{p} {s}" for p, s in mx]}


def comprobar_spf(dominio: str, consulta) -> dict:
    spf = [t for t in _txt(consulta, dominio) if t.lower().startswith("v=spf1")]
    base = {"clave": "spf", "titulo": "SPF (quién puede enviar)", "registros": spf}
    if not spf:
        return {**base, "estado": ERROR, "detalle": "No hay registro SPF: muchos servidores marcarán tu correo como sospechoso. Publica un TXT que empiece por «v=spf1» con los servidores que envían por ti."}
    if len(spf) > 1:
        return {**base, "estado": ERROR, "detalle": "Hay más de un registro SPF: solo se admite uno, y con varios el SPF falla. Únelos en uno."}
    r = spf[0].lower().split()
    if "+all" in r or "?all" in r or "all" in r:
        return {**base, "estado": AVISO, "detalle": "El SPF permite enviar a cualquiera. Termínalo en «~all» o «-all»."}
    if "-all" not in r and "~all" not in r and not any(x.startswith("redirect=") for x in r):
        return {**base, "estado": AVISO, "detalle": "El SPF no termina en «~all» o «-all», así que no dice qué hacer con el resto."}
    consultas = sum(1 for x in r if x.startswith(("include:", "a", "mx", "ptr", "exists:", "redirect=")) and not x.startswith(("all", "ip4:", "ip6:")))
    if consultas > 10:
        return {**base, "estado": AVISO, "detalle": "El SPF hace más de 10 consultas DNS: se ignora por exceso. Simplifícalo."}
    return {**base, "estado": OK, "detalle": "SPF correcto."}


def comprobar_dmarc(dominio: str, consulta) -> dict:
    d = [t for t in _txt(consulta, f"_dmarc.{dominio}") if t.lower().startswith("v=dmarc1")]
    base = {"clave": "dmarc", "titulo": "DMARC (qué hacer si falla)", "registros": d}
    if not d:
        return {**base, "estado": ERROR, "detalle": "No hay DMARC. Publica un TXT en _dmarc con, por ejemplo, «v=DMARC1; p=none; rua=mailto:alguien@tudominio» para empezar a recibir informes."}
    politica = re.search(r"\bp\s*=\s*(\w+)", d[0], re.IGNORECASE)
    p = politica.group(1).lower() if politica else ""
    if p == "none":
        return {**base, "estado": AVISO, "detalle": "DMARC en modo vigilancia (p=none): informa pero no protege. Cuando los informes estén limpios, pasa a quarantine o reject."}
    if p not in ("quarantine", "reject"):
        return {**base, "estado": AVISO, "detalle": "La política de DMARC (p=) no es válida."}
    return {**base, "estado": OK, "detalle": f"DMARC con política {p}."}


def comprobar_dkim(dominio: str, consulta, selector: str | None = None) -> dict:
    selectores = [selector] if selector else list(SELECTORES_HABITUALES)
    hallados = []
    for s in selectores:
        for t in _txt(consulta, f"{s}._domainkey.{dominio}"):
            if "p=" in t.lower() or t.lower().startswith("v=dkim1"):
                hallados.append(f"{s}: {t[:60]}{'…' if len(t) > 60 else ''}")
    base = {"clave": "dkim", "titulo": "DKIM (firma del correo)", "registros": hallados}
    if hallados:
        return {**base, "estado": OK, "detalle": f"Hay clave DKIM publicada ({len(hallados)})."}
    return {**base, "estado": AVISO if not selector else ERROR,
            "detalle": ("No se ha encontrado DKIM con los selectores habituales. Si tu proveedor usa otro, indícalo y vuelve a comprobar; si no hay ninguno, activa DKIM en tu proveedor y publica su clave." if not selector
                        else f"No hay clave DKIM en «{selector}._domainkey.{dominio}».")}


def diagnosticar(dominio: str, selector: str | None = None, consulta=None) -> dict:
    """`{"dominio", "comprobaciones": [...], "estado"}`; `estado` es el peor de las comprobaciones. `ErrorDNS` si no se puede consultar el DNS."""
    dominio = (dominio or "").strip().lower()
    if not dominio_valido(dominio):
        raise ValueError("Ese dominio no es válido.")
    selector = (selector or "").strip().lower() or None
    if selector and not re.fullmatch(r"[a-z0-9]([a-z0-9._-]{0,60}[a-z0-9])?", selector):
        raise ValueError("El selector DKIM no es válido.")
    consulta = consulta or dns_simple.resolver
    comprobaciones = [comprobar_mx(dominio, consulta), comprobar_spf(dominio, consulta), comprobar_dkim(dominio, consulta, selector), comprobar_dmarc(dominio, consulta)]
    peor = ERROR if any(c["estado"] == ERROR for c in comprobaciones) else AVISO if any(c["estado"] == AVISO for c in comprobaciones) else OK
    return {"dominio": dominio, "comprobaciones": comprobaciones, "estado": peor}

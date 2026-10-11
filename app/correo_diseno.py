"""Diseño de los correos que envía Guilda Work (enlaces de acceso, avisos a clientes, alertas internas, códigos de Kratos): el mismo lenguaje que la
pantalla de inicio de sesión —foto de montaña, tarjeta oscura redondeada, botón lima— adaptado a lo que aguantan los clientes de correo.

Por qué es distinto de la web: los clientes de correo (Outlook, Gmail…) no admiten `backdrop-filter`, ni CSS externo, ni casi nada de flex/grid. Por eso
va maquetado con tablas y estilos en línea, con la tarjeta OPACA (sin cristal) y la foto solo como adorno de fondo: si el cliente de correo no la carga,
queda un azul oscuro liso y el correo se lee igual. Texto sobre fondo oscuro con contraste AA (tests/test_correo_diseno.py lo mide). Cada correo lleva
también su versión en texto plano (para quien no ve HTML y para los filtros de spam).

`construir()` devuelve `(texto_plano, html)`. TODO texto que llega de fuera (nombres de clientes, mensajes del portal…) se escapa."""
from __future__ import annotations

import os
from html import escape

BASE = (os.environ.get("GUILDA_ORIGIN") or "https://app.guildawork.com").rstrip("/")

# Colores (contraste sobre la tarjeta #101216 ≥ 4,5:1; ver tests/test_correo_diseno.py)
FONDO_TARJETA = "#101216"
FONDO_RESPALDO = "#16243a"        # lo que se ve si el cliente de correo no carga la foto
TEXTO = "#e8eae9"
TEXTO_SUAVE = "#c4c9d1"
TEXTO_APAGADO = "#9aa1ab"
ACENTO = "#ccff33"
SOBRE_ACENTO = "#0a0a0a"
BORDE = "#2a2d33"

FUENTE = "'Manrope','Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Helvetica,Arial,sans-serif"
FUENTE_CODIGO = "'SFMono-Regular',Menlo,Consolas,'Liberation Mono',monospace"

PIE_POR_DEFECTO = "Guilda Work · el software de gestión de tu gestoría"


def _parrafo_html(texto: str, color: str = TEXTO_SUAVE, tam: int = 16, margen: int = 16) -> str:
    cuerpo = escape(texto).replace("\n", "<br>")
    return f'<p style="margin:0 0 {margen}px;font-size:{tam}px;line-height:1.6;color:{color};">{cuerpo}</p>'


def construir(
    titulo: str, parrafos: list[str] | tuple[str, ...] = (), *, boton: tuple[str, str] | None = None, codigo: str | None = None,
    cita: str | None = None, preformateado: str | None = None, aviso: str | None = None, pie: str | None = None,
    preencabezado: str = "", html_crudo: bool = False, plano: str | None = None, idioma: str = "es",
) -> tuple[str, str]:
    """Plano + HTML de un correo. `html_crudo=True` deja pasar `titulo`, `codigo` y `parrafos` SIN escapar (solo para las plantillas de Kratos,
    donde llevan marcas `{{ .RecoveryCode }}` que Kratos sustituye; nunca con texto de usuarios)."""
    esc = (lambda t: t) if html_crudo else escape
    # --- texto plano ---
    plano_fijo = plano
    plano = [titulo, ""]
    for p in parrafos:
        plano += [p, ""]
    if codigo:
        plano += [f"    {codigo}", ""]
    if cita:
        plano += ["> " + cita.replace("\n", "\n> "), ""]
    if preformateado:
        plano += [preformateado, ""]
    if boton:
        plano += [f"{boton[0]}: {boton[1]}", ""]
    if aviso:
        plano += [aviso, ""]
    plano += ["--", pie or PIE_POR_DEFECTO]
    texto_plano = plano_fijo if plano_fijo is not None else "\n".join(plano) + "\n"

    # --- HTML ---
    bloques = []
    for p in parrafos:
        bloques.append(f'<p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:{TEXTO_SUAVE};">{esc(p).replace(chr(10), "<br>") if not html_crudo else p}</p>')
    if codigo:
        bloques.append(
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:8px auto 24px;"><tr>'
            f'<td align="center" style="background:#0a0a0c;border:1px solid #5b6b1f;border-radius:16px;padding:16px 28px;'
            f'font-family:{FUENTE_CODIGO};font-size:34px;line-height:1.1;font-weight:700;letter-spacing:10px;color:{ACENTO};">{esc(codigo)}</td></tr></table>'
        )
    if cita:
        bloques.append(
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:0 0 20px;"><tr>'
            f'<td style="border-left:3px solid {ACENTO};background:#171a20;border-radius:0 12px 12px 0;padding:14px 18px;font-size:15px;line-height:1.55;color:{TEXTO};">'
            f'{escape(cita).replace(chr(10), "<br>")}</td></tr></table>'
        )
    if preformateado:
        bloques.append(
            f'<pre style="margin:0 0 20px;padding:14px 16px;background:#0a0a0c;border:1px solid {BORDE};border-radius:12px;white-space:pre-wrap;word-break:break-word;'
            f'font-family:{FUENTE_CODIGO};font-size:13px;line-height:1.5;color:{TEXTO_SUAVE};">{escape(preformateado)}</pre>'
        )
    if boton:
        texto_boton, url = boton
        bloques.append(
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:8px auto 24px;"><tr>'
            f'<td align="center" bgcolor="{ACENTO}" style="border-radius:12px;background:{ACENTO};">'
            f'<a href="{escape(url, quote=True)}" target="_blank" style="display:inline-block;padding:14px 30px;border-radius:12px;font-family:{FUENTE};'
            f'font-size:16px;font-weight:700;line-height:1.2;color:{SOBRE_ACENTO};text-decoration:none;">{escape(texto_boton)}</a></td></tr></table>'
            f'<p style="margin:0 0 20px;font-size:12px;line-height:1.5;color:{TEXTO_APAGADO};text-align:center;word-break:break-all;">'
            f'<a href="{escape(url, quote=True)}" target="_blank" style="color:{TEXTO_APAGADO};text-decoration:underline;">{escape(url)}</a></p>'
        )
    if aviso:
        bloques.append(f'<p style="margin:8px 0 0;padding-top:18px;border-top:1px solid {BORDE};font-size:13px;line-height:1.55;color:{TEXTO_APAGADO};">{esc(aviso).replace(chr(10), "<br>") if not html_crudo else aviso}</p>')

    cuerpo = "\n".join(bloques)
    pre = escape(preencabezado or titulo) if not html_crudo else (preencabezado or titulo)
    html = f"""<!doctype html>
<html lang="{idioma}" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="supported-color-schemes" content="dark light">
<title>{esc(titulo)}</title>
<style>
  @media (max-width: 620px) {{ .tarjeta {{ padding: 28px 22px !important; border-radius: 20px !important; }} .exterior {{ padding: 16px 10px !important; }} h1 {{ font-size: 22px !important; }} }}
  a {{ color: {ACENTO}; }}
</style>
</head>
<body style="margin:0;padding:0;background:{FONDO_RESPALDO};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;font-size:1px;line-height:1px;">{pre}&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{FONDO_RESPALDO}" background="{BASE}/static/fotos/email-fondo.jpg"
       style="background:{FONDO_RESPALDO} url('{BASE}/static/fotos/email-fondo.jpg') center center / cover no-repeat;">
  <tr><td class="exterior" align="center" style="padding:40px 16px;">
    <table role="presentation" class="tarjeta" width="560" cellpadding="0" cellspacing="0" border="0"
           style="width:100%;max-width:560px;background:{FONDO_TARJETA};border:1px solid {BORDE};border-radius:28px;padding:40px 44px;font-family:{FUENTE};color:{TEXTO};">
      <tr><td align="center" style="padding:0 0 20px;">
        <img src="{BASE}/static/email-logo.png" width="56" height="56" alt="Guilda Work" style="display:block;border:0;outline:none;width:56px;height:56px;">
      </td></tr>
      <tr><td style="font-family:{FUENTE};">
        <h1 style="margin:0 0 20px;font-size:26px;line-height:1.2;font-weight:800;letter-spacing:-0.02em;color:{TEXTO};text-align:center;">{esc(titulo)}</h1>
        {cuerpo}
      </td></tr>
    </table>
    <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:560px;">
      <tr><td align="center" style="padding:18px 0 0;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center"><tr>
        <td style="background:#0c0e12;border:1px solid {BORDE};border-radius:999px;padding:8px 18px;font-family:{FUENTE};font-size:12px;line-height:1.5;color:{TEXTO_APAGADO};">{esc(pie or PIE_POR_DEFECTO)}</td>
      </tr></table></td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>
"""
    return texto_plano, html

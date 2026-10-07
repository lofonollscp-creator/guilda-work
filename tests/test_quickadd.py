"""Alta rápida en texto libre (app/quickadd.py): fechas, horas, prioridad, @personas y #etiquetas
en cuatro idiomas, y que lo dudoso no se adivine."""
from datetime import date

import pytest

from app.quickadd import interpretar

HOY = date(2026, 10, 7)       # miércoles
PERSONAS = [(1, "Ana García", "ana@x.com"), (2, "Luis Pérez", "luis@x.com"), (3, "Luisa Martín", "luisa@x.com"), (4, "", "jose.ramos@x.com")]
ETIQUETAS = [(10, "IVA"), (11, "Cierre trimestral 2T"), (12, "Cierre anual"), (13, "Recoger documentación")]


def _i(texto, **kw):
    return interpretar(texto, kw.pop("hoy", HOY), PERSONAS, ETIQUETAS)


def test_el_ejemplo_completo():
    r = _i("viernes 10h pedir extractos a Sol @ana !alta #IVA")
    assert (r.asunto, r.vencimiento, r.prioridad, r.persona_id, r.etiqueta_id, r.sin_resolver) == ("pedir extractos a Sol", "2026-10-09T10:00", "alta", 1, 10, [])


@pytest.mark.parametrize("texto,esperada", [
    ("llamar hoy", "2026-10-07"), ("llamar today", "2026-10-07"), ("llamar avui", "2026-10-07"), ("llamar aujourd'hui", "2026-10-07"),
    ("llamar mañana", "2026-10-08"), ("llamar tomorrow", "2026-10-08"), ("llamar demà", "2026-10-08"), ("llamar demain", "2026-10-08"),
    ("llamar pasado mañana", "2026-10-09"), ("call day after tomorrow", "2026-10-09"), ("trucar passat demà", "2026-10-09"),
    ("llamar el lunes", "2026-10-12"), ("llamar viernes", "2026-10-09"), ("llamar próximo martes", "2026-10-13"),
    ("llamar miércoles", "2026-10-14"),                       # hoy ya es miércoles: el de la semana que viene
    ("call monday", "2026-10-12"), ("trucar dimarts", "2026-10-13"), ("appeler jeudi", "2026-10-08"), ("llamar sábado", "2026-10-10"),
    ("llamar en 3 días", "2026-10-10"), ("call in 2 weeks", "2026-10-21"), ("trucar dins de 2 setmanes", "2026-10-21"),
    ("llamar en 1 mes", "2026-11-07"), ("llamar en 4 meses", "2027-02-07"),
    ("presentar el 20/10", "2026-10-20"), ("presentar 5/10", "2027-10-05"), ("presentar 15/07/2027", "2027-07-15"),
    ("presentar 15-07-27", "2027-07-15"), ("presentar 15.07.2027", "2027-07-15"), ("presentar 2026-12-31", "2026-12-31"),
    ("presentar el 15 de noviembre", "2026-11-15"), ("presentar 15 nov", "2026-11-15"), ("presentar 3 de enero de 2028", "2028-01-03"),
    ("presentar 15 de juliol", "2027-07-15"), ("file on october 21", "2026-10-21"), ("file Oct 21st", "2026-10-21"), ("déposer le 14 juillet", "2027-07-14"),
])
def test_fechas_en_varios_idiomas(texto, esperada):
    assert _i(texto).vencimiento == esperada, texto


@pytest.mark.parametrize("texto,hora", [
    ("reunión mañana 10h", "10:00"), ("reunión mañana 10:30", "10:30"), ("reunión mañana 10h30", "10:30"), ("reunión mañana a las 9", "09:00"),
    ("reunión mañana a las 9:15", "09:15"), ("reunión mañana 3pm", "15:00"), ("reunión mañana 12am", "00:00"), ("reunión mañana 12pm", "12:00"),
    ("reunió demà a les 17h", "17:00"),
])
def test_horas(texto, hora):
    r = _i(texto)
    assert r.hora == hora and r.fecha == date(2026, 10, 8) and r.vencimiento == f"2026-10-08T{hora}", texto


def test_una_hora_sin_fecha_es_para_hoy():
    r = _i("llamar a las 17:30")
    assert r.vencimiento == "2026-10-07T17:30" and r.asunto == "llamar"


@pytest.mark.parametrize("texto", ["revisar 5h de trabajo", "estimado 3h", "reunión por la mañana", "10.30 reunión", "pagar 303 y 111", "modelo 347", "llamar a Pérez"])
def test_no_se_confunde_el_texto_normal_con_fechas_u_horas(texto):
    r = _i(texto)
    assert r.fecha is None and r.hora is None and r.asunto == texto, texto


def test_fecha_con_mes_solo_vale_si_lleva_dia():
    assert _i("cerrar marzo").fecha is None and _i("cerrar el 3 de marzo").vencimiento == "2027-03-03"


def test_dias_imposibles_no_se_adivinan():
    assert _i("presentar 31/2").fecha is None and _i("presentar 32/1").fecha is None and _i("presentar 15/13").fecha is None
    assert _i("presentar 30 de febrero").fecha is None


def test_el_29_de_febrero_solo_en_bisiesto():
    assert _i("x 29/2").vencimiento == "2028-02-29"        # el siguiente año bisiesto alcanzable... el 2027 no lo es
    assert _i("x 29/2/2027").fecha is None


@pytest.mark.parametrize("texto,prioridad", [("x !alta", "alta"), ("x !urgente", "alta"), ("x !!", "alta"), ("x !baja", "baja"), ("x !low", "baja"), ("x !normal", "normal"), ("x !media", "normal")])
def test_prioridad(texto, prioridad):
    assert _i(texto).prioridad == prioridad and _i(texto).asunto == "x"


def test_una_exclamacion_normal_no_es_prioridad():
    r = _i("¡Importante! revisar todo")
    assert r.prioridad is None and r.asunto == "¡Importante! revisar todo"
    assert _i("x !inventada").prioridad is None


def test_menciones_a_personas():
    assert _i("@ana revisar").persona_id == 1 and _i("@García revisar").persona_id == 1
    assert _i("@luis revisar").persona_id == 2            # «luis» es palabra exacta de uno y prefijo de «luisa»
    assert _i("@luisa revisar").persona_id == 3
    assert _i("@jose revisar").persona_id == 4            # solo por la parte local del email
    assert _i("@Pérez revisar").persona_id == 2 and _i("@perez revisar").persona_id == 2   # sin acentos ni mayúsculas
    assert _i("revisar @ana.").persona_id == 1             # el punto final no es del nombre


def test_lo_ambiguo_o_inexistente_no_se_adivina():
    r = _i("@lu revisar")
    assert r.persona_id is None and r.sin_resolver == ["@lu"] and r.asunto == "@lu revisar"
    r = _i("@nadie revisar")
    assert r.persona_id is None and r.sin_resolver == ["@nadie"]
    assert _i("enviar a pepe@x.com").persona_id is None and _i("enviar a pepe@x.com").sin_resolver == []   # un email no es una mención


def test_etiquetas_proyecto_o_seccion():
    assert _i("x #IVA").etiqueta_id == 10 and _i("x #iva").etiqueta_id == 10
    assert _i("x #cierre-trimestral").etiqueta_id == 11 and _i("x #trimestral").etiqueta_id == 11
    assert _i("x #recoger").etiqueta_id == 13 and _i('x #"Recoger documentación"').etiqueta_id == 13 and _i("x #documentacion").etiqueta_id == 13
    r = _i("x #cierre")
    assert r.etiqueta_id is None and r.sin_resolver == ["#cierre"]        # «Cierre trimestral» y «Cierre anual»: ambiguo
    assert _i("x #nada").etiqueta_id is None and _i("x #nada").sin_resolver == ["#nada"]


def test_el_titulo_queda_limpio_y_si_todo_son_marcas_se_conserva_el_texto():
    assert _i("para el viernes llamar a Pérez").asunto == "llamar a Pérez"
    assert _i("llamar a Pérez para el viernes").asunto == "llamar a Pérez"
    assert _i("llamar a Pérez el 20/10 !alta @ana").asunto == "llamar a Pérez"
    r = _i("mañana")
    assert r.vencimiento == "2026-10-08" and r.asunto == "mañana"          # nunca se queda una tarea sin título
    assert _i("").asunto == "" and _i("   ").vencimiento is None


def test_solo_se_toma_la_primera_fecha_y_el_resto_se_deja():
    r = _i("pasar de viernes a lunes")
    assert r.fecha == date(2026, 10, 9) and "lunes" in r.asunto


def test_un_fin_de_ano_la_fecha_sin_anio_salta_al_siguiente():
    assert interpretar("x 5/1", date(2026, 12, 20)).vencimiento == "2027-01-05"
    assert interpretar("x 25/12", date(2026, 12, 20)).vencimiento == "2026-12-25"
    assert interpretar("x en 2 semanas", date(2026, 12, 20)).vencimiento == "2027-01-03"


def test_meses_con_menos_dias_al_sumar_meses():
    assert interpretar("x en 1 mes", date(2026, 1, 31)).vencimiento == "2026-02-28"
    assert interpretar("x en 1 mes", date(2028, 1, 31)).vencimiento == "2028-02-29"


def test_texto_hostil_no_rompe_nada():
    for texto in ["@" * 200, "#" * 200, "!" * 200, "9" * 500, "a/b/c " * 100, "'; DROP TABLE tareas; --", "\x00\x01 @ana", "💥 mañana 💥"]:
        r = _i(texto)
        assert isinstance(r.asunto, str)

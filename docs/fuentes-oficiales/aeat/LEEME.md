# Fuentes oficiales de la AEAT (referencia fechada, no código)

Descargadas el 24-oct-2026 desde `sede.agenciatributaria.gob.es` para el módulo fiscal (docs/plan-modulo-fiscal-alquileres.md, hito F0). `manifest.json` guarda la URL, el tamaño y la huella sha256 de cada una.

| Fichero | Qué es |
|---|---|
| `DR303e26v101.xlsx` | **Diseño de registro del modelo 303**, ejercicio 2026 y siguientes, versión 1.01 (actualizado 28/01/2026). De él sale `app/fiscal_modelos/disenos/303_2026_v101.json` con `scripts/fiscal/extraer_diseno.py` |
| `303_instrucciones_2026.html` | Instrucciones de cumplimentación 2026 (periodo 01 y 1T) |
| `303_ayuda_tecnica.html` | Ayuda técnica: importación, validación y exportación del fichero en el formulario web |
| `disenos_300_399.html` | Página de diseños de registro de los modelos 300–399 (para vigilar nuevas revisiones) |

Son material de consulta con su ejercicio: **no son reglas ejecutables**. Si la AEAT publica otra revisión, se descarga, se regenera el JSON y `tests/test_fiscal_diseno_303.py` dice qué ha cambiado.

| `CALCULO_CASILLAS_IVA_PRE303-LSI.xlsx` | **Tabla de decisión oficial** libro → casilla (calificación, tipo, clave de operación, fechas…): base de las reglas de F4 y **oráculo** de la vía de libros |
| `LSI.xlsx`, `LSIJ.xlsx` | Diseños de registro normalizados de los libros de IVA (físicas / jurídicas no SII) |
| `Formato_Electronico_Comun_Libros_Registro_IVA_IRPF.pdf` | Formato electrónico común de los libros |

Descargados el 27-oct-2026 (con permiso expreso de Jorge) para el 390 y los modelos de retenciones:

| Fichero | Qué es |
|---|---|
| `dr390e2025.xlsx` | **Diseño de registro del modelo 390**, ejercicio 2025 (actualizado 05/12/2025). De él sale `app/fiscal_modelos/disenos/390_2025.json` con `scripts/fiscal/extraer_diseno.py` |
| `Instrucciones_modelo_390-2025.pdf` | Instrucciones oficiales del 390 (cómo se rellena cada casilla; p. ej. la 108 = 99+653+103+104+105+110+100+101+102+125+126+127+128+227+228 − 106 − 107) |
| `disenos_100_199.html` | Página de diseños de registro de los modelos 100–199 (para vigilar revisiones del 111, 115, 130 y 131) |
| `dr111e16v18.xls`, `DR115e15v13.xls` | Diseños de registro del 111 y del 115, formato `.xls` antiguo (`xlrd` solo hace falta para extraerlos). De ellos salen `app/fiscal_modelos/disenos/111_v18.json` y `115_v13.json` con `scripts/fiscal/extraer_diseno.py`: base del fichero de retenciones |

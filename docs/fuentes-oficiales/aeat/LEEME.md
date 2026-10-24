# Fuentes oficiales de la AEAT (referencia fechada, no código)

Descargadas el 24-oct-2026 desde `sede.agenciatributaria.gob.es` para el módulo fiscal (docs/plan-modulo-fiscal-alquileres.md, hito F0). `manifest.json` guarda la URL, el tamaño y la huella sha256 de cada una.

| Fichero | Qué es |
|---|---|
| `DR303e26v101.xlsx` | **Diseño de registro del modelo 303**, ejercicio 2026 y siguientes, versión 1.01 (actualizado 28/01/2026). De él sale `app/fiscal_modelos/disenos/303_2026_v101.json` con `scripts/fiscal/extraer_diseno.py` |
| `303_instrucciones_2026.html` | Instrucciones de cumplimentación 2026 (periodo 01 y 1T) |
| `303_ayuda_tecnica.html` | Ayuda técnica: importación, validación y exportación del fichero en el formulario web |
| `disenos_300_399.html` | Página de diseños de registro de los modelos 300–399 (para vigilar nuevas revisiones) |

Son material de consulta con su ejercicio: **no son reglas ejecutables**. Si la AEAT publica otra revisión, se descarga, se regenera el JSON y `tests/test_fiscal_diseno_303.py` dice qué ha cambiado.

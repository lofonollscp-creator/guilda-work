# Fixtures del asistente jurídico — TODO ES SINTÉTICO

Estos ficheros **no son textos jurídicos reales**: reproducen la *estructura* de las respuestas del BOE (inspeccionadas contra el servicio real el 23-oct-2026) con contenido inventado, identificadores
`BOE-A-2099-…` y nombres ficticios. Sirven para probar el software (parsers, versiones, ingesta); **no acreditan calidad jurídica** ni cobertura real. Nunca se cargan en producción.

- `boe_consolidada_lista.xml` — respuesta de `legislacion-consolidada?from&to&offset&limit` (2 normas).
- `boe_norma_sintetica_1.xml` — `legislacion-consolidada/id/BOE-A-2099-0001`: metadatos, análisis, ELI y texto con bloques de varias versiones.
- `boe_norma_sintetica_2.xml` — una norma derogada con una versión sin fecha de vigencia.
- `boe_sumario_tc.xml` — sumario de un día con un departamento «TRIBUNAL CONSTITUCIONAL» (una sentencia, un auto y un nombramiento que se descarta) y un ministerio que menciona al TC.
- `boe_doc_tc_sentencia.xml`, `boe_doc_tc_auto.xml` — `diario_boe/xml.php?id=…` de una sentencia (con los encabezados «I. Antecedentes», «II. Fundamentos jurídicos» y «FALLO» como en el BOE real, y un voto particular) y un auto.

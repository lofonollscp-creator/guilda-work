# Libros de prueba para Guilda Fiscal

Todo inventado. Crea un titular de prueba con NIF **A12345674** (nombre «Empresa de prueba SL»), dale un **perfil fiscal** (sociedad, régimen general, trimestral, vigente desde 2026-01-01) y, en su ficha, usa **Importar un libro registro** con cada fichero. Después **Calcular un periodo** (ejercicio 2026, periodo 2T) y compara con lo esperado: es lo que calcula la propia AEAT con ese mismo libro.

| Fichero | Qué prueba | Casillas esperadas (2T 2026) | Resultado (casilla 71) |
|---|---|---|---|
| `basico.xlsx` | Una venta de 100 € al 21 % y una compra de 50 € al 21 %. | [07] 100.00 · [09] 21.00 · [27] 21.00 · [28] 50.00 · [29] 10.50 · [45] 10.50 · [46] 10.50 | **10.50 €** |
| `tipos.xlsx` | Ventas al 4 %, 10 % y 21 %. | [07] 100.00 · [09] 21.00 · [01] 100.00 · [03] 4.00 · [04] 100.00 · [06] 10.00 · [27] 35.00 · [46] 35.00 | **35.00 €** |
| `rectificativas.xlsx` | Ventas, un abono (R1) y una compra rectificada: casillas 14 y 15, y 40 y 41. | [07] 100.00 · [09] 21.00 · [14] -30.00 · [15] -6.30 · [27] 14.70 · [28] 50.00 · [29] 10.50 · [40] -5.00 · [41] -1.05 · [45] 9.45 · [46] 5.25 | **5.25 €** |
| `otros_trimestres.xlsx` | Facturas de 1T, 2T y 3T: el 303 del 2T solo cuenta las suyas. | [07] 100.00 · [09] 21.00 · [27] 21.00 · [28] 30.00 · [29] 6.30 · [45] 6.30 · [46] 14.70 | **14.70 €** |
| `bien_inversion.xlsx` | Una compra de un bien de inversión (casillas 30 y 31). | [07] 2000.00 · [09] 420.00 · [27] 420.00 · [28] 10.00 · [29] 2.10 · [30] 800.00 · [31] 168.00 · [45] 170.10 · [46] 249.90 | **249.90 €** |
| `adquisicion_intracomunitaria.xlsx` | Compra a un proveedor francés (se devenga y se deduce: casillas 10, 11, 36 y 37). | [07] 100.00 · [09] 21.00 · [10] 200.00 · [11] 42.00 · [27] 63.00 · [36] 200.00 · [37] 42.00 · [45] 42.00 · [46] 21.00 | **21.00 €** |
| `inversion_sujeto_pasivo.xlsx` | Compra con inversión del sujeto pasivo (casillas 12, 13, 28 y 29). | [07] 100.00 · [09] 21.00 · [12] 150.00 · [13] 31.50 · [27] 52.50 · [28] 150.00 · [29] 31.50 · [45] 31.50 · [46] 21.00 | **21.00 €** |
| `alquiler_local_comercial.xlsx` | Alquiler de un local de negocio al 21 % con referencia catastral, y su gasto. | [07] 1000.00 · [09] 210.00 · [27] 210.00 · [28] 345.00 · [29] 72.45 · [45] 72.45 · [46] 137.55 | **137.55 €** |
| `alquiler_vivienda_exento.xlsx` | Alquiler de vivienda exento (no entra en la cuota) junto a una venta normal. | [07] 100.00 · [09] 21.00 · [27] 21.00 · [28] 25.00 · [29] 5.25 · [45] 5.25 · [46] 15.75 | **15.75 €** |
| `alquiler_turistico_al_10.xlsx` | Alquiler turístico (servicio de hospedaje) al 10 %. | [04] 750.00 · [06] 75.00 · [27] 75.00 · [28] 210.00 · [29] 30.90 · [45] 30.90 · [46] 44.10 | **44.10 €** |
| `resultado_negativo.xlsx` | Más IVA soportado que repercutido: sale a favor. | [07] 10.00 · [09] 2.10 · [27] 2.10 · [28] 500.00 · [29] 105.00 · [45] 105.00 · [46] -102.90 | **-102.90 €** |

Nota: los libros están pensados para **un solo titular de prueba cada vez** (se importan sobre apuntes vacíos). Para repetir con otro fichero, crea otro titular de prueba o anula los apuntes anteriores.
Una fila idéntica a otra ya aprobada no se duplica. El 4T no se prueba todavía (la AEAT no lo permite hasta enero de 2027).

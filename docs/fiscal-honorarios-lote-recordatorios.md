# Honorarios por tramos, cambios en lote fiscales y recordatorios de firma (migración 015)

## Honorarios por tramos (`app/honorarios.py`, pantalla `/guilda-fiscal/honorarios`)
- **Reglas** con prioridad: aplica la primera regla activa cuyos filtros encajan (modelo y forma jurídica del titular; vacío = todos). Tres formas de calcular, en céntimos: **fijo**,
  **base + importe por apunte** (con mínimo) y **por tramos** según el número de apuntes (el último tramo queda abierto).
- Los apuntes son los no anulados del titular dentro del periodo del vencimiento («2T 2026», «2026-T2», «2025»). En otro formato de periodo solo sirven las reglas fijas.
- **Proponer no cobra nada.** La dirección (o el revisor fiscal) confirma la propuesta de un vencimiento ya presentado, o fija otro importe: el desglose conserva el cálculo y marca «ajustado a mano».
  Lo confirmado guarda la regla y el cálculo tal y como estaban, aunque la regla cambie después. Se marca como facturado con el nº de factura, o se anula con motivo.
- **No emite facturas.** La factura se sigue creando en FacturaScripts; aquí queda el importe propuesto y la referencia.
- **Pendiente de decidir por el despacho:** las tarifas (son decisión suya) y si quiere enlazar el importe con una factura creada desde el expediente.

## Cambios en lote de vencimientos (`app/fiscal_masivo.py`, `/guilda-fiscal/masivo`)
Mismo patrón que el Comercial: **proponer → confirmar (1 h) → deshacer (90 días)**. Dos acciones: cambiar de responsable y posponer la fecha de seguimiento (1-90 días, con motivo).
Posponer mueve la fecha que sigue el despacho, **no el plazo legal**. Solo se tocan los vencimientos pendientes; marcar como presentado y aprobar apuntes **no** se hacen en lote
(son declaraciones de quien presenta o revisa). Lo que cambió entre la propuesta y la confirmación se omite.

## Recordatorio de firma (`documentos_firma.recordar`, `documenso.reenviar_a_firma`)
- Botón «Recordar la firma» en cada documento pendiente: antes pregunta a Documenso si ya está firmado y, si no, reenvía el aviso solo a quien no ha firmado (`envelope/redistribute`). Hasta 3 veces.
- **Automático, opcional:** en Documentos de firma → «Recordar a quien no firma», la dirección fija los días (0 = no). El temporizador de firmas (`sincronizar-firmas`) reenvía el aviso a quien lleva
  esos días sin firmar desde el último aviso.

## Aviso de vencimientos por correo (Marketing)
Un grupo de Marketing puede filtrar por **modelo fiscal por presentar en los próximos N días** (clientes con Guilda Fiscal enlazada). Se aplica encima de las reglas de siempre: consentimiento
vigente, sin bajas ni rebotes, un correo por dirección. Hay una plantilla de partida «Aviso de vencimiento fiscal». El envío sigue exigiendo confirmación de la dirección: **no hay envíos automáticos**.

## Puesta en producción
Migración 015 con el superusuario **antes** de reiniciar `guilda-work`, `guilda-work-mcp` y `guilda-backoffice` (tres tablas nuevas y dos columnas en `documentos_firma`).
No hay variables nuevas ni temporizadores nuevos: el recordatorio de firma usa el de `sincronizar-firmas`.

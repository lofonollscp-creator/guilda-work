# Portal de clientes: comprobación guiada (lo que solo se puede ver con terceros reales)

Las pruebas automáticas (`scripts/probar.sh` y el barrido `scripts/probar_navegador.sh -k test_barrido_portal`) no pueden ejercitar estas cosas: dependen de servicios de fuera o de un dispositivo real. Se hacen a mano, una vez, con un cliente de prueba de tu propio despacho (o con el equipo en «Vista previa» cuando solo se necesita mirar).

Antes de empezar: crea un cliente de prueba con tu correo y entra con el enlace que llega al correo, desde `https://clientes.guildawork.com/portal/`.

## 1. Notas de voz (OpenAI)
- [ ] En Recordatorios, activa «Notas de voz». Con la clave de OpenAI puesta (y sin «solo local» en el OCR).
- [ ] En Mensajes → nuevo mensaje, pulsa el micrófono, di una frase de 10 segundos y para. Debe aparecer el texto transcrito en el cuadro, editable.
- [ ] Repite en **Safari de iPhone** y en **Chrome de Android** (el permiso del micrófono pide aceptar una vez).
- [ ] Con «solo local» activo el botón del micrófono no debe aparecer.

## 2. Tarea «Llamar a…» a los 14 días
- [ ] Con una espera de cliente de más de 14 días (puedes retrasar a mano la fecha de la solicitud en la base de pruebas), el proceso de avisos crea una tarea «Llamar a…» para quien lleva al cliente. Una sola vez.

## 3. Passkeys en el dominio nuevo
- [ ] Entra a Mi cuenta → Seguridad. Si tenías una passkey creada en `app.guildawork.com`, debe salir el aviso «Tus passkeys se crearon en otra dirección…».
- [ ] Añade una passkey nueva. Cierra la sesión y entra pulsando «Entrar con passkey»: debe abrirse sin pedir correo.

## 4. Pagos y avisos
- [ ] **Stripe**: paga unos honorarios de prueba (modo test) y comprueba que vuelve a Impuestos con «Gracias: hemos recibido tu pago» y que pasa a «Pagado».
- [ ] **Twilio / WhatsApp**: manda un aviso al móvil del cliente de prueba y responde; el webhook sigue firmándose sobre la URL pública de siempre (`GUILDA_URL_PUBLICA`).

## 5. Tema y pantallas pequeñas (en un móvil de verdad)
- [ ] En el menú de perfil, Claro / Oscuro / Sistema cambian al instante y se recuerdan al recargar.
- [ ] En un móvil con el modo oscuro del sistema activado y «Sistema» elegido, el portal sale oscuro sin parpadeo blanco.
- [ ] Facturas y Documentos: las tablas se ven como tarjetas, sin desplazamiento lateral.
- [ ] «Añadir a la pantalla de inicio»: la app instalada lleva el nombre y el color del despacho.

## 6. Cuántos despachos usan todavía el portal antiguo (V4)
Cuando no quede ninguno con el interruptor apagado durante unas semanas, se puede retirar el portal antiguo (la barra de arriba de siempre, `portal_nuevo = 0`):

```sql
SELECT COUNT(*) FROM portal_recordatorios_config WHERE portal_nuevo = 0;
```

Si sale 0, se borra el código del portal antiguo y la fixture `portal_antiguo` de los tests.

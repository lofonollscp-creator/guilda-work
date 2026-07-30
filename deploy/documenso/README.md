# Certificado de firma de Documenso (`cert.p12`)

Documenso exige un certificado PKCS#12 en `/opt/documenso/cert.p12`
dentro del contenedor (confirmado en vivo: sin él, ni arranca) — lo usa
para firmar criptográficamente cada PDF completado.

Este archivo **no se sube al repositorio** (ver `.gitignore`) — genera
el tuyo, una vez, en el servidor:

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 3650 -nodes \
  -subj "/CN=Guilda Work"
openssl pkcs12 -export -out deploy/documenso/cert.p12 -inkey key.pem -in cert.pem \
  -passout pass:TU_PASSPHRASE
rm key.pem cert.pem
```

Guarda `TU_PASSPHRASE` como `DOCUMENSO_SIGNING_PASSPHRASE` en `.env`
(`docker-compose.yml`) — tiene que coincidir con la que uses aquí.

Un certificado autofirmado es suficiente para que Documenso funcione
(firma técnica, verificable con el propio certificado incrustado en el
PDF) — si en el futuro hace falta validez legal reforzada frente a
terceros, se sustituye por uno emitido por una autoridad de
certificación real, sin cambiar nada más de la configuración.

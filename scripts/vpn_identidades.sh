#!/usr/bin/env bash
# Identidades de OpenVPN (acceso VPN al servidor, HOSTING.md 8.18): listar, crear, revocar y dejar el estado para el panel Salud. Se ejecuta como root (o alguien con acceso a Docker), nunca desde la web:
# crear credenciales de acceso a la red desde un panel web daría a quien lo comprometa un acceso VPN, así que se hace a mano y queda anotado.
#
#   scripts/vpn_identidades.sh listar                       identidades, caducidad y si están revocadas
#   scripts/vpn_identidades.sh crear NOMBRE [CARPETA]       crea la identidad (sin contraseña) y guarda NOMBRE.ovpn (modo 600) en CARPETA (por defecto, ./vpn-perfiles); ENTREGA el fichero y BÓRRALO
#   scripts/vpn_identidades.sh revocar NOMBRE               revoca la identidad, regenera la lista de revocación y reinicia el servidor VPN
#   scripts/vpn_identidades.sh estado                       escribe data/backups/vpn_estado.json (lo lee Salud; lo lanza deploy/vpn-estado.timer cada día)
set -euo pipefail
VOLUMEN="${GUILDA_OVPN_VOLUMEN:-guilda-work_ovpn-data}"
CONTENEDOR="${GUILDA_OVPN_CONTENEDOR:-guilda-work-openvpn}"
IMAGEN="${GUILDA_OVPN_IMAGEN:-kylemanna/openvpn:latest@sha256:643531abb010a088f1e23a1c99d44f0bd417a3dbb483f809caf4396b5c9829a0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ESTADO="${GUILDA_VPN_ESTADO:-$REPO/data/backups/vpn_estado.json}"
_ovpn() { docker run -v "$VOLUMEN:/etc/openvpn" --rm "$IMAGEN" "$@"; }
_valido() { [[ "$1" =~ ^[A-Za-z0-9._-]{1,40}$ ]] || { echo "Nombre no válido (letras, números, punto, guion y guion bajo; hasta 40)." >&2; exit 2; }; }

json() {   # imprime [{nombre, caduca, dias, revocada}] leyendo el índice de la PKI
  docker exec "$CONTENEDOR" cat /etc/openvpn/pki/index.txt | python3 -c '
import sys, json, datetime
hoy = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
salida = []
for linea in sys.stdin:
    c = linea.rstrip("\n").split("\t")
    if len(c) < 6: continue
    estado, caduca, revocada, _serie, _x, sujeto = c[0], c[1], c[2], c[3], c[4], c[5]
    nombre = sujeto.split("/CN=")[-1]
    tipo = "servidor" if nombre == "server" else "cliente"
    cad = datetime.datetime.strptime(caduca[:12], "%y%m%d%H%M%S")
    salida.append({"nombre": nombre, "tipo": tipo, "caduca": cad.strftime("%Y-%m-%d"), "dias": (cad - hoy).days, "revocada": estado == "R"})
print(json.dumps(salida))'
}

caso="${1:-}"; shift || true
case "$caso" in
  listar) json | python3 -c "
import sys, json
for i in json.load(sys.stdin):
    print('%-20s %-9s caduca %s (%s días)%s' % (i['nombre'], i['tipo'], i['caduca'], i['dias'], '  REVOCADA' if i['revocada'] else ''))" ;;
  crear)
    n="${1:?falta NOMBRE}"; _valido "$n"; sal="${2:-./vpn-perfiles}"
    if json | python3 -c "import sys, json; sys.exit(0 if any(i['nombre'] == sys.argv[1] for i in json.load(sys.stdin)) else 1)" "$n"; then echo "Ya existe una identidad llamada $n." >&2; exit 1; fi
    mkdir -p "$sal"; chmod 700 "$sal"
    _ovpn easyrsa build-client-full "$n" nopass >/dev/null 2>&1
    ( umask 077; _ovpn ovpn_getclient "$n" > "$sal/$n.ovpn" )
    echo "Creada la identidad $n: $sal/$n.ovpn (contiene la clave privada: entrégalo por un canal seguro y bórralo)." ;;
  revocar)
    n="${1:?falta NOMBRE}"; _valido "$n"
    docker run -v "$VOLUMEN:/etc/openvpn" --rm "$IMAGEN" sh -c "echo yes | easyrsa revoke '$n' && easyrsa gen-crl" >/dev/null 2>&1
    docker restart "$CONTENEDOR" >/dev/null
    echo "Revocada la identidad $n (el servidor VPN se ha reiniciado)." ;;
  estado)
    mkdir -p "$(dirname "$ESTADO")"
    json | python3 -c 'import sys,json,datetime; print(json.dumps({"fecha": datetime.datetime.now().isoformat(timespec="seconds"), "identidades": json.load(sys.stdin)}))' > "$ESTADO.tmp"
    mv "$ESTADO.tmp" "$ESTADO"; chown --reference="$REPO/data" "$ESTADO" 2>/dev/null || true ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac

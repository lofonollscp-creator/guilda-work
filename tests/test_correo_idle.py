"""IMAP IDLE: el núcleo contra un servidor TCP real mínimo, y el gestor de hilos por cuenta."""
import imaplib
import socket
import threading
import time

import pytest

from app import correo, correo_idle, db


class ServidorIdle:
    """Servidor IMAP mínimo en un socket real: LOGIN, SELECT, IDLE/DONE y LOGOUT."""

    def __init__(self, idle=True):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.puerto = self.sock.getsockname()[1]
        self.idle = idle
        self.conexion = None
        self.comandos = []
        self.conectado = threading.Event()
        self.en_idle = threading.Event()
        self.hecho = threading.Event()
        threading.Thread(target=self._aceptar, daemon=True).start()

    def _aceptar(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.conexion = c
            threading.Thread(target=self._atender, args=(c,), daemon=True).start()

    def _atender(self, c):
        f = c.makefile("rb")
        capacidades = "IMAP4rev1 UIDPLUS" + (" IDLE" if self.idle else "")
        c.sendall(f"* OK listo\r\n".encode())
        self.conectado.set()
        for linea in f:
            partes = linea.decode().strip().split(" ", 2)
            etiqueta, comando = partes[0], (partes[1].upper() if len(partes) > 1 else "")
            self.comandos.append(comando if etiqueta != "DONE" else "DONE")
            if etiqueta.upper() == "DONE":
                c.sendall(f"{self._tag_idle} OK IDLE terminado\r\n".encode())
                self.hecho.set()
            elif comando == "CAPABILITY":
                c.sendall(f"* CAPABILITY {capacidades}\r\n{etiqueta} OK ok\r\n".encode())
            elif comando == "LOGIN":
                c.sendall(f"{etiqueta} OK [CAPABILITY {capacidades}] logueado\r\n".encode())
            elif comando in ("SELECT", "EXAMINE"):
                c.sendall(f"* 2 EXISTS\r\n{etiqueta} OK [READ-ONLY] ok\r\n".encode())
            elif comando == "IDLE":
                self._tag_idle = etiqueta
                c.sendall(b"+ idling\r\n")
                self.en_idle.set()
            elif comando == "LOGOUT":
                c.sendall(f"* BYE\r\n{etiqueta} OK adios\r\n".encode())
                c.close()
                return
            else:
                c.sendall(f"{etiqueta} OK ok\r\n".encode())

    def avisar(self, texto=b"* 3 EXISTS\r\n"):
        self.conexion.sendall(texto)

    def cerrar_conexion(self):
        self.conexion.shutdown(socket.SHUT_RDWR)

    def parar(self):
        self.sock.close()


@pytest.fixture
def servidor():
    s = ServidorIdle()
    yield s
    s.parar()


def _conectar(s):
    conn = imaplib.IMAP4("127.0.0.1", s.puerto)
    conn.login("u", "p")
    conn.select("INBOX", readonly=True)
    return conn


def _en_hilo(conn, segundos):
    r = {}
    t = threading.Thread(target=lambda: r.update(valor=correo_idle.esperar_cambios(conn, segundos)), daemon=True)
    t.start()
    return t, r


def test_un_aviso_del_servidor_despierta_el_idle_y_se_cierra_con_done(servidor):
    conn = _conectar(servidor)
    t, r = _en_hilo(conn, 10)
    assert servidor.en_idle.wait(3)
    servidor.avisar()
    t.join(3)
    assert r["valor"] == "cambio" and servidor.hecho.wait(3) and "DONE" in servidor.comandos
    assert conn.noop()[0] == "OK"                     # la conexión sigue siendo utilizable


def test_sin_novedades_vence_el_tiempo_y_termina_el_idle(servidor):
    conn = _conectar(servidor)
    t0 = time.monotonic()
    t, r = _en_hilo(conn, 1)
    t.join(5)
    assert r["valor"] == "timeout" and time.monotonic() - t0 < 4 and servidor.hecho.is_set()


def test_expunge_y_flags_tambien_cuentan_y_otros_avisos_no(servidor):
    for aviso, esperado in ((b"* 1 EXPUNGE\r\n", "cambio"), (b"* 4 FETCH (FLAGS (\\Seen))\r\n", "cambio"), (b"* OK still here\r\n", "timeout")):
        servidor.en_idle.clear(); servidor.hecho.clear()
        conn = _conectar(servidor)
        t, r = _en_hilo(conn, 1.5)
        assert servidor.en_idle.wait(3)
        servidor.avisar(aviso)
        t.join(5)
        assert r["valor"] == esperado, aviso


def test_conexion_cortada_devuelve_cerrada(servidor):
    conn = _conectar(servidor)
    t, r = _en_hilo(conn, 10)
    assert servidor.en_idle.wait(3)
    servidor.cerrar_conexion()
    t.join(5)
    assert r["valor"] == "cerrada"


# --- gestor ---------------------------------------------------------------------------------

def _cuenta(email, protocolo="imap"):
    uid = db.crear_usuario(email, "contrasena123")
    return uid, db.crear_cuenta_correo(uid, "c", protocolo, "127.0.0.1", 1, "u", usa_tls=False)


def test_el_gestor_arranca_un_hilo_por_cuenta_imap_y_respeta_el_maximo(monkeypatch):
    arrancados = []
    monkeypatch.setattr(correo_idle.GestorIdle, "_trabajar", lambda self, c, u: arrancados.append(c) or self.parar.wait(2))
    _, a = _cuenta("idle-1@x.com")
    _, b = _cuenta("idle-2@x.com")
    _, pop = _cuenta("idle-3@x.com", "pop3")
    g = correo_idle.GestorIdle(maximo=1)
    assert g.revisar() == 1 and g.revisar() == 1
    g.parar.set()
    g2 = correo_idle.GestorIdle(maximo=10)
    assert g2.revisar() == 2 and pop not in g2.hilos and {a, b} == set(g2.hilos)
    g2.parar.set()


def test_el_hilo_sincroniza_al_recibir_aviso_y_sale_si_no_hay_idle(servidor, monkeypatch):
    uid = db.crear_usuario("idle-4@x.com", "contrasena123")
    cuenta = db.crear_cuenta_correo(uid, "c", "imap", "127.0.0.1", servidor.puerto, "u", usa_tls=False)
    monkeypatch.setattr(correo, "_contrasena", lambda cuenta_id: "p")
    sincronizadas = []
    monkeypatch.setattr(correo, "sincronizar_bandeja", lambda u, c: sincronizadas.append((u, c)) or {"nuevos": 1})
    monkeypatch.setattr(correo_idle, "ESPERA_ANTES_DE_SINCRONIZAR", 0.05)
    g = correo_idle.GestorIdle()
    hilo = threading.Thread(target=g._trabajar, args=(cuenta, uid), daemon=True)
    hilo.start()
    assert servidor.en_idle.wait(5)
    servidor.avisar()
    for _ in range(50):
        if sincronizadas:
            break
        time.sleep(0.1)
    assert sincronizadas == [(uid, cuenta)]
    g.parar.set()
    servidor.cerrar_conexion()
    hilo.join(5)
    # servidor sin IDLE: el hilo termina solo
    sin = ServidorIdle(idle=False)
    try:
        c2 = db.crear_cuenta_correo(uid, "d", "imap", "127.0.0.1", sin.puerto, "u", usa_tls=False)
        g2 = correo_idle.GestorIdle()
        h2 = threading.Thread(target=g2._trabajar, args=(c2, uid), daemon=True)
        h2.start(); h2.join(5)
        assert not h2.is_alive()
    finally:
        sin.parar()


def test_configuracion_por_entorno(monkeypatch):
    monkeypatch.setenv("GUILDA_CORREO_IDLE", "0")
    assert correo_idle.habilitado() is False
    monkeypatch.setenv("GUILDA_CORREO_IDLE", "1")
    monkeypatch.setenv("GUILDA_CORREO_IDLE_MAX", "x")
    assert correo_idle.habilitado() and correo_idle.maximo_cuentas() == 100

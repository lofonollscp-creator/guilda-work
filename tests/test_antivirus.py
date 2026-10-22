"""Antivirus (app/antivirus.py): protocolo de ClamAV contra un `clamd` simulado, política (apagado, amenaza, antivirus caído) y los tres puntos de subida del portal."""
import io
import socket
import struct
import threading

import pytest

from app import antivirus, db, notificaciones_email, tareas_trabajo as tt
from tests.test_tareas_adjuntos_cliente import PDF, _filas_adjuntos, _subir
from tests.test_tareas_portal_cliente import _guardados, _mundo, _portal, _tarea_comentable

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class FakeClamd:
    """Habla lo justo del protocolo de clamd: zPING y zINSTREAM (trozos con longitud de 4 bytes y cero final). Marca como infectado lo que lleve EICAR."""

    def __init__(self, modo="normal"):
        self.modo, self.conexiones, self.bytes_recibidos = modo, 0, []
        self.servidor = socket.socket()
        self.servidor.bind(("127.0.0.1", 0))
        self.servidor.listen(8)
        self.puerto = self.servidor.getsockname()[1]
        threading.Thread(target=self._servir, daemon=True).start()

    def _servir(self):
        while True:
            try:
                s, _ = self.servidor.accept()
            except OSError:
                return
            self.conexiones += 1
            threading.Thread(target=self._atender, args=(s,), daemon=True).start()

    def _leer(self, s, n):
        datos = b""
        while len(datos) < n:
            parte = s.recv(n - len(datos))
            if not parte:
                raise ConnectionError
            datos += parte
        return datos

    def _atender(self, s):
        try:
            if self.modo == "cerrar":
                return
            orden = b""
            while not orden.endswith(b"\0"):
                orden += self._leer(s, 1)
            if orden == b"zPING\0":
                s.sendall(b"PONG\0")
                return
            contenido = b""
            while True:
                (n,) = struct.unpack("!I", self._leer(s, 4))
                if n == 0:
                    break
                contenido += self._leer(s, n)
            self.bytes_recibidos.append(len(contenido))
            if self.modo == "error":
                s.sendall(b"INSTREAM size limit exceeded. ERROR\0")
            elif b"EICAR" in contenido:
                s.sendall(b"stream: Eicar-Test-Signature FOUND\0")
            else:
                s.sendall(b"stream: OK\0")
        except (ConnectionError, OSError):
            pass
        finally:
            s.close()

    def cerrar(self):
        self.servidor.close()


@pytest.fixture
def clamd(monkeypatch):
    f = FakeClamd()
    monkeypatch.setenv("CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMAV_PUERTO", str(f.puerto))
    yield f
    f.cerrar()


def test_el_protocolo_distingue_limpio_infectado_y_error(clamd):
    assert antivirus.escanear(b"hola") == ("limpio", "")
    assert antivirus.escanear(EICAR) == ("infectado", "Eicar-Test-Signature")
    clamd.modo = "error"
    r, detalle = antivirus.escanear(b"hola")
    assert r == "error" and "ERROR" in detalle
    clamd.modo = "cerrar"
    assert antivirus.escanear(b"hola")[0] == "error"
    clamd.modo = "normal"
    assert antivirus.disponible() is True


def test_un_archivo_grande_llega_entero_en_varios_trozos(clamd):
    grande = b"a" * (5 * 1024 * 1024 + 123)
    assert antivirus.escanear(grande)[0] == "limpio" and clamd.bytes_recibidos == [len(grande)]


def test_sin_configurar_no_se_escanea_ni_se_conecta(monkeypatch):
    f = FakeClamd()
    monkeypatch.delenv("CLAMAV_HOST", raising=False)
    antivirus.exigir_limpio("virus.pdf", EICAR)                                                    # apagado: no hace nada
    assert antivirus.configurado() is False and f.conexiones == 0
    f.cerrar()


def test_una_amenaza_se_rechaza_con_aviso_a_la_direccion_y_auditoria(clamd):
    from app import auditoria
    t = db.crear_tenant("Despacho antivirus")
    dir_ = db.crear_usuario_vinculado_a_kratos("dir-av@ejemplo.com", "k-dir-av"); db.asignar_tenant(dir_, t); db.asignar_supervisor_tenant(dir_, True)
    c = db.crear_cliente_fiscal(t, "Cliente Infectado")
    with pytest.raises(antivirus.ArchivoRechazado) as e:
        antivirus.exigir_limpio("factura.pdf", PDF + EICAR, t, c)
    assert e.value.codigo == "virus" and "Eicar" not in str(e.value) and "peligroso" in str(e.value)       # al cliente no se le cuenta la firma
    conn = db.get_connection()
    try:
        avisos = [dict(f) for f in conn.execute("SELECT * FROM notificaciones WHERE usuario_id = ? AND tipo = 'antivirus'", (dir_,))]
    finally:
        conn.close()
    assert len(avisos) == 1 and "Cliente Infectado" in avisos[0]["titulo"] and "Eicar-Test-Signature" in avisos[0]["cuerpo"]
    assert "antivirus.rechazado" in {x["accion"] for x in auditoria.listar(t, entidad="cliente")}
    antivirus.exigir_limpio("limpio.pdf", PDF, t, c)                                                 # lo limpio pasa


def test_si_el_antivirus_cae_se_rechaza_por_defecto_y_se_puede_aceptar(clamd, monkeypatch):
    clamd.modo = "cerrar"
    with pytest.raises(antivirus.ArchivoRechazado) as e:
        antivirus.exigir_limpio("a.pdf", PDF)
    assert e.value.codigo == "antivirus_no_disponible"
    monkeypatch.setenv("CLAMAV_SI_FALLA", "aceptar")
    antivirus.exigir_limpio("a.pdf", PDF)                                                           # decisión explícita del despacho
    monkeypatch.setenv("CLAMAV_SI_FALLA", "rechazar")
    monkeypatch.setenv("CLAMAV_PUERTO", "1")                                                         # ni siquiera hay nadie escuchando
    with pytest.raises(antivirus.ArchivoRechazado):
        antivirus.exigir_limpio("a.pdf", PDF)


# --- Los puntos de subida del portal ---------------------------------------------------------------------------------------------

def test_un_comentario_con_un_archivo_infectado_no_se_guarda_ni_el_texto(cliente, clamd):
    uid, t, c1, c2 = _mundo(cliente, "av1@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    r = _subir(portal, tid, [("bueno.pdf", PDF), ("malo.pdf", PDF + EICAR)], "Os mando todo")
    assert r.status_code == 302 and "aviso=" in r.headers["Location"] and _guardados(tid) == [] and _filas_adjuntos(tid) == []
    assert _subir(portal, tid, [("bueno.pdf", PDF)]).status_code == 302 and len(_filas_adjuntos(tid)) == 1        # lo limpio sí


def test_un_comentario_con_el_antivirus_caido_no_se_guarda(cliente, clamd):
    uid, t, c1, c2 = _mundo(cliente, "av2@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    clamd.modo = "cerrar"
    r = _subir(_portal(cliente, c1), tid, [("bueno.pdf", PDF)])
    assert "aviso=" in r.headers["Location"] and _filas_adjuntos(tid) == [] and _guardados(tid) == []


def test_documentos_de_un_vencimiento_infectados_se_rechazan(cliente, clamd):
    tenant_id = db.crear_tenant("Gestoría antivirus documentos")
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente doc", email="av3@ejemplo.com")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    cliente.get(f"/portal/entrar/{db.crear_acceso_cliente_fiscal(cliente_id, '127.0.0.1')}")
    r = cliente.post(f"/portal/vencimientos/{v_id}/documentos", data={"documento": [(io.BytesIO(PDF + EICAR), "malo.pdf", "application/pdf"), (io.BytesIO(PDF), "bueno.pdf", "application/pdf")]},
                     content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "antivirus ha detectado" in html
    assert [d["nombre_archivo"] for d in db.listar_documentos_vencimiento(v_id)] == ["bueno.pdf"]


def test_facturas_del_portal_infectadas_se_rechazan_y_no_se_guarda_ninguna(cliente, clamd):
    from tests.test_facturas_contables import _portal as _portal_facturas, fc
    t, u, c = _portal_facturas(cliente, "Despacho antivirus facturas")
    r = cliente.post("/portal/facturas", data={"tipo": "recibida", "fecha": "2026-09-10", "numero": "M-1", "tercero_nombre": "X", "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21",
                                                "archivo": (io.BytesIO(PDF + EICAR), "factura.pdf", "application/pdf")}, content_type="multipart/form-data")
    assert r.status_code == 200 and "antivirus ha detectado" in r.get_data(as_text=True) and fc.listar(t, u) == []
    r = cliente.post("/portal/facturas", data={"modo": "archivos", "tipo": "recibida", "archivos": [(io.BytesIO(PDF), "ok.pdf", "application/pdf"), (io.BytesIO(PDF + EICAR), "malo.pdf", "application/pdf")]},
                     content_type="multipart/form-data")
    assert r.status_code == 200 and "antivirus ha detectado" in r.get_data(as_text=True) and fc.listar(t, u) == []          # si uno falla, no entra ninguno


def test_sin_antivirus_configurado_todo_funciona_como_siempre(cliente, monkeypatch):
    monkeypatch.delenv("CLAMAV_HOST", raising=False)
    uid, t, c1, c2 = _mundo(cliente, "av5@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    assert _subir(_portal(cliente, c1), tid, [("malo.pdf", PDF + EICAR)]).status_code == 302 and len(_filas_adjuntos(tid)) == 1

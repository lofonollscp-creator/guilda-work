"""Acceso a la base de datos SQLite de Guilda Work.

Todos los timestamps se guardan en hora local (Europe/Madrid), formato
ISO 8601 sin zona horaria explícita, ej: 2026-07-10T14:32:05.

Multiusuario (Fase 1 de la app móvil): categorias, notas, tareas,
tareas_outlook, correo_cuentas, correo_categorias e ia_mensajes llevan
`usuario_id` directamente (denormalizado incluso en las que cuelgan de una
categoría, porque notas/tareas pueden no tener categoría). Las tablas que
cuelgan de una de esas con FK NOT NULL (pausas, plantillas,
correo_carpetas, correo_mensajes, correo_adjuntos) se aíslan a través de su
padre, sin columna propia. `correo_preferencias`/`ia_preferencias` pasan de
fila única global (`id=1`) a una fila por usuario (`usuario_id` como clave
primaria).

Limitación conocida de esta fase: `categorias.nombre` y
`correo_categorias.nombre` siguen siendo UNIQUE de forma global (no por
usuario) — cambiarlo exige reconstruir esas tablas igual que se hizo con
las de preferencias; se deja para una fase posterior si llega a ser un
problema real con más de un usuario.
"""
import hashlib
import json
import time
import os
import re
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

if hasattr(sys, "_MEIPASS"):
    # Empaquetado con PyInstaller: sys._MEIPASS es una carpeta temporal que se
    # borra al cerrar, así que la base de datos vive junto al .exe, no ahí.
    RAIZ_PROYECTO = Path(sys.executable).resolve().parent
else:
    RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

DB_PATH = RAIZ_PROYECTO / "data" / "registro.db"
# GUILDA_BACKUPS_DIR permite llevar la copia a otro disco físico (en producción,
# el volumen Hetzner montado en /mnt/...) sin tocar código.
BACKUPS_DIR = Path(os.environ["GUILDA_BACKUPS_DIR"]) if os.environ.get("GUILDA_BACKUPS_DIR") else RAIZ_PROYECTO / "data" / "backups"

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    contrasena_hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'usuario' CHECK (rol IN ('usuario','admin')),
    es_local INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    creado_en TEXT NOT NULL
);

-- Clientes fiscales de un tenant (gestoría), para el calendario de
-- vencimientos -- deliberadamente NO integrado con EspoCRM (app/espocrm.py):
-- EspoCRM es opcional/ocultable por tenant (ver tabla de abajo), así que
-- depender de él aquí dejaría el calendario fiscal roto para cualquier
-- tenant sin EspoCRM configurado. Solo lo mínimo para identificar al
-- cliente en un vencimiento -- nada de facturación ni contacto.
CREATE TABLE IF NOT EXISTS clientes_fiscales (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    nombre TEXT NOT NULL,
    nif TEXT,
    notas TEXT,
    creado_en TEXT NOT NULL,
    papelera_en TEXT
);

-- Vencimientos fiscales: una fila por vencimiento CONCRETO ya fechado (no
-- una regla de recurrencia -- no existe motor de recurrencia genérico en
-- Guilda Work, y construir uno de propósito general es fase 2, no v1).
-- `usuario_id` es quien debe ocuparse / recibe el aviso -- puede
-- reasignarse dentro del mismo tenant sin más (a diferencia de fichajes,
-- esto no es un registro legal inmutable).
CREATE TABLE IF NOT EXISTS vencimientos_fiscales (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id),
    usuario_id INTEGER REFERENCES usuarios(id),
    modelo TEXT NOT NULL,
    periodo TEXT NOT NULL,
    fecha_limite TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('pendiente','presentado','fuera_plazo')) DEFAULT 'pendiente',
    notas TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    papelera_en TEXT
);

-- Enlaces mágicos de un solo uso para el portal de cliente (clientes de
-- la gestoría, no empleados -- ver app/rutas_portal_cliente.py). Vida
-- corta y de un solo uso a propósito: es la única puerta de entrada sin
-- contraseña, así que el margen de error tiene que ser mínimo.
CREATE TABLE IF NOT EXISTS clientes_fiscales_accesos (
    id INTEGER PRIMARY KEY,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id),
    token TEXT NOT NULL UNIQUE,
    creado_en TEXT NOT NULL,
    expira_en TEXT NOT NULL,
    usado_en TEXT,
    ip_solicitante TEXT
);

-- Recordatorios del portal ya enviados por correo al cliente (uno por
-- vencimiento y antelación: 7 y 2 días), para no repetirlos nunca.
CREATE TABLE IF NOT EXISTS vencimientos_recordatorios (
    vencimiento_id INTEGER NOT NULL REFERENCES vencimientos_fiscales(id) ON DELETE CASCADE,
    dias_antes INTEGER NOT NULL,
    enviado_en TEXT NOT NULL,
    PRIMARY KEY (vencimiento_id, dias_antes)
);

-- Documentos que sube el CLIENTE (portal) para un vencimiento concreto --
-- no confundir con vencimientos_fiscales.notas, de uso interno del
-- equipo. `contenido` (BLOB, mismo diseño que tiquets_adjuntos) y
-- `ruta_nextcloud` son mutuamente excluyentes en la práctica: si el
-- tenant tiene Nextcloud configurado, el contenido vive ahí y
-- `contenido` es NULL; si no, cae a BLOB local como hasta ahora (ver
-- db.subir_documento_vencimiento/contenido_documento_vencimiento).
CREATE TABLE IF NOT EXISTS vencimientos_fiscales_documentos (
    id INTEGER PRIMARY KEY,
    vencimiento_id INTEGER NOT NULL,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB,
    ruta_nextcloud TEXT,
    creado_en TEXT NOT NULL,
    FOREIGN KEY (vencimiento_id) REFERENCES vencimientos_fiscales(id) ON DELETE CASCADE
);

-- Mensajería del portal de cliente (v2): conversación ligada a un
-- vencimiento concreto, no a un cliente_fiscal_id suelto -- mismo
-- criterio que los documentos de arriba (contexto concreto, "el 303
-- del T2", no un totum revolutum de mensajes sin agrupar). `leido_en`
-- es deliberadamente simple (una marca, no "leído por quién" a nivel
-- de usuario individual) -- solo dos partes posibles en la
-- conversación (cliente / equipo), no hace falta más.
CREATE TABLE IF NOT EXISTS vencimientos_fiscales_mensajes (
    id INTEGER PRIMARY KEY,
    vencimiento_id INTEGER NOT NULL,
    autor TEXT NOT NULL CHECK (autor IN ('cliente', 'empleado')),
    usuario_id INTEGER REFERENCES usuarios(id),
    texto TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    leido_en TEXT,
    FOREIGN KEY (vencimiento_id) REFERENCES vencimientos_fiscales(id) ON DELETE CASCADE
);

-- Solicitudes de acceso al portal de cliente (v2): un cliente sin
-- ficha previa en clientes_fiscales no puede pedir un enlace mágico
-- (v1 es opt-in, ver clientes_fiscales.email) -- esto es la cola por
-- la que pide que un empleado lo vincule a mano, mismo patrón que
-- leads_contacto (sin acción automática, un admin decide desde
-- backoffice).
CREATE TABLE IF NOT EXISTS solicitudes_acceso_portal (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL,
    nif TEXT,
    mensaje TEXT,
    creado_en TEXT NOT NULL,
    atendida INTEGER NOT NULL DEFAULT 0
);

-- Herramientas del catálogo (app/herramientas.py, por su `id` de texto)
-- ocultas para un tenant concreto. Ausencia de fila = visible (así una
-- herramienta nueva, o un tenant sin ninguna fila aquí, no pierde acceso
-- por accidente al desplegar esto) — nunca se guarda "visible=1" a
-- propósito, solo las excepciones.
CREATE TABLE IF NOT EXISTS tenants_herramientas_ocultas (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    herramienta_id TEXT NOT NULL,
    UNIQUE (tenant_id, herramienta_id)
);

CREATE TABLE IF NOT EXISTS tokens_api (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    token_hash TEXT NOT NULL UNIQUE,
    nombre_dispositivo TEXT,
    creado_en TEXT NOT NULL,
    ultimo_uso_en TEXT
);

-- Solicitudes de contacto desde la landing pública (guildawork.com) — no
-- crea tenant ni usuario por sí sola: el alta sigue siendo manual desde el
-- backoffice (ver app/rutas_backoffice.py:crear_tenant/crear_usuario), esto
-- solo guarda el interés para que un admin lo procese.
CREATE TABLE IF NOT EXISTS leads_contacto (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    empresa TEXT,
    email TEXT NOT NULL,
    telefono TEXT,
    mensaje TEXT,
    creado_en TEXT NOT NULL,
    atendido INTEGER NOT NULL DEFAULT 0
);

-- Tokens FCM de la app móvil (no confundir con tokens_api: esto identifica
-- un dispositivo para poder enviarle un push, no autentica nada). Un mismo
-- usuario puede tener varios dispositivos; un mismo fcm_token solo puede
-- apuntar a un usuario a la vez (si se reinstala la app con otra cuenta,
-- REPLACE se encarga de reasignarlo, ver registrar_dispositivo_push).
CREATE TABLE IF NOT EXISTS dispositivos_push (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fcm_token TEXT NOT NULL UNIQUE,
    plataforma TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);

-- Centro de notificaciones unificado (app/notificaciones.py): además del
-- push FCM (efímero, solo llega si el móvil está a mano), cada aviso se
-- registra aquí para verlo dentro de la propia app -- correo nuevo,
-- vencimiento fiscal próximo, mensaje del portal de cliente, resumen IA
-- semanal. `url` es la ruta a la que lleva al pulsar la notificación,
-- nullable si el aviso no tiene destino concreto.
CREATE TABLE IF NOT EXISTS notificaciones (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    cuerpo TEXT,
    url TEXT,
    creado_en TEXT NOT NULL,
    leido_en TEXT
);

-- Log de auditoría del backoffice (app/rutas_backoffice.py) -- registro
-- de solo lectura de acciones sensibles/destructivas de administración
-- (crear/borrar tenant, cambiar rol, asignar tenant a un usuario,
-- guardar una API key). Deliberadamente simple: sin niveles de
-- severidad ni retención configurable, se puede ampliar después si
-- hace falta de verdad -- ver db.registrar_auditoria().
CREATE TABLE IF NOT EXISTS auditoria_backoffice (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER REFERENCES usuarios(id),
    accion TEXT NOT NULL,
    detalle TEXT,
    creado_en TEXT NOT NULL
);

-- Webhooks salientes (ver app/eventos.py). tenant_id NULL = modo
-- escritorio/usuario sin tenant (mismo criterio que otras tablas ya
-- nullable de este archivo) — se asocia al usuario que lo dio de alta
-- en ese caso. `secreto` se guarda en claro (no un hash, a diferencia
-- de tokens_api): hace falta releerlo para firmar cada entrega HMAC,
-- no solo compararlo una vez.
CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    url TEXT NOT NULL,
    eventos TEXT NOT NULL,
    secreto TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL
);

-- Log de entregas — para que el admin pueda ver por qué un webhook
-- está fallando desde el backoffice, sin tener que mirar logs del
-- servidor. Se poda a las últimas N entradas por webhook (ver
-- app/eventos.py), no crece sin límite.
CREATE TABLE IF NOT EXISTS webhooks_entregas (
    id INTEGER PRIMARY KEY,
    webhook_id INTEGER NOT NULL REFERENCES webhooks(id),
    evento TEXT NOT NULL,
    estado_http INTEGER,
    intento_num INTEGER NOT NULL,
    entregado_en TEXT NOT NULL,
    error TEXT
);

-- UNIQUE por (usuario_id, nombre), NO solo por nombre -- antes era
-- "nombre TEXT NOT NULL UNIQUE" a secas (global, entre TODOS los
-- usuarios), así que dos usuarios que le pusieran el mismo nombre a un
-- proyecto acababan compartiendo la misma fila sin saberlo (encontrado y
-- reproducido en producción, revisión de lógica -- ver
-- _migrar_categorias_unique_por_usuario para instalaciones ya
-- existentes con el esquema viejo).
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    color TEXT,
    creada_en TEXT NOT NULL,
    papelera_en TEXT,
    orden INTEGER,
    UNIQUE (usuario_id, nombre)
);

CREATE TABLE IF NOT EXISTS tareas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    categoria_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('duracion','instantanea')) DEFAULT 'duracion',
    estado TEXT NOT NULL CHECK (estado IN ('pendiente','en_curso','pausada','finalizada')),
    inicio_en TEXT,
    fin_en TEXT,
    duracion_segundos INTEGER,
    papelera_en TEXT,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

CREATE TABLE IF NOT EXISTS notas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    texto TEXT NOT NULL,
    categoria_id INTEGER,
    tarea_id INTEGER,
    creada_en TEXT NOT NULL,
    papelera_en TEXT,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id),
    FOREIGN KEY (tarea_id) REFERENCES tareas(id)
);

CREATE TABLE IF NOT EXISTS pausas (
    id INTEGER PRIMARY KEY,
    tarea_id INTEGER NOT NULL,
    pausada_en TEXT NOT NULL,
    reanudada_en TEXT,
    FOREIGN KEY (tarea_id) REFERENCES tareas(id)
);

-- Frases favoritas (plantillas) para registrar notas en un clic
CREATE TABLE IF NOT EXISTS plantillas (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER NOT NULL,
    texto TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id)
);

-- Tareas al estilo Microsoft Outlook (lista + calendario): independientes
-- de los proyectos y de las tareas con duración de arriba. Los nombres de campo
-- calcan el modelo de objetos de Outlook (Subject, Status, PercentComplete,
-- Importance, StartDate, DueDate, DateCompleted, Categories, EntryID) y el
-- VTODO de iCalendar, para que el mapeo de importación/exportación sea 1:1.
CREATE TABLE IF NOT EXISTS tareas_outlook (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    asunto TEXT NOT NULL,
    cuerpo TEXT,
    estado TEXT NOT NULL CHECK (estado IN
        ('no_iniciada','en_progreso','completada','esperando','aplazada'))
        DEFAULT 'no_iniciada',
    porcentaje_completado INTEGER NOT NULL DEFAULT 0,
    prioridad TEXT NOT NULL CHECK (prioridad IN ('baja','normal','alta'))
        DEFAULT 'normal',
    fecha_inicio TEXT,
    fecha_vencimiento TEXT,
    fecha_completada TEXT,
    categoria_outlook TEXT,
    outlook_entry_id TEXT UNIQUE,
    creada_en TEXT NOT NULL,
    actualizada_en TEXT,
    papelera_en TEXT
);

-- Reglas de recurrencia para tareas_outlook (semanal/mensual) --
-- deliberadamente simples (un solo día por regla, sin motor de
-- recurrencia genérico, ver comentario de vencimientos_fiscales más
-- arriba, mismo criterio). `dia` es 0-6 (lunes-domingo) si
-- periodicidad='semanal', o 1-31 si periodicidad='mensual' (si el mes
-- no tiene ese día, se usa el último día del mes -- ver
-- generar_tareas_recurrentes()).
CREATE TABLE IF NOT EXISTS tareas_recurrentes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    categoria_id INTEGER REFERENCES categorias(id),
    asunto TEXT NOT NULL,
    periodicidad TEXT NOT NULL CHECK (periodicidad IN ('diaria','laborables','semanal','mensual','trimestral','anual')),
    dia INTEGER NOT NULL,
    mes INTEGER,
    activa INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL
);

-- Adjuntos de una nota (imágenes, PDF, texto): se guardan en la propia base de
-- datos, con tope de tamaño y de número por nota (ver NOTAS_ADJUNTOS_*).
CREATE TABLE IF NOT EXISTS notas_adjuntos (
    id INTEGER PRIMARY KEY,
    nota_id INTEGER NOT NULL REFERENCES notas(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    creado_en TEXT NOT NULL
);

-- Participantes de una tarea compartida (además del dueño y del asignado):
-- 'colabora' puede editarla, completarla y trabajar su checklist/cronómetro;
-- 'observa' solo la ve. Siempre del mismo tenant que el dueño.
CREATE TABLE IF NOT EXISTS tareas_participantes (
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    rol TEXT NOT NULL CHECK (rol IN ('colabora', 'observa')) DEFAULT 'colabora',
    compartida_en TEXT NOT NULL,
    PRIMARY KEY (tarea_id, usuario_id)
);

-- Proyectos compartidos con compañeros del despacho (categorias = proyectos).
CREATE TABLE IF NOT EXISTS proyecto_miembros (
    categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    rol TEXT NOT NULL CHECK (rol IN ('colabora', 'observa')),
    anadido_en TEXT NOT NULL,
    PRIMARY KEY (categoria_id, usuario_id)
);
CREATE INDEX IF NOT EXISTS idx_proyecto_miembros_usuario ON proyecto_miembros(usuario_id);
CREATE TABLE IF NOT EXISTS proyecto_secciones (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    orden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_proyecto_secciones_categoria ON proyecto_secciones(categoria_id, orden);
-- Notas compartidas del proyecto (distintas del registro privado de cada persona) y plantillas guardadas por el despacho.
CREATE TABLE IF NOT EXISTS proyecto_notas (
    id INTEGER PRIMARY KEY,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    texto TEXT NOT NULL,
    fijada INTEGER NOT NULL DEFAULT 0,
    creada_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proyecto_notas_categoria ON proyecto_notas(categoria_id, fijada, id);
CREATE TABLE IF NOT EXISTS proyecto_plantillas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nombre TEXT NOT NULL,
    estructura TEXT NOT NULL,
    creada_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proyecto_plantillas_tenant ON proyecto_plantillas(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tareas_participantes_usuario ON tareas_participantes(usuario_id);

-- Correo de equipo: no se comparten cuentas ni contraseñas, solo mensajes
-- concretos. El dueño del mensaje puede asignarlo a un compañero del despacho
-- (que pasa a verlo, en solo lectura, y a llevar su estado) o compartirlo sin
-- asignar; las notas internas las ven todos los que tienen acceso y nunca
-- salen hacia el remitente.
CREATE TABLE IF NOT EXISTS correo_equipo (
    mensaje_id INTEGER PRIMARY KEY REFERENCES correo_mensajes(id) ON DELETE CASCADE,
    asignado_a INTEGER REFERENCES usuarios(id),
    asignado_por INTEGER REFERENCES usuarios(id),
    estado TEXT NOT NULL DEFAULT 'abierto' CHECK (estado IN ('abierto', 'resuelto')),
    actualizado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correo_equipo_asignado ON correo_equipo(asignado_a, estado);
CREATE TABLE IF NOT EXISTS correo_compartidos (
    mensaje_id INTEGER NOT NULL REFERENCES correo_mensajes(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    compartido_en TEXT NOT NULL,
    PRIMARY KEY (mensaje_id, usuario_id)
);
CREATE INDEX IF NOT EXISTS idx_correo_compartidos_usuario ON correo_compartidos(usuario_id);
CREATE TABLE IF NOT EXISTS correo_notas_internas (
    id INTEGER PRIMARY KEY,
    mensaje_id INTEGER NOT NULL REFERENCES correo_mensajes(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    texto TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correo_notas_internas_mensaje ON correo_notas_internas(mensaje_id, id);
-- Quién hizo qué con un correo compartido (asignar, compartir, quitar, estado,
-- notas y primeras lecturas de cada día): lo ve el dueño del mensaje.
CREATE TABLE IF NOT EXISTS correo_equipo_auditoria (
    id INTEGER PRIMARY KEY,
    mensaje_id INTEGER NOT NULL REFERENCES correo_mensajes(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    accion TEXT NOT NULL,
    detalle TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correo_equipo_auditoria_mensaje ON correo_equipo_auditoria(mensaje_id, id);

-- Recordatorios de una tarea: cada persona pone los suyos. `canales` es una
-- lista separada por comas de app (centro de avisos + push del móvil), correo
-- y ntfy; `enviado_en` NULL = pendiente (al posponer vuelve a NULL).
CREATE TABLE IF NOT EXISTS tarea_recordatorios (
    id INTEGER PRIMARY KEY,
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    avisar_en TEXT NOT NULL,
    canales TEXT NOT NULL DEFAULT 'app',
    enviado_en TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tarea_recordatorios_pendientes ON tarea_recordatorios(enviado_en, avisar_en);

-- Dependencias: `tarea_id` espera a `depende_de_id` (no se puede iniciar ni
-- completar hasta que la otra esté completada).
CREATE TABLE IF NOT EXISTS tareas_dependencias (
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    depende_de_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    PRIMARY KEY (tarea_id, depende_de_id)
);
CREATE INDEX IF NOT EXISTS idx_tareas_dependencias_origen ON tareas_dependencias(depende_de_id);

-- Plantillas de tareas / proyectos ("alta de cliente", "cierre trimestral"):
-- un conjunto de tareas con plazos relativos a la fecha de inicio. Las
-- compartidas las ven y usan todos los del despacho; editarlas es del autor.
CREATE TABLE IF NOT EXISTS plantillas_tareas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nombre TEXT NOT NULL,
    descripcion TEXT,
    compartida INTEGER NOT NULL DEFAULT 0,
    creada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plantilla_tareas_items (
    id INTEGER PRIMARY KEY,
    plantilla_id INTEGER NOT NULL REFERENCES plantillas_tareas(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    asunto TEXT NOT NULL,
    prioridad TEXT NOT NULL DEFAULT 'normal',
    dias INTEGER NOT NULL DEFAULT 0,
    checklist TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_plantilla_items_plantilla ON plantilla_tareas_items(plantilla_id, orden);

-- Participantes de una nota compartida (mismos roles que en las tareas).
CREATE TABLE IF NOT EXISTS notas_participantes (
    nota_id INTEGER NOT NULL REFERENCES notas(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    rol TEXT NOT NULL CHECK (rol IN ('colabora', 'observa')) DEFAULT 'colabora',
    compartida_en TEXT NOT NULL,
    PRIMARY KEY (nota_id, usuario_id)
);
CREATE INDEX IF NOT EXISTS idx_notas_participantes_usuario ON notas_participantes(usuario_id);

-- Historial de actividad de una tarea (quién hizo qué y cuándo).
CREATE TABLE IF NOT EXISTS tarea_actividad (
    id INTEGER PRIMARY KEY,
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tipo TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tarea_actividad_tarea ON tarea_actividad(tarea_id, id);

-- Comentarios de una tarea compartida; `menciones` lleva los ids de usuario
-- mencionados con @ (separados por comas).
CREATE TABLE IF NOT EXISTS tarea_comentarios (
    id INTEGER PRIMARY KEY,
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    texto TEXT NOT NULL,
    menciones TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tarea_comentarios_tarea ON tarea_comentarios(tarea_id, id);

-- Checklist (subtareas) de una tarea de la lista (tareas_outlook).
CREATE TABLE IF NOT EXISTS tarea_checklist (
    id INTEGER PRIMARY KEY,
    tarea_outlook_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    texto TEXT NOT NULL,
    hecha INTEGER NOT NULL DEFAULT 0,
    orden INTEGER NOT NULL DEFAULT 0
);

-- Cliente de correo IMAP/POP3. La contraseña de cada cuenta NO se guarda
-- aquí: vive en el almacén de credenciales del sistema (keyring), bajo la
-- clave "cuenta-<id>" — esta tabla solo tiene metadatos de conexión.
-- firma_html: firma enriquecida (HTML), propia de esta cuenta; los dos
-- interruptores controlan cuándo se antepone al redactar (ver
-- app/correo.py::preparar_cuerpo_inicial). Cualquier combinación es válida,
-- incluida ninguna de las dos.
CREATE TABLE IF NOT EXISTS correo_cuentas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    protocolo TEXT NOT NULL CHECK (protocolo IN ('imap','pop3')),
    host TEXT NOT NULL,
    puerto INTEGER NOT NULL,
    usa_tls INTEGER NOT NULL DEFAULT 1,
    usuario TEXT NOT NULL,
    smtp_host TEXT,
    smtp_puerto INTEGER,
    smtp_tls INTEGER NOT NULL DEFAULT 1,
    creada_en TEXT NOT NULL,
    ultima_sincronizacion TEXT,
    firma_html TEXT,
    firma_en_nuevos INTEGER NOT NULL DEFAULT 1,
    firma_en_respuestas INTEGER NOT NULL DEFAULT 1
);

-- Carpetas IMAP descubiertas al sincronizar (POP3 no tiene fila aquí: su
-- única carpeta "INBOX" se sintetiza en Python, nunca se guarda, porque
-- POP3 no tiene ningún concepto de carpetas a nivel de protocolo).
CREATE TABLE IF NOT EXISTS correo_carpetas (
    id INTEGER PRIMARY KEY,
    cuenta_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    nombre_visible TEXT NOT NULL,
    FOREIGN KEY (cuenta_id) REFERENCES correo_cuentas(id),
    UNIQUE (cuenta_id, nombre)
);

-- Cambios hechos aquí (leído, destacado, borrado) que aún hay que reflejar en el
-- servidor IMAP. Se aplican en segundo plano y se reintentan; la sincronización
-- de entrada no pisa un mensaje que tenga una operación pendiente.
CREATE TABLE IF NOT EXISTS correo_operaciones (
    id INTEGER PRIMARY KEY,
    cuenta_id INTEGER NOT NULL REFERENCES correo_cuentas(id) ON DELETE CASCADE,
    carpeta TEXT NOT NULL,
    uid TEXT NOT NULL,
    uidvalidity TEXT,
    operacion TEXT NOT NULL CHECK (operacion IN ('leido', 'no_leido', 'destacar', 'quitar_destacar', 'eliminar')),
    creada_en TEXT NOT NULL,
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'error'))
);
CREATE INDEX IF NOT EXISTS idx_correo_operaciones_cuenta ON correo_operaciones(cuenta_id, estado, id);

-- Categorías de color propias de Guilda Work (no existe un estándar real de
-- "categorías con color" en IMAP/POP3 genérico — es propietario de
-- Exchange/Outlook — así que estas nunca se sincronizan con el servidor).
-- UNIQUE por (usuario_id, nombre), no solo por nombre -- mismo bug que
-- categorias (revisión de lógica), aquí incluso peor: sin ninguna lógica
-- de "reutilizar si ya existe", así que el segundo usuario con el mismo
-- nombre de etiqueta de correo directamente reventaba con un
-- IntegrityError sin capturar (500 en crudo, reproducido en vivo).
CREATE TABLE IF NOT EXISTS correo_categorias (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    nombre TEXT NOT NULL,
    color TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    UNIQUE (usuario_id, nombre)
);

-- Plantillas de respuesta guardadas -- mismo espíritu que `plantillas`
-- (frases favoritas de notas rápidas) pero con asunto+cuerpo, para
-- insertar en el editor de redactar/responder sin mandar nada
-- automáticamente (el usuario sigue revisando antes de enviar).
CREATE TABLE IF NOT EXISTS correo_plantillas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    asunto TEXT,
    cuerpo TEXT NOT NULL,
    creada_en TEXT NOT NULL
);

-- Borradores al redactar -- solo locales, nunca se suben a la carpeta
-- Drafts del servidor IMAP (evita sincronizar un borrador a medias).
CREATE TABLE IF NOT EXISTS correo_borradores (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    cuenta_id INTEGER,
    destinatarios TEXT,
    cc TEXT,
    bcc TEXT,
    asunto TEXT,
    cuerpo_html TEXT,
    en_respuesta_a TEXT,
    actualizado_en TEXT NOT NULL
);

-- Adjuntos de un borrador (los que venían de un envío deshecho o fallido).
CREATE TABLE IF NOT EXISTS correo_borradores_adjuntos (
    id INTEGER PRIMARY KEY,
    borrador_id INTEGER NOT NULL REFERENCES correo_borradores(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL,
    contenido BLOB NOT NULL
);

-- Caché local de mensajes ya descargados (para no ir a red en cada
-- consulta). cc: cabecera Cc del mensaje recibido. Cco (Bcc) nunca se guarda
-- aquí porque, por diseño del propio correo electrónico, nadie salvo el
-- remitente original sabe quién iba en copia oculta — no es una limitación
-- nuestra, un mensaje recibido jamás trae esa información.
CREATE TABLE IF NOT EXISTS correo_mensajes (
    id INTEGER PRIMARY KEY,
    cuenta_id INTEGER NOT NULL,
    carpeta TEXT NOT NULL DEFAULT 'INBOX',
    uid TEXT NOT NULL,
    asunto TEXT,
    remitente TEXT,
    destinatarios TEXT,
    cc TEXT,
    fecha TEXT,
    cuerpo_texto TEXT,
    cuerpo_html TEXT,
    message_id TEXT,       -- cabecera Message-ID, para poder responder con hilo (In-Reply-To/References)
    leido INTEGER NOT NULL DEFAULT 0,
    categoria_id INTEGER,
    destacado INTEGER NOT NULL DEFAULT 0,
    fecha_aviso TEXT,      -- recordatorio opcional del destacado
    pospuesto_hasta TEXT,  -- mientras sea futuro, se oculta de la lista por defecto
    descargado_en TEXT NOT NULL,
    FOREIGN KEY (cuenta_id) REFERENCES correo_cuentas(id),
    FOREIGN KEY (categoria_id) REFERENCES correo_categorias(id) ON DELETE SET NULL,
    UNIQUE (cuenta_id, carpeta, uid)
);

-- Adjuntos reales de mensajes recibidos (Content-Disposition: attachment).
-- Los bytes viven en la propia SQLite, igual que el resto de la app: un
-- único archivo .db, sin carpeta aparte que sincronizar/hacer backup.
CREATE TABLE IF NOT EXISTS correo_adjuntos (
    id INTEGER PRIMARY KEY,
    mensaje_id INTEGER NOT NULL,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    creado_en TEXT NOT NULL,
    FOREIGN KEY (mensaje_id) REFERENCES correo_mensajes(id) ON DELETE CASCADE
);

-- Remitentes marcados como de confianza: sus imágenes remotas y adjuntos
-- no se bloquean/avisan antes de mostrarlos.
CREATE TABLE IF NOT EXISTS correo_remitentes_confiables (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    direccion TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    UNIQUE (usuario_id, direccion)
);

-- Reglas de categorización automática: al llegar un mensaje nuevo cuyo
-- remitente coincide con remitente_patron (email exacto o "@dominio.com"),
-- se le asigna categoria_id sin intervención manual.
CREATE TABLE IF NOT EXISTS correo_reglas_categoria (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    remitente_patron TEXT NOT NULL,
    categoria_id INTEGER NOT NULL,
    creada_en TEXT NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES correo_categorias(id) ON DELETE CASCADE
);

-- Reglas avanzadas de correo: condiciones por remitente y/o asunto y varias
-- acciones a la vez (categoría, marcar como leído, destacar, cliente fiscal).
-- Conviven con correo_reglas_categoria (la regla simple de siempre).
CREATE TABLE IF NOT EXISTS correo_reglas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    remitente_patron TEXT,
    asunto_patron TEXT,
    categoria_id INTEGER REFERENCES correo_categorias(id) ON DELETE SET NULL,
    marcar_leido INTEGER NOT NULL DEFAULT 0,
    destacar INTEGER NOT NULL DEFAULT 0,
    cliente_fiscal_id INTEGER,
    creada_en TEXT NOT NULL
);

-- Cola de envío de correo: "deshacer envío" (retraso de unos segundos) y
-- envío programado. Un hilo del servidor envía lo pendiente cuando llega
-- su hora; el estado se reclama con un UPDATE condicional (dos procesos
-- nunca envían el mismo correo).
CREATE TABLE IF NOT EXISTS correo_envios (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    cuenta_id INTEGER NOT NULL,
    destinatarios TEXT NOT NULL,
    cc TEXT,
    bcc TEXT,
    asunto TEXT NOT NULL,
    cuerpo_html TEXT NOT NULL,
    en_respuesta_a TEXT,
    enviar_en TEXT NOT NULL,
    programado INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | enviando | enviado | cancelado | error
    error TEXT,
    creado_en TEXT NOT NULL,
    procesado_en TEXT
);
CREATE TABLE IF NOT EXISTS correo_envios_adjuntos (
    id INTEGER PRIMARY KEY,
    envio_id INTEGER NOT NULL REFERENCES correo_envios(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL,
    contenido BLOB NOT NULL
);

-- Direcciones a las que ya se ha enviado correo, para sugerirlas al
-- redactar uno nuevo (autocompletar). veces_usado/ultima_vez_en permiten
-- ordenar las sugerencias por relevancia.
CREATE TABLE IF NOT EXISTS correo_destinatarios_recientes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    direccion TEXT NOT NULL,
    nombre_mostrado TEXT,
    ultima_vez_en TEXT NOT NULL,
    veces_usado INTEGER NOT NULL DEFAULT 1,
    UNIQUE (usuario_id, direccion)
);

-- Conversaciones con el Asistente IA: cada usuario puede tener varias, una
-- de ellas "activa" (la que ve el chat y a la que se añaden mensajes).
CREATE TABLE IF NOT EXISTS ia_conversaciones (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    titulo TEXT,
    creada_en TEXT NOT NULL,
    actualizada_en TEXT NOT NULL,
    activa INTEGER NOT NULL DEFAULT 0
);

-- Mensajes del Asistente IA, repartidos en conversaciones (conversacion_id).
-- Atajos de prompts propios del usuario para el chat del asistente (máx. 20).
CREATE TABLE IF NOT EXISTS ia_atajos (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    prompt TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ia_mensajes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER,
    rol TEXT NOT NULL CHECK (rol IN ('user','assistant','tool')),
    contenido TEXT,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    nombre_herramienta TEXT,
    creado_en TEXT NOT NULL
);

-- Tiquets de soporte interno (errores/sugerencias sobre la propia Guilda
-- Work) — a diferencia de notas/tareas/correo, es un tablero COMPARTIDO
-- entre todos los usuarios, no privado por usuario_id (ver app/rutas_tiquets.py).
-- AUTOINCREMENT para que el número mostrado (el propio id, "#N") nunca se
-- repita ni siquiera tras borrar un tiquet -- sin esto SQLite podría
-- reutilizar el id más alto libre.
CREATE TABLE IF NOT EXISTS tiquets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('error', 'sugerencia')),
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('sin_revisar', 'en_revision', 'finalizado')) DEFAULT 'sin_revisar',
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

-- Adjuntos de un tiquet (capturas de pantalla, PDF...) -- mismo diseño que
-- correo_adjuntos (BLOB en la propia base de datos, sin filesystem aparte
-- que gestionar). ON DELETE CASCADE: al borrar un tiquet desaparecen sus
-- adjuntos solos (get_connection() ya activa "PRAGMA foreign_keys = ON").
CREATE TABLE IF NOT EXISTS tiquets_adjuntos (
    id INTEGER PRIMARY KEY,
    tiquet_id INTEGER NOT NULL,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    creado_en TEXT NOT NULL,
    FOREIGN KEY (tiquet_id) REFERENCES tiquets(id) ON DELETE CASCADE
);

-- Fichaje de trabajadores (registro horario, art. 34.9 ET / RD-ley 8/2019).
-- Datos personales del trabajador que exige la normativa para identificarlo
-- ante una inspección -- fila única por usuario, igual que correo_preferencias.
CREATE TABLE IF NOT EXISTS fichaje_datos (
    usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
    nombre_completo TEXT,
    dni_nie TEXT,
    numero_afiliacion_ss TEXT,
    categoria_profesional TEXT,
    tipo_contrato TEXT,
    fecha_alta TEXT,
    jornada_semanal_horas REAL,
    convenio_colectivo TEXT,
    actualizado_en TEXT
);

-- El registro horario en sí. INSERT-only a propósito -- nunca hay UPDATE
-- ni DELETE sobre esta tabla (ni siquiera vía papelera): la norma exige
-- conservar el registro 4 años y que no se pueda manipular a posteriori
-- sin dejar rastro. Una corrección se hace con una fila NUEVA que
-- referencia a la original en `corrige_a`, nunca sobrescribiendo.
-- `tenant_id` se duplica aquí (no solo en usuarios) porque debe reflejar
-- el tenant al que pertenecía el trabajador EN EL MOMENTO del fichaje
-- -- un registro legal histórico no debe cambiar si más adelante se
-- reasigna a alguien de tenant.
CREATE TABLE IF NOT EXISTS fichajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tenant_id INTEGER REFERENCES tenants(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada','pausa_inicio','pausa_fin','salida')),
    marca_tiempo TEXT NOT NULL,
    origen TEXT NOT NULL DEFAULT 'web',
    nota TEXT,
    corrige_a INTEGER REFERENCES fichajes(id),
    creado_por INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);

-- Latidos de las tareas periódicas del servidor (panel de salud del backoffice).
CREATE TABLE IF NOT EXISTS latidos (
    nombre TEXT PRIMARY KEY,
    ultimo_ok TEXT,
    ultimo_error TEXT,
    detalle TEXT,
    intervalo_segundos INTEGER NOT NULL DEFAULT 0
);

-- Avisos del vigilante de salud ya enviados (uno por motivo y día).
CREATE TABLE IF NOT EXISTS salud_alertas (
    motivo TEXT NOT NULL,
    dia TEXT NOT NULL,
    enviada_en TEXT NOT NULL,
    PRIMARY KEY (motivo, dia)
);

-- Aviso de "salida olvidada": una sola vez por jornada (la entrada abierta).
CREATE TABLE IF NOT EXISTS fichaje_avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    entrada_id INTEGER NOT NULL REFERENCES fichajes(id),
    avisado_en TEXT NOT NULL,
    UNIQUE (usuario_id, entrada_id)
);

-- Facturación de plataforma (Guilda Work cobra a sus propios tenants,
-- bloque 6 -- DISTINTO de Stripe Connect, que es cada tenant cobrando a
-- SUS clientes finales, ver tenants.stripe_account_id más abajo).
-- precio_mensual_centimos/precio_centimos NULL a propósito: el mecanismo
-- se deja listo desde esta ronda, pero sin ningún precio fijado todavía
-- -- el usuario los edita desde el backoffice cuando decida las tarifas.
CREATE TABLE IF NOT EXISTS planes_guilda (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    precio_mensual_centimos INTEGER,
    max_usuarios INTEGER,
    stripe_price_id TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extras_guilda (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    precio_centimos INTEGER,
    stripe_price_id TEXT,
    creado_en TEXT NOT NULL
);

-- Extras activados TEMPORALMENTE en la suscripción de un tenant --
-- activo_hasta NULL = indefinido, con fecha = expira solo.
CREATE TABLE IF NOT EXISTS tenants_extras_activos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    extra_id INTEGER NOT NULL REFERENCES extras_guilda(id),
    cantidad INTEGER NOT NULL DEFAULT 1,
    activo_desde TEXT NOT NULL,
    activo_hasta TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tenants_extras_activos_tenant ON tenants_extras_activos(tenant_id);

-- Registro local de un cobro con Stripe Connect (bloque 5) sobre un
-- vencimiento fiscal -- no se asume que la API de FacturaScripts
-- permita marcar una factura como cobrada, así que el estado de cobro
-- vive aquí. stripe_checkout_session_id es UNIQUE: el webhook puede
-- reintentar la misma entrega, esto evita duplicar el registro.
CREATE TABLE IF NOT EXISTS vencimientos_fiscales_pagos (
    id INTEGER PRIMARY KEY,
    vencimiento_id INTEGER NOT NULL REFERENCES vencimientos_fiscales(id),
    stripe_checkout_session_id TEXT NOT NULL UNIQUE,
    importe_centimos INTEGER NOT NULL,
    pagado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vencimientos_fiscales_pagos_vencimiento ON vencimientos_fiscales_pagos(vencimiento_id);

-- Enlaces de un solo uso para abrir FacturaScripts en facturacion.guildawork.com
-- (app/rutas_facturacion_proxy.py) -- mismo patrón que clientes_fiscales_accesos:
-- vida corta (1 minuto) y de un solo uso, porque solo sirve para resolver "qué
-- tenant" antes de fijar la sesión del proxy; FacturaScripts sigue pidiendo su
-- propio login por separado, esto no es una credencial de acceso a datos.
CREATE TABLE IF NOT EXISTS facturacion_accesos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    token TEXT NOT NULL UNIQUE,
    creado_en TEXT NOT NULL,
    expira_en TEXT NOT NULL,
    usado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_facturacion_accesos_token ON facturacion_accesos(token);

"""

# Índices: sin ellos, cualquier filtro por fecha/categoría/leído acaba en un
# escaneo completo de la tabla. A partir de unos pocos miles de filas (uso
# de empresa: 100+ tareas y 200+ correos al día) eso se nota en cada carga
# del Dashboard/Correo/Tareas. `CREATE INDEX IF NOT EXISTS` es idempotente,
# así que se ejecuta en cada init_db() sin coste real si ya existen. Va en
# un script APARTE de SCHEMA (no dentro) porque los índices sobre
# `usuario_id` referencian una columna que en bases de datos migradas se
# añade con `_asegurar_columna` DESPUÉS de crear las tablas — si viviera en
# el mismo `executescript(SCHEMA)`, fallaría en cualquier base de datos ya
# existente donde la tabla ya existe pero todavía no tiene esa columna.
INDICES = """
CREATE INDEX IF NOT EXISTS idx_correo_no_leidos ON correo_mensajes(cuenta_id, carpeta) WHERE leido = 0;
CREATE INDEX IF NOT EXISTS idx_notas_categoria_creada ON notas(categoria_id, creada_en);
CREATE INDEX IF NOT EXISTS idx_notas_papelera ON notas(papelera_en);
CREATE INDEX IF NOT EXISTS idx_notas_usuario ON notas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_tareas_categoria_inicio ON tareas(categoria_id, inicio_en);
CREATE INDEX IF NOT EXISTS idx_tareas_papelera ON tareas(papelera_en);
CREATE INDEX IF NOT EXISTS idx_tareas_usuario ON tareas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_categorias_papelera ON categorias(papelera_en);
CREATE INDEX IF NOT EXISTS idx_categorias_usuario ON categorias(usuario_id);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_papelera_vencimiento ON tareas_outlook(papelera_en, fecha_vencimiento);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_estado ON tareas_outlook(estado);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_usuario ON tareas_outlook(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_cuentas_usuario ON correo_cuentas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_categorias_usuario ON correo_categorias(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_plantillas_usuario ON correo_plantillas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_borradores_usuario ON correo_borradores(usuario_id, actualizado_en);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_cuenta_carpeta_fecha ON correo_mensajes(cuenta_id, carpeta, fecha);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_leido ON correo_mensajes(leido);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_cuenta_leido ON correo_mensajes(cuenta_id, leido);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_cliente_fiscal ON correo_mensajes(cliente_fiscal_id);
CREATE INDEX IF NOT EXISTS idx_correo_adjuntos_mensaje ON correo_adjuntos(mensaje_id);
CREATE INDEX IF NOT EXISTS idx_notas_adjuntos_nota ON notas_adjuntos(nota_id);
CREATE INDEX IF NOT EXISTS idx_correo_reglas_usuario ON correo_reglas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_borradores_adjuntos ON correo_borradores_adjuntos(borrador_id);
CREATE INDEX IF NOT EXISTS idx_correo_envios_estado ON correo_envios(estado, enviar_en);
CREATE INDEX IF NOT EXISTS idx_correo_envios_usuario ON correo_envios(usuario_id, estado);
CREATE INDEX IF NOT EXISTS idx_correo_envios_adjuntos_envio ON correo_envios_adjuntos(envio_id);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_hilo ON correo_mensajes(cuenta_id, hilo_clave);
CREATE INDEX IF NOT EXISTS idx_correo_mensajes_message_id ON correo_mensajes(cuenta_id, message_id);
CREATE INDEX IF NOT EXISTS idx_tarea_checklist_tarea ON tarea_checklist(tarea_outlook_id);
CREATE INDEX IF NOT EXISTS idx_tareas_tarea_outlook ON tareas(tarea_outlook_id);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_asignada ON tareas_outlook(asignada_a);
CREATE INDEX IF NOT EXISTS idx_ia_mensajes_usuario ON ia_mensajes(usuario_id);
CREATE INDEX IF NOT EXISTS idx_ia_mensajes_conversacion ON ia_mensajes(conversacion_id);
CREATE INDEX IF NOT EXISTS idx_ia_conversaciones_usuario ON ia_conversaciones(usuario_id, actualizada_en);
CREATE INDEX IF NOT EXISTS idx_ia_atajos_usuario ON ia_atajos(usuario_id);
CREATE INDEX IF NOT EXISTS idx_tokens_api_usuario ON tokens_api(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_remitentes_confiables_usuario ON correo_remitentes_confiables(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_reglas_categoria_usuario ON correo_reglas_categoria(usuario_id);
CREATE INDEX IF NOT EXISTS idx_correo_destinatarios_recientes_usuario ON correo_destinatarios_recientes(usuario_id);
CREATE INDEX IF NOT EXISTS idx_fichajes_usuario_marca ON fichajes(usuario_id, marca_tiempo);
CREATE INDEX IF NOT EXISTS idx_fichajes_tenant_marca ON fichajes(tenant_id, marca_tiempo);
CREATE INDEX IF NOT EXISTS idx_webhooks_tenant ON webhooks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_usuario ON webhooks(usuario_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_entregas_webhook ON webhooks_entregas(webhook_id);
CREATE INDEX IF NOT EXISTS idx_tiquets_usuario ON tiquets(usuario_id);
CREATE INDEX IF NOT EXISTS idx_tiquets_asignado ON tiquets(usuario_asignado_id);
CREATE INDEX IF NOT EXISTS idx_tiquets_adjuntos_tiquet ON tiquets_adjuntos(tiquet_id);
CREATE INDEX IF NOT EXISTS idx_correo_carpetas_cuenta ON correo_carpetas(cuenta_id);
CREATE INDEX IF NOT EXISTS idx_plantillas_categoria ON plantillas(categoria_id);
CREATE INDEX IF NOT EXISTS idx_pausas_tarea ON pausas(tarea_id);
CREATE INDEX IF NOT EXISTS idx_clientes_fiscales_tenant ON clientes_fiscales(tenant_id, papelera_en);
CREATE INDEX IF NOT EXISTS idx_vencimientos_fiscales_tenant_fecha ON vencimientos_fiscales(tenant_id, fecha_limite, papelera_en);
CREATE INDEX IF NOT EXISTS idx_vencimientos_fiscales_cliente ON vencimientos_fiscales(cliente_fiscal_id);
CREATE INDEX IF NOT EXISTS idx_clientes_fiscales_accesos_token ON clientes_fiscales_accesos(token);
CREATE INDEX IF NOT EXISTS idx_clientes_fiscales_accesos_cliente ON clientes_fiscales_accesos(cliente_fiscal_id);
CREATE INDEX IF NOT EXISTS idx_vencimientos_fiscales_documentos_vencimiento ON vencimientos_fiscales_documentos(vencimiento_id);
CREATE INDEX IF NOT EXISTS idx_vencimientos_fiscales_mensajes_vencimiento ON vencimientos_fiscales_mensajes(vencimiento_id);
CREATE INDEX IF NOT EXISTS idx_notificaciones_usuario ON notificaciones(usuario_id, leido_en, creado_en);
CREATE INDEX IF NOT EXISTS idx_auditoria_backoffice_creado ON auditoria_backoffice(creado_en);
CREATE INDEX IF NOT EXISTS idx_tareas_recurrentes_usuario ON tareas_recurrentes(usuario_id, activa);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_recurrente ON tareas_outlook(tarea_recurrente_id);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fecha_exclusiva(fecha: str) -> str:
    """`fecha` (YYYY-MM-DD, límite inclusive) -> el día siguiente (YYYY-MM-DD).

    Permite filtrar con `columna < _fecha_exclusiva(hasta)` en vez de
    `substr(columna,1,10) <= hasta`: envolver la columna en `substr()`
    impide a SQLite usar cualquier índice sobre ella (fuerza un escaneo
    completo de la tabla en cada consulta). Comparar el timestamp completo
    contra el día siguiente, sin tocar la columna, sí puede usar un índice
    — y da el mismo resultado porque los timestamps ISO 8601 ordenan bien
    como texto."""
    return (datetime.strptime(fecha, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def _marca_papelera() -> str:
    """Timestamp con precisión de microsegundos para `papelera_en`.

    A diferencia de now_iso() (precisión de segundos, pensada para que se
    lea bien), esto se usa para poder identificar qué se borró exactamente
    en la misma operación (p.ej. un proyecto y sus tareas/notas al mandarlo a la
    papelera) y restaurarlo junto — con precisión de segundos, dos borrados
    distintos en el mismo segundo compartirían marca por error.
    """
    return datetime.now().isoformat(timespec="microseconds")


_HASH_FICHAJE_GENESIS = "0" * 64


def _hash_fichaje(hash_anterior: str, usuario_id: int, tipo: str, marca_tiempo: str, creado_por: int) -> str:
    """Encadenado de hashes de la tabla `fichajes` (Fase G3, "registro
    horario digital"): cada fila incluye el hash de la anterior, igual que
    una cadena de bloques de un solo nodo -- alterar o borrar una fila
    directamente en la BD (saltándose la app, que ya era insert-only por
    convención) rompe la cadena a partir de ahí de forma detectable, ver
    verificar_integridad_fichajes(). Es una única cadena GLOBAL (no una
    por tenant/usuario): más simple de mantener y más fuerte -- cualquier
    alteración en cualquier fila de cualquier tenant se detecta igual."""
    base = f"{hash_anterior}|{usuario_id}|{tipo}|{marca_tiempo}|{creado_por}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _backfill_hash_fichajes(conn: sqlite3.Connection) -> None:
    """Rellena `hash` para filas de `fichajes` creadas antes de que
    existiera esta columna (migración de una BD ya en uso) -- continúa la
    cadena desde el último hash ya calculado, o desde el génesis si no
    hay ninguno. Se llama en cada init_db(); si no hay filas con hash
    NULL, no hace nada (barato de comprobar en cada arranque)."""
    ultima = conn.execute("SELECT hash FROM fichajes WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    hash_anterior = ultima["hash"] if ultima else _HASH_FICHAJE_GENESIS
    pendientes = conn.execute(
        "SELECT id, usuario_id, tipo, marca_tiempo, creado_por FROM fichajes WHERE hash IS NULL ORDER BY id"
    ).fetchall()
    for fila in pendientes:
        h = _hash_fichaje(hash_anterior, fila["usuario_id"], fila["tipo"], fila["marca_tiempo"], fila["creado_por"])
        conn.execute("UPDATE fichajes SET hash = ? WHERE id = ?", (h, fila["id"]))
        hash_anterior = h


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL permite que la app de escritorio (GuildaWork.exe) y un serve.py
    # expuesto a internet (Fase 3, app móvil) lean/escriban el mismo
    # registro.db a la vez sin bloquearse mutuamente; busy_timeout evita que
    # el choque puntual entre dos escrituras casi simultáneas falle al
    # instante con "database is locked" en vez de esperar un poco.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _asegurar_columna(conn: sqlite3.Connection, tabla: str, columna: str, tipo: str) -> None:
    """Añade `columna` a `tabla` si no existe ya (migración ligera para bases
    de datos creadas con una versión anterior del esquema)."""
    columnas = {fila["name"] for fila in conn.execute(f"PRAGMA table_info({tabla})")}
    if columna not in columnas:
        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def _asegurar_orden_categorias(conn: sqlite3.Connection) -> None:
    """Rellena `orden` para categorías que no lo tengan (bases de datos
    migradas desde antes de que existiera esta columna), por nombre."""
    sin_orden = conn.execute("SELECT id FROM categorias WHERE orden IS NULL ORDER BY nombre").fetchall()
    if not sin_orden:
        return
    base = conn.execute("SELECT COALESCE(MAX(orden), -1) FROM categorias").fetchone()[0]
    for i, fila in enumerate(sin_orden, start=base + 1):
        conn.execute("UPDATE categorias SET orden = ? WHERE id = ?", (i, fila["id"]))


def _resolver_usuario_local(conn: sqlite3.Connection) -> int:
    """Usuario de confianza para procesos locales (cli.py, mcp_server.py,
    y para migrar datos de antes de que existiera el login) que no pasan
    por una sesión web. Si no existe todavía, se crea automáticamente con
    una contraseña aleatoria (nadie inicia sesión "como" este usuario desde
    fuera; es un ancla interna, no una cuenta pensada para usarse en la web)."""
    fila = conn.execute("SELECT id FROM usuarios WHERE es_local = 1 ORDER BY id LIMIT 1").fetchone()
    if fila:
        return fila["id"]
    cur = conn.execute(
        "INSERT INTO usuarios (email, contrasena_hash, es_local, creado_en) VALUES (?, ?, 1, ?)",
        ("local@guilda-work.local", generate_password_hash(secrets.token_urlsafe(16)), now_iso()),
    )
    return cur.lastrowid


def _migrar_datos_sin_usuario(conn: sqlite3.Connection, usuario_id: int) -> None:
    """Asigna al usuario local cualquier fila de las tablas "raíz" que
    todavía no tenga dueño — es decir, todo lo que se anotó antes de que
    existiera el login. No toca nada que ya pertenezca a un usuario."""
    for tabla in (
        "categorias", "notas", "tareas", "tareas_outlook",
        "correo_cuentas", "correo_categorias", "ia_mensajes",
    ):
        conn.execute(f"UPDATE {tabla} SET usuario_id = ? WHERE usuario_id IS NULL", (usuario_id,))


_ESPECIFICACION_PREFERENCIAS = {
    "correo_preferencias": (
        ["densidad", "marcar_leido_automatico", "limite_mensajes"],
        """CREATE TABLE correo_preferencias (
               usuario_id INTEGER PRIMARY KEY,
               densidad TEXT NOT NULL DEFAULT 'normal' CHECK (densidad IN ('normal','compacta')),
               marcar_leido_automatico INTEGER NOT NULL DEFAULT 1,
               limite_mensajes INTEGER NOT NULL DEFAULT 50
           )""",
    ),
    "ia_preferencias": (
        ["modelo", "modo_autonomo"],
        """CREATE TABLE ia_preferencias (
               usuario_id INTEGER PRIMARY KEY,
               modelo TEXT NOT NULL DEFAULT '',
               modo_autonomo INTEGER NOT NULL DEFAULT 0
           )""",
    ),
}


def _migrar_preferencias_singleton(conn: sqlite3.Connection, usuario_id_local: int) -> None:
    """`correo_preferencias`/`ia_preferencias` eran una única fila global
    (`id=1`). Multiusuario necesita una fila por usuario, con `usuario_id`
    como clave primaria — un cambio de clave primaria que SQLite no permite
    con `ALTER TABLE`, así que se reconstruye la tabla la primera vez que
    se detecta el esquema antiguo (o se crea directamente con el esquema
    nuevo si es una instalación nunca antes usada)."""
    for tabla, (columnas, ddl_nueva) in _ESPECIFICACION_PREFERENCIAS.items():
        cols_actuales = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})")}
        if not cols_actuales:
            conn.execute(ddl_nueva)
            continue
        if "usuario_id" in cols_actuales:
            continue
        conn.execute(f"ALTER TABLE {tabla} RENAME TO {tabla}_viejo")
        conn.execute(ddl_nueva)
        fila = conn.execute(f"SELECT * FROM {tabla}_viejo WHERE id = 1").fetchone()
        if fila:
            marcadores = ", ".join("?" * len(columnas))
            conn.execute(
                f"INSERT INTO {tabla} (usuario_id, {', '.join(columnas)}) VALUES (?, {marcadores})",
                [usuario_id_local, *[fila[c] for c in columnas]],
            )
        conn.execute(f"DROP TABLE {tabla}_viejo")


def _migrar_categorias_unique_por_usuario(conn_ignorada: sqlite3.Connection) -> None:
    """`categorias.nombre` tenía UNIQUE global (sin usuario_id) -- dos
    usuarios con un proyecto del mismo nombre acababan compartiendo la
    misma fila sin saberlo (bug real, reproducido en producción: el
    segundo en crearlo recibía el id del primero en vez de uno propio,
    y ese proyecto no le aparecía ni en su propio listado). SQLite no deja
    tocar una UNIQUE con ALTER TABLE, así que se reconstruye la tabla
    la primera vez que se detecta el esquema antiguo -- se comprueba
    leyendo su propio SQL en sqlite_master, sin ninguna bandera aparte.
    Llamar DESPUÉS de que existan papelera_en/orden/favorito (ver
    llamadas a _asegurar_columna justo antes), para no perderlas al
    reconstruir. Sin duplicados posibles que choquen con la nueva
    UNIQUE(usuario_id, nombre): la UNIQUE(nombre) vieja ya impedía que
    hubiera dos filas con el mismo nombre, así que a fortiori tampoco
    hay dos con el mismo (usuario_id, nombre).

    Usa su PROPIA conexión (ignora la que recibe) con
    `PRAGMA foreign_keys = OFF`, siguiendo el procedimiento de 12 pasos
    documentado por SQLite para tablas con FOREIGN KEY entrantes desde
    otras tablas (notas/tareas/tareas_outlook referencian categorias) --
    con las claves foráneas activas (lo normal en get_connection()),
    renombrar la tabla vieja fuera y crear una nueva con el mismo nombre
    hace que SQLite reescriba las FK de las tablas hijas para que sigan
    apuntando al nombre viejo (¡no al nuevo!), y el DROP final de la
    tabla vieja revienta con FOREIGN KEY constraint failed -- exactamente
    lo que pasó la primera vez que se escribió esta función, detectado
    y corregido a mano en el propio despliegue antes de arreglarla aquí.
    El orden correcto es crear la tabla nueva bajo un nombre aparte,
    copiar los datos, BORRAR la vieja (con foreign_keys=OFF esto no
    reescribe nada en las hijas) y solo entonces renombrar la nueva al
    nombre definitivo -- así las hijas, que nunca dejan de decir
    "REFERENCES categorias(...)", vuelven a apuntar a una tabla real en
    cuanto esta reaparece con ese nombre, sin necesidad de tocarlas."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        definicion = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='categorias'"
        ).fetchone()
        if definicion is None or "UNIQUE (usuario_id, nombre)" in definicion["sql"]:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """CREATE TABLE categorias_nueva (
                   id INTEGER PRIMARY KEY,
                   usuario_id INTEGER,
                   nombre TEXT NOT NULL,
                   color TEXT,
                   creada_en TEXT NOT NULL,
                   papelera_en TEXT,
                   orden INTEGER,
                   favorito INTEGER NOT NULL DEFAULT 0,
                   UNIQUE (usuario_id, nombre)
               )"""
        )
        conn.execute(
            """INSERT INTO categorias_nueva (id, usuario_id, nombre, color, creada_en, papelera_en, orden, favorito)
               SELECT id, usuario_id, nombre, color, creada_en, papelera_en, orden, favorito
               FROM categorias"""
        )
        conn.execute("DROP TABLE categorias")
        conn.execute("ALTER TABLE categorias_nueva RENAME TO categorias")
        violaciones = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            conn.rollback()
            raise RuntimeError(f"Migración de categorias abortada: foreign_key_check encontró {violaciones}")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def _migrar_tareas_recurrentes_periodicidades(conn_ignorada: sqlite3.Connection) -> None:
    """`tareas_recurrentes.periodicidad` solo admitía 'semanal' y 'mensual'
    (CHECK) y no tenía mes. SQLite no deja cambiar un CHECK con ALTER TABLE,
    así que se reconstruye la tabla la primera vez que se detecta el esquema
    antiguo (se comprueba leyendo su SQL en sqlite_master). Mismo
    procedimiento que _migrar_categorias_unique_por_usuario -- ver su
    docstring: conexión propia con foreign_keys=OFF, tabla nueva con otro
    nombre, copia, DROP de la vieja y renombrado -- porque
    tareas_outlook.tarea_recurrente_id apunta a esta tabla."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        definicion = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tareas_recurrentes'"
        ).fetchone()
        if definicion is None or "'trimestral'" in definicion["sql"]:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """CREATE TABLE tareas_recurrentes_nueva (
                   id INTEGER PRIMARY KEY,
                   usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                   categoria_id INTEGER REFERENCES categorias(id),
                   asunto TEXT NOT NULL,
                   periodicidad TEXT NOT NULL CHECK (periodicidad IN
                       ('diaria','laborables','semanal','mensual','trimestral','anual')),
                   dia INTEGER NOT NULL,
                   mes INTEGER,
                   activa INTEGER NOT NULL DEFAULT 1,
                   creado_en TEXT NOT NULL
               )"""
        )
        conn.execute(
            """INSERT INTO tareas_recurrentes_nueva (id, usuario_id, categoria_id, asunto, periodicidad, dia, activa, creado_en)
               SELECT id, usuario_id, categoria_id, asunto, periodicidad, dia, activa, creado_en FROM tareas_recurrentes"""
        )
        conn.execute("DROP TABLE tareas_recurrentes")
        conn.execute("ALTER TABLE tareas_recurrentes_nueva RENAME TO tareas_recurrentes")
        violaciones = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            conn.rollback()
            raise RuntimeError(f"Migración de tareas_recurrentes abortada: foreign_key_check encontró {violaciones}")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def _migrar_correo_categorias_unique_por_usuario(conn_ignorada: sqlite3.Connection) -> None:
    """Mismo bug, mismo arreglo que _migrar_categorias_unique_por_usuario
    (ver su docstring para el porqué del procedimiento exacto) -- aquí
    con correo_mensajes.categoria_id (ON DELETE SET NULL) y
    correo_reglas_categoria.categoria_id (ON DELETE CASCADE) como tablas
    hijas en vez de notas/tareas/tareas_outlook."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        definicion = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='correo_categorias'"
        ).fetchone()
        if definicion is None or "UNIQUE (usuario_id, nombre)" in definicion["sql"]:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """CREATE TABLE correo_categorias_nueva (
                   id INTEGER PRIMARY KEY,
                   usuario_id INTEGER,
                   nombre TEXT NOT NULL,
                   color TEXT NOT NULL,
                   creada_en TEXT NOT NULL,
                   UNIQUE (usuario_id, nombre)
               )"""
        )
        conn.execute(
            """INSERT INTO correo_categorias_nueva (id, usuario_id, nombre, color, creada_en)
               SELECT id, usuario_id, nombre, color, creada_en FROM correo_categorias"""
        )
        conn.execute("DROP TABLE correo_categorias")
        conn.execute("ALTER TABLE correo_categorias_nueva RENAME TO correo_categorias")
        violaciones = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            conn.rollback()
            raise RuntimeError(f"Migración de correo_categorias abortada: foreign_key_check encontró {violaciones}")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def _migrar_documentos_vencimiento_a_nextcloud(conn_ignorada: sqlite3.Connection) -> None:
    """Documentos fiscales del portal de cliente: pasan de BLOB obligatorio
    en SQLite a poder vivir en Nextcloud (ver app/nextcloud.py,
    db.subir_documento_vencimiento) -- solo metadatos + `ruta_nextcloud`
    en SQLite para los que se suben ahí, `contenido` se queda como
    fallback para tenants sin Nextcloud configurado. Mismo procedimiento
    de reconstrucción de tabla que _migrar_correo_categorias_unique_por_usuario
    (ver su docstring) -- `contenido` tiene que dejar de ser NOT NULL, y
    SQLite no permite quitar una restricción NOT NULL con ALTER TABLE."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        definicion = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='vencimientos_fiscales_documentos'"
        ).fetchone()
        if definicion is None or "contenido BLOB NOT NULL" not in definicion["sql"]:
            return
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """CREATE TABLE vencimientos_fiscales_documentos_nueva (
                   id INTEGER PRIMARY KEY,
                   vencimiento_id INTEGER NOT NULL,
                   nombre_archivo TEXT NOT NULL,
                   tipo_mime TEXT NOT NULL,
                   tamano_bytes INTEGER NOT NULL,
                   contenido BLOB,
                   ruta_nextcloud TEXT,
                   creado_en TEXT NOT NULL,
                   FOREIGN KEY (vencimiento_id) REFERENCES vencimientos_fiscales(id) ON DELETE CASCADE
               )"""
        )
        conn.execute(
            """INSERT INTO vencimientos_fiscales_documentos_nueva
                   (id, vencimiento_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en)
               SELECT id, vencimiento_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en
               FROM vencimientos_fiscales_documentos"""
        )
        conn.execute("DROP TABLE vencimientos_fiscales_documentos")
        conn.execute(
            "ALTER TABLE vencimientos_fiscales_documentos_nueva RENAME TO vencimientos_fiscales_documentos"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vencimientos_fiscales_documentos_vencimiento "
            "ON vencimientos_fiscales_documentos(vencimiento_id)"
        )
        violaciones = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            conn.rollback()
            raise RuntimeError(
                f"Migración de vencimientos_fiscales_documentos abortada: foreign_key_check encontró {violaciones}"
            )
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _asegurar_columna(conn, "categorias", "papelera_en", "TEXT")
        _asegurar_columna(conn, "tareas", "papelera_en", "TEXT")
        _asegurar_columna(conn, "notas", "papelera_en", "TEXT")
        _asegurar_columna(conn, "categorias", "orden", "INTEGER")
        _asegurar_columna(conn, "categorias", "favorito", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "categorias", "icono", "TEXT")
        _migrar_categorias_unique_por_usuario(conn)
        _migrar_correo_categorias_unique_por_usuario(conn)
        _migrar_tareas_recurrentes_periodicidades(conn)
        _migrar_documentos_vencimiento_a_nextcloud(conn)
        _asegurar_columna(conn, "correo_mensajes", "message_id", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "cc", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "categoria_id", "INTEGER")
        # Error de la última sincronización AUTOMÁTICA de la cuenta (ver
        # correo.sincronizar_todas_las_cuentas): se muestra en Cuentas y en la
        # bandeja para que una contraseña caducada no pase desapercibida.
        _asegurar_columna(conn, "correo_cuentas", "ultimo_error_sincronizacion", "TEXT")
        _asegurar_columna(conn, "correo_cuentas", "ultimo_error_sincronizacion_en", "TEXT")
        _asegurar_columna(conn, "correo_cuentas", "firma_html", "TEXT")
        _asegurar_columna(conn, "correo_cuentas", "firma_en_nuevos", "INTEGER NOT NULL DEFAULT 1")
        _asegurar_columna(conn, "correo_cuentas", "firma_en_respuestas", "INTEGER NOT NULL DEFAULT 1")
        # Conversaciones: cabeceras de enlace y clave de hilo (ver
        # calcular_hilo_clave). ANTES de executescript(INDICES).
        _asegurar_columna(conn, "tokens_api", "permisos", "TEXT NOT NULL DEFAULT 'completo'")
        _asegurar_columna(conn, "correo_mensajes", "in_reply_to", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "referencias", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "hilo_clave", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "destacado", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "correo_mensajes", "fecha_aviso", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "pospuesto_hasta", "TEXT")
        # Vínculo manual con un cliente fiscal (app/rutas_correo.py,
        # app/rutas_fiscal.py:ficha_cliente) -- nullable y opt-in, el
        # empleado lo rellena a mano desde la vista de un mensaje, sin
        # ningún intento de adivinarlo automáticamente por remitente.
        # Va ANTES de conn.executescript(INDICES) porque ese script crea
        # un índice sobre esta misma columna (mismo motivo que
        # tareas_outlook.tarea_recurrente_id más abajo).
        _asegurar_columna(conn, "correo_mensajes", "cliente_fiscal_id", "INTEGER REFERENCES clientes_fiscales(id)")
        # Tiquets: prioridad y responsable asignado (app/rutas_tiquets.py) --
        # sin CHECK a nivel de esquema para "prioridad" (ALTER TABLE ADD
        # COLUMN con CHECK es más frágil de migrar en SQLite que
        # simplemente validar el valor en Python antes de escribir, mismo
        # criterio ya aplicado a vencimientos_fiscales.modelo). Van ANTES
        # de conn.executescript(INDICES), mismo motivo que
        # correo_mensajes.cliente_fiscal_id justo arriba.
        _asegurar_columna(conn, "tiquets", "prioridad", "TEXT NOT NULL DEFAULT 'normal'")
        _asegurar_columna(conn, "tiquets", "usuario_asignado_id", "INTEGER REFERENCES usuarios(id)")
        _asegurar_columna(conn, "usuarios", "kratos_identity_id", "TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_kratos_identity_id "
            "ON usuarios(kratos_identity_id) WHERE kratos_identity_id IS NOT NULL"
        )
        # Tenants (Fase 7c.3): agrupar usuarios por organización. Opcional
        # (NULL = sin asignar) — no aísla datos entre tenants, solo
        # identifica de qué organización viene cada usuario para el
        # panel de administración y para integraciones externas (p.ej.
        # el widget de soporte de Chatwoot, que necesita saber a qué
        # tenant pertenece quien escribe).
        _asegurar_columna(conn, "usuarios", "tenant_id", "INTEGER REFERENCES tenants(id)")

        # Fichaje (registro horario): quien tiene este flag administra el
        # fichaje SOLO de su propio tenant (usuarios.tenant_id) -- distinto
        # de rol='admin' (superadmin global de todo el backoffice, ver
        # app/auth.py:admin_required). Lo asigna un superadmin desde el
        # backoffice, igual que hacer_admin/quitar_admin.
        _asegurar_columna(conn, "usuarios", "gestor_fichajes", "INTEGER NOT NULL DEFAULT 0")

        # Rol general de "supervisor de tenant" -- mismo patrón que
        # gestor_fichajes (flag aparte, no un tercer valor del CHECK de
        # usuarios.rol), pero no scoped a un único módulo: permite actuar
        # sobre datos de OTROS usuarios de su propio tenant en cualquier
        # módulo que lo compruebe (hoy: tiquets, ver app/rutas_tiquets.py).
        # Lo asigna un superadmin desde el backoffice.
        _asegurar_columna(conn, "usuarios", "supervisor_tenant", "INTEGER NOT NULL DEFAULT 0")

        # Identificación de empresa (CIF/dirección fiscal), exigida junto a
        # la del trabajador en cualquier registro horario que se presente
        # a una inspección -- aparece en la cabecera de los export CSV/PDF.
        _asegurar_columna(conn, "tenants", "cif", "TEXT")
        _asegurar_columna(conn, "tenants", "direccion_fiscal", "TEXT")
        _asegurar_columna(conn, "tenants", "zona_horaria", "TEXT")

        # FacturaScripts (Fase facturación): a diferencia de EspoCRM/
        # Nextcloud (una instancia compartida), cada tenant tiene su
        # propia instancia física — estas columnas guardan cómo llegar a
        # la suya. Nulas hasta que app/facturascripts.py:aprovisionar_tenant()
        # las rellena; facturascripts_api_key queda nula más tiempo
        # todavía, es un paso manual aparte (ver HOSTING.md 8.21).
        _asegurar_columna(conn, "tenants", "facturascripts_url", "TEXT")
        _asegurar_columna(conn, "tenants", "facturascripts_admin_user", "TEXT")
        _asegurar_columna(conn, "tenants", "facturascripts_admin_pass", "TEXT")
        _asegurar_columna(conn, "tenants", "facturascripts_api_key", "TEXT")

        # Documenso (firma electrónica): a diferencia de FacturaScripts,
        # aquí la instancia SÍ es compartida (una URL global, ver
        # HERRAMIENTA_DOCUMENSO_URL) — no hace falta guardar URL/usuario
        # por tenant, solo el token de API generado a mano dentro del
        # Equipo de ese tenant (verificado en vivo que no hay API para
        # crear Equipos/invitar miembros, ver HOSTING.md). Ese token es
        # lo único que hace falta para que el aislamiento entre tenants
        # funcione de verdad al llamar a la API de documentos.
        _asegurar_columna(conn, "tenants", "documenso_api_key", "TEXT")

        # Paperless-ngx (gestión documental/OCR): instancia compartida,
        # igual que Documenso, pero aquí SÍ hay API real de Usuarios y
        # Grupos (verificado en el código fuente, ver app/paperless.py)
        # — el aprovisionamiento es 100% automático, sin ningún paso
        # manual. Guarda el Grupo y el usuario de servicio creados para
        # ese tenant, y su token de API ya generado.
        _asegurar_columna(conn, "tenants", "paperless_group_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "paperless_user_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "paperless_api_key", "TEXT")

        # Baserow (hojas de cálculo tipo base de datos): instancia
        # compartida. A diferencia de Paperless-ngx, aquí NO hay un
        # usuario de servicio propio — el token de base de datos de
        # Baserow queda ligado directamente al Workspace, no a ningún
        # usuario (ver app/baserow.py) — solo hace falta guardar el
        # Workspace y su token.
        _asegurar_columna(conn, "tenants", "baserow_workspace_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "baserow_api_key", "TEXT")

        # Cal.diy (reserva de citas): instancia compartida, igual que
        # Documenso/Paperless-ngx/Baserow (no una física por tenant como
        # FacturaScripts — Cal.diy es una app Next.js con la URL pública
        # fijada en tiempo de compilación, no de ejecución, así que un
        # contenedor por tenant no es viable). El aislamiento aquí es a
        # nivel de usuario individual (Cal.diy no tiene Equipos/SSO en su
        # edición libre, ver app/calcom.py) — un usuario de servicio de
        # Cal.diy por tenant, con su propio API Key generado a mano desde
        # su cuenta (paso manual, igual que facturascripts_api_key).
        # calcom_email guarda el identificador real (el endpoint de alta
        # de Cal.diy no devuelve un id numérico, solo confirma la
        # creación — verificado leyendo su código fuente real, ver
        # app/calcom.py).
        _asegurar_columna(conn, "tenants", "calcom_email", "TEXT")
        _asegurar_columna(conn, "tenants", "calcom_admin_pass", "TEXT")
        _asegurar_columna(conn, "tenants", "calcom_api_key", "TEXT")

        # Listmonk (newsletter/envíos masivos): instancia compartida.
        # Verificado en vivo (contenedor real) que el aislamiento por
        # lista es real, aplicado en el propio backend, no una
        # convención de UI (ver app/listmonk.py) — cada tenant tiene su
        # propia Lista + Rol de lista + usuario de servicio tipo "api",
        # y el token viaja en la propia respuesta de creación: sin
        # ningún paso manual, a diferencia de FacturaScripts/Documenso/
        # Cal.diy.
        _asegurar_columna(conn, "tenants", "listmonk_list_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "listmonk_list_role_id", "INTEGER")
        _asegurar_columna(conn, "tenants", "listmonk_api_key", "TEXT")

        # Stalwart (correo propio, backend alternativo con mejor API para
        # MCP que el cliente IMAP genérico de app/correo.py): instancia
        # compartida. Verificado en vivo (contenedor real, sin licencia
        # Enterprise) que el aislamiento por Tenant/Domain/Account es
        # real y aplicado por el propio servidor a nivel de accountId
        # JMAP (una llamada con el accountId de otro tenant devuelve un
        # 403 "forbidden" real, no un filtro de cliente) — ver
        # app/stalwart.py. Los ids de Stalwart son cadenas cortas
        # (base32), no numéricas, de ahí TEXT. Cada tenant usa su propio
        # dominio real (decisión del usuario, no un subdominio de
        # guilda.cat), por eso stalwart_domain_name se guarda tal cual se
        # introduce al aprovisionar, no se deriva de ningún otro campo.
        # El API Key se genera 100% automático (x:ApiKey/set devuelve el
        # secreto en la propia respuesta), sin ningún paso manual — igual
        # que Listmonk/Paperless-ngx/Baserow.
        _asegurar_columna(conn, "tenants", "stalwart_tenant_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_domain_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_domain_name", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_account_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stalwart_api_key", "TEXT")

        # ntfy (notificaciones push): topic + token generados por
        # app/ntfy.py:aprovisionar_tenant() — el token no se puede volver
        # a leer una vez generado (mismo criterio que stalwart_api_key).
        _asegurar_columna(conn, "tenants", "ntfy_topic", "TEXT")
        _asegurar_columna(conn, "tenants", "ntfy_token", "TEXT")

        # Umami (analítica web, MIT): Team + sitio (website) creados por
        # app/umami.py:aprovisionar_tenant() — 100% automático. Los ids
        # de Umami son UUID (cadenas), no numéricos, de ahí TEXT — mismo
        # criterio que los ids de Stalwart.
        _asegurar_columna(conn, "tenants", "umami_team_id", "TEXT")
        _asegurar_columna(conn, "tenants", "umami_website_id", "TEXT")

        # Calendario fiscal — ampliación (dedup de recordatorios): sin esta
        # columna, _recordatorio_vencimientos_fiscales (app/main.py) volvía a
        # avisar cada día mientras el vencimiento siguiera "pendiente" y
        # dentro de la ventana de aviso, hasta 7 veces por el mismo
        # vencimiento. Se marca tras el primer push correcto y
        # vencimientos_fiscales_proximos() excluye lo ya marcado.
        _asegurar_columna(conn, "vencimientos_fiscales", "recordatorio_enviado_en", "TEXT")

        # Calendario fiscal — ampliación (más funcionalidades): qué modelos
        # aplica cada cliente (JSON tipo '["303","130"]'), para no tener que
        # reescribirlos a mano cada vez en "Generar vencimientos" -- y base
        # de la generación automática por cron (generacion_automatica).
        _asegurar_columna(conn, "clientes_fiscales", "modelos_fiscales", "TEXT")
        _asegurar_columna(conn, "clientes_fiscales", "generacion_automatica", "INTEGER NOT NULL DEFAULT 0")
        # EspoCRM (opcional, best-effort -- ver app/espocrm.py): nunca se
        # rellena si ESPOCRM_API_KEY no está configurada, el calendario
        # fiscal sigue funcionando igual sin ella.
        _asegurar_columna(conn, "clientes_fiscales", "espocrm_cuenta_id", "TEXT")
        # Portal de cliente (app/rutas_portal_cliente.py): nullable a
        # propósito -- el acceso es opt-in, solo si un empleado pone el
        # email desde la ficha del cliente puede este pedir un enlace.
        _asegurar_columna(conn, "clientes_fiscales", "email", "TEXT")
        # Recordatorios automáticos por correo de los vencimientos próximos
        # (activos por defecto; el cliente puede quedar fuera desde su ficha).
        _asegurar_columna(conn, "clientes_fiscales", "recordatorios_portal", "INTEGER NOT NULL DEFAULT 1")
        # Idioma de los correos que se le mandan al cliente (es/ca/en/fr).
        _asegurar_columna(conn, "clientes_fiscales", "idioma", "TEXT NOT NULL DEFAULT 'es'")
        # Quién subió el documento: 'cliente' (portal), 'justificante'
        # (oficial, lo sube el equipo) o 'constancia' (PDF generado por la app).
        _asegurar_columna(conn, "vencimientos_fiscales_documentos", "origen", "TEXT NOT NULL DEFAULT 'cliente'")
        # Vínculo con FacturaScripts (app/facturascripts.py) -- opcional,
        # solo si el empleado vincula el cliente fiscal a un cliente de
        # FacturaScripts desde su ficha (mismo criterio best-effort que
        # espocrm_cuenta_id de arriba).
        _asegurar_columna(conn, "clientes_fiscales", "facturascripts_cliente_codigo", "TEXT")
        # País de tributación del cliente (app/vencimientos_fiscales.py:
        # MODELOS_POR_PAIS) -- reestructuración del calendario fiscal para
        # soportar clientes que tributan fuera de España. DEFAULT 'ES' para
        # que todos los clientes ya existentes queden clasificados sin
        # necesitar ninguna migración manual (hasta ahora el calendario era
        # implícitamente España-only). Código ISO 3166-1 alfa-2 en
        # mayúsculas (validado/normalizado en la ruta, no aquí).
        _asegurar_columna(conn, "clientes_fiscales", "pais", "TEXT NOT NULL DEFAULT 'ES'")
        # Firma electrónica desde un vencimiento (app/documenso.py) --
        # id del envelope de Documenso una vez enviado a firma, para
        # poder consultar su estado/descargarlo sin volver a crearlo.
        _asegurar_columna(conn, "vencimientos_fiscales", "documenso_documento_id", "TEXT")
        # Portal de cliente -- pedir un documento concreto
        # (app/rutas_fiscal.py:editar_vencimiento,
        # app/rutas_portal_cliente.py): texto libre que el empleado rellena
        # ("Factura de compra del trimestre"), mostrado destacado en el
        # portal si todavía no hay documento subido para este vencimiento.
        _asegurar_columna(conn, "vencimientos_fiscales", "documento_solicitado", "TEXT")
        # Tareas recurrentes (app/db.py:generar_tareas_recurrentes): marca
        # qué regla generó esta tarea concreta, para poder comprobar si ya
        # se generó la de este periodo (idempotencia del cron) sin tener
        # que adivinarlo por asunto/fecha. Tiene que ir ANTES de
        # conn.executescript(INDICES) -- ese script crea un índice sobre
        # esta misma columna, y en una base de datos nueva (creada solo por
        # SCHEMA, que no la incluye) todavía no existiría.
        _asegurar_columna(conn, "tareas_outlook", "tarea_recurrente_id", "INTEGER REFERENCES tareas_recurrentes(id)")
        # Tareas unificadas: asignación a un compañero del despacho, vínculo con
        # un cliente fiscal y con el correo del que nació; y el enlace de cada
        # registro de tiempo (tareas) con la tarea de la lista a la que se dedicó.
        _asegurar_columna(conn, "tareas_outlook", "asignada_a", "INTEGER")
        _asegurar_columna(conn, "tareas_outlook", "cliente_fiscal_id", "INTEGER")
        _asegurar_columna(conn, "tareas_outlook", "mensaje_correo_id", "INTEGER")
        _asegurar_columna(conn, "tareas", "tarea_outlook_id", "INTEGER")
        # Notas con título, fijadas y vinculadas a un cliente fiscal, a una tarea
        # de la lista y al correo del que nacieron.
        _asegurar_columna(conn, "notas", "titulo", "TEXT")
        _asegurar_columna(conn, "notas", "fijada", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "notas", "cliente_fiscal_id", "INTEGER")
        _asegurar_columna(conn, "notas", "tarea_outlook_id", "INTEGER")
        _asegurar_columna(conn, "notas", "mensaje_correo_id", "INTEGER")

        # Multiusuario: por si SCHEMA no llegó a crear la tabla con la
        # columna (bases de datos migradas desde una versión sin ella).
        for tabla in (
            "categorias", "notas", "tareas", "tareas_outlook",
            "correo_cuentas", "correo_categorias", "ia_mensajes",
        ):
            _asegurar_columna(conn, tabla, "usuario_id", "INTEGER")

        # Conversaciones del Asistente IA: los mensajes se reparten en
        # conversaciones. Tiene que ir ANTES de executescript(INDICES) (hay un
        # índice sobre esta columna).
        _asegurar_columna(conn, "ia_mensajes", "conversacion_id", "INTEGER")
        # Fuentes citadas bajo la respuesta final del asistente (JSON).
        _asegurar_columna(conn, "ia_mensajes", "fuentes_json", "TEXT")

        conn.executescript(INDICES)
        _asegurar_orden_categorias(conn)

        usuario_id_local = _resolver_usuario_local(conn)
        _migrar_datos_sin_usuario(conn, usuario_id_local)
        _migrar_conversaciones_ia(conn)
        _migrar_preferencias_singleton(conn, usuario_id_local)
        _asegurar_columna(conn, "correo_preferencias", "deshacer_segundos", "INTEGER NOT NULL DEFAULT 10")
        _rellenar_hilos_correo(conn)

        # IA local (Ollama/LM Studio): columnas añadidas después de la
        # migración del singleton, ya que esta es la que crea/asegura la
        # propia tabla ia_preferencias en primer lugar.
        _asegurar_columna(conn, "ia_preferencias", "proveedor_local", "TEXT NOT NULL DEFAULT 'ollama'")
        _asegurar_columna(conn, "ia_preferencias", "modelo_local", "TEXT NOT NULL DEFAULT ''")
        # Modo solo lectura del asistente: al modelo solo se le ofrecen (y solo
        # se ejecutan) las herramientas de lectura.
        _asegurar_columna(conn, "ia_preferencias", "solo_lectura", "INTEGER NOT NULL DEFAULT 0")

        # Relación opcional con un proyecto (categorias) para las Tareas Outlook
        # — mismo patrón ya usado en correo_mensajes.categoria_id más arriba.
        _asegurar_columna(conn, "tareas_outlook", "categoria_id", "INTEGER REFERENCES categorias(id)")

        # Idempotencia para la cola offline de la app móvil (fichaje y notas
        # creados sin cobertura, sincronizados al recuperar conexión): un
        # cliente_uuid repetido en un reintento no debe duplicar la fila.
        # ALTER TABLE de SQLite no admite añadir UNIQUE directamente, así que
        # la columna se añade normal y la unicidad se fuerza con un índice
        # parcial aparte (ignora NULL, o sea el resto de orígenes que no
        # mandan cliente_uuid).
        _asegurar_columna(conn, "fichajes", "cliente_uuid", "TEXT")
        _asegurar_columna(conn, "notas", "cliente_uuid", "TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fichajes_cliente_uuid ON fichajes(cliente_uuid) WHERE cliente_uuid IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notas_cliente_uuid ON notas(cliente_uuid) WHERE cliente_uuid IS NOT NULL")

        # Checklist de onboarding del dashboard (web y móvil) — los pasos en
        # sí NO se trackean aparte (crear un proyecto, conectar correo, hablar
        # con la IA ya se pueden comprobar con datos que ya existen); esta
        # columna solo recuerda si el usuario ha pedido ocultar la tarjeta.
        _asegurar_columna(conn, "usuarios", "onboarding_visible", "INTEGER NOT NULL DEFAULT 1")

        # Multi-idioma: 'es' (por defecto, sin marcar explícitamente hasta
        # que el usuario cambia) | 'ca' | 'en' | 'fr'. NULL se trata como
        # "todavía no ha elegido" en el selector de locale (ver
        # app/main.py) y cae al idioma del navegador en vez de forzar
        # castellano a alguien que nunca lo pidió.
        _asegurar_columna(conn, "usuarios", "idioma", "TEXT")
        _asegurar_columna(conn, "usuarios", "ultimo_acceso", "TEXT")

        # Ampliación "fichaje 100% compliant" (Fase G3): blindaje técnico
        # hacia el registro horario digital que se avecina en España --
        # encadenado de hashes (ver _hash_fichaje/_backfill_hash_fichajes
        # más abajo) para que una alteración/borrado directo en la BD deje
        # rastro matemáticamente detectable, no solo "por convención" como
        # hasta ahora (fichajes ya era insert-only, pero sin nada que lo
        # verificara). Geolocalización nullable y opt-in por tenant (RGPD:
        # una gestoría sin fichaje en remoto no tiene por qué recogerla).
        _asegurar_columna(conn, "fichajes", "hash", "TEXT")
        _asegurar_columna(conn, "fichajes", "latitud", "REAL")
        _asegurar_columna(conn, "fichajes", "longitud", "REAL")
        _asegurar_columna(conn, "tenants", "fichaje_geolocalizacion", "INTEGER NOT NULL DEFAULT 0")
        _backfill_hash_fichajes(conn)

        # Backoffice renovado (cuarta ronda): suspender/reactivar un tenant a
        # mano, independiente de si paga o no (eso lo aporta la suscripción
        # de plataforma, ver planes_guilda más abajo).
        _asegurar_columna(conn, "tenants", "activo", "INTEGER NOT NULL DEFAULT 1")

        # Stripe Connect (bloque 5) -- cada tenant cobra a SUS clientes
        # finales con su propia cuenta Connect, el dinero le llega
        # directo a su banco.
        _asegurar_columna(conn, "tenants", "stripe_account_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stripe_onboarding_completado", "INTEGER NOT NULL DEFAULT 0")

        # Facturación de plataforma (bloque 6) -- Guilda Work cobra a sus
        # propios tenants por usar la app, cuenta de PLATAFORMA sin Connect.
        _asegurar_columna(conn, "tenants", "plan_id", "INTEGER REFERENCES planes_guilda(id)")
        _asegurar_columna(conn, "tenants", "stripe_customer_id", "TEXT")
        _asegurar_columna(conn, "tenants", "stripe_subscription_id", "TEXT")
        _asegurar_columna(conn, "tenants", "suscripcion_estado", "TEXT")

        # Ampliación "asistente de IA" (Fase G2): adjuntos subidos al chat --
        # texto/CSV pequeños que el asistente puede leer bajo demanda vía la
        # tool leer_adjunto_chat (app/ia_herramientas.py). Mismo criterio de
        # BLOB en la propia fila que usuario_perfil.avatar_contenido (G1),
        # sin filesystem aparte. Ligados a usuario_id (no a la conversación
        # en sí, que no tiene su propio id) -- se listan/leen siempre
        # filtrando por dueño, igual que el resto de recursos de este módulo.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ia_adjuntos (
                   id INTEGER PRIMARY KEY,
                   usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                   nombre_archivo TEXT NOT NULL,
                   tipo_mime TEXT,
                   contenido BLOB NOT NULL,
                   creado_en TEXT NOT NULL
               )"""
        )
        # 'usuario' = subido por el usuario con el clip (como hasta ahora);
        # 'asistente' = una tool se lo manda al usuario por el chat (Drive,
        # documento firmado...) -- distingue el sentido para pintar la
        # burbuja correcta en el chat sin tocar el resto del esquema.
        _asegurar_columna(conn, "ia_adjuntos", "origen", "TEXT NOT NULL DEFAULT 'usuario'")

        # Ampliación "espacio de ajustes de usuario" (Fase G1): perfil
        # propio (nombre a mostrar, avatar, preferencias de notificación).
        # Mismo patrón singleton usuario_id PRIMARY KEY que ia_preferencias/
        # correo_preferencias, pero como tabla nueva desde el principio (no
        # hace falta migrar desde un esquema global anterior). El avatar se
        # guarda como BLOB en la propia fila, igual que correo_adjuntos.contenido
        # -- mismo criterio de "sin filesystem aparte" ya establecido en este
        # proyecto, no una carpeta data/avatares/ nueva.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS usuario_perfil (
                   usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
                   nombre_mostrado TEXT,
                   avatar_contenido BLOB,
                   avatar_tipo_mime TEXT,
                   notificar_push_vencimientos INTEGER NOT NULL DEFAULT 1,
                   notificar_push_tiquets INTEGER NOT NULL DEFAULT 1,
                   notificar_resumen_semanal INTEGER NOT NULL DEFAULT 0
               )"""
        )
        # Ampliación (tercera ronda de mejoras): las 4 preferencias de
        # notificación deberían cubrir los 4 tipos reales que emite
        # app/notificaciones.py -- faltaban columnas para correo_nuevo y
        # portal_mensaje_nuevo (antes solo existían para
        # vencimiento_fiscal/tiquets, y ni siquiera esas dos se
        # comprobaban de verdad en ningún punto de emisión, ver
        # db.notificacion_tipo_activa()).
        _asegurar_columna(conn, "usuario_perfil", "notificar_push_correo", "INTEGER NOT NULL DEFAULT 1")
        _asegurar_columna(conn, "usuario_perfil", "notificar_push_portal_mensajes", "INTEGER NOT NULL DEFAULT 1")
        _asegurar_columna(conn, "correo_carpetas", "ultimo_uid_sincronizado", "TEXT")
        _asegurar_columna(conn, "correo_carpetas", "uidvalidity", "TEXT")
        _asegurar_columna(conn, "correo_carpetas", "ultima_pasada_completa", "TEXT")
        _asegurar_columna(conn, "correo_carpetas", "descarga_pendiente", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_fts_correo(conn)
        for columna, definicion in (
            # Con prefijo `proy_`: `estado`, `cliente_fiscal_id`… ya existen en las tablas que se unen con categorias y
            # sin prefijo harían ambiguas decenas de consultas.
            ("proy_compartido", "INTEGER NOT NULL DEFAULT 0"), ("proy_estado", "TEXT NOT NULL DEFAULT 'activo'"), ("proy_descripcion", "TEXT"),
            ("proy_fecha_objetivo", "TEXT"), ("proy_responsable_id", "INTEGER"), ("proy_cliente_id", "INTEGER"),
        ):
            _asegurar_columna(conn, "categorias", columna, definicion)
        _asegurar_columna(conn, "tareas_outlook", "seccion_id", "INTEGER")
        _asegurar_columna(conn, "tareas_outlook", "orden_proyecto", "INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tareas_outlook_proyecto ON tareas_outlook(categoria_id, seccion_id)")
        _crear_vista_participantes_todos(conn)

        conn.commit()
    finally:
        conn.close()


def hacer_backup_si_hace_falta(forzar: bool = False) -> None:
    """Mantiene UNA sola copia de registro.db en BACKUPS_DIR (la última
    verificada), en vez de acumular copias diarias.

    Flujo: crear (en un .tmp) -> verificar (PRAGMA integrity_check) ->
    sustituir de forma atómica -> borrar el resto. Si algo falla, la copia
    anterior se conserva intacta y se lanza la excepción (nunca se queda
    uno sin copia por un backup a medias). Sin `forzar`, si ya hay copia de
    hoy no hace nada.

    Usa la API de backup de sqlite3 en vez de una copia de archivo a pelo,
    para que sea segura aunque haya alguna conexión abierta en ese instante.
    """
    if not DB_PATH.exists():
        return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    hoy = datetime.now().strftime("%Y-%m-%d")
    destino = BACKUPS_DIR / f"registro_{hoy}.db"
    if destino.exists() and not forzar:
        return

    temporal = BACKUPS_DIR / f"registro_{hoy}.db.tmp"
    temporal.unlink(missing_ok=True)
    try:
        origen = sqlite3.connect(DB_PATH)
        try:
            copia = sqlite3.connect(temporal)
            try:
                origen.backup(copia)
            finally:
                copia.close()
        finally:
            origen.close()

        verificacion = sqlite3.connect(temporal)
        try:
            resultado = verificacion.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            verificacion.close()
        if resultado != "ok":
            raise RuntimeError(f"La copia de seguridad no supera integrity_check: {resultado}")

        os.replace(temporal, destino)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise

    # Solo llegamos aquí con la copia nueva ya verificada y en su sitio.
    for f in BACKUPS_DIR.glob("registro_*.db"):
        if f != destino:
            f.unlink(missing_ok=True)


def listar_backups() -> list[dict]:
    """Copias locales de registro.db ya hechas (ver
    hacer_backup_si_hace_falta) -- para la pantalla "Copias de
    seguridad" del backoffice. Lee del disco directamente, no hay
    tabla propia: la fuente de verdad son los propios ficheros."""
    if not BACKUPS_DIR.exists():
        return []
    backups = [
        {"nombre": f.name, "fecha": f.stem.removeprefix("registro_"), "tamano_bytes": f.stat().st_size}
        for f in BACKUPS_DIR.glob("registro_*.db")
    ]
    backups.sort(key=lambda b: b["fecha"], reverse=True)
    return backups


# --- Usuarios / autenticación ------------------------------------------------

def crear_usuario(email: str, contrasena: str) -> int:
    """Crea una cuenta con la contraseña ya hasheada (nunca en texto plano).
    Lanza sqlite3.IntegrityError si el email ya existe (el email es UNIQUE)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO usuarios (email, contrasena_hash, creado_en) VALUES (?, ?, ?)",
            (email.strip().lower(), generate_password_hash(contrasena), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_usuario_por_email(email: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM usuarios WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    finally:
        conn.close()


def obtener_usuario(usuario_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()


def onboarding_visible(usuario_id: int) -> bool:
    conn = get_connection()
    try:
        fila = conn.execute("SELECT onboarding_visible FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return bool(fila["onboarding_visible"]) if fila else False
    finally:
        conn.close()


def ocultar_onboarding(usuario_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET onboarding_visible = 0 WHERE id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def idioma_usuario(usuario_id: int) -> str | None:
    """None si el usuario nunca ha elegido idioma explícitamente -- el
    selector de locale (app/main.py) cae entonces al del navegador."""
    conn = get_connection()
    try:
        fila = conn.execute("SELECT idioma FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return fila["idioma"] if fila else None
    finally:
        conn.close()


def cambiar_idioma_usuario(usuario_id: int, codigo: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET idioma = ? WHERE id = ?", (codigo, usuario_id))
        conn.commit()
    finally:
        conn.close()


def listar_usuarios() -> list[sqlite3.Row]:
    """Todos los usuarios con el nombre de su tenant (si tiene), para el
    backoffice (Fase 7c) — no existe paginación porque el uso previsto es
    un puñado de usuarios, no miles."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT usuarios.*, tenants.nombre AS tenant_nombre "
            "FROM usuarios LEFT JOIN tenants ON tenants.id = usuarios.tenant_id "
            "ORDER BY usuarios.email"
        ).fetchall()
    finally:
        conn.close()


def es_admin(usuario_id: int) -> bool:
    usuario = obtener_usuario(usuario_id)
    return usuario is not None and usuario["rol"] == "admin"


def hacer_admin(email: str) -> None:
    """Lanza ValueError si no existe ningún usuario con ese email."""
    conn = get_connection()
    try:
        cur = conn.execute("UPDATE usuarios SET rol = 'admin' WHERE email = ?", (email.strip().lower(),))
        if cur.rowcount == 0:
            raise ValueError(f"No existe ningún usuario con el email '{email}'.")
        conn.commit()
    finally:
        conn.close()


def es_gestor_fichajes(usuario_id: int) -> bool:
    usuario = obtener_usuario(usuario_id)
    return usuario is not None and bool(usuario["gestor_fichajes"])


def asignar_gestor_fichajes(usuario_id: int, valor: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET gestor_fichajes = ? WHERE id = ?", (int(valor), usuario_id))
        conn.commit()
    finally:
        conn.close()


def es_supervisor_tenant(usuario_id: int) -> bool:
    usuario = obtener_usuario(usuario_id)
    return usuario is not None and bool(usuario["supervisor_tenant"])


def asignar_supervisor_tenant(usuario_id: int, valor: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET supervisor_tenant = ? WHERE id = ?", (int(valor), usuario_id))
        conn.commit()
    finally:
        conn.close()


def usuario_pertenece_a_tenant(usuario_id: int, tenant_id: int) -> bool:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (usuario_id, tenant_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def fijar_fichaje_geolocalizacion(tenant_id: int, valor: bool) -> None:
    """Opt-in por tenant (Fase G3) -- una gestoría sin trabajadores en
    remoto no tiene por qué recoger ubicación al fichar (RGPD). Ver
    app/rutas_fichaje.py:marcar()."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET fichaje_geolocalizacion = ? WHERE id = ?", (int(valor), tenant_id))
        conn.commit()
    finally:
        conn.close()


def quitar_admin(email: str) -> None:
    """Lanza ValueError si no existe ningún usuario con ese email."""
    conn = get_connection()
    try:
        cur = conn.execute("UPDATE usuarios SET rol = 'usuario' WHERE email = ?", (email.strip().lower(),))
        if cur.rowcount == 0:
            raise ValueError(f"No existe ningún usuario con el email '{email}'.")
        conn.commit()
    finally:
        conn.close()


def verificar_credenciales(email: str, contrasena: str) -> sqlite3.Row | None:
    """Devuelve la fila del usuario si el email existe y la contraseña es
    correcta; None en cualquier otro caso (sin distinguir el motivo, para no
    filtrar si un email concreto existe o no).

    Solo queda en uso para el usuario "local" del modo escritorio (que
    nunca pasa por Kratos, ver `usuario_local_id`) — el login real
    (hospedado, web/API) verifica credenciales contra Kratos a partir de
    la Fase 7a; ver `app/kratos.py`."""
    usuario = obtener_usuario_por_email(email)
    if usuario is None or not check_password_hash(usuario["contrasena_hash"], contrasena):
        return None
    return usuario


# --- Vínculo con la identidad de Ory Kratos (Fase 7a) -------------------

def usuario_por_kratos_id(identity_id: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM usuarios WHERE kratos_identity_id = ?", (identity_id,)
        ).fetchone()
    finally:
        conn.close()


def vincular_kratos_id(usuario_id: int, identity_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE usuarios SET kratos_identity_id = ? WHERE id = ?", (identity_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def crear_usuario_vinculado_a_kratos(email: str, identity_id: str) -> int:
    """Crea la fila local de `usuarios` para una identidad que YA existe en
    Kratos (login/registro real, a partir de la Fase 7a) — no guarda
    ninguna contraseña propia, Kratos es quien la custodia."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO usuarios (email, contrasena_hash, kratos_identity_id, creado_en) "
            "VALUES (?, ?, ?, ?)",
            (email.strip().lower(), "", identity_id, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- Tenants (Fase 7c.3) -------------------------------------------------

def crear_tenant(nombre: str) -> int:
    """Lanza sqlite3.IntegrityError si el nombre ya existe (UNIQUE)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tenants (nombre, creado_en) VALUES (?, ?)",
            (nombre.strip(), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tenants() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tenants ORDER BY nombre").fetchall()
    finally:
        conn.close()


def listar_tenants_con_conteo() -> list[sqlite3.Row]:
    """Como listar_tenants(), pero con el nº de usuarios asignados a cada
    uno (columna `n_usuarios`) — para la tabla del backoffice (Fase 7c)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT tenants.*, COUNT(usuarios.id) AS n_usuarios "
            "FROM tenants LEFT JOIN usuarios ON usuarios.tenant_id = tenants.id "
            "GROUP BY tenants.id ORDER BY tenants.nombre"
        ).fetchall()
    finally:
        conn.close()


def resumen_equipos_tenants() -> dict[int, dict]:
    """Por tenant: usuarios totales, administradores, gestores de fichajes,
    supervisores, clientes fiscales activos y nombre del plan -- una sola
    consulta para las pantallas de visión global del backoffice."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT t.id,
                      (SELECT COUNT(*) FROM usuarios u WHERE u.tenant_id = t.id) AS usuarios,
                      (SELECT COUNT(*) FROM usuarios u WHERE u.tenant_id = t.id AND u.rol = 'admin') AS admins,
                      (SELECT COUNT(*) FROM usuarios u WHERE u.tenant_id = t.id AND u.gestor_fichajes = 1) AS gestores,
                      (SELECT COUNT(*) FROM usuarios u WHERE u.tenant_id = t.id AND u.supervisor_tenant = 1) AS supervisores,
                      (SELECT COUNT(*) FROM clientes_fiscales c WHERE c.tenant_id = t.id AND c.papelera_en IS NULL) AS clientes,
                      (SELECT p.nombre FROM planes_guilda p WHERE p.id = t.plan_id) AS plan
               FROM tenants t"""
        ).fetchall()
        return {f["id"]: dict(f) for f in filas}
    finally:
        conn.close()


def resumen_usuarios_backoffice() -> dict[int, dict]:
    """Por usuario: nº de dispositivos/tokens y último uso de cualquiera de ellos."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT usuario_id, COUNT(*) AS dispositivos, MAX(COALESCE(ultimo_uso_en, creado_en)) AS ultimo_uso
               FROM tokens_api GROUP BY usuario_id"""
        ).fetchall()
        return {f["usuario_id"]: dict(f) for f in filas}
    finally:
        conn.close()


def resumen_plataforma() -> dict:
    """Métricas agregadas para la pantalla "Resumen" del backoffice --
    una sola función porque todas las consultas son baratas (COUNT/SUM
    sobre tablas pequeñas) y siempre se piden juntas."""
    conn = get_connection()
    try:
        tenants_total = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        tenants_activos = conn.execute("SELECT COUNT(*) FROM tenants WHERE activo = 1").fetchone()[0]
        usuarios_total = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        mrr_centimos = conn.execute(
            "SELECT COALESCE(SUM(pg.precio_mensual_centimos), 0) FROM tenants t "
            "JOIN planes_guilda pg ON pg.id = t.plan_id "
            "WHERE t.suscripcion_estado = 'activa'"
        ).fetchone()[0]
        tenants_recientes = conn.execute(
            "SELECT id, nombre, creado_en FROM tenants ORDER BY creado_en DESC LIMIT 5"
        ).fetchall()
        return {
            "tenants_total": tenants_total,
            "tenants_activos": tenants_activos,
            "usuarios_total": usuarios_total,
            "mrr_centimos": mrr_centimos,
            "tenants_recientes": tenants_recientes,
        }
    finally:
        conn.close()


def listar_suscripciones_tenants() -> list[sqlite3.Row]:
    """Todos los tenants con su plan (si tiene) y estado de suscripción,
    para la vista agregada de Ingresos del backoffice -- JOIN con
    planes_guilda para traer nombre/precio en una sola consulta."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT tenants.*, planes_guilda.nombre AS plan_nombre, "
            "planes_guilda.precio_mensual_centimos AS plan_precio_centimos "
            "FROM tenants LEFT JOIN planes_guilda ON planes_guilda.id = tenants.plan_id "
            "ORDER BY tenants.nombre"
        ).fetchall()
    finally:
        conn.close()


def renombrar_tenant(tenant_id: int, nuevo_nombre: str) -> None:
    """Lanza sqlite3.IntegrityError si el nombre ya existe (UNIQUE)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET nombre = ? WHERE id = ?", (nuevo_nombre.strip(), tenant_id))
        conn.commit()
    finally:
        conn.close()


def alternar_activo_tenant(tenant_id: int, valor: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET activo = ? WHERE id = ?", (int(valor), tenant_id))
        conn.commit()
    finally:
        conn.close()


def ultima_actividad_tenant(tenant_id: int) -> str | None:
    """Fecha/hora del registro más reciente entre tareas/notas/fichajes/
    correo de cualquier usuario del tenant -- ISO 8601 o None si el tenant
    no tiene ninguna actividad todavía. Solo para mostrar "hace X" en el
    backoffice, no se usa para ninguna decisión de negocio."""
    ids = usuarios_de_tenant(tenant_id)
    if not ids:
        return None
    conn = get_connection()
    try:
        marcadores = ",".join("?" * len(ids))
        fila = conn.execute(
            f"""SELECT MAX(fecha) AS ultima FROM (
                SELECT MAX(COALESCE(fin_en, inicio_en)) AS fecha FROM tareas WHERE usuario_id IN ({marcadores})
                UNION ALL
                SELECT MAX(creada_en) AS fecha FROM notas WHERE usuario_id IN ({marcadores})
                UNION ALL
                SELECT MAX(creado_en) AS fecha FROM fichajes WHERE usuario_id IN ({marcadores})
                UNION ALL
                SELECT MAX(m.fecha) AS fecha FROM correo_mensajes m
                    JOIN correo_cuentas cu ON cu.id = m.cuenta_id
                    WHERE cu.usuario_id IN ({marcadores})
            )""",
            ids * 4,
        ).fetchone()
        return fila["ultima"] if fila else None
    finally:
        conn.close()


# --- Stripe Connect (bloque 5 -- cada tenant cobra a sus clientes) --------

def guardar_stripe_account_id(tenant_id: int, stripe_account_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_account_id = ? WHERE id = ?", (stripe_account_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def marcar_stripe_onboarding_completado(tenant_id: int, valor: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_onboarding_completado = ? WHERE id = ?", (int(valor), tenant_id))
        conn.commit()
    finally:
        conn.close()


def registrar_pago_vencimiento(vencimiento_id: int, stripe_checkout_session_id: str, importe_centimos: int) -> bool:
    """True si se registró un pago nuevo, False si esta sesión de
    Checkout ya se había procesado antes (el webhook de Stripe puede
    reintentar la misma entrega -- stripe_checkout_session_id es UNIQUE,
    así que un segundo intento no duplica el registro)."""
    conn = get_connection()
    try:
        try:
            conn.execute(
                "INSERT INTO vencimientos_fiscales_pagos (vencimiento_id, stripe_checkout_session_id, importe_centimos, pagado_en) "
                "VALUES (?, ?, ?, ?)",
                (vencimiento_id, stripe_checkout_session_id, importe_centimos, now_iso()),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        conn.close()


def pago_de_vencimiento(vencimiento_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM vencimientos_fiscales_pagos WHERE vencimiento_id = ? ORDER BY id DESC LIMIT 1",
            (vencimiento_id,),
        ).fetchone()
    finally:
        conn.close()


# --- Facturación de plataforma (bloque 6 -- Guilda Work cobra a sus tenants)

def crear_plan_guilda(nombre: str, descripcion: str | None, precio_mensual_centimos: int | None, max_usuarios: int | None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO planes_guilda (nombre, descripcion, precio_mensual_centimos, max_usuarios, creado_en) "
            "VALUES (?, ?, ?, ?, ?)",
            (nombre.strip(), descripcion, precio_mensual_centimos, max_usuarios, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_planes_guilda(solo_activos: bool = False) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM planes_guilda"
        if solo_activos:
            sql += " WHERE activo = 1"
        sql += " ORDER BY precio_mensual_centimos IS NULL, precio_mensual_centimos, nombre"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def obtener_plan_guilda(plan_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM planes_guilda WHERE id = ?", (plan_id,)).fetchone()
    finally:
        conn.close()


def editar_plan_guilda(plan_id: int, nombre: str, descripcion: str | None, precio_mensual_centimos: int | None, max_usuarios: int | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE planes_guilda SET nombre = ?, descripcion = ?, precio_mensual_centimos = ?, max_usuarios = ? WHERE id = ?",
            (nombre.strip(), descripcion, precio_mensual_centimos, max_usuarios, plan_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_stripe_price_id_plan(plan_id: int, stripe_price_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE planes_guilda SET stripe_price_id = ? WHERE id = ?", (stripe_price_id, plan_id))
        conn.commit()
    finally:
        conn.close()


def crear_extra_guilda(nombre: str, descripcion: str | None, precio_centimos: int | None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO extras_guilda (nombre, descripcion, precio_centimos, creado_en) VALUES (?, ?, ?, ?)",
            (nombre.strip(), descripcion, precio_centimos, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_extras_guilda() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM extras_guilda ORDER BY nombre").fetchall()
    finally:
        conn.close()


def obtener_extra_guilda(extra_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM extras_guilda WHERE id = ?", (extra_id,)).fetchone()
    finally:
        conn.close()


def guardar_stripe_price_id_extra(extra_id: int, stripe_price_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE extras_guilda SET stripe_price_id = ? WHERE id = ?", (stripe_price_id, extra_id))
        conn.commit()
    finally:
        conn.close()


def editar_extra_guilda(extra_id: int, nombre: str, descripcion: str | None, precio_centimos: int | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE extras_guilda SET nombre = ?, descripcion = ?, precio_centimos = ? WHERE id = ?",
            (nombre.strip(), descripcion, precio_centimos, extra_id),
        )
        conn.commit()
    finally:
        conn.close()


def limpiar_stripe_price_id_plan(plan_id: int) -> None:
    """Los Price de Stripe son inmutables -- si cambia el precio de un
    plan ya sincronizado, el stripe_price_id guardado deja de
    corresponder al importe mostrado. Se limpia para que
    "Sincronizar con Stripe" vuelva a estar disponible y cree un Price
    nuevo con el importe correcto (el Price antiguo queda huérfano en
    Stripe, sin usarse más, pero Stripe no permite borrarlos)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE planes_guilda SET stripe_price_id = NULL WHERE id = ?", (plan_id,))
        conn.commit()
    finally:
        conn.close()


def limpiar_stripe_price_id_extra(extra_id: int) -> None:
    """Mismo motivo que limpiar_stripe_price_id_plan, para extras."""
    conn = get_connection()
    try:
        conn.execute("UPDATE extras_guilda SET stripe_price_id = NULL WHERE id = ?", (extra_id,))
        conn.commit()
    finally:
        conn.close()


def asignar_plan_tenant(tenant_id: int, plan_id: int | None) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET plan_id = ? WHERE id = ?", (plan_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_stripe_customer_id(tenant_id: int, stripe_customer_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_customer_id = ? WHERE id = ?", (stripe_customer_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_stripe_subscription_id(tenant_id: int, stripe_subscription_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET stripe_subscription_id = ? WHERE id = ?", (stripe_subscription_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def actualizar_suscripcion_estado(tenant_id: int, estado: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET suscripcion_estado = ? WHERE id = ?", (estado, tenant_id))
        conn.commit()
    finally:
        conn.close()


def tenant_por_stripe_customer_id(stripe_customer_id: str) -> sqlite3.Row | None:
    """Usado por el webhook de Stripe (evento ligado a un customer, no a
    un tenant_id de Guilda Work directamente) para resolver a qué tenant
    corresponde."""
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE stripe_customer_id = ?", (stripe_customer_id,)).fetchone()
    finally:
        conn.close()


def activar_extra_tenant(tenant_id: int, extra_id: int, cantidad: int = 1, activo_hasta: str | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tenants_extras_activos (tenant_id, extra_id, cantidad, activo_desde, activo_hasta, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, extra_id, cantidad, now_iso(), activo_hasta, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_extras_activos_tenant(tenant_id: int) -> list[sqlite3.Row]:
    """Solo los que no han caducado -- activo_hasta NULL es indefinido,
    con fecha se compara contra el momento actual."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT tea.*, eg.nombre, eg.precio_centimos FROM tenants_extras_activos tea "
            "JOIN extras_guilda eg ON eg.id = tea.extra_id "
            "WHERE tea.tenant_id = ? AND (tea.activo_hasta IS NULL OR tea.activo_hasta >= ?) "
            "ORDER BY tea.activo_desde DESC",
            (tenant_id, now_iso()),
        ).fetchall()
    finally:
        conn.close()


def desactivar_extra_tenant(tenant_extra_id: int) -> None:
    """Corta un extra activo AHORA (fija activo_hasta a un instante ya
    pasado) en vez de borrar la fila -- listar_extras_activos_tenant()
    ya deja de devolverlo desde la siguiente consulta, pero el
    historial de que estuvo activo se conserva, mismo criterio de "no
    perder datos" que el resto del proyecto. Un segundo antes de ahora
    (no exactamente ahora) porque now_iso() solo tiene precisión de
    segundo y el filtro de listar_extras_activos_tenant es inclusive
    (activo_hasta >= ahora) -- con el mismo instante, una consulta en
    el mismo segundo seguiría viéndolo activo."""
    conn = get_connection()
    try:
        activo_hasta = (datetime.now() - timedelta(seconds=1)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE tenants_extras_activos SET activo_hasta = ? WHERE id = ?",
            (activo_hasta, tenant_extra_id),
        )
        conn.commit()
    finally:
        conn.close()


def contar_fichajes_tenant(tenant_id: int) -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM fichajes WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
    finally:
        conn.close()


def borrar_tenant(tenant_id: int, incluir_fichajes: bool = False) -> None:
    """Borra el tenant y todo lo que cuelga de él (clientes fiscales con sus
    vencimientos, documentos, mensajes, pagos y accesos del portal; webhooks y
    sus entregas; extras y accesos de facturación). Los usuarios quedan sin
    tenant, no se borran, igual que sus tareas, notas y correo.

    El registro de jornada (fichajes) hay que conservarlo cuatro años por ley
    (art. 34.9 ET): si el tenant tiene fichajes, se rechaza el borrado salvo que
    se pida expresamente `incluir_fichajes`. Todo ocurre en una sola
    transacción: o se borra todo o no se toca nada."""
    conn = get_connection()
    try:
        if not incluir_fichajes:
            n = conn.execute("SELECT COUNT(*) FROM fichajes WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
            if n:
                raise ValueError(
                    f"El tenant tiene {n} fichajes, que la ley obliga a conservar cuatro años. "
                    "Expórtalos y confirma que quieres borrarlos también."
                )
        venc = "SELECT id FROM vencimientos_fiscales WHERE tenant_id = ?"
        clientes = "SELECT id FROM clientes_fiscales WHERE tenant_id = ?"
        conn.execute(f"DELETE FROM vencimientos_fiscales_pagos WHERE vencimiento_id IN ({venc})", (tenant_id,))
        conn.execute("DELETE FROM vencimientos_fiscales WHERE tenant_id = ?", (tenant_id,))  # documentos, mensajes y recordatorios en cascada
        for tabla in ("correo_mensajes", "tareas_outlook", "notas", "correo_reglas"):
            conn.execute(f"UPDATE {tabla} SET cliente_fiscal_id = NULL WHERE cliente_fiscal_id IN ({clientes})", (tenant_id,))
        conn.execute(f"DELETE FROM clientes_fiscales_accesos WHERE cliente_fiscal_id IN ({clientes})", (tenant_id,))
        conn.execute("DELETE FROM clientes_fiscales WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM webhooks_entregas WHERE webhook_id IN (SELECT id FROM webhooks WHERE tenant_id = ?)", (tenant_id,))
        conn.execute("DELETE FROM webhooks WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM fichaje_avisos WHERE entrada_id IN (SELECT id FROM fichajes WHERE tenant_id = ?)", (tenant_id,))
        conn.execute("DELETE FROM fichajes WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants_extras_activos WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM facturacion_accesos WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants_herramientas_ocultas WHERE tenant_id = ?", (tenant_id,))
        conn.execute("UPDATE usuarios SET tenant_id = NULL WHERE tenant_id = ?", (tenant_id,))
        conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def desasignar_tenant(usuario_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = NULL WHERE id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def obtener_tenant(tenant_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()


# --- Visibilidad de herramientas por tenant ----------------------------------

def ocultar_herramienta(tenant_id: int, herramienta_id: str) -> None:
    """Idempotente: ocultar dos veces la misma herramienta no falla."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO tenants_herramientas_ocultas (tenant_id, herramienta_id) VALUES (?, ?)",
            (tenant_id, herramienta_id),
        )
        conn.commit()
    finally:
        conn.close()


def mostrar_herramienta(tenant_id: int, herramienta_id: str) -> None:
    """Idempotente: quitar la ocultación de una herramienta ya visible no falla."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM tenants_herramientas_ocultas WHERE tenant_id = ? AND herramienta_id = ?",
            (tenant_id, herramienta_id),
        )
        conn.commit()
    finally:
        conn.close()


def herramientas_ocultas_de_tenant(tenant_id: int) -> set[str]:
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT herramienta_id FROM tenants_herramientas_ocultas WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        return {f["herramienta_id"] for f in filas}
    finally:
        conn.close()


def herramientas_ocultas_de_tenants(tenant_ids: list[int]) -> dict[int, set[str]]:
    """Igual que herramientas_ocultas_de_tenant() pero para varios tenants a
    la vez (una consulta con IN en vez de una por tenant) -- usado en el
    backoffice, que antes hacía una llamada por tenant listado."""
    if not tenant_ids:
        return {}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(tenant_ids))
        filas = conn.execute(
            f"SELECT tenant_id, herramienta_id FROM tenants_herramientas_ocultas WHERE tenant_id IN ({marcas})",
            tenant_ids,
        ).fetchall()
        resultado: dict[int, set[str]] = {tid: set() for tid in tenant_ids}
        for f in filas:
            resultado[f["tenant_id"]].add(f["herramienta_id"])
        return resultado
    finally:
        conn.close()


def adopcion_herramientas(ocultas_por_tenant: dict[int, set[str]], catalogo_ids: list[str]) -> dict[str, int]:
    """Nº de tenants que tienen cada herramienta VISIBLE (no oculta) --
    para la pantalla "Catálogo de herramientas" del backoffice. Cálculo
    en Python (no SQL) porque la fuente de verdad ya está en memoria
    tras herramientas_ocultas_de_tenants(), sin tabla propia que
    consultar -- ausencia de fila = visible, ver db.py más arriba."""
    return {
        herramienta_id: sum(1 for ocultas in ocultas_por_tenant.values() if herramienta_id not in ocultas)
        for herramienta_id in catalogo_ids
    }


def guardar_facturascripts(tenant_id: int, url: str, admin_user: str, admin_pass: str) -> None:
    """Guarda cómo llegar a la instancia de FacturaScripts recién
    aprovisionada de un tenant — ver app/facturascripts.py:aprovisionar_tenant."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET facturascripts_url = ?, facturascripts_admin_user = ?, "
            "facturascripts_admin_pass = ? WHERE id = ?",
            (url, admin_user, admin_pass, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_facturascripts_api_key(tenant_id: int, api_key: str) -> None:
    """La API Key se genera a mano dentro de cada instancia (paso manual,
    ver HOSTING.md 8.21) — esto solo la guarda una vez que el admin la
    pega en el backoffice."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET facturascripts_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_documenso_api_key(tenant_id: int, api_key: str) -> None:
    """El token se genera a mano dentro del Equipo de Documenso de ese
    tenant (paso manual, ver HOSTING.md) — esto solo lo guarda una vez
    que el admin lo pega en el backoffice."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET documenso_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_paperless(tenant_id: int, group_id: int, user_id: int, api_key: str) -> None:
    """A diferencia de facturascripts/documenso, aquí no hay ningún paso
    manual: app/paperless.py:aprovisionar_tenant() crea el Grupo, el
    usuario de servicio y su token por API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET paperless_group_id = ?, paperless_user_id = ?, paperless_api_key = ? WHERE id = ?",
            (group_id, user_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_baserow(tenant_id: int, workspace_id: int, api_key: str) -> None:
    """Igual que guardar_paperless: sin pasos manuales,
    app/baserow.py:aprovisionar_tenant() crea el Workspace y su token
    por API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET baserow_workspace_id = ?, baserow_api_key = ? WHERE id = ?",
            (workspace_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_calcom(tenant_id: int, email: str, admin_pass: str) -> None:
    """Guarda el usuario de servicio de Cal.diy recién creado para un
    tenant — ver app/calcom.py:aprovisionar_tenant. admin_pass se enseña
    una sola vez en el backoffice, igual que facturascripts_admin_pass."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET calcom_email = ?, calcom_admin_pass = ? WHERE id = ?",
            (email, admin_pass, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_calcom_api_key(tenant_id: int, api_key: str) -> None:
    """La API Key se genera a mano desde la propia cuenta de servicio
    (paso manual, ver HOSTING.md 8.25) — esto solo la guarda una vez que
    el admin la pega en el backoffice."""
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET calcom_api_key = ? WHERE id = ?", (api_key, tenant_id))
        conn.commit()
    finally:
        conn.close()


def guardar_listmonk(tenant_id: int, list_id: int, list_role_id: int, api_key: str) -> None:
    """Igual que guardar_paperless: sin pasos manuales,
    app/listmonk.py:aprovisionar_tenant() crea la Lista, el Rol de lista
    y el usuario de servicio por API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET listmonk_list_id = ?, listmonk_list_role_id = ?, listmonk_api_key = ? WHERE id = ?",
            (list_id, list_role_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_stalwart(
    tenant_id: int,
    stalwart_tenant_id: str,
    domain_id: str,
    domain_name: str,
    account_id: str,
    api_key: str,
) -> None:
    """Igual que guardar_listmonk: sin pasos manuales,
    app/stalwart.py:aprovisionar_tenant() crea el Tenant, el Domain
    (con el dominio propio real del cliente), la Account y el ApiKey por
    API, esto solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET stalwart_tenant_id = ?, stalwart_domain_id = ?, "
            "stalwart_domain_name = ?, stalwart_account_id = ?, stalwart_api_key = ? "
            "WHERE id = ?",
            (stalwart_tenant_id, domain_id, domain_name, account_id, api_key, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_ntfy(tenant_id: int, topic: str, token: str) -> None:
    """Igual que guardar_stalwart: sin pasos manuales,
    app/ntfy.py:aprovisionar_tenant() crea el usuario+ACL+token, esto
    solo los guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET ntfy_topic = ?, ntfy_token = ? WHERE id = ?",
            (topic, token, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_umami(tenant_id: int, team_id: str, website_id: str) -> None:
    """Igual que guardar_ntfy: sin pasos manuales,
    app/umami.py:aprovisionar_tenant() crea el Team+sitio, esto solo los
    guarda."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET umami_team_id = ?, umami_website_id = ? WHERE id = ?",
            (team_id, website_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_tenant_por_nombre(nombre: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tenants WHERE nombre = ?", (nombre.strip(),)).fetchone()
    finally:
        conn.close()


def asignar_tenant(usuario_id: int, tenant_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE usuarios SET tenant_id = ? WHERE id = ?", (tenant_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def guardar_datos_tenant(tenant_id: int, cif: str | None, direccion_fiscal: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tenants SET cif = ?, direccion_fiscal = ? WHERE id = ?",
            (cif or None, direccion_fiscal or None, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()


ZONA_HORARIA_DEFECTO = "Europe/Madrid"  # hora oficial de España peninsular
ZONAS_HORARIAS = [
    ("Europe/Madrid", "España peninsular (Europe/Madrid)"),
    ("Atlantic/Canary", "Canarias (Atlantic/Canary)"),
    ("Europe/Lisbon", "Portugal (Europe/Lisbon)"),
    ("Europe/London", "Reino Unido (Europe/London)"),
    ("Europe/Paris", "Europa central (Europe/Paris)"),
    ("UTC", "UTC"),
    ("America/Mexico_City", "México (America/Mexico_City)"),
    ("America/Bogota", "Colombia (America/Bogota)"),
    ("America/Lima", "Perú (America/Lima)"),
    ("America/Santiago", "Chile (America/Santiago)"),
    ("America/Argentina/Buenos_Aires", "Argentina (America/Argentina/Buenos_Aires)"),
    ("America/New_York", "Este de EE. UU. (America/New_York)"),
]


def zona_horaria_valida(nombre: str | None) -> bool:
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(nombre or "")
        return bool(nombre)
    except Exception:
        return False


def zona_horaria_tenant(tenant_id: int | None) -> str:
    """Huso horario IANA del tenant; por defecto la hora oficial de España peninsular."""
    if tenant_id:
        tenant = obtener_tenant(tenant_id)
        if tenant and tenant["zona_horaria"] and zona_horaria_valida(tenant["zona_horaria"]):
            return tenant["zona_horaria"]
    return ZONA_HORARIA_DEFECTO


def guardar_zona_horaria_tenant(tenant_id: int, zona: str) -> None:
    if not zona_horaria_valida(zona):
        raise ValueError("Huso horario no válido")
    conn = get_connection()
    try:
        conn.execute("UPDATE tenants SET zona_horaria = ? WHERE id = ?", (zona, tenant_id))
        conn.commit()
    finally:
        conn.close()


_ULTIMO_ACCESO_ANOTADO: dict[int, float] = {}


def registrar_acceso(usuario_id: int, cada_minutos: int = 10) -> None:
    """Anota `usuarios.ultimo_acceso` (solo para mostrarlo en el backoffice).
    Como mucho una escritura cada `cada_minutos` por usuario, para no cargar
    SQLite con una escritura por petición; un fallo nunca rompe la petición."""
    # Memoria del proceso: sin esto cada petición ejecutaba el UPDATE (aunque no cambiara
    # ninguna fila) y con él una transacción de escritura por página vista.
    marca = time.monotonic()
    if marca - _ULTIMO_ACCESO_ANOTADO.get(usuario_id, -1e9) < cada_minutos * 60:
        return
    _ULTIMO_ACCESO_ANOTADO[usuario_id] = marca
    ahora = datetime.now()
    limite = (ahora - timedelta(minutes=cada_minutos)).isoformat(timespec="seconds")
    try:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE usuarios SET ultimo_acceso = ? WHERE id = ? AND (ultimo_acceso IS NULL OR ultimo_acceso < ?)",
                (ahora.isoformat(timespec="seconds"), usuario_id, limite),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def tenant_de_usuario(usuario_id: int) -> sqlite3.Row | None:
    """El tenant del usuario, o None si no tiene ninguno asignado todavía."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT tenants.* FROM tenants "
            "JOIN usuarios ON usuarios.tenant_id = tenants.id "
            "WHERE usuarios.id = ?",
            (usuario_id,),
        ).fetchone()
    finally:
        conn.close()


def usuarios_de_tenant(tenant_id: int) -> list[int]:
    """IDs de los usuarios asignados a un tenant -- patrón reutilizable para
    cualquier consulta futura que necesite agregar entre varios usuarios de
    un mismo tenant (p.ej. reasignar un vencimiento fiscal a otro miembro
    del equipo), en vez de que cada función nueva reinvente el JOIN a mano.
    Deliberadamente no se añadió `tenant_id` a tareas/notas/categorias (se
    quedaría obsoleto si un usuario cambia de tenant) -- este helper es la
    forma correcta de agregar por tenant sin ese problema."""
    conn = get_connection()
    try:
        filas = conn.execute("SELECT id FROM usuarios WHERE tenant_id = ?", (tenant_id,)).fetchall()
        return [f["id"] for f in filas]
    finally:
        conn.close()


def usuario_local_id() -> int:
    """Para procesos locales de confianza (cli.py, mcp_server.py) que no
    pasan por login web: resuelve (o crea la primera vez) el usuario local
    fijo, y lo usan siempre como su `usuario_id`."""
    conn = get_connection()
    try:
        uid = _resolver_usuario_local(conn)
        conn.commit()
        return uid
    finally:
        conn.close()


# --- Tokens de la API (Fase 2, app móvil) -------------------------------
# Tokens opacos (no JWT): el valor en claro se genera una vez y se devuelve
# al cliente; aquí solo se guarda su hash SHA-256 (no generate_password_hash
# — el token ya tiene alta entropía propia y hace falta una búsqueda exacta
# rápida por igualdad, no una comparación tipo contraseña).

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


PERMISOS_TOKEN_API = ("completo", "solo_lectura")


def crear_token_api(usuario_id: int, nombre_dispositivo: str | None = None, permisos: str = "completo") -> str:
    """`permisos`: "completo" (como siempre) o "solo_lectura" (solo GET: lo
    aplica auth.token_required)."""
    if permisos not in PERMISOS_TOKEN_API:
        raise ValueError("Permisos de token no válidos.")
    token = secrets.token_urlsafe(32)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO tokens_api (usuario_id, token_hash, nombre_dispositivo, creado_en, permisos) "
            "VALUES (?, ?, ?, ?, ?)",
            (usuario_id, _hash_token(token), nombre_dispositivo, now_iso(), permisos),
        )
        conn.commit()
        return token
    finally:
        conn.close()


TOKEN_API_DIAS_INACTIVIDAD = 90


def usuario_id_por_token(token: str) -> int | None:
    autenticado = autenticar_token(token)
    return autenticado[0] if autenticado else None


def autenticar_token(token: str) -> tuple[int, str] | None:
    """(usuario_id, permisos), o None si el token no existe, o si lleva
    TOKEN_API_DIAS_INACTIVIDAD días sin usarse (se borra en el momento, no
    hace falta una tarea periódica aparte: con que se compruebe en cada uso
    es suficiente para un catálogo de tokens que no es previsible que
    crezca mucho)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT usuario_id, creado_en, ultimo_uso_en, permisos FROM tokens_api WHERE token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
        if fila is None:
            return None
        ultima_actividad = fila["ultimo_uso_en"] or fila["creado_en"]
        limite = (datetime.now() - timedelta(days=TOKEN_API_DIAS_INACTIVIDAD)).isoformat(timespec="seconds")
        if ultima_actividad < limite:
            conn.execute("DELETE FROM tokens_api WHERE token_hash = ?", (_hash_token(token),))
            conn.commit()
            return None
        conn.execute(
            "UPDATE tokens_api SET ultimo_uso_en = ? WHERE token_hash = ?",
            (now_iso(), _hash_token(token)),
        )
        conn.commit()
        return fila["usuario_id"], fila["permisos"]
    finally:
        conn.close()


def revocar_token_api(token: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tokens_api WHERE token_hash = ?", (_hash_token(token),))
        conn.commit()
    finally:
        conn.close()


def listar_tokens_api(usuario_id: int):
    """Dispositivos móviles con sesión activa de este usuario (para la
    pantalla "Mis dispositivos" y, con verificación de tenant en la propia
    ruta, para que un admin revoque los de un compañero de tenant) — nunca
    expone el token ni su hash, solo lo necesario para reconocerlo y
    decidir si revocarlo."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, nombre_dispositivo, creado_en, ultimo_uso_en, permisos FROM tokens_api "
            "WHERE usuario_id = ? ORDER BY COALESCE(ultimo_uso_en, creado_en) DESC",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def revocar_token_api_por_id(usuario_id: int, token_id: int) -> bool:
    """Revoca por id en vez de por token (la web nunca tiene el token en
    claro, solo el móvil lo guarda). Exige usuario_id para que un usuario
    no pueda revocar el token de otro solo adivinando su id — quien llame
    a esto con el id de un compañero de tenant debe haber verificado antes
    que puede administrar sus dispositivos (ver backoffice)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM tokens_api WHERE id = ? AND usuario_id = ?", (token_id, usuario_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def crear_lead_contacto(
    nombre: str, email: str, empresa: str | None = None,
    telefono: str | None = None, mensaje: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads_contacto (nombre, empresa, email, telefono, mensaje, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, empresa, email, telefono, mensaje, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_leads_contacto():
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM leads_contacto ORDER BY atendido ASC, creado_en DESC"
        ).fetchall()
    finally:
        conn.close()


def marcar_lead_atendido(lead_id: int, atendido: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE leads_contacto SET atendido = ? WHERE id = ?", (1 if atendido else 0, lead_id))
        conn.commit()
    finally:
        conn.close()


# --- Dispositivos push (ver app/push.py) --------------------------------

def registrar_dispositivo_push(usuario_id: int, fcm_token: str, plataforma: str) -> None:
    """Alta o refresco de un token FCM. REPLACE por fcm_token (UNIQUE): si
    el mismo dispositivo ya estaba registrado a otro usuario_id (reinstalo
    la app con otra cuenta), se reasigna al usuario actual en vez de dejar
    dos filas o rechazar el alta."""
    conn = get_connection()
    try:
        ahora = now_iso()
        conn.execute(
            "INSERT INTO dispositivos_push (usuario_id, fcm_token, plataforma, creado_en, actualizado_en) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(fcm_token) DO UPDATE SET usuario_id = excluded.usuario_id, "
            "plataforma = excluded.plataforma, actualizado_en = excluded.actualizado_en",
            (usuario_id, fcm_token, plataforma, ahora, ahora),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_dispositivo_push(usuario_id: int, fcm_token: str) -> None:
    """Se llama en logout (ver /api/v1/dispositivos-push DELETE) para dejar
    de mandar push a un dispositivo del que el usuario ya ha cerrado
    sesión -- exige usuario_id igual que revocar_token_api_por_id, mismo
    motivo (que no se pueda borrar el token de otro adivinando el valor)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM dispositivos_push WHERE fcm_token = ? AND usuario_id = ?", (fcm_token, usuario_id))
        conn.commit()
    finally:
        conn.close()


def tokens_push_de_usuario(usuario_id: int) -> list[str]:
    conn = get_connection()
    try:
        filas = conn.execute("SELECT fcm_token FROM dispositivos_push WHERE usuario_id = ?", (usuario_id,)).fetchall()
        return [f["fcm_token"] for f in filas]
    finally:
        conn.close()


def eliminar_tokens_push(tokens: list[str]) -> None:
    """Limpieza cuando app/push.py detecta que FCM ha rechazado un token
    (desinstalado, expirado) -- se borra en vez de reintentar para
    siempre."""
    if not tokens:
        return
    conn = get_connection()
    try:
        marcadores = ",".join("?" for _ in tokens)
        conn.execute(f"DELETE FROM dispositivos_push WHERE fcm_token IN ({marcadores})", tokens)
        conn.commit()
    finally:
        conn.close()


# --- Centro de notificaciones (app/notificaciones.py) -----------------------

def crear_notificacion(usuario_id: int, tipo: str, titulo: str, cuerpo: str | None, url: str | None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notificaciones (usuario_id, tipo, titulo, cuerpo, url, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, tipo, titulo, cuerpo, url, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_notificaciones(usuario_id: int, limite: int = 10) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notificaciones WHERE usuario_id = ? ORDER BY creado_en DESC LIMIT ?",
            (usuario_id, limite),
        ).fetchall()
    finally:
        conn.close()


def contar_notificaciones_no_leidas(usuario_id: int) -> int:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id = ? AND leido_en IS NULL", (usuario_id,),
        ).fetchone()
        return fila["n"]
    finally:
        conn.close()


def marcar_notificaciones_leidas(usuario_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notificaciones SET leido_en = ? WHERE usuario_id = ? AND leido_en IS NULL",
            (now_iso(), usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_notificacion(usuario_id: int, notificacion_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM notificaciones WHERE id = ? AND usuario_id = ?",
            (notificacion_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_todas_notificaciones(usuario_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notificaciones WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


# --- Log de auditoría del backoffice (app/rutas_backoffice.py) -------------

def registrar_auditoria(usuario_id: int | None, accion: str, detalle: str | None = None) -> None:
    """Nunca debe romper la acción que audita -- quien llama (rutas_backoffice.py)
    la envuelve en su propio try/except best-effort, mismo criterio que el
    resto de efectos secundarios "de segunda fila" del proyecto (eventos,
    notificaciones)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO auditoria_backoffice (usuario_id, accion, detalle, creado_en) VALUES (?, ?, ?, ?)",
            (usuario_id, accion, detalle, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def listar_auditoria_backoffice(limite: int = 200) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT a.*, u.email AS usuario_email
               FROM auditoria_backoffice a LEFT JOIN usuarios u ON u.id = a.usuario_id
               ORDER BY a.id DESC LIMIT ?""",
            (limite,),
        ).fetchall()
    finally:
        conn.close()


# --- Exportación de datos de un tenant (GDPR, solo lectura) -----------------
#
# MVP de "derecho de acceso": un único JSON con metadatos + enlaces de
# descarga -- deliberadamente SIN incrustar el contenido de documentos/
# adjuntos (BLOBs, potencialmente grandes y ya descargables uno a uno
# desde sus propios endpoints existentes). Purga/"derecho al olvido" NO
# está cubierto aquí -- un borrado real es mucho más delicado y se
# diseñaría aparte si hiciera falta. `SELECT *` se evita a propósito en
# `tenants`/`usuarios`: ambas tablas tienen columnas sensibles (API keys
# de integraciones, hash de contraseña) que nunca deben salir en un
# export -- se listan las columnas exportables explícitamente.

def exportar_datos_tenant(tenant_id: int) -> dict:
    tenant = obtener_tenant(tenant_id)
    if tenant is None:
        raise ValueError(f"No existe el tenant #{tenant_id}.")
    usuarios_ids = usuarios_de_tenant(tenant_id)
    conn = get_connection()
    try:
        usuarios = []
        if usuarios_ids:
            marcadores_usuarios = ",".join("?" * len(usuarios_ids))
            usuarios = [
                dict(u) for u in conn.execute(
                    f"SELECT id, email, rol, creado_en FROM usuarios WHERE id IN ({marcadores_usuarios})",
                    usuarios_ids,
                ).fetchall()
            ]

        clientes_fiscales = [
            dict(c) for c in conn.execute(
                "SELECT * FROM clientes_fiscales WHERE tenant_id = ?", (tenant_id,)
            ).fetchall()
        ]

        vencimientos_fiscales = []
        for v in conn.execute("SELECT * FROM vencimientos_fiscales WHERE tenant_id = ?", (tenant_id,)).fetchall():
            v = dict(v)
            v["documentos"] = [
                {**dict(d), "url_descarga": f"/fiscal/vencimientos/{v['id']}/documentos/{d['id']}"}
                for d in conn.execute(
                    "SELECT id, nombre_archivo, tipo_mime, tamano_bytes, creado_en "
                    "FROM vencimientos_fiscales_documentos WHERE vencimiento_id = ?",
                    (v["id"],),
                ).fetchall()
            ]
            v["mensajes"] = [
                dict(m) for m in conn.execute(
                    "SELECT autor, usuario_id, texto, creado_en, leido_en "
                    "FROM vencimientos_fiscales_mensajes WHERE vencimiento_id = ?",
                    (v["id"],),
                ).fetchall()
            ]
            vencimientos_fiscales.append(v)

        tareas, notas, tiquets, correos = [], [], [], []
        if usuarios_ids:
            marcadores = ",".join("?" * len(usuarios_ids))
            tareas = [
                dict(t) for t in conn.execute(
                    f"SELECT id, usuario_id, nombre, tipo, estado, inicio_en, fin_en, duracion_segundos "
                    f"FROM tareas WHERE usuario_id IN ({marcadores}) AND papelera_en IS NULL",
                    usuarios_ids,
                ).fetchall()
            ]
            notas = [
                dict(n) for n in conn.execute(
                    f"SELECT id, usuario_id, texto, creada_en FROM notas "
                    f"WHERE usuario_id IN ({marcadores}) AND papelera_en IS NULL",
                    usuarios_ids,
                ).fetchall()
            ]
            tiquets = [
                dict(t) for t in conn.execute(
                    f"SELECT id, usuario_id, tipo, titulo, descripcion, estado, prioridad, "
                    f"usuario_asignado_id, creado_en FROM tiquets WHERE usuario_id IN ({marcadores})",
                    usuarios_ids,
                ).fetchall()
            ]
            correos = [
                dict(c) for c in conn.execute(
                    f"""SELECT m.id, m.asunto, m.remitente, m.destinatarios, m.fecha, cu.usuario_id
                        FROM correo_mensajes m JOIN correo_cuentas cu ON cu.id = m.cuenta_id
                        WHERE cu.usuario_id IN ({marcadores})""",
                    usuarios_ids,
                ).fetchall()
            ]

        tareas_lista, comentarios_tareas, notas_internas_correo, asignaciones_correo = [], [], [], []
        fichajes = [
            dict(f) for f in conn.execute(
                "SELECT id, usuario_id, tipo, marca_tiempo, origen, nota, corrige_a, creado_por, creado_en "
                "FROM fichajes WHERE tenant_id = ? ORDER BY marca_tiempo", (tenant_id,),
            ).fetchall()
        ]
        if usuarios_ids:
            marcadores = ",".join("?" * len(usuarios_ids))
            tareas_lista = [
                dict(t) for t in conn.execute(
                    f"""SELECT id, usuario_id, asunto, cuerpo, estado, prioridad, fecha_vencimiento, fecha_completada,
                               asignada_a, cliente_fiscal_id, creada_en
                        FROM tareas_outlook WHERE usuario_id IN ({marcadores}) AND papelera_en IS NULL""",
                    usuarios_ids,
                ).fetchall()
            ]
            if tareas_lista:
                ids_tareas = [t["id"] for t in tareas_lista]
                comentarios_tareas = [
                    dict(c) for c in conn.execute(
                        f"SELECT tarea_id, usuario_id, texto, creado_en FROM tarea_comentarios "
                        f"WHERE tarea_id IN ({','.join('?' * len(ids_tareas))})", ids_tareas,
                    ).fetchall()
                ]
            notas_internas_correo = [
                dict(n) for n in conn.execute(
                    f"SELECT mensaje_id, usuario_id, texto, creado_en FROM correo_notas_internas WHERE usuario_id IN ({marcadores})",
                    usuarios_ids,
                ).fetchall()
            ]
            asignaciones_correo = [
                dict(a) for a in conn.execute(
                    f"SELECT mensaje_id, asignado_a, asignado_por, estado, actualizado_en FROM correo_equipo "
                    f"WHERE asignado_a IN ({marcadores}) OR asignado_por IN ({marcadores})",
                    usuarios_ids + usuarios_ids,
                ).fetchall()
            ]
        return {
            "tenant": {"id": tenant["id"], "nombre": tenant["nombre"], "creado_en": tenant["creado_en"]},
            "generado_en": now_iso(),
            "usuarios": usuarios,
            "clientes_fiscales": clientes_fiscales,
            "vencimientos_fiscales": vencimientos_fiscales,
            "tareas": tareas,
            "tareas_lista": tareas_lista,
            "comentarios_tareas": comentarios_tareas,
            "notas": notas,
            "tiquets": tiquets,
            "correos": correos,
            "correo_equipo_asignaciones": asignaciones_correo,
            "correo_equipo_notas_internas": notas_internas_correo,
            "fichajes": fichajes,
        }
    finally:
        conn.close()


# --- Webhooks (ver app/eventos.py) --------------------------------------

_MAX_ENTREGAS_POR_WEBHOOK = 50


def crear_webhook(usuario_id: int, tenant_id: int | None, url: str, eventos: list[str]) -> dict:
    """`eventos` es una lista de nombres (ver app/eventos.py:EVENTOS) —
    se guarda como JSON, no una tabla aparte: no hace falta consultarlos
    por separado, siempre se leen todos juntos para un webhook dado."""
    secreto = secrets.token_urlsafe(32)
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO webhooks (tenant_id, usuario_id, url, eventos, secreto, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, usuario_id, url, json.dumps(eventos), secreto, now_iso()),
        )
        conn.commit()
        return dict(obtener_webhook(cursor.lastrowid))
    finally:
        conn.close()


def obtener_webhook(webhook_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
    finally:
        conn.close()


def listar_webhooks(tenant_id: int | None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        if tenant_id is None:
            return conn.execute(
                "SELECT * FROM webhooks WHERE tenant_id IS NULL ORDER BY creado_en DESC"
            ).fetchall()
        return conn.execute(
            "SELECT * FROM webhooks WHERE tenant_id = ? ORDER BY creado_en DESC", (tenant_id,)
        ).fetchall()
    finally:
        conn.close()


def listar_todos_los_webhooks() -> dict[int | None, list[sqlite3.Row]]:
    """Igual que llamar a listar_webhooks() para None + cada tenant, pero en
    una sola consulta -- usado en el backoffice, que antes hacía una
    consulta por tenant listado."""
    conn = get_connection()
    try:
        filas = conn.execute("SELECT * FROM webhooks ORDER BY tenant_id IS NOT NULL, tenant_id, creado_en DESC").fetchall()
        resultado: dict[int | None, list[sqlite3.Row]] = {}
        for w in filas:
            resultado.setdefault(w["tenant_id"], []).append(w)
        return resultado
    finally:
        conn.close()


def borrar_webhook(webhook_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM webhooks_entregas WHERE webhook_id = ?", (webhook_id,))
        conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
        conn.commit()
    finally:
        conn.close()


def webhooks_para_evento(evento: str, tenant_id: int | None) -> list[sqlite3.Row]:
    """Webhooks activos de este tenant (o del ámbito local si `tenant_id`
    es None) suscritos a `evento` — el filtro por evento se hace en
    Python (sobre `eventos` como JSON), no en SQL: la tabla no está
    pensada para volúmenes altos de webhooks por tenant."""
    candidatos = listar_webhooks(tenant_id)
    return [w for w in candidatos if w["activo"] and evento in json.loads(w["eventos"])]


def registrar_entrega_webhook(
    webhook_id: int, evento: str, estado_http: int | None, intento_num: int, error: str | None = None
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO webhooks_entregas (webhook_id, evento, estado_http, intento_num, entregado_en, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (webhook_id, evento, estado_http, intento_num, now_iso(), error),
        )
        # Poda: solo las últimas _MAX_ENTREGAS_POR_WEBHOOK por webhook —
        # el log de entregas es para depurar, no un histórico permanente.
        conn.execute(
            "DELETE FROM webhooks_entregas WHERE webhook_id = ? AND id NOT IN ("
            "  SELECT id FROM webhooks_entregas WHERE webhook_id = ? "
            "  ORDER BY id DESC LIMIT ?"
            ")",
            (webhook_id, webhook_id, _MAX_ENTREGAS_POR_WEBHOOK),
        )
        conn.commit()
    finally:
        conn.close()


def entregas_de_webhook(webhook_id: int, limite: int = 20) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM webhooks_entregas WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
            (webhook_id, limite),
        ).fetchall()
    finally:
        conn.close()


def entregas_de_webhooks(webhook_ids: list[int], limite: int = 5) -> dict[int, list[sqlite3.Row]]:
    """Igual que entregas_de_webhook() pero para varios webhooks a la vez
    (una consulta con ventana en vez de una por webhook) -- usado en el
    backoffice, que antes hacía una llamada por webhook listado."""
    if not webhook_ids:
        return {}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(webhook_ids))
        filas = conn.execute(
            f"""SELECT id, webhook_id, evento, estado_http, intento_num, entregado_en, error FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY webhook_id ORDER BY id DESC) AS _orden
                    FROM webhooks_entregas WHERE webhook_id IN ({marcas})
                ) WHERE _orden <= ?""",
            [*webhook_ids, limite],
        ).fetchall()
        resultado: dict[int, list[sqlite3.Row]] = {wid: [] for wid in webhook_ids}
        for f in filas:
            resultado[f["webhook_id"]].append(f)
        return resultado
    finally:
        conn.close()


# --- Categorías --------------------------------------------------------

def crear_categoria(usuario_id: int, nombre: str, color: str | None = None, icono: str | None = None) -> int:
    """Crea un proyecto, o reutiliza uno existente del MISMO usuario con el
    mismo nombre.

    `nombre` tiene una restricción UNIQUE por (usuario_id, nombre) en la
    tabla, y esa restricción no distingue entre proyectos activos y en la
    papelera — así que sin este chequeo, crear un proyecto con el mismo
    nombre que uno propio ya borrado (pero todavía en la papelera)
    reventaría con un IntegrityError. Si el que existe está en la
    papelera, se restaura en vez de fallar.

    El filtro `usuario_id = ?` de aquí abajo es imprescindible: sin él,
    dos usuarios distintos con un proyecto de igual nombre acababan
    compartiendo la misma fila sin saberlo (bug real, corregido en la
    revisión de lógica — ver también _migrar_categorias_unique_por_usuario).
    """
    nombre = nombre.strip()
    conn = get_connection()
    try:
        existente = conn.execute(
            "SELECT id, papelera_en FROM categorias WHERE nombre = ? AND usuario_id = ?", (nombre, usuario_id)
        ).fetchone()
        if existente is not None:
            if existente["papelera_en"] is not None:
                conn.execute(
                    "UPDATE categorias SET papelera_en = NULL WHERE id = ?", (existente["id"],)
                )
                conn.commit()
            return existente["id"]

        siguiente_orden = conn.execute(
            "SELECT COALESCE(MAX(orden), -1) + 1 FROM categorias WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO categorias (usuario_id, nombre, color, icono, creada_en, orden) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, nombre, color, icono, now_iso(), siguiente_orden),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL ORDER BY orden, nombre",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def _categoria_id_propio(conn: sqlite3.Connection, usuario_id: int, categoria_id: int | None) -> int | None:
    """Defensa en profundidad: ningún punto que recibe un categoria_id ya
    numérico (formulario manipulado a mano, o la tool de MCP cuando se le
    pasa el id directamente en vez del nombre) comprobaba que esa
    categoría fuera de verdad del usuario que la usa -- con la UNIQUE
    global de antes eso ya no hacía falta que colisionara por nombre
    para pasar desapercibido (revisión de lógica). Si no es suya, se
    trata como si no se hubiera indicado ninguna (mismo criterio
    permisivo que el resto de validaciones de esta app: se degrada en
    silencio, no revienta la petición entera)."""
    if categoria_id is None:
        return None
    fila = conn.execute(
        "SELECT 1 FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
    ).fetchone()
    if fila is not None:
        return categoria_id
    # También un proyecto compartido del despacho en el que se puede colaborar.
    return categoria_id if _rol_en_proyecto(conn, usuario_id, categoria_id) == "colabora" else None


def mover_categoria(usuario_id: int, categoria_id: int, direccion: str) -> None:
    """Reordena un proyecto un puesto arriba o abajo (`direccion`: 'arriba'/'abajo')."""
    conn = get_connection()
    try:
        activas = conn.execute(
            "SELECT id, orden FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL ORDER BY orden, nombre",
            (usuario_id,),
        ).fetchall()
        ids = [f["id"] for f in activas]
        if categoria_id not in ids:
            return
        idx = ids.index(categoria_id)
        vecino_idx = idx - 1 if direccion == "arriba" else idx + 1
        if vecino_idx < 0 or vecino_idx >= len(ids):
            return
        conn.execute(
            "UPDATE categorias SET orden = ? WHERE id = ?", (activas[vecino_idx]["orden"], categoria_id)
        )
        conn.execute(
            "UPDATE categorias SET orden = ? WHERE id = ?", (activas[idx]["orden"], ids[vecino_idx])
        )
        conn.commit()
    finally:
        conn.close()


def reordenar_categorias(usuario_id: int, orden_ids: list[int]) -> None:
    """Reescribe `orden` según la lista completa recibida (0, 1, 2...), para
    el arrastrar-y-soltar de la barra lateral — a diferencia de
    `mover_categoria`, que mueve un solo puesto. Los ids que no existan (o no
    estén activos, o no sean del usuario) se ignoran sin fallar; los proyectos
    activos que falten en la lista conservan su `orden` actual, detrás de
    los que sí se han movido."""
    conn = get_connection()
    try:
        activos = {
            f["id"] for f in conn.execute(
                "SELECT id FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL", (usuario_id,)
            )
        }
        siguiente = 0
        for categoria_id in orden_ids:
            if categoria_id in activos:
                conn.execute("UPDATE categorias SET orden = ? WHERE id = ?", (siguiente, categoria_id))
                siguiente += 1
        conn.commit()
    finally:
        conn.close()


def alternar_favorito_categoria(usuario_id: int, categoria_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET favorito = 1 - favorito WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_categoria(usuario_id: int, categoria_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (categoria_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def renombrar_categoria(usuario_id: int, categoria_id: int, nombre: str, color: str | None = None, icono: str | None = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET nombre = ?, color = ?, icono = ? WHERE id = ? AND usuario_id = ?",
            (nombre.strip(), color, icono, categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_categoria(usuario_id: int, categoria_id: int) -> None:
    """Manda un proyecto (y todo lo que contiene) a la papelera. No borra nada de
    verdad — se puede restaurar, o purgar definitivamente desde la papelera."""
    conn = get_connection()
    try:
        ahora = _marca_papelera()
        conn.execute(
            "UPDATE categorias SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (ahora, categoria_id, usuario_id),
        )
        conn.execute(
            "UPDATE tareas SET papelera_en = ? WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id, usuario_id),
        )
        conn.execute(
            "UPDATE notas SET papelera_en = ? WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_categoria(usuario_id: int, categoria_id: int) -> None:
    """Saca un proyecto de la papelera, junto con lo que se mandó a la papelera
    a la vez que él (no restaura notas/tareas que ya estaban en la papelera
    por separado antes de borrar el proyecto)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT papelera_en FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone()
        if fila is None or fila["papelera_en"] is None:
            return
        marca = fila["papelera_en"]
        conn.execute("UPDATE categorias SET papelera_en = NULL WHERE id = ?", (categoria_id,))
        conn.execute(
            "UPDATE tareas SET papelera_en = NULL WHERE categoria_id = ? AND papelera_en = ?",
            (categoria_id, marca),
        )
        conn.execute(
            "UPDATE notas SET papelera_en = NULL WHERE categoria_id = ? AND papelera_en = ?",
            (categoria_id, marca),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_categoria_definitivamente(usuario_id: int, categoria_id: int) -> None:
    """Borra un proyecto y todo lo que contiene de verdad (sin pasar por la
    papelera). Lo usa el botón "Eliminar definitivamente" y la purga
    automática de la papelera."""
    conn = get_connection()
    try:
        tarea_ids = [
            row["id"] for row in conn.execute(
                "SELECT id FROM tareas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id)
            ).fetchall()
        ]
        if tarea_ids:
            marcas = ",".join("?" * len(tarea_ids))
            conn.execute(f"DELETE FROM pausas WHERE tarea_id IN ({marcas})", tarea_ids)
            conn.execute(f"DELETE FROM notas WHERE tarea_id IN ({marcas})", tarea_ids)
        conn.execute("DELETE FROM notas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.execute("DELETE FROM tareas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.execute("DELETE FROM plantillas WHERE categoria_id = ?", (categoria_id,))
        conn.execute("DELETE FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def contar_entradas_hoy_por_usuario(usuario_id: int) -> dict[int, int]:
    """Cuenta las entradas (notas + tareas) de hoy por proyecto, para todos los
    proyectos del usuario a la vez (2 consultas GROUP BY en vez de una por
    proyecto) -- usado en el dashboard."""
    conn = get_connection()
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        manana = _fecha_exclusiva(hoy)
        resultado: dict[int, int] = {}
        for fila in conn.execute(
            "SELECT categoria_id, COUNT(*) AS n FROM notas WHERE usuario_id = ? AND papelera_en IS NULL AND creada_en >= ? AND creada_en < ? AND categoria_id IS NOT NULL GROUP BY categoria_id",
            (usuario_id, hoy, manana),
        ):
            resultado[fila["categoria_id"]] = resultado.get(fila["categoria_id"], 0) + fila["n"]
        for fila in conn.execute(
            "SELECT categoria_id, COUNT(*) AS n FROM tareas WHERE usuario_id = ? AND papelera_en IS NULL AND inicio_en >= ? AND inicio_en < ? AND categoria_id IS NOT NULL GROUP BY categoria_id",
            (usuario_id, hoy, manana),
        ):
            resultado[fila["categoria_id"]] = resultado.get(fila["categoria_id"], 0) + fila["n"]
        return resultado
    finally:
        conn.close()


# --- Tareas / eventos ---------------------------------------------------

def crear_tarea(usuario_id: int, nombre: str, categoria_id: int, tipo: str, tarea_outlook_id: int | None = None) -> int:
    conn = get_connection()
    try:
        # categoria_id es NOT NULL en esta tabla (a diferencia de notas/
        # tareas_outlook, aquí el proyecto es obligatorio) -- así que si no es
        # del usuario no se puede degradar a None como en el resto, hay
        # que rechazar la petición entera (defensa en profundidad: en uso
        # normal el <select> del formulario ya solo ofrece proyectos propios).
        if _categoria_id_propio(conn, usuario_id, categoria_id) is None:
            raise ValueError(f"La categoría/proyecto {categoria_id} no existe o no es tuya.")
        ahora = now_iso()
        if tipo == "instantanea":
            cur = conn.execute(
                """INSERT INTO tareas
                   (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
                   VALUES (?, ?, ?, 'instantanea', 'finalizada', ?, NULL, NULL)""",
                (usuario_id, nombre.strip(), categoria_id, ahora),
            )
        else:
            cur = conn.execute(
                """INSERT INTO tareas
                   (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos, tarea_outlook_id)
                   VALUES (?, ?, ?, 'duracion', 'en_curso', ?, NULL, NULL, ?)""",
                (usuario_id, nombre.strip(), categoria_id, ahora, tarea_outlook_id),
            )
        conn.commit()
        tarea_id = cur.lastrowid
    finally:
        conn.close()
    _reindexar_tarea(usuario_id, tarea_id)
    return tarea_id


def _reindexar_tarea(usuario_id: int, tarea_id: int) -> None:
    """Mismo criterio que _reindexar_nota (ver más arriba) — falla en
    silencio, es una mejora de UX, no debe romper el registro de
    actividad en sí."""
    from . import busqueda
    try:
        tarea = obtener_tarea(usuario_id, tarea_id)
        if tarea is not None:
            busqueda.indexar_tarea(dict(tarea))
    except busqueda.ErrorBusqueda:
        pass


def _quitar_tarea_del_indice(tarea_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("tarea", tarea_id)
    except busqueda.ErrorBusqueda:
        pass


def importar_tarea(
    usuario_id: int,
    nombre: str,
    categoria_id: int,
    tipo: str,
    inicio_en: str,
    fin_en: str | None,
    duracion_segundos: int | None,
) -> int:
    """Inserta una tarea/evento ya finalizado con timestamps explícitos
    (usado por la importación de datos exportados previamente). A
    diferencia de crear_tarea(), no usa la hora actual ni deja la tarea en
    curso — todo lo que se importa entra como histórico ya cerrado."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tareas
               (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
               VALUES (?, ?, ?, ?, 'finalizada', ?, ?, ?)""",
            (usuario_id, nombre.strip(), categoria_id, tipo, inicio_en, fin_en, duracion_segundos),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def hubo_actividad_reciente(usuario_id: int, minutos: int) -> bool:
    """True si se ha creado alguna nota o tarea en los últimos `minutos`."""
    conn = get_connection()
    try:
        limite = (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")
        n = conn.execute(
            "SELECT COUNT(*) FROM notas WHERE usuario_id = ? AND creada_en >= ?", (usuario_id, limite)
        ).fetchone()[0]
        t = conn.execute(
            "SELECT COUNT(*) FROM tareas WHERE usuario_id = ? AND inicio_en >= ?", (usuario_id, limite)
        ).fetchone()[0]
        return (n + t) > 0
    finally:
        conn.close()


def _segundos_pausados_cerrados(conn: sqlite3.Connection, tarea_id: int) -> int:
    """Suma la duración de las pausas ya cerradas (reanudadas) de una tarea."""
    total = 0
    for r in conn.execute(
        "SELECT pausada_en, reanudada_en FROM pausas WHERE tarea_id = ? AND reanudada_en IS NOT NULL",
        (tarea_id,),
    ):
        total += int(
            (datetime.fromisoformat(r["reanudada_en"]) - datetime.fromisoformat(r["pausada_en"])).total_seconds()
        )
    return total


def pausar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'pausada' WHERE id = ? AND usuario_id = ? AND tipo = 'duracion' AND estado = 'en_curso'",
            (tarea_id, usuario_id),
        )
        if cur.rowcount:
            conn.execute(
                "INSERT INTO pausas (tarea_id, pausada_en) VALUES (?, ?)",
                (tarea_id, now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def reanudar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'en_curso' WHERE id = ? AND usuario_id = ? AND estado = 'pausada'",
            (tarea_id, usuario_id),
        )
        if cur.rowcount:
            conn.execute(
                """UPDATE pausas SET reanudada_en = ?
                   WHERE tarea_id = ? AND reanudada_en IS NULL""",
                (now_iso(), tarea_id),
            )
        conn.commit()
    finally:
        conn.close()


def finalizar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT inicio_en, estado, nombre FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        ).fetchone()
        if row is None:
            return
        fin = now_iso()
        if row["estado"] == "pausada":
            conn.execute(
                "UPDATE pausas SET reanudada_en = ? WHERE tarea_id = ? AND reanudada_en IS NULL",
                (fin, tarea_id),
            )
        inicio = datetime.fromisoformat(row["inicio_en"])
        segundos_pausados = _segundos_pausados_cerrados(conn, tarea_id)
        duracion = max(int((datetime.fromisoformat(fin) - inicio).total_seconds()) - segundos_pausados, 0)
        conn.execute(
            "UPDATE tareas SET estado = 'finalizada', fin_en = ?, duracion_segundos = ? WHERE id = ?",
            (fin, duracion, tarea_id),
        )
        conn.commit()
    finally:
        conn.close()
    _emitir_evento_tarea_finalizada(usuario_id, tarea_id, row["nombre"], duracion)


def _emitir_evento(usuario_id: int, evento: str, payload: dict) -> None:
    """Webhook saliente del tenant del usuario (ver app/eventos.py). Un fallo
    al emitir nunca afecta a la operación ya hecha."""
    from . import eventos
    try:
        tenant = tenant_de_usuario(usuario_id)
        eventos.emitir(evento, tenant["id"] if tenant else None, payload)
    except Exception:
        pass


def _emitir_evento_tarea_finalizada(usuario_id: int, tarea_id: int, nombre: str, duracion_segundos: int) -> None:
    """Segunda excepción documentada (junto a busqueda) a "db.py no
    depende de otros app/*.py": un webhook es, por naturaleza, un
    efecto secundario de la escritura, no una operación de negocio más
    — mismo criterio ya aplicado a la indexación de búsqueda. Import
    perezoso para evitar cualquier ciclo, aunque hoy app/eventos.py
    solo importa db.py, no al revés."""
    from . import eventos
    try:
        tenant = tenant_de_usuario(usuario_id)
        eventos.emitir(
            "tarea.finalizada", tenant["id"] if tenant else None,
            {"tarea_id": tarea_id, "nombre": nombre, "duracion_segundos": duracion_segundos},
        )
    except Exception:
        pass  # un fallo al emitir el evento no debe afectar a la tarea ya finalizada


def tareas_activas(usuario_id: int) -> list[dict]:
    """Tareas con duración en curso o en pausa, con el tiempo ya pausado calculado."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.usuario_id = ? AND t.tipo = 'duracion' AND t.estado IN ('en_curso', 'pausada')
                 AND t.papelera_en IS NULL
               ORDER BY t.inicio_en""",
            (usuario_id,),
        ).fetchall()
        resultado = []
        for f in filas:
            d = dict(f)
            d["segundos_pausados"] = _segundos_pausados_cerrados(conn, f["id"])
            if f["estado"] == "pausada":
                pausa_abierta = conn.execute(
                    "SELECT pausada_en FROM pausas WHERE tarea_id = ? AND reanudada_en IS NULL",
                    (f["id"],),
                ).fetchone()
                inicio = datetime.fromisoformat(f["inicio_en"])
                pausada_en = datetime.fromisoformat(pausa_abierta["pausada_en"])
                d["segundos_trabajados_congelado"] = max(
                    int((pausada_en - inicio).total_seconds()) - d["segundos_pausados"], 0
                )
            resultado.append(d)
        return resultado
    finally:
        conn.close()


def obtener_tarea(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND t.usuario_id = ? AND t.papelera_en IS NULL""",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def editar_tarea(usuario_id: int, tarea_id: int, nombre: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET nombre = ? WHERE id = ? AND usuario_id = ?",
            (nombre.strip(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_tarea(usuario_id, tarea_id)


def editar_tiempos_tarea(usuario_id: int, tarea_id: int, inicio_en: str, fin_en: str | None = None) -> str | None:
    """Ajusta manualmente el inicio (y el fin, si la tarea ya está finalizada).

    Devuelve un mensaje de error legible si la entrada no es válida, o None si todo fue bien.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT tipo, estado, fin_en FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        ).fetchone()
        if row is None:
            return "La tarea ya no existe."
        try:
            inicio = datetime.fromisoformat(inicio_en)
        except ValueError:
            return "La fecha/hora de inicio no es válida."

        if row["estado"] == "finalizada" and row["tipo"] == "duracion":
            if not fin_en:
                return "Falta la fecha/hora de fin."
            try:
                fin = datetime.fromisoformat(fin_en)
            except ValueError:
                return "La fecha/hora de fin no es válida."
            if fin <= inicio:
                return "El fin debe ser posterior al inicio."
            segundos_pausados = _segundos_pausados_cerrados(conn, tarea_id)
            duracion = max(int((fin - inicio).total_seconds()) - segundos_pausados, 0)
            conn.execute(
                "UPDATE tareas SET inicio_en = ?, fin_en = ?, duracion_segundos = ? WHERE id = ?",
                (inicio.isoformat(timespec="seconds"), fin.isoformat(timespec="seconds"), duracion, tarea_id),
            )
        else:
            if inicio > datetime.now():
                return "El inicio no puede ser en el futuro."
            conn.execute(
                "UPDATE tareas SET inicio_en = ? WHERE id = ?",
                (inicio.isoformat(timespec="seconds"), tarea_id),
            )
        conn.commit()
        return None
    finally:
        conn.close()


def eliminar_tarea(usuario_id: int, tarea_id: int) -> None:
    """Manda una tarea/evento a la papelera (no la borra de verdad)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_marca_papelera(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    _quitar_tarea_del_indice(tarea_id)


def restaurar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_tarea(usuario_id, tarea_id)


def eliminar_tarea_definitivamente(usuario_id: int, tarea_id: int) -> None:
    """Borra una tarea/evento y sus pausas y notas asociadas de verdad."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM pausas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM notas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id))
        conn.commit()
    finally:
        conn.close()
    _quitar_tarea_del_indice(tarea_id)


# --- Notas ---------------------------------------------------------------

def crear_nota(
    usuario_id: int, texto: str, categoria_id: int | None = None, tarea_id: int | None = None,
    creada_en: str | None = None, cliente_uuid: str | None = None,
    titulo: str | None = None, fijada: bool = False, cliente_fiscal_id: int | None = None,
    tarea_outlook_id: int | None = None, mensaje_correo_id: int | None = None,
) -> int:
    """`creada_en`/`cliente_uuid`: igual que en `fichar()`, para la cola
    offline de la app móvil -- conservan la hora real de creación y evitan
    duplicar la nota si se reintenta la sincronización."""
    conn = get_connection()
    try:
        if cliente_uuid is not None:
            existente = conn.execute("SELECT id FROM notas WHERE cliente_uuid = ?", (cliente_uuid,)).fetchone()
            if existente is not None:
                return existente["id"]
        # Aquí categoria_id sí es opcional -- si no es del usuario, se
        # degrada a "sin proyecto" en vez de rechazar la nota entera (ver
        # _categoria_id_propio).
        categoria_id = _categoria_id_propio(conn, usuario_id, categoria_id)
        ahora = now_iso()
        if creada_en is not None and creada_en > ahora:
            raise ValueError("La fecha de creación de la nota no puede ser futura.")
        cur = conn.execute(
            """INSERT INTO notas (usuario_id, texto, categoria_id, tarea_id, creada_en, cliente_uuid,
                                  titulo, fijada, cliente_fiscal_id, tarea_outlook_id, mensaje_correo_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, texto.strip(), categoria_id, tarea_id, creada_en or ahora, cliente_uuid,
                _titulo_nota(titulo), 1 if fijada else 0,
                _cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id),
                _tarea_outlook_id_propia(conn, usuario_id, tarea_outlook_id),
                _mensaje_correo_id_propio(conn, usuario_id, mensaje_correo_id),
            ),
        )
        conn.commit()
        nota_id = cur.lastrowid
    finally:
        conn.close()
    _reindexar_nota(usuario_id, nota_id)
    _emitir_evento_nota_creada(usuario_id, nota_id, texto.strip())
    return nota_id


def _emitir_evento_nota_creada(usuario_id: int, nota_id: int, texto: str) -> None:
    """Solo al CREAR — editar una nota no vuelve a emitir el evento
    (ver _reindexar_nota, compartido entre crear/editar, que sí se
    ejecuta en ambos casos). Mismo criterio de import perezoso que
    _emitir_evento_tarea_finalizada."""
    from . import eventos
    try:
        tenant = tenant_de_usuario(usuario_id)
        eventos.emitir("nota.creada", tenant["id"] if tenant else None, {"nota_id": nota_id, "texto": texto})
    except Exception:
        pass


def _reindexar_nota(usuario_id: int, nota_id: int) -> None:
    """Reindexa una nota en el buscador unificado (ver app/busqueda.py)
    tras crearla/editarla — falla en silencio si el buscador no está
    configurado/caído, es una mejora de UX, no debe romper el registro
    de actividad en sí. Import perezoso a propósito: db.py no depende
    de ningún otro módulo de app/ como regla general, esta es la única
    excepción (indexar es, por naturaleza, un efecto secundario de cada
    escritura, no una operación de negocio más)."""
    from . import busqueda
    try:
        nota = obtener_nota(usuario_id, nota_id)
        if nota is not None:
            busqueda.indexar_nota(dict(nota))
    except busqueda.ErrorBusqueda:
        pass


def importar_nota(usuario_id: int, texto: str, categoria_id: int | None, creada_en: str, titulo: str | None = None) -> int:
    """Inserta una nota con un timestamp explícito (importación de datos exportados)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notas (usuario_id, texto, categoria_id, tarea_id, creada_en, titulo) VALUES (?, ?, ?, NULL, ?, ?)",
            (usuario_id, texto.strip(), categoria_id, creada_en, _titulo_nota(titulo)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_nota(usuario_id: int, nota_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT n.*, c.nombre AS categoria_nombre, cf.nombre AS cliente_fiscal_nombre
               FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
               LEFT JOIN clientes_fiscales cf ON cf.id = n.cliente_fiscal_id
               WHERE n.id = ? AND n.usuario_id = ? AND n.papelera_en IS NULL""",
            (nota_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def rol_en_nota(usuario_id: int, nota_id: int) -> str | None:
    """'dueno', 'colabora', 'observa' o None si no la ve."""
    conn = get_connection()
    try:
        n = conn.execute("SELECT usuario_id FROM notas WHERE id = ? AND papelera_en IS NULL", (nota_id,)).fetchone()
        if n is None:
            return None
        if n["usuario_id"] == usuario_id:
            return "dueno"
        p = conn.execute(
            "SELECT rol FROM notas_participantes WHERE nota_id = ? AND usuario_id = ?", (nota_id, usuario_id)
        ).fetchone()
        return p["rol"] if p else None
    finally:
        conn.close()


def obtener_nota_visible(usuario_id: int, nota_id: int) -> sqlite3.Row | None:
    """Como obtener_nota, pero también para quien la tiene compartida."""
    if rol_en_nota(usuario_id, nota_id) is None:
        return None
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT n.*, c.nombre AS categoria_nombre, cf.nombre AS cliente_fiscal_nombre,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS dueno_nombre
               FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
               LEFT JOIN clientes_fiscales cf ON cf.id = n.cliente_fiscal_id
               JOIN usuarios u ON u.id = n.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
               WHERE n.id = ? AND n.papelera_en IS NULL""",
            (nota_id,),
        ).fetchone()
    finally:
        conn.close()


def compartir_nota(usuario_id: int, nota_id: int, otro_id: int, rol: str = "colabora") -> bool:
    """El dueño comparte la nota con un compañero del mismo despacho (o cambia su rol)."""
    if rol not in ROLES_PARTICIPANTE:
        return False
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM notas WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (nota_id, usuario_id)
        ).fetchone() is None:
            return False
        destino = _companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        conn.execute(
            """INSERT INTO notas_participantes (nota_id, usuario_id, rol, compartida_en) VALUES (?, ?, ?, ?)
               ON CONFLICT(nota_id, usuario_id) DO UPDATE SET rol = excluded.rol""",
            (nota_id, destino, rol, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    _emitir_evento(usuario_id, "nota.compartida", {"nota_id": nota_id, "con": destino, "rol": rol})
    return True


def dejar_de_compartir_nota(usuario_id: int, nota_id: int, otro_id: int) -> bool:
    """El dueño quita a un participante; el propio participante puede salirse."""
    conn = get_connection()
    try:
        dueno = conn.execute("SELECT 1 FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)).fetchone()
        if not dueno and otro_id != usuario_id:
            return False
        cur = conn.execute("DELETE FROM notas_participantes WHERE nota_id = ? AND usuario_id = ?", (nota_id, otro_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def participantes_de_nota(nota_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT p.usuario_id, p.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
               FROM notas_participantes p JOIN usuarios u ON u.id = p.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
               WHERE p.nota_id = ? ORDER BY nombre""",
            (nota_id,),
        ).fetchall()
    finally:
        conn.close()


def contar_participantes_notas(nota_ids: list[int]) -> dict[int, int]:
    if not nota_ids:
        return {}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(nota_ids))
        return {
            f["nota_id"]: f["n"]
            for f in conn.execute(
                f"SELECT nota_id, COUNT(*) AS n FROM notas_participantes WHERE nota_id IN ({marcas}) GROUP BY nota_id", nota_ids
            )
        }
    finally:
        conn.close()


NOTA_TITULO_MAX_CARACTERES = 120
_SIN_CAMBIO = object()


def _titulo_nota(titulo: str | None) -> str | None:
    titulo = " ".join((titulo or "").split())[:NOTA_TITULO_MAX_CARACTERES]
    return titulo or None


def _tarea_outlook_id_propia(conn: sqlite3.Connection, usuario_id: int, tarea_id: int | None) -> int | None:
    if tarea_id is None:
        return None
    fila = conn.execute(
        "SELECT id FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
    ).fetchone()
    return fila["id"] if fila else None


def editar_nota(
    usuario_id: int, nota_id: int, texto: str, *, titulo=_SIN_CAMBIO, fijada=_SIN_CAMBIO,
    cliente_fiscal_id=_SIN_CAMBIO, tarea_outlook_id=_SIN_CAMBIO, mensaje_correo_id=_SIN_CAMBIO,
) -> None:
    """Actualiza el texto y, si se indican, el título, si está fijada y sus
    vínculos (cliente fiscal, tarea de la lista, correo). Lo no indicado no se toca.
    La edita su dueño o un colaborador; el colaborador solo cambia texto y título
    (fijar y los vínculos son del dueño)."""
    rol = rol_en_nota(usuario_id, nota_id)
    if rol not in ("dueno", "colabora"):
        return
    if rol == "colabora":
        fijada = cliente_fiscal_id = tarea_outlook_id = mensaje_correo_id = _SIN_CAMBIO
    conn = get_connection()
    try:
        dueno_id = conn.execute("SELECT usuario_id FROM notas WHERE id = ?", (nota_id,)).fetchone()["usuario_id"]
        cambios = {"texto": texto.strip()}
        if titulo is not _SIN_CAMBIO:
            cambios["titulo"] = _titulo_nota(titulo)
        if fijada is not _SIN_CAMBIO:
            cambios["fijada"] = 1 if fijada else 0
        if cliente_fiscal_id is not _SIN_CAMBIO:
            cambios["cliente_fiscal_id"] = _cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id)
        if tarea_outlook_id is not _SIN_CAMBIO:
            cambios["tarea_outlook_id"] = _tarea_outlook_id_propia(conn, usuario_id, tarea_outlook_id)
        if mensaje_correo_id is not _SIN_CAMBIO:
            cambios["mensaje_correo_id"] = _mensaje_correo_id_propio(conn, usuario_id, mensaje_correo_id)
        asignaciones = ", ".join(f"{c} = ?" for c in cambios)
        conn.execute(
            f"UPDATE notas SET {asignaciones} WHERE id = ?",
            [*cambios.values(), nota_id],
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_nota(dueno_id, nota_id)
    _emitir_evento(usuario_id, "nota.editada", {"nota_id": nota_id})


def alternar_fijada_nota(usuario_id: int, nota_id: int) -> bool:
    """Fija o desfija la nota. Devuelve False si no es del usuario."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE notas SET fijada = 1 - fijada WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (nota_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def listar_notas_fijadas(usuario_id: int, categoria_id: int | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        cond, params = ["n.usuario_id = ?", "n.fijada = 1", "n.papelera_en IS NULL"], [usuario_id]
        if categoria_id is not None:
            cond.append("n.categoria_id = ?"); params.append(categoria_id)
        return conn.execute(
            f"""SELECT n.*, c.nombre AS categoria_nombre, c.color AS categoria_color
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE {' AND '.join(cond)} ORDER BY n.creada_en DESC""",
            params,
        ).fetchall()
    finally:
        conn.close()


def listar_notas(
    usuario_id: int, categoria_id: int | None = None, texto: str | None = None, limite: int = 300,
    incluir_compartidas: bool = False, solo_compartidas: bool = False,
) -> list[sqlite3.Row]:
    """Notas del usuario para la pantalla Notas: las fijadas primero y luego
    las más recientes; filtro opcional por proyecto y por texto/título."""
    conn = get_connection()
    try:
        compartida = "n.id IN (SELECT nota_id FROM notas_participantes WHERE usuario_id = ?)"
        if solo_compartidas:
            cond, params = [compartida, "n.papelera_en IS NULL"], [usuario_id]
        elif incluir_compartidas:
            cond, params = [f"(n.usuario_id = ? OR {compartida})", "n.papelera_en IS NULL"], [usuario_id, usuario_id]
        else:
            cond, params = ["n.usuario_id = ?", "n.papelera_en IS NULL"], [usuario_id]
        if categoria_id is not None:
            cond.append("n.categoria_id = ?"); params.append(categoria_id)
        if texto:
            patron = "%" + texto.replace("%", r"\%").replace("_", r"\_") + "%"
            cond.append("(n.texto LIKE ? ESCAPE '\\' OR n.titulo LIKE ? ESCAPE '\\')"); params += [patron, patron]
        return conn.execute(
            f"""SELECT n.*, c.nombre AS categoria_nombre, c.color AS categoria_color,
                       COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS dueno_nombre
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                JOIN usuarios u ON u.id = n.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
                WHERE {' AND '.join(cond)}
                ORDER BY n.fijada DESC, n.creada_en DESC LIMIT ?""",
            params + [limite],
        ).fetchall()
    finally:
        conn.close()


# ---- Adjuntos de nota ---------------------------------------------------------

NOTAS_ADJUNTOS_MIME = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain", "text/csv",
}
NOTAS_ADJUNTOS_TAMANO_MAXIMO = 5 * 1024 * 1024
NOTAS_ADJUNTOS_MAXIMO_POR_NOTA = 5


def agregar_adjunto_nota(usuario_id: int, nota_id: int, nombre: str, tipo_mime: str, contenido: bytes) -> int:
    """Adjunta un fichero a una nota propia. Lanza ValueError con un mensaje
    para la persona usuaria si no procede (tipo, tamaño, límite, nota ajena)."""
    nombre = (nombre or "").replace("\\", "/").split("/")[-1].strip()[:200] or "adjunto"
    if tipo_mime not in NOTAS_ADJUNTOS_MIME:
        raise ValueError("Tipo de archivo no permitido: solo imágenes, PDF o texto.")
    if len(contenido) > NOTAS_ADJUNTOS_TAMANO_MAXIMO:
        raise ValueError("El archivo pesa demasiado (máximo 5 MB).")
    if not contenido:
        raise ValueError("El archivo está vacío.")
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM notas WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (nota_id, usuario_id)
        ).fetchone() is None:
            raise ValueError("La nota no existe.")
        if conn.execute("SELECT COUNT(*) FROM notas_adjuntos WHERE nota_id = ?", (nota_id,)).fetchone()[0] >= NOTAS_ADJUNTOS_MAXIMO_POR_NOTA:
            raise ValueError(f"Una nota admite como máximo {NOTAS_ADJUNTOS_MAXIMO_POR_NOTA} adjuntos.")
        cur = conn.execute(
            "INSERT INTO notas_adjuntos (nota_id, nombre, tipo_mime, tamano, contenido, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
            (nota_id, nombre, tipo_mime, len(contenido), contenido, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_adjuntos_nota(nota_id: int) -> list[sqlite3.Row]:
    """Sin el contenido (BLOB): solo lo necesario para listarlos."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, nota_id, nombre, tipo_mime, tamano, creado_en FROM notas_adjuntos WHERE nota_id = ? ORDER BY id",
            (nota_id,),
        ).fetchall()
    finally:
        conn.close()


def contar_adjuntos_notas(nota_ids: list[int]) -> dict[int, int]:
    if not nota_ids:
        return {}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(nota_ids))
        return {
            f["nota_id"]: f["n"]
            for f in conn.execute(f"SELECT nota_id, COUNT(*) AS n FROM notas_adjuntos WHERE nota_id IN ({marcas}) GROUP BY nota_id", nota_ids)
        }
    finally:
        conn.close()


def obtener_adjunto_nota(usuario_id: int, adjunto_id: int) -> sqlite3.Row | None:
    """Con contenido; si la nota es del usuario o está compartida con él."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT a.* FROM notas_adjuntos a JOIN notas n ON n.id = a.nota_id
               WHERE a.id = ? AND n.papelera_en IS NULL AND (n.usuario_id = ? OR n.id IN (
                     SELECT nota_id FROM notas_participantes WHERE usuario_id = ?))""",
            (adjunto_id, usuario_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def eliminar_adjunto_nota(usuario_id: int, adjunto_id: int) -> bool:
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM notas_adjuntos a JOIN notas n ON n.id = a.nota_id WHERE a.id = ? AND n.usuario_id = ?",
            (adjunto_id, usuario_id),
        ).fetchone() is None:
            return False
        conn.execute("DELETE FROM notas_adjuntos WHERE id = ?", (adjunto_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_nota(usuario_id: int, nota_id: int) -> None:
    """Manda una nota a la papelera (no la borra de verdad)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notas SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_marca_papelera(), nota_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    _quitar_nota_del_indice(nota_id)


def _quitar_nota_del_indice(nota_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("nota", nota_id)
    except busqueda.ErrorBusqueda:
        pass


def restaurar_nota(usuario_id: int, nota_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_nota(usuario_id, nota_id)


def eliminar_nota_definitivamente(usuario_id: int, nota_id: int) -> None:
    conn_p = get_connection()
    try:
        if conn_p.execute("SELECT 1 FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)).fetchone():
            conn_p.execute("DELETE FROM notas_participantes WHERE nota_id = ?", (nota_id,))
            conn_p.commit()
    finally:
        conn_p.close()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id))
        conn.commit()
    finally:
        conn.close()
    _quitar_nota_del_indice(nota_id)


# --- Histórico combinado ---------------------------------------------------

def historial(
    usuario_id: int,
    desde: str | None = None,
    hasta: str | None = None,
    categoria_id: int | None = None,
    texto: str | None = None,
    limite: int | None = None,
    offset: int = 0,
):
    """Devuelve notas y tareas combinadas, ordenadas cronológicamente descendente.

    desde/hasta: fechas 'YYYY-MM-DD' (inclusive).
    texto: si se indica, filtra por coincidencia parcial (insensible a mayúsculas).
    limite/offset: paginación (mismo estilo que db.listar_mensajes_correo) --
    si `limite` es None (por defecto) devuelve todo, sin paginar, para no
    romper a quien ya llama a esta función esperando el conjunto completo
    (export.py, el widget "hoy" del dashboard, etc.).
    """
    conn = get_connection()
    try:
        # El filtro de fecha se aplica DENTRO de cada rama (sobre la columna
        # de timestamp real, notas.creada_en / tareas.inicio_en) en vez de
        # sobre un alias calculado en la consulta exterior — así SQLite
        # puede usar los índices idx_notas_categoria_creada /
        # idx_tareas_categoria_inicio en vez de escanear ambas tablas
        # enteras antes de filtrar.
        hasta_excl = _fecha_exclusiva(hasta) if hasta else None

        cond_n = ["n.usuario_id = ?", "n.papelera_en IS NULL"]
        cond_t = ["t.usuario_id = ?", "t.papelera_en IS NULL"]
        params_n: list = [usuario_id]
        params_t: list = [usuario_id]
        if desde:
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
        if hasta_excl:
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
        if categoria_id:
            cond_n.append("n.categoria_id = ?"); params_n.append(categoria_id)
            cond_t.append("t.categoria_id = ?"); params_t.append(categoria_id)
        if texto:
            cond_n.append("(n.texto LIKE ? OR n.titulo LIKE ?)"); params_n.extend([f"%{texto}%", f"%{texto}%"])
            cond_t.append("t.nombre LIKE ?"); params_t.append(f"%{texto}%")

        query = f"""
            SELECT * FROM (
                SELECT
                    'nota' AS origen,
                    n.id AS id,
                    n.texto AS texto,
                    NULL AS tipo,
                    NULL AS estado,
                    n.creada_en AS timestamp,
                    NULL AS fin_en,
                    NULL AS duracion_segundos,
                    n.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color,
                    n.titulo AS titulo,
                    n.fijada AS fijada
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE {' AND '.join(cond_n)}

                UNION ALL

                SELECT
                    'tarea' AS origen,
                    t.id AS id,
                    t.nombre AS texto,
                    t.tipo AS tipo,
                    t.estado AS estado,
                    t.inicio_en AS timestamp,
                    t.fin_en AS fin_en,
                    t.duracion_segundos AS duracion_segundos,
                    t.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color,
                    NULL AS titulo,
                    0 AS fijada
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE {' AND '.join(cond_t)}
            )
            ORDER BY timestamp DESC
        """
        params = [*params_n, *params_t]
        if limite is not None:
            query += " LIMIT ? OFFSET ?"
            params += [limite, offset]
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def resumen_historial(usuario_id: int, desde=None, hasta=None, categoria_id=None, texto=None) -> dict:
    """Agregado del histórico para el filtro dado (panel "Resumen del
    periodo" de /historial): total de entradas, tiempo total registrado y
    reparto por proyecto. Reutiliza historial() sin paginar -- mismo criterio
    que export.py (construir_export), que ya trae el conjunto completo del
    filtro para generar el export; aquí solo se agrega en Python en vez de
    escribirse como columnas, porque el dataset por usuario es pequeño
    (nunca miles de filas) y así se evita duplicar la query UNION ALL de
    arriba con un segundo camino de SQL a mantener en paralelo.
    """
    filas = historial(usuario_id, desde=desde, hasta=hasta, categoria_id=categoria_id, texto=texto)
    total_segundos = sum(f["duracion_segundos"] or 0 for f in filas)
    por_menu: dict[str, dict] = {}
    for f in filas:
        nombre = f["categoria_nombre"] or "Sin proyecto"
        entrada = por_menu.setdefault(nombre, {"nombre": nombre, "color": f["categoria_color"] or "#7c8ba1", "entradas": 0})
        entrada["entradas"] += 1
    total_entradas = len(filas)
    for entrada in por_menu.values():
        entrada["porcentaje"] = round(entrada["entradas"] / total_entradas * 100) if total_entradas else 0
    return {
        "total_entradas": total_entradas,
        "total_segundos": total_segundos,
        "por_menu": sorted(por_menu.values(), key=lambda e: e["entradas"], reverse=True),
    }


# --- Estadísticas ----------------------------------------------------------

def estadisticas_por_categoria(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total (tareas finalizadas) y nº de entradas por categoría."""
    conn = get_connection()
    try:
        cond_t = ["t.usuario_id = ?", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        cond_ev = ["tt.usuario_id = ?", "tt.tipo = 'instantanea'", "tt.papelera_en IS NULL"]
        cond_n = ["n.usuario_id = ?", "n.papelera_en IS NULL"]
        params_t: list = [usuario_id]
        params_ev: list = [usuario_id]
        params_n: list = [usuario_id]
        hasta_excl = _fecha_exclusiva(hasta) if hasta else None
        if desde:
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
            cond_ev.append("tt.inicio_en >= ?"); params_ev.append(desde)
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
        if hasta_excl:
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
            cond_ev.append("tt.inicio_en < ?"); params_ev.append(hasta_excl)
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)

        filas = conn.execute(
            f"""SELECT c.id, c.nombre, c.color,
                   COALESCE((SELECT SUM(t.duracion_segundos) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS segundos_totales,
                   COALESCE((SELECT COUNT(*) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS num_tareas,
                   COALESCE((SELECT COUNT(*) FROM tareas tt
                             WHERE tt.categoria_id = c.id AND {' AND '.join(cond_ev)}), 0) AS num_eventos,
                   COALESCE((SELECT COUNT(*) FROM notas n
                             WHERE n.categoria_id = c.id AND {' AND '.join(cond_n)}), 0) AS num_notas
               FROM categorias c
               WHERE c.usuario_id = ?
               ORDER BY segundos_totales DESC, c.nombre""",
            [*params_t, *params_t, *params_ev, *params_n, usuario_id],
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def estadisticas_por_dia(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total en tareas con duración finalizadas, agrupado por día y categoría."""
    conn = get_connection()
    try:
        cond = ["t.usuario_id = ?", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        params: list = [usuario_id]
        if desde:
            cond.append("t.inicio_en >= ?"); params.append(desde)
        if hasta:
            cond.append("t.inicio_en < ?"); params.append(_fecha_exclusiva(hasta))
        where = " AND ".join(cond)
        filas = conn.execute(
            f"""SELECT substr(t.inicio_en,1,10) AS fecha, c.nombre AS categoria, c.color AS categoria_color,
                       SUM(t.duracion_segundos) AS segundos
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE {where}
                GROUP BY fecha, c.id
                ORDER BY fecha DESC, segundos DESC""",
            params,
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def estadisticas_equipo_por_usuario(
    tenant_id: int, desde: str | None = None, hasta: str | None = None,
) -> list[dict]:
    """Carga de trabajo por usuario de un tenant -- a diferencia de
    estadisticas_por_categoria(), no se puede reutilizar esa misma
    consulta ampliándola con un IN de usuarios: las categorías
    (`categorias.usuario_id`) son propias de cada persona, no
    compartidas por tenant, así que agregar "por categoría" mezclaría
    categorías de nombre distinto entre sí sin ningún criterio común.
    Aquí se agrega directamente por usuario (email), que sí es una
    dimensión compartida con sentido a nivel de equipo."""
    conn = get_connection()
    try:
        ids = usuarios_de_tenant(tenant_id)
        if not ids:
            return []
        marcadores = ",".join("?" * len(ids))
        cond_t = [f"t.usuario_id IN ({marcadores})", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        cond_n = [f"n.usuario_id IN ({marcadores})", "n.papelera_en IS NULL"]
        params_t: list = list(ids)
        params_n: list = list(ids)
        hasta_excl = _fecha_exclusiva(hasta) if hasta else None
        if desde:
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
        if hasta_excl:
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)

        filas = conn.execute(
            f"""SELECT u.id, u.email,
                   COALESCE((SELECT SUM(t.duracion_segundos) FROM tareas t
                             WHERE t.usuario_id = u.id AND {' AND '.join(cond_t)}), 0) AS segundos_totales,
                   COALESCE((SELECT COUNT(*) FROM tareas t
                             WHERE t.usuario_id = u.id AND {' AND '.join(cond_t)}), 0) AS num_tareas,
                   COALESCE((SELECT COUNT(*) FROM notas n
                             WHERE n.usuario_id = u.id AND {' AND '.join(cond_n)}), 0) AS num_notas
               FROM usuarios u
               WHERE u.id IN ({marcadores})
               ORDER BY segundos_totales DESC, u.email""",
            [*params_t, *params_t, *params_n, *ids],
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def tiempo_medio_resolucion_vencimientos(tenant_id: int) -> float | None:
    """Media de días entre crear un vencimiento fiscal y marcarlo como
    presentado -- KPI de equipo, no personal. None si no hay ningún
    vencimiento presentado todavía (evita mostrar un falso "0 días").
    No existe un equivalente para tiquets: son un tablero interno
    COMPARTIDO por toda la plataforma (sin tenant_id, ver
    app/rutas_tiquets.py), no datos de un tenant/cliente concreto --
    calcular un tiempo de resolución "por tenant" no tendría sentido
    ahí."""
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT AVG(julianday(actualizado_en) - julianday(creado_en)) AS media_dias
               FROM vencimientos_fiscales
               WHERE tenant_id = ? AND estado = 'presentado' AND actualizado_en IS NOT NULL""",
            (tenant_id,),
        ).fetchone()
        return fila["media_dias"]
    finally:
        conn.close()


# --- Frases favoritas (plantillas) ------------------------------------------
# Se aíslan a través de categoria_id (NOT NULL, siempre de un usuario ya
# validado por la ruta antes de llamar aquí) — no llevan usuario_id propio.

def crear_plantilla(categoria_id: int, texto: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO plantillas (categoria_id, texto, creada_en) VALUES (?, ?, ?)",
            (categoria_id, texto.strip(), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_plantillas(categoria_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM plantillas WHERE categoria_id = ? ORDER BY id", (categoria_id,)
        ).fetchall()
    finally:
        conn.close()


def eliminar_plantilla(plantilla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM plantillas WHERE id = ?", (plantilla_id,))
        conn.commit()
    finally:
        conn.close()


# --- Tareas al estilo Outlook (lista + calendario) --------------------------
# Independientes de las tareas con duración de más arriba (ese sistema es un
# cronómetro en vivo, no un horario planificado de antemano). SÍ admiten un
# proyecto opcional (categoria_id, relación real con la tabla categorias, mismo
# patrón que correo_mensajes.categoria_id) además de categoria_outlook (texto
# libre, para importar/exportar con Outlook real — son dos campos
# independientes a propósito, no hay que confundirlos). Los campos calcan el
# modelo de objetos de Outlook / VTODO de iCalendar para que importar y
# exportar sea un mapeo directo, campo a campo.

CAMPOS_TAREA_OUTLOOK = (
    "asunto", "cuerpo", "estado", "porcentaje_completado", "prioridad",
    "fecha_inicio", "fecha_vencimiento", "fecha_completada",
    "categoria_outlook", "categoria_id", "outlook_entry_id",
)


def registrar_actividad_tarea(usuario_id: int, tarea_id: int, tipo: str, detalle: str = "") -> None:
    """Anota una línea en el historial de la tarea. Es solo un registro: un fallo
    aquí nunca debe romper la acción que se está registrando."""
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO tarea_actividad (tarea_id, usuario_id, tipo, detalle, creado_en) VALUES (?, ?, ?, ?, ?)",
                (tarea_id, usuario_id, tipo, (detalle or "")[:200], now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def crear_tarea_outlook(
    usuario_id: int,
    asunto: str,
    cuerpo: str | None = None,
    estado: str = "no_iniciada",
    porcentaje_completado: int = 0,
    prioridad: str = "normal",
    fecha_inicio: str | None = None,
    fecha_vencimiento: str | None = None,
    categoria_outlook: str | None = None,
    categoria_id: int | None = None,
    outlook_entry_id: str | None = None,
    tarea_recurrente_id: int | None = None,
    cliente_fiscal_id: int | None = None,
    mensaje_correo_id: int | None = None,
    asignada_a: int | None = None,
) -> int:
    conn = get_connection()
    try:
        categoria_id = _categoria_id_propio(conn, usuario_id, categoria_id)
        cliente_fiscal_id = _cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id)
        mensaje_correo_id = _mensaje_correo_id_propio(conn, usuario_id, mensaje_correo_id)
        asignada_a = _companero_del_tenant(conn, usuario_id, asignada_a)
        cur = conn.execute(
            """INSERT INTO tareas_outlook
               (usuario_id, asunto, cuerpo, estado, porcentaje_completado, prioridad,
                fecha_inicio, fecha_vencimiento, categoria_outlook, categoria_id,
                outlook_entry_id, tarea_recurrente_id, cliente_fiscal_id, mensaje_correo_id,
                asignada_a, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, asunto.strip(), (cuerpo or "").strip() or None, estado,
                porcentaje_completado, prioridad, fecha_inicio, fecha_vencimiento,
                (categoria_outlook or "").strip() or None, categoria_id, outlook_entry_id,
                tarea_recurrente_id, cliente_fiscal_id, mensaje_correo_id, asignada_a, now_iso(),
            ),
        )
        conn.commit()
        tarea_id = cur.lastrowid
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_id, "creada")
    _emitir_evento(usuario_id, "tarea.creada", {"tarea_id": tarea_id, "asunto": asunto.strip(), "asignada_a": asignada_a})
    return tarea_id


def _cliente_fiscal_id_del_tenant(conn: sqlite3.Connection, usuario_id: int, cliente_fiscal_id: int | None) -> int | None:
    """Solo se enlaza un cliente fiscal del propio despacho (mismo criterio
    permisivo que _categoria_id_propio: si no es válido, se ignora)."""
    if cliente_fiscal_id is None:
        return None
    fila = conn.execute(
        """SELECT c.id FROM clientes_fiscales c JOIN usuarios u ON u.tenant_id = c.tenant_id
           WHERE c.id = ? AND u.id = ? AND c.papelera_en IS NULL""",
        (cliente_fiscal_id, usuario_id),
    ).fetchone()
    return fila["id"] if fila else None


def _mensaje_correo_id_propio(conn: sqlite3.Connection, usuario_id: int, mensaje_id: int | None) -> int | None:
    if mensaje_id is None:
        return None
    fila = conn.execute(
        """SELECT m.id FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
           WHERE m.id = ? AND c.usuario_id = ?""",
        (mensaje_id, usuario_id),
    ).fetchone()
    return fila["id"] if fila else None


def _companero_del_tenant(conn: sqlite3.Connection, usuario_id: int, otro_id: int | None) -> int | None:
    """Solo se puede asignar a alguien del MISMO despacho (y no a uno mismo:
    la tarea ya es suya). Si no, se ignora."""
    if otro_id is None or otro_id == usuario_id:
        return None
    fila = conn.execute(
        """SELECT o.id FROM usuarios o JOIN usuarios yo ON yo.tenant_id = o.tenant_id
           WHERE o.id = ? AND yo.id = ? AND yo.tenant_id IS NOT NULL""",
        (otro_id, usuario_id),
    ).fetchone()
    return fila["id"] if fila else None


def listar_companeros_tenant(usuario_id: int) -> list[sqlite3.Row]:
    """Compañeros del mismo despacho (sin el propio usuario), con el nombre
    elegido o, en su defecto, el correo -- para el selector de asignación."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT o.id, COALESCE(NULLIF(p.nombre_mostrado, ''), o.email) AS nombre
               FROM usuarios o JOIN usuarios yo ON yo.tenant_id = o.tenant_id
               LEFT JOIN usuario_perfil p ON p.usuario_id = o.id
               WHERE yo.id = ? AND yo.tenant_id IS NOT NULL AND o.id != ? ORDER BY nombre""",
            (usuario_id, usuario_id),
        ).fetchall()
    finally:
        conn.close()


# --- Tareas recurrentes (app/rutas_tareas.py) --------------------------

PERIODICIDADES_RECURRENTES = ("diaria", "laborables", "semanal", "mensual", "trimestral", "anual")


def crear_tarea_recurrente(
    usuario_id: int, asunto: str, periodicidad: str, dia: int, categoria_id: int | None = None,
    mes: int | None = None,
) -> int:
    """`dia`: 0-6 (lunes-domingo) si es semanal; 1-31 si es mensual, trimestral
    (primer mes de cada trimestre) o anual; sin uso (0) en diaria/laborables.
    `mes` (1-12) solo se usa en anual."""
    if periodicidad not in PERIODICIDADES_RECURRENTES:
        raise ValueError(f"Periodicidad no válida: {periodicidad}")
    conn = get_connection()
    try:
        categoria_id = _categoria_id_propio(conn, usuario_id, categoria_id)
        cur = conn.execute(
            "INSERT INTO tareas_recurrentes (usuario_id, categoria_id, asunto, periodicidad, dia, mes, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, categoria_id, asunto.strip(), periodicidad, dia, mes, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tareas_recurrentes(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_recurrentes WHERE usuario_id = ? ORDER BY creado_en DESC", (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def alternar_activa_tarea_recurrente(usuario_id: int, regla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas_recurrentes SET activa = 1 - activa WHERE id = ? AND usuario_id = ?",
            (regla_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_recurrente(usuario_id: int, regla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tareas_recurrentes WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def _existe_tarea_generada_este_periodo(conn: sqlite3.Connection, regla_id: int, desde: str, hasta: str) -> bool:
    fila = conn.execute(
        "SELECT 1 FROM tareas_outlook WHERE tarea_recurrente_id = ? AND creada_en >= ? AND creada_en < ? "
        "AND papelera_en IS NULL LIMIT 1",
        (regla_id, desde, hasta),
    ).fetchone()
    return fila is not None


def generar_tareas_recurrentes() -> int:
    """Recurrencia automática por cron (ver scripts/generar_tareas_recurrentes.py),
    pensado para correr una vez al día -- para cada regla activa, comprueba
    si HOY es el día que le toca (día de la semana si es semanal, día del
    mes si es mensual -- si el mes no tiene ese día, se usa su último día,
    ver `dia_efectivo` abajo) y, si es así y todavía no se ha generado una
    tarea de ESTE periodo (semana o mes en curso, ver
    _existe_tarea_generada_este_periodo), crea una tareas_outlook nueva
    enlazada a la regla vía tarea_recurrente_id. Idempotente -- ejecutarlo
    varias veces el mismo día no duplica nada, mismo criterio que
    generar_vencimientos_automaticos()."""
    hoy = datetime.now()
    hoy_iso = hoy.strftime("%Y-%m-%d")
    manana_iso = (hoy + timedelta(days=1)).strftime("%Y-%m-%d")
    inicio_anio, fin_anio = f"{hoy.year}-01-01", f"{hoy.year + 1}-01-01"
    inicio_semana = (hoy - timedelta(days=hoy.weekday())).strftime("%Y-%m-%d")
    fin_semana = (hoy - timedelta(days=hoy.weekday()) + timedelta(days=7)).strftime("%Y-%m-%d")
    inicio_mes = hoy.replace(day=1).strftime("%Y-%m-%d")
    if hoy.month == 12:
        fin_mes = hoy.replace(year=hoy.year + 1, month=1, day=1).strftime("%Y-%m-%d")
    else:
        fin_mes = hoy.replace(month=hoy.month + 1, day=1).strftime("%Y-%m-%d")
    ultimo_dia_del_mes = (datetime.fromisoformat(fin_mes) - timedelta(days=1)).day

    creadas = 0
    conn = get_connection()
    try:
        reglas = conn.execute("SELECT * FROM tareas_recurrentes WHERE activa = 1").fetchall()
        for regla in reglas:
            periodicidad = regla["periodicidad"]
            if periodicidad == "diaria":
                le_toca_hoy, (desde, hasta) = True, (hoy_iso, manana_iso)
            elif periodicidad == "laborables":
                le_toca_hoy, (desde, hasta) = hoy.weekday() < 5, (hoy_iso, manana_iso)
            elif periodicidad == "semanal":
                le_toca_hoy = hoy.weekday() == regla["dia"]
                desde, hasta = inicio_semana, fin_semana
            elif periodicidad == "trimestral":
                # Primer mes de cada trimestre (enero, abril, julio, octubre).
                le_toca_hoy = hoy.month in (1, 4, 7, 10) and hoy.day == min(regla["dia"], ultimo_dia_del_mes)
                desde, hasta = inicio_mes, fin_mes
            elif periodicidad == "anual":
                le_toca_hoy = hoy.month == (regla["mes"] or 1) and hoy.day == min(regla["dia"], ultimo_dia_del_mes)
                desde, hasta = inicio_anio, fin_anio
            else:  # mensual
                dia_efectivo = min(regla["dia"], ultimo_dia_del_mes)
                le_toca_hoy = hoy.day == dia_efectivo
                desde, hasta = inicio_mes, fin_mes
            if not le_toca_hoy:
                continue
            if _existe_tarea_generada_este_periodo(conn, regla["id"], desde, hasta):
                continue
            categoria_id = _categoria_id_propio(conn, regla["usuario_id"], regla["categoria_id"])
            conn.execute(
                """INSERT INTO tareas_outlook
                   (usuario_id, asunto, categoria_id, tarea_recurrente_id, creada_en)
                   VALUES (?, ?, ?, ?, ?)""",
                (regla["usuario_id"], regla["asunto"], categoria_id, regla["id"], now_iso()),
            )
            creadas += 1
        conn.commit()
        return creadas
    finally:
        conn.close()


def listar_tareas_outlook(
    usuario_id: int,
    estado: str | None = None,
    prioridad: str | None = None,
    categoria_outlook: str | None = None,
    texto: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    excluir_completadas: bool = False,
    limite: int | None = None,
    offset: int = 0,
    incluir_asignadas: bool = False,
    solo_asignadas: bool = False,
    categoria_id: int | None = None,
    cliente_fiscal_id: int | None = None,
    solo_compartidas: bool = False,
) -> list[sqlite3.Row]:
    """Tareas activas (no en la papelera), filtradas opcionalmente.

    Por defecto solo las del propio usuario (las llamadas existentes -- API,
    MCP, exportaciones -- no cambian). `incluir_asignadas`: añade las que un
    compañero le ha asignado; `solo_asignadas`: solo esas. `categoria_id`
    filtra por proyecto y `cliente_fiscal_id` por cliente.

    `desde`/`hasta` filtran por fecha_vencimiento (YYYY-MM-DD, inclusive) —
    los usa la vista calendario para pedir solo las de un rango de días.
    `excluir_completadas`: atajo para la vista "To-Do" por defecto de
    tareas_lista.html (solo tiene efecto si no se pasa `estado` explícito;
    antes ese filtro se aplicaba en Python DESPUÉS de traer las filas, lo
    que rompía la paginación por SQL de abajo).
    `limite`/`offset`: paginación (mismo estilo que db.listar_mensajes_correo)
    -- `limite=None` (por defecto) devuelve todo, para no romper a las
    llamadas existentes que esperan el conjunto completo (calendario,
    export a .ics/.csv, la API en rutas_api.py).
    """
    conn = get_connection()
    try:
        # t.usuario_id/t.papelera_en llevan el prefijo de tabla porque
        # categorias también tiene esas dos columnas (JOIN ambiguo si no);
        # el resto de condiciones no lo necesitan, son propias de tareas_outlook.
        compartida = "t.id IN (SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?)"
        if solo_compartidas:
            cond, params = [compartida, "t.papelera_en IS NULL"], [usuario_id]
        elif solo_asignadas:
            cond, params = ["t.asignada_a = ?", "t.papelera_en IS NULL"], [usuario_id]
        elif incluir_asignadas:
            cond, params = [f"(t.usuario_id = ? OR t.asignada_a = ? OR {compartida})", "t.papelera_en IS NULL"], [usuario_id, usuario_id, usuario_id]
        else:
            cond, params = ["t.usuario_id = ?", "t.papelera_en IS NULL"], [usuario_id]
        if categoria_id is not None:
            cond.append("t.categoria_id = ?"); params.append(categoria_id)
        if cliente_fiscal_id is not None:
            cond.append("t.cliente_fiscal_id = ?"); params.append(cliente_fiscal_id)
        if estado:
            cond.append("estado = ?"); params.append(estado)
        elif excluir_completadas:
            cond.append("estado != 'completada'")
        if prioridad:
            cond.append("prioridad = ?"); params.append(prioridad)
        if categoria_outlook:
            cond.append("categoria_outlook = ?"); params.append(categoria_outlook)
        if texto:
            cond.append("(asunto LIKE ? OR cuerpo LIKE ?)")
            params.extend([f"%{texto}%", f"%{texto}%"])
        if desde:
            cond.append("fecha_vencimiento >= ?"); params.append(desde)
        if hasta:
            cond.append("fecha_vencimiento < ?"); params.append(_fecha_exclusiva(hasta))
        where = " AND ".join(cond)
        query = f"""SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color,
                       COALESCE(NULLIF(pa.nombre_mostrado, ''), ua.email) AS asignada_nombre,
                       COALESCE(NULLIF(po.nombre_mostrado, ''), uo.email) AS creador_nombre,
                       cf.nombre AS cliente_fiscal_nombre
                FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
                LEFT JOIN usuarios ua ON ua.id = t.asignada_a LEFT JOIN usuario_perfil pa ON pa.usuario_id = t.asignada_a
                LEFT JOIN usuarios uo ON uo.id = t.usuario_id LEFT JOIN usuario_perfil po ON po.usuario_id = t.usuario_id
                LEFT JOIN clientes_fiscales cf ON cf.id = t.cliente_fiscal_id
                WHERE {where}
                ORDER BY (t.fecha_vencimiento IS NULL), t.fecha_vencimiento, t.prioridad DESC"""
        if limite is not None:
            query += " LIMIT ? OFFSET ?"
            params = params + [limite, offset]
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def obtener_tarea_outlook(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND t.usuario_id = ? AND t.papelera_en IS NULL""",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def obtener_tarea_outlook_visible(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    """Como obtener_tarea_outlook, pero también para quien la tiene ASIGNADA:
    puede verla, completarla, cambiarle el estado, marcar su checklist y
    dedicarle tiempo; y también para sus participantes (ver rol_en_tarea).
    Eliminarla o compartirla sigue siendo solo del dueño."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND (t.usuario_id = ? OR t.asignada_a = ? OR t.id IN (
                         SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ?))
                 AND t.papelera_en IS NULL""",
            (tarea_id, usuario_id, usuario_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def obtener_tarea_outlook_por_entry_id(usuario_id: int, entry_id: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_outlook WHERE outlook_entry_id = ? AND usuario_id = ?", (entry_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def upsert_tarea_outlook_por_entry_id(usuario_id: int, outlook_entry_id: str | None, **campos) -> tuple[int, bool]:
    """Crea la tarea, o actualiza la ya existente con ese `outlook_entry_id`.

    Devuelve (id, creada) — creada=True si no existía y se ha creado nueva.
    Pensado para sincronizar desde una fuente externa (.ics, .csv, o más
    adelante COM) sin duplicar tareas ya importadas en una sincronización anterior.
    """
    existente = obtener_tarea_outlook_por_entry_id(usuario_id, outlook_entry_id) if outlook_entry_id else None
    if existente:
        campos_validos = {c: v for c, v in campos.items() if c in CAMPOS_TAREA_OUTLOOK}
        editar_tarea_outlook(usuario_id, existente["id"], **campos_validos)
        return existente["id"], False

    # crear_tarea_outlook no acepta fecha_completada como argumento de creación
    # (una tarea recién creada no puede nacer ya completada por diseño del
    # formulario normal) — si el origen externo trae una, se aplica aparte.
    fecha_completada = campos.get("fecha_completada")
    campos_creacion = {
        c: v for c, v in campos.items()
        if c in CAMPOS_TAREA_OUTLOOK and c not in ("fecha_completada", "outlook_entry_id")
    }
    tid = crear_tarea_outlook(usuario_id, outlook_entry_id=outlook_entry_id, **campos_creacion)
    if fecha_completada:
        editar_tarea_outlook(usuario_id, tid, fecha_completada=fecha_completada)
    return tid, True


ETIQUETAS_CAMPO_TAREA = {
    "asunto": "asunto", "cuerpo": "descripción", "prioridad": "prioridad", "estado": "estado",
    "fecha_inicio": "inicio", "fecha_vencimiento": "vencimiento", "cliente_fiscal_id": "cliente",
    "categoria_id": "proyecto", "categoria_outlook": "categoría",
}


def editar_tarea_outlook(usuario_id: int, tarea_id: int, **campos) -> None:
    """Actualiza los campos indicados (cualquiera de CAMPOS_TAREA_OUTLOOK)."""
    columnas = [c for c in campos if c in CAMPOS_TAREA_OUTLOOK or c in ("cliente_fiscal_id", "mensaje_correo_id")]
    if not columnas:
        return
    conn = get_connection()
    try:
        # Dueño o colaborador. El proyecto y el correo enlazado son del dueño:
        # un colaborador no los cambia (sus propios proyectos no valen aquí).
        es_dueno = conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)).fetchone()
        if not es_dueno:
            if not _es_colaborador(conn, usuario_id, tarea_id):
                return
            columnas = [c for c in columnas if c not in ("categoria_id", "mensaje_correo_id")]
            if not columnas:
                return
        if "categoria_id" in campos:
            campos["categoria_id"] = _categoria_id_propio(conn, usuario_id, campos["categoria_id"])
        if "cliente_fiscal_id" in campos:
            campos["cliente_fiscal_id"] = _cliente_fiscal_id_del_tenant(conn, usuario_id, campos["cliente_fiscal_id"])
        if "mensaje_correo_id" in campos:
            campos["mensaje_correo_id"] = _mensaje_correo_id_propio(conn, usuario_id, campos["mensaje_correo_id"])
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        antes = conn.execute("SELECT * FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        conn.execute(
            f"UPDATE tareas_outlook SET {asignaciones}, actualizada_en = ? WHERE id = ?",
            [*valores, now_iso(), tarea_id],
        )
        conn.commit()
        cambiados = [
            ETIQUETAS_CAMPO_TAREA[c] for c in columnas
            if c in ETIQUETAS_CAMPO_TAREA and antes is not None and (antes[c] or None) != (campos[c] or None)
        ]
        if cambiados:
            registrar_actividad_tarea(usuario_id, tarea_id, "editada", ", ".join(cambiados))
    finally:
        conn.close()


def completar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    """Completa la tarea (la puede completar su dueño o quien la tiene
    asignada) y cierra los cronómetros que siguieran en marcha sobre ella.
    No hace nada si aún espera a otras tareas (ver tarea_bloqueada)."""
    if tarea_bloqueada(tarea_id):
        return
    conn = get_connection()
    try:
        cur = conn.execute(
            """UPDATE tareas_outlook
               SET estado = 'completada', porcentaje_completado = 100,
                   fecha_completada = ?, actualizada_en = ?
               WHERE id = ? AND (usuario_id = ? OR asignada_a = ? OR id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))""",
            (now_iso(), now_iso(), tarea_id, usuario_id, usuario_id, usuario_id),
        )
        conn.commit()
        abiertos = conn.execute(
            "SELECT id, usuario_id FROM tareas WHERE tarea_outlook_id = ? AND tipo = 'duracion' "
            "AND estado IN ('en_curso', 'pausada') AND papelera_en IS NULL",
            (tarea_id,),
        ).fetchall() if cur.rowcount else []
        completada = cur.rowcount > 0
    finally:
        conn.close()
    for abierto in abiertos:
        finalizar_tarea(abierto["usuario_id"], abierto["id"])
    if completada:
        registrar_actividad_tarea(usuario_id, tarea_id, "completada")
        for libre in tareas_desbloqueadas_por(tarea_id):
            registrar_actividad_tarea(usuario_id, libre["id"], "desbloqueada", _asunto_tarea(tarea_id))
            _emitir_evento(usuario_id, "tarea.desbloqueada", {"tarea_id": libre["id"], "responsable_id": libre["responsable_id"]})
        _emitir_evento(usuario_id, "tarea.completada", {"tarea_id": tarea_id, "completada_por": usuario_id})


def cambiar_estado_tarea_outlook(usuario_id: int, tarea_id: int, estado: str) -> bool:
    """Cambia el estado (tablero). 'completada' pasa por completar_tarea_outlook
    (porcentaje, fecha y cronómetros); al reabrir una completada se limpia su fecha."""
    estados = ("no_iniciada", "en_progreso", "completada", "esperando", "aplazada")
    if estado not in estados or not puede_trabajar_tarea(usuario_id, tarea_id):
        return False
    if estado in ("en_progreso", "completada") and tarea_bloqueada(tarea_id):
        return False
    if estado == "completada":
        completar_tarea_outlook(usuario_id, tarea_id)
        return True
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE tareas_outlook SET estado = ?, fecha_completada = NULL, actualizada_en = ?,
                   porcentaje_completado = CASE WHEN estado = 'completada' THEN 0 ELSE porcentaje_completado END
               WHERE id = ? AND (usuario_id = ? OR asignada_a = ? OR id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))""",
            (estado, now_iso(), tarea_id, usuario_id, usuario_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_id, "estado", estado)
    return True


# ---- Compartir tareas con compañeros del tenant ---------------------------

ROLES_PARTICIPANTE = ("colabora", "observa")


def _es_colaborador(conn: sqlite3.Connection, usuario_id: int, tarea_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM tareas_participantes_todos WHERE tarea_id = ? AND usuario_id = ? AND rol = 'colabora'",
        (tarea_id, usuario_id),
    ).fetchone() is not None


def rol_en_tarea(usuario_id: int, tarea_id: int) -> str | None:
    """'dueno', 'asignada', 'colabora', 'observa' o None si no la ve."""
    conn = get_connection()
    try:
        t = conn.execute(
            "SELECT usuario_id, asignada_a FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)
        ).fetchone()
        if t is None:
            return None
        if t["usuario_id"] == usuario_id:
            return "dueno"
        p = conn.execute(
            "SELECT rol FROM tareas_participantes_todos WHERE tarea_id = ? AND usuario_id = ? ORDER BY rol = 'colabora' DESC",
            (tarea_id, usuario_id),
        ).fetchone()
        if p is not None:
            return p["rol"]
        return "asignada" if t["asignada_a"] == usuario_id else None
    finally:
        conn.close()


def puede_trabajar_tarea(usuario_id: int, tarea_id: int) -> bool:
    """Completar, cambiar estado, checklist y cronómetro: dueño, asignado y
    colaboradores (los observadores solo ven)."""
    return rol_en_tarea(usuario_id, tarea_id) in ("dueno", "asignada", "colabora")


def puede_editar_tarea(usuario_id: int, tarea_id: int) -> bool:
    """Editar los datos de la tarea: dueño y colaboradores."""
    return rol_en_tarea(usuario_id, tarea_id) in ("dueno", "colabora")


def compartir_tarea_outlook(usuario_id: int, tarea_id: int, otro_id: int, rol: str = "colabora") -> bool:
    """El dueño comparte la tarea con un compañero del mismo tenant (o cambia
    su rol). False si no es suya, el compañero no es del tenant o el rol no vale."""
    if rol not in ROLES_PARTICIPANTE:
        return False
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
        ).fetchone() is None:
            return False
        destino = _companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        conn.execute(
            """INSERT INTO tareas_participantes (tarea_id, usuario_id, rol, compartida_en) VALUES (?, ?, ?, ?)
               ON CONFLICT(tarea_id, usuario_id) DO UPDATE SET rol = excluded.rol""",
            (tarea_id, destino, rol, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    registrar_actividad_tarea(
        usuario_id, tarea_id, "compartida", f"{nombre_mostrado_usuario(destino) or destino} ({'colabora' if rol == 'colabora' else 'solo lectura'})"
    )
    _emitir_evento(usuario_id, "tarea.compartida", {"tarea_id": tarea_id, "con": destino, "rol": rol})
    return True


def dejar_de_compartir_tarea_outlook(usuario_id: int, tarea_id: int, otro_id: int) -> bool:
    """El dueño quita a un participante; el propio participante puede salirse."""
    conn = get_connection()
    try:
        dueno = conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)).fetchone()
        if not dueno and otro_id != usuario_id:
            return False
        cur = conn.execute("DELETE FROM tareas_participantes WHERE tarea_id = ? AND usuario_id = ?", (tarea_id, otro_id))
        conn.commit()
        quitado = cur.rowcount > 0
    finally:
        conn.close()
    if quitado:
        registrar_actividad_tarea(usuario_id, tarea_id, "dejo_compartir", nombre_mostrado_usuario(otro_id) or str(otro_id))
    return quitado


def participantes_de_tarea(tarea_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT p.usuario_id, p.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
               FROM tareas_participantes p JOIN usuarios u ON u.id = p.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
               WHERE p.tarea_id = ? ORDER BY nombre""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()


def participantes_de_tareas(tarea_ids: list[int]) -> dict[int, list[dict]]:
    """Participantes por tarea (para mostrar las insignias en lista/tablero)."""
    if not tarea_ids:
        return {}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        filas = conn.execute(
            f"""SELECT p.tarea_id, p.usuario_id, p.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
                FROM tareas_participantes p JOIN usuarios u ON u.id = p.usuario_id
                LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
                WHERE p.tarea_id IN ({marcas}) ORDER BY nombre""",
            tarea_ids,
        ).fetchall()
    finally:
        conn.close()
    resultado: dict[int, list[dict]] = {}
    for f in filas:
        resultado.setdefault(f["tarea_id"], []).append(dict(f))
    return resultado


# ---- Comentarios con menciones ---------------------------------------------

COMENTARIO_MAX_CARACTERES = 2000


def personas_de_tarea(usuario_id: int, tarea_id: int) -> list[dict]:
    """Quienes ven la tarea (dueño, asignado y participantes), con su nombre y
    rol: las únicas personas a las que se puede mencionar. [] si el usuario no la ve."""
    if rol_en_tarea(usuario_id, tarea_id) is None:
        return []
    conn = get_connection()
    try:
        t = conn.execute("SELECT usuario_id, asignada_a FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        ids: dict[int, str] = {t["usuario_id"]: "dueno"}
        if t["asignada_a"]:
            ids.setdefault(t["asignada_a"], "asignada")
        for p in conn.execute("SELECT usuario_id, rol FROM tareas_participantes WHERE tarea_id = ?", (tarea_id,)):
            ids.setdefault(p["usuario_id"], p["rol"])
        resultado = []
        for uid, rol in ids.items():
            f = conn.execute(
                """SELECT COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre FROM usuarios u
                   LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id WHERE u.id = ?""",
                (uid,),
            ).fetchone()
            if f:
                resultado.append({"id": uid, "nombre": f["nombre"], "rol": rol})
        return sorted(resultado, key=lambda x: x["nombre"].lower())
    finally:
        conn.close()


def detectar_menciones(texto: str, personas: list[dict], excluir_id: int | None = None) -> list[int]:
    """Ids de las personas citadas como @Nombre en el texto (el nombre completo,
    sin distinguir mayúsculas; el más largo primero para que '@Ana Ruiz' no se
    confunda con '@Ana')."""
    bajo = (texto or "").lower()
    encontradas: list[int] = []
    consumido = bajo
    for p in sorted(personas, key=lambda x: len(x["nombre"]), reverse=True):
        marca = "@" + p["nombre"].lower()
        if marca in consumido and p["id"] != excluir_id and p["id"] not in encontradas:
            encontradas.append(p["id"])
            consumido = consumido.replace(marca, " " * len(marca))
    return encontradas


def comentar_tarea_outlook(usuario_id: int, tarea_id: int, texto: str) -> dict | None:
    """Añade un comentario (lo puede hacer cualquiera que vea la tarea, también
    un observador). Devuelve {id, menciones, destinatarios} o None si no procede."""
    texto = (texto or "").strip()[:COMENTARIO_MAX_CARACTERES]
    if not texto:
        return None
    personas = personas_de_tarea(usuario_id, tarea_id)
    if not personas:
        return None
    menciones = detectar_menciones(texto, personas, excluir_id=usuario_id)
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tarea_comentarios (tarea_id, usuario_id, texto, menciones, creado_en) VALUES (?, ?, ?, ?, ?)",
            (tarea_id, usuario_id, texto, ",".join(str(i) for i in menciones), now_iso()),
        )
        conn.commit()
        nuevo = cur.lastrowid
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_id, "comentario")
    _emitir_evento(usuario_id, "tarea.comentada", {"tarea_id": tarea_id, "comentario_id": nuevo, "menciones": menciones})
    otros = [p["id"] for p in personas if p["id"] != usuario_id and p["id"] not in menciones]
    return {"id": nuevo, "menciones": menciones, "otros": otros}


def listar_comentarios_tarea(usuario_id: int, tarea_id: int) -> list[dict]:
    """Comentarios de la tarea (viejos primero), solo si el usuario la ve. Cada uno
    lleva `autor`, `mios` y los nombres de lo mencionado en `mencionados`."""
    personas = personas_de_tarea(usuario_id, tarea_id)
    if not personas:
        return []
    nombres = {p["id"]: p["nombre"] for p in personas}
    dueno = next((p["id"] for p in personas if p["rol"] == "dueno"), None)
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT c.*, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM tarea_comentarios c JOIN usuarios u ON u.id = c.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = c.usuario_id
               WHERE c.tarea_id = ? ORDER BY c.id""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()
    resultado = []
    for f in filas:
        d = dict(f)
        ids = [int(i) for i in d["menciones"].split(",") if i]
        d["mencionados"] = [nombres[i] for i in ids if i in nombres]
        d["mio"] = d["usuario_id"] == usuario_id
        d["puede_borrar"] = d["mio"] or usuario_id == dueno
        resultado.append(d)
    return resultado


def eliminar_comentario_tarea(usuario_id: int, tarea_id: int, comentario_id: int) -> bool:
    """Lo borra su autor o el dueño de la tarea."""
    es_dueno = rol_en_tarea(usuario_id, tarea_id) == "dueno"
    conn = get_connection()
    try:
        c = conn.execute(
            "SELECT usuario_id FROM tarea_comentarios WHERE id = ? AND tarea_id = ?", (comentario_id, tarea_id)
        ).fetchone()
        if c is None or not (es_dueno or c["usuario_id"] == usuario_id) or rol_en_tarea(usuario_id, tarea_id) is None:
            return False
        conn.execute("DELETE FROM tarea_comentarios WHERE id = ?", (comentario_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def contar_comentarios_tareas(tarea_ids: list[int]) -> dict[int, int]:
    if not tarea_ids:
        return {}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        return {
            f["tarea_id"]: f["n"]
            for f in conn.execute(
                f"SELECT tarea_id, COUNT(*) AS n FROM tarea_comentarios WHERE tarea_id IN ({marcas}) GROUP BY tarea_id",
                tarea_ids,
            )
        }
    finally:
        conn.close()


# ---- Plantillas de tareas ---------------------------------------------------

PLANTILLA_MAX_ITEMS = 40


def parsear_items_plantilla(texto: str) -> list[dict]:
    """Una tarea por línea con el formato `asunto | días | prioridad` (días y
    prioridad son opcionales: días desde la fecha de inicio, prioridad baja/
    normal/alta). Las líneas que empiezan por `- ` son subtareas de la tarea
    anterior. Ignora líneas vacías y los valores que no se entienden."""
    items: list[dict] = []
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if linea.startswith("- "):
            if items and linea[2:].strip():
                items[-1]["checklist"].append(" ".join(linea[2:].split())[:CHECKLIST_MAX_CARACTERES])
            continue
        partes = [p.strip() for p in linea.split("|")]
        asunto = " ".join(partes[0].split())[:200]
        if not asunto:
            continue
        dias = 0
        if len(partes) > 1 and partes[1].lstrip("+-").isdigit():
            dias = max(-3650, min(3650, int(partes[1])))
        prioridad = partes[2].lower() if len(partes) > 2 and partes[2].lower() in ("baja", "normal", "alta") else "normal"
        items.append({"asunto": asunto, "dias": dias, "prioridad": prioridad, "checklist": []})
        if len(items) >= PLANTILLA_MAX_ITEMS:
            break
    return items


def items_a_texto(items) -> str:
    """Inversa de parsear_items_plantilla (para volver a mostrar la plantilla al editarla)."""
    lineas = []
    for i in items:
        lineas.append(f"{i['asunto']} | {i['dias']} | {i['prioridad']}")
        lineas += [f"- {c}" for c in (i["checklist"].split("\n") if isinstance(i["checklist"], str) else i["checklist"]) if c]
    return "\n".join(lineas)


def crear_plantilla_tareas(usuario_id: int, nombre: str, descripcion: str | None, texto_items: str, compartida: bool = False) -> int | None:
    """None si no tiene nombre o no hay ninguna tarea válida."""
    nombre = " ".join((nombre or "").split())[:120]
    items = parsear_items_plantilla(texto_items)
    if not nombre or not items:
        return None
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO plantillas_tareas (usuario_id, nombre, descripcion, compartida, creada_en) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, nombre, (descripcion or "").strip()[:500] or None, 1 if compartida else 0, now_iso()),
        )
        plantilla_id = cur.lastrowid
        _guardar_items_plantilla(conn, plantilla_id, items)
        conn.commit()
        return plantilla_id
    finally:
        conn.close()


def _guardar_items_plantilla(conn: sqlite3.Connection, plantilla_id: int, items: list[dict]) -> None:
    conn.execute("DELETE FROM plantilla_tareas_items WHERE plantilla_id = ?", (plantilla_id,))
    for orden, i in enumerate(items, 1):
        conn.execute(
            "INSERT INTO plantilla_tareas_items (plantilla_id, orden, asunto, prioridad, dias, checklist) VALUES (?, ?, ?, ?, ?, ?)",
            (plantilla_id, orden, i["asunto"], i["prioridad"], i["dias"], "\n".join(i["checklist"])),
        )


def editar_plantilla_tareas(usuario_id: int, plantilla_id: int, nombre: str, descripcion: str | None, texto_items: str, compartida: bool) -> bool:
    nombre = " ".join((nombre or "").split())[:120]
    items = parsear_items_plantilla(texto_items)
    if not nombre or not items:
        return False
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE plantillas_tareas SET nombre = ?, descripcion = ?, compartida = ? WHERE id = ? AND usuario_id = ?",
            (nombre, (descripcion or "").strip()[:500] or None, 1 if compartida else 0, plantilla_id, usuario_id),
        )
        if cur.rowcount == 0:
            return False
        _guardar_items_plantilla(conn, plantilla_id, items)
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_plantilla_tareas(usuario_id: int, plantilla_id: int) -> bool:
    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM plantillas_tareas WHERE id = ? AND usuario_id = ?", (plantilla_id, usuario_id)).fetchone() is None:
            return False
        conn.execute("DELETE FROM plantilla_tareas_items WHERE plantilla_id = ?", (plantilla_id,))
        conn.execute("DELETE FROM plantillas_tareas WHERE id = ?", (plantilla_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def listar_plantillas_tareas(usuario_id: int) -> list[dict]:
    """Las propias y las compartidas por compañeros del mismo despacho."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT p.*, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor,
                      (SELECT COUNT(*) FROM plantilla_tareas_items i WHERE i.plantilla_id = p.id) AS n_tareas
               FROM plantillas_tareas p JOIN usuarios u ON u.id = p.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
               WHERE p.usuario_id = ? OR (p.compartida = 1 AND u.tenant_id IS NOT NULL
                     AND u.tenant_id = (SELECT tenant_id FROM usuarios WHERE id = ?))
               ORDER BY p.nombre""",
            (usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def obtener_plantilla_tareas(usuario_id: int, plantilla_id: int) -> dict | None:
    """Con sus tareas (`items`), si es del usuario o está compartida en su despacho."""
    visibles = {p["id"]: p for p in listar_plantillas_tareas(usuario_id)}
    p = visibles.get(plantilla_id)
    if p is None:
        return None
    conn = get_connection()
    try:
        p["items"] = [
            dict(i) for i in conn.execute(
                "SELECT asunto, prioridad, dias, checklist FROM plantilla_tareas_items WHERE plantilla_id = ? ORDER BY orden",
                (plantilla_id,),
            )
        ]
    finally:
        conn.close()
    return p


def aplicar_plantilla_tareas(
    usuario_id: int, plantilla_id: int, fecha_inicio: str, *, categoria_id: int | None = None,
    nuevo_proyecto: str | None = None, cliente_fiscal_id: int | None = None, asignada_a: int | None = None,
    encadenar: bool = False,
) -> list[int]:
    """Crea las tareas de la plantilla con vencimiento = fecha de inicio + sus días
    (YYYY-MM-DD). `nuevo_proyecto` crea (o reutiliza) un proyecto con ese nombre.
    `encadenar`: cada tarea espera a que se complete la anterior.
    Devuelve los ids de las tareas creadas ([] si la plantilla no es visible)."""
    plantilla = obtener_plantilla_tareas(usuario_id, plantilla_id)
    if plantilla is None:
        return []
    try:
        base = datetime.strptime(fecha_inicio[:10], "%Y-%m-%d").date()
    except ValueError:
        base = datetime.now().date()
    if nuevo_proyecto and nuevo_proyecto.strip():
        categoria_id = crear_categoria(usuario_id, nuevo_proyecto.strip()[:80])
    ids = []
    for item in plantilla["items"]:
        vence = (base + timedelta(days=item["dias"])).strftime("%Y-%m-%dT09:00")
        tarea_id = crear_tarea_outlook(
            usuario_id, item["asunto"], prioridad=item["prioridad"], fecha_inicio=base.strftime("%Y-%m-%dT09:00"),
            fecha_vencimiento=vence, categoria_id=categoria_id, cliente_fiscal_id=cliente_fiscal_id, asignada_a=asignada_a,
        )
        for texto in (item["checklist"] or "").split("\n"):
            if texto:
                agregar_item_checklist(usuario_id, tarea_id, texto)
        if encadenar and ids:
            anadir_dependencia_tarea(usuario_id, tarea_id, ids[-1])  # cada tarea espera a la anterior
        ids.append(tarea_id)
    return ids


# ---- Dependencias entre tareas -----------------------------------------------

def _depende_transitivamente(conn: sqlite3.Connection, tarea_id: int, objetivo_id: int) -> bool:
    """¿`tarea_id` depende (directa o indirectamente) de `objetivo_id`?"""
    visto: set[int] = set()
    pendientes = [tarea_id]
    while pendientes:
        actual = pendientes.pop()
        if actual == objetivo_id:
            return True
        if actual in visto:
            continue
        visto.add(actual)
        pendientes += [f["depende_de_id"] for f in conn.execute(
            "SELECT depende_de_id FROM tareas_dependencias WHERE tarea_id = ?", (actual,))]
    return False


def anadir_dependencia_tarea(usuario_id: int, tarea_id: int, depende_de_id: int) -> bool:
    """`tarea_id` pasa a esperar a `depende_de_id`. Hace falta poder editar la
    primera y ver la segunda; no se permiten ciclos ni auto-dependencias."""
    if tarea_id == depende_de_id or not puede_editar_tarea(usuario_id, tarea_id):
        return False
    if rol_en_tarea(usuario_id, depende_de_id) is None:
        return False
    conn = get_connection()
    try:
        if _depende_transitivamente(conn, depende_de_id, tarea_id):
            return False  # crearía un ciclo
        conn.execute(
            "INSERT OR IGNORE INTO tareas_dependencias (tarea_id, depende_de_id) VALUES (?, ?)", (tarea_id, depende_de_id)
        )
        conn.commit()
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_id, "dependencia", _asunto_tarea(depende_de_id))
    return True


def quitar_dependencia_tarea(usuario_id: int, tarea_id: int, depende_de_id: int) -> bool:
    if not puede_editar_tarea(usuario_id, tarea_id):
        return False
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM tareas_dependencias WHERE tarea_id = ? AND depende_de_id = ?", (tarea_id, depende_de_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _asunto_tarea(tarea_id: int) -> str:
    conn = get_connection()
    try:
        f = conn.execute("SELECT asunto FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        return f["asunto"][:80] if f else ""
    finally:
        conn.close()


def dependencias_de_tarea(tarea_id: int) -> list[dict]:
    """De qué tareas depende (con su estado); las eliminadas no cuentan."""
    conn = get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT t.id, t.asunto, t.estado FROM tareas_dependencias d JOIN tareas_outlook t ON t.id = d.depende_de_id
               WHERE d.tarea_id = ? AND t.papelera_en IS NULL ORDER BY t.id""",
            (tarea_id,),
        )]
    finally:
        conn.close()


def bloqueos_de_tareas(tarea_ids: list[int]) -> dict[int, int]:
    """{tarea_id: nº de tareas previas sin completar}, solo para las bloqueadas.

    Dos consultas simples en vez de un JOIN: el planificador de SQLite arrancaba el
    JOIN recorriendo TODAS las tareas (60-135 ms con 3.000 y la tabla vacía); así
    se parte de las dependencias, que casi siempre son pocas o ninguna."""
    if not tarea_ids:
        return {}
    conn = get_connection()
    try:
        previas: dict[int, list[int]] = {}
        for inicio in range(0, len(tarea_ids), 500):
            lote = tarea_ids[inicio:inicio + 500]
            for f in conn.execute(
                f"SELECT tarea_id, depende_de_id FROM tareas_dependencias WHERE tarea_id IN ({','.join('?' * len(lote))})", lote
            ):
                previas.setdefault(f["tarea_id"], []).append(f["depende_de_id"])
        if not previas:
            return {}
        todas = sorted({d for lista in previas.values() for d in lista})
        abiertas: set[int] = set()
        for inicio in range(0, len(todas), 500):
            lote = todas[inicio:inicio + 500]
            abiertas.update(
                f["id"] for f in conn.execute(
                    f"SELECT id FROM tareas_outlook WHERE id IN ({','.join('?' * len(lote))}) AND papelera_en IS NULL AND estado != 'completada'",
                    lote,
                )
            )
        cuentas = {tid: sum(1 for d in lista if d in abiertas) for tid, lista in previas.items()}
        return {tid: n for tid, n in cuentas.items() if n}
    finally:
        conn.close()


def tarea_bloqueada(tarea_id: int) -> bool:
    return bool(bloqueos_de_tareas([tarea_id]).get(tarea_id))


def tareas_desbloqueadas_por(tarea_id: int) -> list[dict]:
    """Tareas abiertas que esperaban a `tarea_id` y que ya no esperan a nadie
    (con su responsable: el asignado o, si no, el dueño)."""
    conn = get_connection()
    try:
        candidatas = conn.execute(
            """SELECT t.id, t.asunto, COALESCE(t.asignada_a, t.usuario_id) AS responsable_id
               FROM tareas_dependencias d JOIN tareas_outlook t ON t.id = d.tarea_id
               WHERE d.depende_de_id = ? AND t.papelera_en IS NULL AND t.estado != 'completada'""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()
    pendientes = bloqueos_de_tareas([c["id"] for c in candidatas])
    return [dict(c) for c in candidatas if not pendientes.get(c["id"])]


# ---- Correo de equipo (mensajes asignados / compartidos / notas internas) ------

def _dueno_del_mensaje(conn: sqlite3.Connection, mensaje_id: int) -> int | None:
    f = conn.execute(
        "SELECT c.usuario_id FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id WHERE m.id = ?", (mensaje_id,)
    ).fetchone()
    return f["usuario_id"] if f else None


def rol_en_correo(usuario_id: int, mensaje_id: int) -> str | None:
    """'dueno', 'asignado', 'compartido' o None si no lo ve."""
    conn = get_connection()
    try:
        dueno = _dueno_del_mensaje(conn, mensaje_id)
        if dueno is None:
            return None
        if dueno == usuario_id:
            return "dueno"
        # Quien ya no está en el despacho del dueño pierde el acceso aunque
        # siga figurando como asignado o compartido.
        mismo_despacho = conn.execute(
            "SELECT 1 FROM usuarios a JOIN usuarios b ON b.tenant_id = a.tenant_id "
            "WHERE a.id = ? AND b.id = ? AND a.tenant_id IS NOT NULL", (usuario_id, dueno),
        ).fetchone()
        if mismo_despacho is None:
            return None
        eq = conn.execute("SELECT asignado_a FROM correo_equipo WHERE mensaje_id = ?", (mensaje_id,)).fetchone()
        if eq and eq["asignado_a"] == usuario_id:
            return "asignado"
        if conn.execute(
            "SELECT 1 FROM correo_compartidos WHERE mensaje_id = ? AND usuario_id = ?", (mensaje_id, usuario_id)
        ).fetchone():
            return "compartido"
        return None
    finally:
        conn.close()


MAX_COMPARTIDOS_POR_MENSAJE = 10
MAX_NOTAS_INTERNAS_POR_MENSAJE = 100


def _auditar_correo_equipo(conn: sqlite3.Connection, mensaje_id: int, usuario_id: int, accion: str, detalle: str | None = None) -> None:
    conn.execute(
        "INSERT INTO correo_equipo_auditoria (mensaje_id, usuario_id, accion, detalle, creado_en) VALUES (?, ?, ?, ?, ?)",
        (mensaje_id, usuario_id, accion, detalle, now_iso()),
    )


def registrar_lectura_correo_equipo(usuario_id: int, mensaje_id: int) -> None:
    """Anota que un compañero (no el dueño) ha abierto el mensaje: una vez por
    persona y día, para saber quién lo ha visto sin llenar el historial."""
    hoy = now_iso()[:10]
    conn = get_connection()
    try:
        if _dueno_del_mensaje(conn, mensaje_id) in (None, usuario_id):
            return
        ya = conn.execute(
            "SELECT 1 FROM correo_equipo_auditoria WHERE mensaje_id = ? AND usuario_id = ? AND accion = 'leer' AND creado_en >= ?",
            (mensaje_id, usuario_id, hoy),
        ).fetchone()
        if ya is None:
            _auditar_correo_equipo(conn, mensaje_id, usuario_id, "leer")
            conn.commit()
    finally:
        conn.close()


def historial_correo_equipo(usuario_id: int, mensaje_id: int) -> list[dict]:
    """Solo el dueño del mensaje ve quién ha hecho qué con él."""
    conn = get_connection()
    try:
        if _dueno_del_mensaje(conn, mensaje_id) != usuario_id:
            return []
        return [dict(f) for f in conn.execute(
            """SELECT a.accion, a.detalle, a.creado_en, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM correo_equipo_auditoria a JOIN usuarios u ON u.id = a.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = a.usuario_id
               WHERE a.mensaje_id = ? ORDER BY a.id DESC LIMIT 100""",
            (mensaje_id,),
        )]
    finally:
        conn.close()


def asignar_correo(usuario_id: int, mensaje_id: int, destino_id: int | None) -> bool:
    """El dueño asigna el mensaje a un compañero del despacho (que además pasa a
    verlo) o quita la asignación con None. Cada asignación nueva reabre el estado."""
    conn = get_connection()
    try:
        if _dueno_del_mensaje(conn, mensaje_id) != usuario_id:
            return False
        destino = None
        if destino_id is not None:
            destino = _companero_del_tenant(conn, usuario_id, destino_id)
            if destino is None:
                return False
        conn.execute(
            """INSERT INTO correo_equipo (mensaje_id, asignado_a, asignado_por, estado, actualizado_en)
               VALUES (?, ?, ?, 'abierto', ?)
               ON CONFLICT(mensaje_id) DO UPDATE SET asignado_a = excluded.asignado_a,
                   asignado_por = excluded.asignado_por, estado = 'abierto', actualizado_en = excluded.actualizado_en""",
            (mensaje_id, destino, usuario_id, now_iso()),
        )
        _auditar_correo_equipo(conn, mensaje_id, usuario_id, "asignar" if destino else "desasignar", str(destino) if destino else None)
        conn.commit()
    finally:
        conn.close()
    _emitir_evento(usuario_id, "correo.asignado", {"mensaje_id": mensaje_id, "asignado_a": destino})
    return True


def compartir_correo(usuario_id: int, mensaje_id: int, otro_id: int) -> bool:
    """El dueño comparte el mensaje (solo lectura) con un compañero del despacho."""
    conn = get_connection()
    try:
        if _dueno_del_mensaje(conn, mensaje_id) != usuario_id:
            return False
        destino = _companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        ya = conn.execute("SELECT 1 FROM correo_compartidos WHERE mensaje_id = ? AND usuario_id = ?", (mensaje_id, destino)).fetchone()
        if ya is None:
            if conn.execute("SELECT COUNT(*) FROM correo_compartidos WHERE mensaje_id = ?", (mensaje_id,)).fetchone()[0] >= MAX_COMPARTIDOS_POR_MENSAJE:
                return False
            conn.execute(
                "INSERT INTO correo_compartidos (mensaje_id, usuario_id, compartido_en) VALUES (?, ?, ?)",
                (mensaje_id, destino, now_iso()),
            )
            _auditar_correo_equipo(conn, mensaje_id, usuario_id, "compartir", str(destino))
            conn.commit()
        return True
    finally:
        conn.close()


def dejar_de_compartir_correo(usuario_id: int, mensaje_id: int, otro_id: int) -> bool:
    """El dueño quita a alguien; cada persona puede salirse. No toca la asignación."""
    conn = get_connection()
    try:
        if _dueno_del_mensaje(conn, mensaje_id) != usuario_id and otro_id != usuario_id:
            return False
        cur = conn.execute("DELETE FROM correo_compartidos WHERE mensaje_id = ? AND usuario_id = ?", (mensaje_id, otro_id))
        if cur.rowcount > 0:
            _auditar_correo_equipo(conn, mensaje_id, usuario_id, "quitar", str(otro_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def cambiar_estado_correo_equipo(usuario_id: int, mensaje_id: int, estado: str) -> bool:
    """'abierto' o 'resuelto': lo cambia el dueño o quien lo tiene asignado."""
    if estado not in ("abierto", "resuelto") or rol_en_correo(usuario_id, mensaje_id) not in ("dueno", "asignado"):
        return False
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO correo_equipo (mensaje_id, asignado_a, asignado_por, estado, actualizado_en)
               VALUES (?, NULL, ?, ?, ?)
               ON CONFLICT(mensaje_id) DO UPDATE SET estado = excluded.estado, actualizado_en = excluded.actualizado_en""",
            (mensaje_id, usuario_id, estado, now_iso()),
        )
        _auditar_correo_equipo(conn, mensaje_id, usuario_id, "estado", estado)
        conn.commit()
        return True
    finally:
        conn.close()


def estado_correo_equipo(mensaje_id: int) -> dict:
    """Asignación, estado y personas con acceso de un mensaje (sin comprobar permisos:
    el llamante ya ha comprobado que el usuario lo ve)."""
    conn = get_connection()
    try:
        eq = conn.execute(
            """SELECT e.asignado_a, e.estado, e.actualizado_en,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS asignado_nombre
               FROM correo_equipo e LEFT JOIN usuarios u ON u.id = e.asignado_a
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = e.asignado_a WHERE e.mensaje_id = ?""",
            (mensaje_id,),
        ).fetchone()
        compartidos = [dict(f) for f in conn.execute(
            """SELECT c.usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
               FROM correo_compartidos c JOIN usuarios u ON u.id = c.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = c.usuario_id
               WHERE c.mensaje_id = ? ORDER BY nombre""",
            (mensaje_id,),
        )]
    finally:
        conn.close()
    base = dict(eq) if eq else {"asignado_a": None, "estado": "abierto", "actualizado_en": None, "asignado_nombre": None}
    base["compartidos"] = compartidos
    return base


def obtener_correo_equipo(usuario_id: int, mensaje_id: int) -> dict | None:
    """El mensaje (sin HTML ni adjuntos: solo texto) para quien lo ve por estar
    asignado o compartido, con su rol y el nombre del dueño."""
    rol = rol_en_correo(usuario_id, mensaje_id)
    if rol is None:
        return None
    conn = get_connection()
    try:
        f = conn.execute(
            """SELECT m.id, m.asunto, m.remitente, m.destinatarios, m.fecha, m.cuerpo_texto,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS dueno_nombre, c.usuario_id AS dueno_id
               FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               JOIN usuarios u ON u.id = c.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = c.usuario_id
               WHERE m.id = ?""",
            (mensaje_id,),
        ).fetchone()
    finally:
        conn.close()
    if f is None:
        return None
    d = dict(f)
    d["rol"] = rol
    d.update({k: v for k, v in estado_correo_equipo(mensaje_id).items()})
    return d


def listar_correo_equipo(usuario_id: int, vista: str = "asignados") -> list[dict]:
    """'asignados' (a mí), 'compartidos' (conmigo) o 'enviados' (los míos que he
    asignado o compartido). Lo resuelto va al final."""
    conn = get_connection()
    try:
        base = """SELECT m.id, m.asunto, m.remitente, m.fecha, COALESCE(e.estado, 'abierto') AS estado, e.asignado_a,
                         COALESCE(NULLIF(pfd.nombre_mostrado, ''), ud.email) AS dueno_nombre,
                         COALESCE(NULLIF(pfa.nombre_mostrado, ''), ua.email) AS asignado_nombre,
                         (SELECT COUNT(*) FROM correo_notas_internas n WHERE n.mensaje_id = m.id) AS n_notas
                  FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
                  JOIN usuarios ud ON ud.id = c.usuario_id LEFT JOIN usuario_perfil pfd ON pfd.usuario_id = c.usuario_id
                  LEFT JOIN correo_equipo e ON e.mensaje_id = m.id
                  LEFT JOIN usuarios ua ON ua.id = e.asignado_a LEFT JOIN usuario_perfil pfa ON pfa.usuario_id = e.asignado_a"""
        if vista == "compartidos":
            donde, params = "WHERE m.id IN (SELECT mensaje_id FROM correo_compartidos WHERE usuario_id = ?)", [usuario_id]
        elif vista == "enviados":
            donde, params = (
                "WHERE c.usuario_id = ? AND (e.asignado_a IS NOT NULL OR m.id IN (SELECT mensaje_id FROM correo_compartidos))",
                [usuario_id],
            )
        else:
            donde, params = "WHERE e.asignado_a = ?", [usuario_id]
        filas = conn.execute(
            f"{base} {donde} ORDER BY (COALESCE(e.estado, 'abierto') = 'resuelto'), m.fecha DESC LIMIT 200", params
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def contar_correo_asignado_abierto(usuario_id: int) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM correo_equipo WHERE asignado_a = ? AND estado = 'abierto'", (usuario_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


NOTA_INTERNA_MAX_CARACTERES = 2000


def anadir_nota_interna_correo(usuario_id: int, mensaje_id: int, texto: str) -> int | None:
    """Nota interna del equipo sobre un mensaje: la puede escribir cualquiera que lo vea."""
    texto = (texto or "").strip()[:NOTA_INTERNA_MAX_CARACTERES]
    if not texto or rol_en_correo(usuario_id, mensaje_id) is None:
        return None
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM correo_notas_internas WHERE mensaje_id = ?", (mensaje_id,)).fetchone()[0] >= MAX_NOTAS_INTERNAS_POR_MENSAJE:
            return None
        cur = conn.execute(
            "INSERT INTO correo_notas_internas (mensaje_id, usuario_id, texto, creado_en) VALUES (?, ?, ?, ?)",
            (mensaje_id, usuario_id, texto, now_iso()),
        )
        _auditar_correo_equipo(conn, mensaje_id, usuario_id, "nota")
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_notas_internas_correo(usuario_id: int, mensaje_id: int) -> list[dict]:
    rol = rol_en_correo(usuario_id, mensaje_id)
    if rol is None:
        return []
    conn = get_connection()
    try:
        return [
            {**dict(f), "mia": f["usuario_id"] == usuario_id, "puede_borrar": f["usuario_id"] == usuario_id or rol == "dueno"}
            for f in conn.execute(
                """SELECT n.id, n.usuario_id, n.texto, n.creado_en, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
                   FROM correo_notas_internas n JOIN usuarios u ON u.id = n.usuario_id
                   LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
                   WHERE n.mensaje_id = ? ORDER BY n.id""",
                (mensaje_id,),
            )
        ]
    finally:
        conn.close()


def eliminar_nota_interna_correo(usuario_id: int, mensaje_id: int, nota_id: int) -> bool:
    rol = rol_en_correo(usuario_id, mensaje_id)
    if rol is None:
        return False
    conn = get_connection()
    try:
        n = conn.execute("SELECT usuario_id FROM correo_notas_internas WHERE id = ? AND mensaje_id = ?", (nota_id, mensaje_id)).fetchone()
        if n is None or not (n["usuario_id"] == usuario_id or rol == "dueno"):
            return False
        conn.execute("DELETE FROM correo_notas_internas WHERE id = ?", (nota_id,))
        _auditar_correo_equipo(conn, mensaje_id, usuario_id, "nota_borrada")
        conn.commit()
        return True
    finally:
        conn.close()


# ---- Recordatorios por tarea ----------------------------------------------------

CANALES_RECORDATORIO = ("app", "correo", "ntfy")


def _canales_validos(canales) -> str:
    elegidos = [c for c in CANALES_RECORDATORIO if c in (canales or [])]
    return ",".join(elegidos or ["app"])


def anadir_recordatorio_tarea(usuario_id: int, tarea_id: int, avisar_en: str, canales=None) -> int | None:
    """Pone un recordatorio propio en una tarea que el usuario ve. `avisar_en`
    es una fecha y hora ISO (YYYY-MM-DDTHH:MM). None si no procede."""
    if rol_en_tarea(usuario_id, tarea_id) is None:
        return None
    try:
        momento = datetime.fromisoformat(avisar_en.strip().replace(" ", "T")[:19])
    except (ValueError, AttributeError):
        return None
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tarea_recordatorios (tarea_id, usuario_id, avisar_en, canales, creado_en) VALUES (?, ?, ?, ?, ?)",
            (tarea_id, usuario_id, momento.isoformat(timespec="seconds"), _canales_validos(canales), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def recordatorio_relativo(usuario_id: int, tarea_id: int, clave: str, canales=None) -> int | None:
    """Atajos respecto al vencimiento: 'al_vencer', '1h_antes', '1d_antes'. None si la
    tarea no tiene vencimiento."""
    tarea = obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if tarea is None or not tarea["fecha_vencimiento"]:
        return None
    try:
        vence = datetime.fromisoformat(tarea["fecha_vencimiento"].replace(" ", "T")[:19])
    except ValueError:
        return None
    restas = {"al_vencer": timedelta(0), "1h_antes": timedelta(hours=1), "1d_antes": timedelta(days=1)}
    if clave not in restas:
        return None
    return anadir_recordatorio_tarea(usuario_id, tarea_id, (vence - restas[clave]).isoformat(timespec="seconds"), canales)


def listar_recordatorios_tarea(usuario_id: int, tarea_id: int) -> list[dict]:
    """Los recordatorios del propio usuario en esa tarea (si la ve)."""
    if rol_en_tarea(usuario_id, tarea_id) is None:
        return []
    conn = get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT * FROM tarea_recordatorios WHERE tarea_id = ? AND usuario_id = ? ORDER BY avisar_en",
            (tarea_id, usuario_id),
        )]
    finally:
        conn.close()


def eliminar_recordatorio_tarea(usuario_id: int, recordatorio_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM tarea_recordatorios WHERE id = ? AND usuario_id = ?", (recordatorio_id, usuario_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def posponer_recordatorio_tarea(usuario_id: int, recordatorio_id: int, opcion: str, ahora: datetime | None = None) -> bool:
    """Reprograma un recordatorio propio (vuelve a estar pendiente): '1h' (dentro de
    una hora), 'manana' (mañana a las 9:00) o '1s' (dentro de una semana, 9:00)."""
    ahora = ahora or datetime.now()
    if opcion == "1h":
        nuevo = ahora + timedelta(hours=1)
    elif opcion == "manana":
        nuevo = (ahora + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif opcion == "1s":
        nuevo = (ahora + timedelta(days=7)).replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        return False
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tarea_recordatorios SET avisar_en = ?, enviado_en = NULL WHERE id = ? AND usuario_id = ?",
            (nuevo.isoformat(timespec="seconds"), recordatorio_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def recordatorios_de_tarea_pendientes_de_aviso(ahora: datetime | None = None) -> list[dict]:
    """Recordatorios cuyo momento ya ha llegado y no se han enviado, de tareas que
    siguen abiertas, con los datos para avisar."""
    ahora = ahora or datetime.now()
    conn = get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT r.id, r.tarea_id, r.usuario_id, r.avisar_en, r.canales, t.asunto, t.fecha_vencimiento,
                      u.email, tn.ntfy_topic, tn.ntfy_token
               FROM tarea_recordatorios r JOIN tareas_outlook t ON t.id = r.tarea_id
               JOIN usuarios u ON u.id = r.usuario_id LEFT JOIN tenants tn ON tn.id = u.tenant_id
               WHERE r.enviado_en IS NULL AND r.avisar_en <= ? AND t.papelera_en IS NULL AND t.estado != 'completada'
               ORDER BY r.avisar_en""",
            (ahora.isoformat(timespec="seconds"),),
        )]
    finally:
        conn.close()


def reservar_recordatorio_tarea(recordatorio_id: int) -> bool:
    """Se queda con el recordatorio de forma atómica: devuelve True solo a UNA
    de las llamadas (hilo o proceso) que lo intenten a la vez; el resto ve False
    y no lo envía, así no hay avisos duplicados aunque haya varios workers."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE tarea_recordatorios SET enviado_en = ? WHERE id = ? AND enviado_en IS NULL", (now_iso(), recordatorio_id)
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def marcar_recordatorio_tarea_enviado(recordatorio_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE tarea_recordatorios SET enviado_en = ? WHERE id = ?", (now_iso(), recordatorio_id))
        conn.commit()
    finally:
        conn.close()


def carga_equipo(usuario_id: int) -> list[dict]:
    """Carga de trabajo por persona sobre las tareas abiertas que el usuario ve
    (propias, asignadas a él o compartidas con él). Cada tarea cuenta para su
    responsable: el asignado o, si no hay, el dueño. Así nunca se revela nada de
    tareas privadas de otros. Ordenado por más atrasadas y más abiertas."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT COALESCE(t.asignada_a, t.usuario_id) AS responsable_id,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre,
                      COUNT(*) AS abiertas,
                      SUM(CASE WHEN t.fecha_vencimiento IS NOT NULL AND substr(t.fecha_vencimiento, 1, 10) < ? THEN 1 ELSE 0 END) AS atrasadas,
                      SUM(CASE WHEN substr(t.fecha_vencimiento, 1, 10) = ? THEN 1 ELSE 0 END) AS hoy,
                      SUM(CASE WHEN t.estado = 'en_progreso' THEN 1 ELSE 0 END) AS en_progreso
               FROM tareas_outlook t
               JOIN usuarios u ON u.id = COALESCE(t.asignada_a, t.usuario_id)
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id
               WHERE t.papelera_en IS NULL AND t.estado != 'completada'
                 AND (t.usuario_id = ? OR t.asignada_a = ?
                      OR t.id IN (SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?))
               GROUP BY responsable_id ORDER BY atrasadas DESC, abiertas DESC, nombre""",
            (hoy, hoy, usuario_id, usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def actividad_de_tarea(usuario_id: int, tarea_id: int, limite: int = 40) -> list[dict]:
    """Historial de la tarea (lo más reciente primero), solo para quien la ve."""
    if rol_en_tarea(usuario_id, tarea_id) is None:
        return []
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT a.tipo, a.detalle, a.creado_en, a.usuario_id,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM tarea_actividad a JOIN usuarios u ON u.id = a.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = a.usuario_id
               WHERE a.tarea_id = ? ORDER BY a.id DESC LIMIT ?""",
            (tarea_id, limite),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def tiempo_equipo_tarea(usuario_id: int, tarea_id: int) -> dict:
    """Tiempo registrado en la tarea por cada persona (cronómetros finalizados) y
    el total del equipo. Solo si el usuario la ve; {'total': 0, 'personas': []} si no."""
    vacio = {"total": 0, "personas": []}
    if rol_en_tarea(usuario_id, tarea_id) is None:
        return vacio
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT t.usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre,
                      COALESCE(SUM(t.duracion_segundos), 0) AS segundos
               FROM tareas t JOIN usuarios u ON u.id = t.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = t.usuario_id
               WHERE t.tarea_outlook_id = ? AND t.estado = 'finalizada' AND t.papelera_en IS NULL
               GROUP BY t.usuario_id ORDER BY segundos DESC""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()
    personas = [dict(f) for f in filas if f["segundos"]]
    return {"total": sum(p["segundos"] for p in personas), "personas": personas}


def asignar_tarea_outlook(usuario_id: int, tarea_id: int, asignada_a: int | None) -> bool:
    """Asigna la tarea a un compañero del mismo despacho (o la desasigna con
    None). Solo su dueño. Devuelve False si no es suya o el compañero no es
    válido."""
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
        ).fetchone() is None:
            return False
        destino = _companero_del_tenant(conn, usuario_id, asignada_a)
        if asignada_a is not None and destino is None:
            return False
        conn.execute(
            "UPDATE tareas_outlook SET asignada_a = ?, actualizada_en = ? WHERE id = ?", (destino, now_iso(), tarea_id)
        )
        conn.commit()
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_id, "asignada", (nombre_mostrado_usuario(destino) or "") if destino else "")
    if destino is not None:
        _emitir_evento(usuario_id, "tarea.asignada", {"tarea_id": tarea_id, "asignada_a": destino})
    return True


# ---- Cronómetro enlazado a una tarea de la lista ---------------------------

def iniciar_cronometro_tarea_outlook(usuario_id: int, tarea_id: int, categoria_id: int | None = None) -> int:
    """Pone en marcha un registro de tiempo (tareas) enlazado a esta tarea de
    la lista. Quien lo inicia es quien registra el tiempo. Necesita un
    proyecto: el de la tarea o el indicado."""
    tarea = obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if tarea is None or not puede_trabajar_tarea(usuario_id, tarea_id):
        raise ValueError("La tarea no existe.")
    if tarea_bloqueada(tarea_id):
        raise ValueError("Esta tarea espera a otras que todavía no están completadas.")
    conn = get_connection()
    try:
        en_marcha = conn.execute(
            "SELECT 1 FROM tareas WHERE tarea_outlook_id = ? AND usuario_id = ? AND estado IN ('en_curso', 'pausada') "
            "AND papelera_en IS NULL",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()
    if en_marcha:
        raise ValueError("Esta tarea ya tiene el cronómetro en marcha.")
    proyecto = categoria_id or tarea["categoria_id"]
    if proyecto is None:
        raise ValueError("Elige un proyecto para registrar el tiempo de esta tarea.")
    nuevo = crear_tarea(usuario_id, tarea["asunto"], proyecto, "duracion", tarea_outlook_id=tarea_id)
    registrar_actividad_tarea(usuario_id, tarea_id, "cronometro")
    if tarea["estado"] == "no_iniciada":
        cambiar_estado_tarea_outlook(usuario_id, tarea_id, "en_progreso")
    return nuevo


def cronometros_de_tareas_outlook(usuario_id: int, tarea_ids: list[int]) -> dict[int, dict]:
    """Por tarea de la lista: el tiempo ya registrado por este usuario
    (`total_segundos`, cronómetros finalizados) y su cronómetro en marcha o
    en pausa, si lo hay (`activo`, con el formato de tareas_activas)."""
    if not tarea_ids:
        return {}
    resultado = {i: {"total_segundos": 0, "activo": None} for i in tarea_ids}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        for f in conn.execute(
            f"""SELECT tarea_outlook_id, COALESCE(SUM(duracion_segundos), 0) AS total FROM tareas
                WHERE usuario_id = ? AND estado = 'finalizada' AND papelera_en IS NULL
                  AND tarea_outlook_id IN ({marcas}) GROUP BY tarea_outlook_id""",
            [usuario_id, *tarea_ids],
        ):
            resultado[f["tarea_outlook_id"]]["total_segundos"] = f["total"]
    finally:
        conn.close()
    for activa in tareas_activas(usuario_id):
        enlace = activa.get("tarea_outlook_id")
        if enlace in resultado:
            resultado[enlace]["activo"] = activa
    return resultado


# ---- Checklist (subtareas) -------------------------------------------------

CHECKLIST_MAX_ITEMS = 50
CHECKLIST_MAX_CARACTERES = 200


def listar_checklist(tarea_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tarea_checklist WHERE tarea_outlook_id = ? ORDER BY orden, id", (tarea_id,)
        ).fetchall()
    finally:
        conn.close()


def resumen_checklist(tarea_ids: list[int]) -> dict[int, tuple[int, int]]:
    """{tarea_id: (hechas, total)} solo para las tareas que tienen items."""
    if not tarea_ids:
        return {}
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        return {
            f["tarea_outlook_id"]: (f["hechas"], f["total"])
            for f in conn.execute(
                f"""SELECT tarea_outlook_id, SUM(hecha) AS hechas, COUNT(*) AS total FROM tarea_checklist
                    WHERE tarea_outlook_id IN ({marcas}) GROUP BY tarea_outlook_id""",
                tarea_ids,
            )
        }
    finally:
        conn.close()


def _recalcular_porcentaje_checklist(conn: sqlite3.Connection, tarea_id: int) -> None:
    fila = conn.execute(
        "SELECT SUM(hecha) AS hechas, COUNT(*) AS total FROM tarea_checklist WHERE tarea_outlook_id = ?", (tarea_id,)
    ).fetchone()
    if fila["total"]:
        conn.execute(
            "UPDATE tareas_outlook SET porcentaje_completado = ? WHERE id = ? AND estado != 'completada'",
            (round(100 * (fila["hechas"] or 0) / fila["total"]), tarea_id),
        )


def agregar_item_checklist(usuario_id: int, tarea_id: int, texto: str) -> int | None:
    """El dueño o un colaborador. Devuelve el id, o None si no procede."""
    texto = " ".join((texto or "").split())[:CHECKLIST_MAX_CARACTERES]
    if not texto:
        return None
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
        ).fetchone() is None and not (
            _es_colaborador(conn, usuario_id, tarea_id)
            and conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        ):
            return None
        actuales = conn.execute("SELECT COUNT(*) AS n, COALESCE(MAX(orden), 0) AS m FROM tarea_checklist WHERE tarea_outlook_id = ?", (tarea_id,)).fetchone()
        if actuales["n"] >= CHECKLIST_MAX_ITEMS:
            return None
        cur = conn.execute(
            "INSERT INTO tarea_checklist (tarea_outlook_id, texto, orden) VALUES (?, ?, ?)", (tarea_id, texto, actuales["m"] + 1)
        )
        _recalcular_porcentaje_checklist(conn, tarea_id)
        conn.commit()
        nuevo_item = cur.lastrowid
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_id, "subtarea_nueva", texto)
    return nuevo_item

def alternar_item_checklist(usuario_id: int, item_id: int) -> bool:
    """Marca o desmarca un item: lo puede hacer el dueño o quien tiene la tarea asignada."""
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT i.tarea_outlook_id FROM tarea_checklist i JOIN tareas_outlook t ON t.id = i.tarea_outlook_id
               WHERE i.id = ? AND (t.usuario_id = ? OR t.asignada_a = ? OR t.id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))
                 AND t.papelera_en IS NULL""",
            (item_id, usuario_id, usuario_id, usuario_id),
        ).fetchone()
        if fila is None:
            return False
        conn.execute("UPDATE tarea_checklist SET hecha = 1 - hecha WHERE id = ?", (item_id,))
        _recalcular_porcentaje_checklist(conn, fila["tarea_outlook_id"])
        conn.commit()
        item = conn.execute("SELECT texto, hecha FROM tarea_checklist WHERE id = ?", (item_id,)).fetchone()
        tarea_del_item = fila["tarea_outlook_id"]
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_del_item, "subtarea_hecha" if item["hecha"] else "subtarea_reabierta", item["texto"])
    return True

def eliminar_item_checklist(usuario_id: int, item_id: int) -> bool:
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT i.tarea_outlook_id FROM tarea_checklist i JOIN tareas_outlook t ON t.id = i.tarea_outlook_id
               WHERE i.id = ? AND (t.usuario_id = ? OR t.id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))""",
            (item_id, usuario_id, usuario_id),
        ).fetchone()
        if fila is None:
            return False
        conn.execute("DELETE FROM tarea_checklist WHERE id = ?", (item_id,))
        _recalcular_porcentaje_checklist(conn, fila["tarea_outlook_id"])
        conn.commit()
        return True
    finally:
        conn.close()


def tareas_para_hoy(usuario_id: int) -> dict[str, list]:
    """"Mi día": lo pendiente (propio o asignado) que hay que mirar hoy.
    `vencidas` (vencimiento anterior a hoy), `hoy` (vence hoy), `en_progreso`
    (en progreso sin vencimiento hoy/anterior) y `asignadas` (asignadas a mí,
    pendientes, que no estén ya en otra sección)."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    vistas: set[int] = set()
    secciones: dict[str, list] = {"vencidas": [], "hoy": [], "en_progreso": [], "asignadas": [], "compartidas": []}
    conn = get_connection()
    try:
        compartidas_conmigo = {f["tarea_id"] for f in conn.execute(
            "SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?", (usuario_id,))}
    finally:
        conn.close()
    for t in listar_tareas_outlook(usuario_id, excluir_completadas=True, incluir_asignadas=True):
        fecha = (t["fecha_vencimiento"] or "")[:10]
        if fecha and fecha < hoy:
            secciones["vencidas"].append(t)
        elif fecha == hoy:
            secciones["hoy"].append(t)
        elif t["estado"] == "en_progreso":
            secciones["en_progreso"].append(t)
        elif t["asignada_a"] == usuario_id:
            secciones["asignadas"].append(t)
        elif t["id"] in compartidas_conmigo and t["usuario_id"] != usuario_id:
            secciones["compartidas"].append(t)  # compartidas conmigo, sin fecha ni en curso
        else:
            continue
        vistas.add(t["id"])
    return secciones


def contar_mi_dia(usuario_id: int) -> tuple[int, int]:
    """(vencidas, de hoy) de "Mi día" SIN cargar las tareas: lo pide la barra
    superior en cada página y antes traía todas las tareas abiertas (con sus
    JOINs) solo para contarlas. Mismo criterio que tareas_para_hoy."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT COALESCE(SUM(substr(t.fecha_vencimiento, 1, 10) < ?), 0) AS vencidas,
                      COALESCE(SUM(substr(t.fecha_vencimiento, 1, 10) = ?), 0) AS hoy
               FROM tareas_outlook t
               WHERE t.papelera_en IS NULL AND t.estado != 'completada'
                 AND t.fecha_vencimiento IS NOT NULL AND substr(t.fecha_vencimiento, 1, 10) <= ?
                 AND (t.usuario_id = ? OR t.asignada_a = ?
                      OR t.id IN (SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?))""",
            (hoy, hoy, hoy, usuario_id, usuario_id, usuario_id),
        ).fetchone()
        return int(fila["vencidas"]), int(fila["hoy"])
    finally:
        conn.close()


def eliminar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas_outlook SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_marca_papelera(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tareas_outlook SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_outlook_definitivamente(usuario_id: int, tarea_id: int) -> None:
    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)).fetchone():
            conn.execute("DELETE FROM tareas_participantes WHERE tarea_id = ?", (tarea_id,))
            conn.execute("DELETE FROM tarea_comentarios WHERE tarea_id = ?", (tarea_id,))
            conn.execute("DELETE FROM tarea_actividad WHERE tarea_id = ?", (tarea_id,))
            conn.execute("DELETE FROM tareas_dependencias WHERE tarea_id = ? OR depende_de_id = ?", (tarea_id, tarea_id))
            conn.execute("DELETE FROM tarea_recordatorios WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def listar_categorias_outlook(usuario_id: int) -> list[str]:
    """Nombres de categoría (estilo "Categories" de Outlook) usados hasta ahora."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT DISTINCT categoria_outlook FROM tareas_outlook
               WHERE usuario_id = ? AND categoria_outlook IS NOT NULL AND papelera_en IS NULL
               ORDER BY categoria_outlook""",
            (usuario_id,),
        ).fetchall()
        return [f["categoria_outlook"] for f in filas]
    finally:
        conn.close()


# --- Calendario fiscal (clientes_fiscales + vencimientos_fiscales) ----------
# A diferencia de todo lo de arriba, estas dos tablas se filtran por
# tenant_id, no por usuario_id -- son datos de la GESTORÍA (el tenant), no
# de un miembro del equipo concreto. Primera funcionalidad de Guilda Work
# con este patrón; cualquier función nueva aquí recibe tenant_id como
# primer filtro (WHERE tenant_id = ?), igual que las de arriba reciben
# usuario_id -- las rutas siempre pasan g.tenant_id, nunca un valor del
# request (ver app/rutas_fiscal.py).

CAMPOS_CLIENTE_FISCAL = (
    "nombre", "nif", "notas", "modelos_fiscales", "generacion_automatica", "espocrm_cuenta_id", "email",
    "facturascripts_cliente_codigo", "pais", "recordatorios_portal", "idioma",
)
_MINUTOS_VIDA_ACCESO_PORTAL = 15
MIME_PERMITIDOS_DOCUMENTO_VENCIMIENTO = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf",
}
TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO = 8 * 1024 * 1024
CAMPOS_VENCIMIENTO_FISCAL = (
    "usuario_id", "modelo", "periodo", "fecha_limite", "estado", "notas", "documenso_documento_id",
    "documento_solicitado",
)


def serializar_modelos_fiscales(modelos: list[str] | None) -> str | None:
    """Pública (no `_`) porque tanto crear_cliente_fiscal como la ruta de
    edición (app/rutas_fiscal.py, que llama a editar_cliente_fiscal con el
    whitelist genérico CAMPOS_CLIENTE_FISCAL) necesitan serializar antes de
    guardar."""
    return json.dumps(modelos) if modelos else None


def modelos_fiscales_de_cliente(cliente: sqlite3.Row) -> list[str]:
    """Deserializa clientes_fiscales.modelos_fiscales -- fila puede venir de
    antes de que existiera la columna (None) o con JSON corrupto en teoría
    imposible (siempre se escribe con serializar_modelos_fiscales), pero se
    protege igual con un try/except silencioso, mismo criterio defensivo
    que el resto de columnas JSON de este módulo."""
    valor = cliente["modelos_fiscales"] if "modelos_fiscales" in cliente.keys() else None
    if not valor:
        return []
    try:
        return json.loads(valor)
    except (TypeError, ValueError):
        return []


def crear_cliente_fiscal(
    tenant_id: int, nombre: str, nif: str | None = None, notas: str | None = None,
    modelos_fiscales: list[str] | None = None, email: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO clientes_fiscales (tenant_id, nombre, nif, notas, modelos_fiscales, email, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id, nombre.strip(), (nif or "").strip() or None, (notas or "").strip() or None,
                serializar_modelos_fiscales(modelos_fiscales), (email or "").strip() or None, now_iso(),
            ),
        )
        conn.commit()
        cliente_id = cur.lastrowid
    finally:
        conn.close()
    _reindexar_cliente_fiscal(tenant_id, cliente_id)
    return cliente_id


def _reindexar_cliente_fiscal(tenant_id: int, cliente_id: int) -> None:
    """Falla en silencio, mismo criterio que _reindexar_tarea/_reindexar_nota
    -- una mejora de UX (buscador global), nunca debe romper el alta/edición
    del cliente en sí."""
    from . import busqueda
    try:
        cliente = obtener_cliente_fiscal(tenant_id, cliente_id)
        if cliente is not None:
            busqueda.indexar_cliente_fiscal(dict(cliente))
    except busqueda.ErrorBusqueda:
        pass


def _quitar_cliente_fiscal_del_indice(cliente_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("cliente_fiscal", cliente_id)
    except busqueda.ErrorBusqueda:
        pass


def listar_clientes_fiscales(tenant_id: int, q: str | None = None, pais: str | None = None) -> list[sqlite3.Row]:
    """`q` filtra por nombre/NIF (LIKE, insensible a mayúsculas) -- tabla
    pequeña por tenant, no hace falta Meilisearch para esto. `pais` filtra
    por país de tributación exacto (ver app/vencimientos_fiscales.py)."""
    conn = get_connection()
    try:
        cond = ["tenant_id = ?", "papelera_en IS NULL"]
        params: list = [tenant_id]
        if q:
            cond.append("(nombre LIKE ? OR nif LIKE ?)")
            comodin = f"%{q.strip()}%"
            params.extend([comodin, comodin])
        if pais:
            cond.append("pais = ?")
            params.append(pais)
        return conn.execute(
            f"SELECT * FROM clientes_fiscales WHERE {' AND '.join(cond)} ORDER BY nombre", params,
        ).fetchall()
    finally:
        conn.close()


def paises_clientes_fiscales(tenant_id: int) -> list[str]:
    """Países de tributación en uso por los clientes de este tenant
    (distintos, orden alfabético) -- para el <select> de filtro por país
    en /fiscal/clientes y /fiscal/vencimientos. Con un solo país en uso
    (el caso normal hoy) el filtro no aporta mucho, pero no hace falta
    tocar esta función cuando se añada soporte a un segundo país."""
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT DISTINCT pais FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY pais",
            (tenant_id,),
        ).fetchall()
        return [f["pais"] for f in filas]
    finally:
        conn.close()


def obtener_cliente_fiscal(tenant_id: int, cliente_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL",
            (cliente_id, tenant_id),
        ).fetchone()
    finally:
        conn.close()


def editar_cliente_fiscal(tenant_id: int, cliente_id: int, **campos) -> None:
    columnas = [c for c in campos if c in CAMPOS_CLIENTE_FISCAL]
    if not columnas:
        return
    conn = get_connection()
    try:
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        conn.execute(
            f"UPDATE clientes_fiscales SET {asignaciones} WHERE id = ? AND tenant_id = ?",
            [*valores, cliente_id, tenant_id],
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_cliente_fiscal(tenant_id, cliente_id)


def eliminar_cliente_fiscal(tenant_id: int, cliente_id: int) -> None:
    """Manda el cliente a la papelera (no lo borra de verdad). No toca sus
    vencimientos -- se quedan huérfanos visualmente (el cliente ya no
    aparece en el listado) pero no se pierden, igual que pasa con una
    categoría y sus tareas."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE clientes_fiscales SET papelera_en = ? WHERE id = ? AND tenant_id = ?",
            (_marca_papelera(), cliente_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()
    _quitar_cliente_fiscal_del_indice(cliente_id)


def restaurar_cliente_fiscal(tenant_id: int, cliente_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE clientes_fiscales SET papelera_en = NULL WHERE id = ? AND tenant_id = ?",
            (cliente_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_cliente_fiscal(tenant_id, cliente_id)


def eliminar_cliente_fiscal_definitivamente(tenant_id: int, cliente_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    _quitar_cliente_fiscal_del_indice(cliente_id)


def crear_vencimiento_fiscal(
    tenant_id: int, cliente_fiscal_id: int, modelo: str, periodo: str, fecha_limite: str,
    usuario_id: int | None = None, notas: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO vencimientos_fiscales
               (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, notas, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tenant_id, cliente_fiscal_id, usuario_id, modelo.strip(), periodo.strip(),
                fecha_limite, (notas or "").strip() or None, now_iso(),
            ),
        )
        conn.commit()
        vencimiento_id = cur.lastrowid
    finally:
        conn.close()
    _reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)
    return vencimiento_id


def _reindexar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> None:
    from . import busqueda
    try:
        vencimiento = obtener_vencimiento_fiscal(tenant_id, vencimiento_id)
        if vencimiento is not None:
            busqueda.indexar_vencimiento_fiscal(dict(vencimiento))
    except busqueda.ErrorBusqueda:
        pass


def _quitar_vencimiento_fiscal_del_indice(vencimiento_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("vencimiento_fiscal", vencimiento_id)
    except busqueda.ErrorBusqueda:
        pass


def listar_vencimientos_fiscales(
    tenant_id: int,
    desde: str | None = None,
    hasta: str | None = None,
    estado: str | None = None,
    cliente_fiscal_id: int | None = None,
    pais: str | None = None,
) -> list[sqlite3.Row]:
    """`desde`/`hasta` filtran por fecha_limite (YYYY-MM-DD, inclusive/
    exclusive respectivamente, mismo criterio que listar_tareas_outlook).
    `pais` filtra por el país de tributación del CLIENTE (columna `c.pais`,
    no hay columna propia en vencimientos_fiscales -- ver
    app/vencimientos_fiscales.py)."""
    conn = get_connection()
    try:
        cond = ["v.tenant_id = ?", "v.papelera_en IS NULL"]
        params: list = [tenant_id]
        if desde:
            cond.append("v.fecha_limite >= ?"); params.append(desde)
        if hasta:
            cond.append("v.fecha_limite < ?"); params.append(_fecha_exclusiva(hasta))
        if estado:
            cond.append("v.estado = ?"); params.append(estado)
        if cliente_fiscal_id:
            cond.append("v.cliente_fiscal_id = ?"); params.append(cliente_fiscal_id)
        if pais:
            cond.append("c.pais = ?"); params.append(pais)
        where = " AND ".join(cond)
        return conn.execute(
            f"""SELECT v.*, c.nombre AS cliente_nombre
                FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
                WHERE {where}
                ORDER BY v.fecha_limite""",
            params,
        ).fetchall()
    finally:
        conn.close()


def tenant_id_de_vencimiento_fiscal(vencimiento_id: int) -> int | None:
    """Resuelve el tenant de un vencimiento por su solo id -- usado por
    el webhook de Stripe (app/rutas_stripe_webhook.py), que no tiene
    ningún contexto de sesión/tenant propio para filtrar por él."""
    conn = get_connection()
    try:
        fila = conn.execute("SELECT tenant_id FROM vencimientos_fiscales WHERE id = ?", (vencimiento_id,)).fetchone()
        return fila["tenant_id"] if fila else None
    finally:
        conn.close()


def obtener_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT v.*, c.nombre AS cliente_nombre
               FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               WHERE v.id = ? AND v.tenant_id = ? AND v.papelera_en IS NULL""",
            (vencimiento_id, tenant_id),
        ).fetchone()
    finally:
        conn.close()


def editar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int, **campos) -> None:
    columnas = [c for c in campos if c in CAMPOS_VENCIMIENTO_FISCAL]
    if not columnas:
        return
    conn = get_connection()
    try:
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        conn.execute(
            f"UPDATE vencimientos_fiscales SET {asignaciones}, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
            [*valores, now_iso(), vencimiento_id, tenant_id],
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)


def marcar_presentado_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE vencimientos_fiscales SET estado = 'presentado', actualizado_en = ?
               WHERE id = ? AND tenant_id = ?""",
            (now_iso(), vencimiento_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)


def eliminar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE vencimientos_fiscales SET papelera_en = ? WHERE id = ? AND tenant_id = ?",
            (_marca_papelera(), vencimiento_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()
    _quitar_vencimiento_fiscal_del_indice(vencimiento_id)


def restaurar_vencimiento_fiscal(tenant_id: int, vencimiento_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE vencimientos_fiscales SET papelera_en = NULL WHERE id = ? AND tenant_id = ?",
            (vencimiento_id, tenant_id),
        )
        conn.commit()
    finally:
        conn.close()
    _reindexar_vencimiento_fiscal(tenant_id, vencimiento_id)


def eliminar_vencimiento_fiscal_definitivamente(tenant_id: int, vencimiento_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM vencimientos_fiscales WHERE id = ? AND tenant_id = ?", (vencimiento_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    _quitar_vencimiento_fiscal_del_indice(vencimiento_id)


def marcar_recordatorio_vencimiento_fiscal_enviado(vencimiento_id: int) -> None:
    """Llamada por el hilo de recordatorio (app/main.py) tras un push
    correcto -- sin tenant_id porque ese hilo cruza todos los tenants a
    propósito, igual que vencimientos_fiscales_proximos()."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE vencimientos_fiscales SET recordatorio_enviado_en = ? WHERE id = ?",
            (now_iso(), vencimiento_id),
        )
        conn.commit()
    finally:
        conn.close()


def vencimientos_fiscales_proximos(dias: int) -> list[sqlite3.Row]:
    """Cruza TODOS los tenants a propósito -- usada solo por el hilo de
    recordatorio periódico (app/main.py:_recordatorio_vencimientos_fiscales),
    nunca desde una ruta servida a un usuario concreto. Excluye lo que ya
    tenga recordatorio_enviado_en -- sin esto se reenviaba el mismo aviso
    cada día mientras el vencimiento siguiera pendiente y dentro de la
    ventana (hasta `dias` veces por vencimiento)."""
    conn = get_connection()
    try:
        hoy = now_iso()[:10]
        ultimo_dia = (datetime.strptime(hoy, "%Y-%m-%d") + timedelta(days=dias)).strftime("%Y-%m-%d")
        limite = _fecha_exclusiva(ultimo_dia)
        return conn.execute(
            """SELECT v.*, c.nombre AS cliente_nombre
               FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               WHERE v.estado = 'pendiente' AND v.papelera_en IS NULL
                 AND v.recordatorio_enviado_en IS NULL
                 AND v.fecha_limite >= ? AND v.fecha_limite < ?""",
            (hoy, limite),
        ).fetchall()
    finally:
        conn.close()


def papelera_fiscal(tenant_id: int) -> list[dict]:
    """Clientes fiscales y vencimientos en la papelera de un tenant, más
    recientes primero -- aparte de papelera() (que es por usuario_id) porque
    estas dos tablas son por tenant_id, otra granularidad (ver comentario
    de cabecera de la sección "Calendario fiscal" más arriba)."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """
            SELECT * FROM (
                SELECT 'cliente_fiscal' AS origen, c.id AS id, c.nombre AS texto,
                       NULL AS cliente_nombre, c.papelera_en AS papelera_en
                FROM clientes_fiscales c
                WHERE c.tenant_id = ? AND c.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'vencimiento_fiscal' AS origen, v.id AS id,
                       v.modelo || ' ' || v.periodo AS texto,
                       c.nombre AS cliente_nombre, v.papelera_en AS papelera_en
                FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
                WHERE v.tenant_id = ? AND v.papelera_en IS NOT NULL
            )
            ORDER BY papelera_en DESC
            """,
            (tenant_id, tenant_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def _existe_vencimiento_fiscal(tenant_id: int, cliente_fiscal_id: int, modelo: str, periodo: str) -> bool:
    """Da igual si está en la papelera o no -- si ya se generó/borró antes
    este mismo periodo, no hay que volver a crearlo solo (el usuario pudo
    haberlo eliminado a propósito). Usada por generar_vencimientos_automaticos()
    para no duplicar en ejecuciones repetidas del cron (idempotencia)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? "
            "AND modelo = ? AND periodo = ? LIMIT 1",
            (tenant_id, cliente_fiscal_id, modelo, periodo),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def generar_vencimientos_automaticos() -> int:
    """Recurrencia automática por cron (ver scripts/generar_vencimientos_fiscales.py
    y deploy/vencimientos-fiscales.timer) -- para cada cliente_fiscal con
    generacion_automatica=1 y modelos_fiscales definido, en CUALQUIER
    tenant, genera los vencimientos que falten y los inserta directamente
    (a diferencia de "Generar vencimientos" del backoffice, que solo
    propone y deja confirmar a mano).

    Sin lógica de "qué trimestre exacto toca hoy": se calculan las
    propuestas del año en curso y del anterior (cubre de sobra el caso
    T4/anuales, cuyo plazo cae en enero del año siguiente al periodo) y
    solo se inserta lo que no exista ya para ese cliente+modelo+periodo
    (`_existe_vencimiento_fiscal`) -- así el script es 100% idempotente:
    ejecutarlo todos los días no duplica nada, y no hace falta saber si
    hoy es el primer día de un trimestre nuevo o no.

    Devuelve cuántos vencimientos nuevos se han creado."""
    # Import tardío: vencimientos_fiscales.py es una función pura a
    # propósito (ver su docstring, "nunca un cron que auto-genera") y no
    # importa db.py -- este orquestador vive aquí, no allí, precisamente
    # para no romper esa separación.
    from .vencimientos_fiscales import generar_vencimientos_propuestos

    anio_actual = datetime.now().year
    creados = 0
    conn = get_connection()
    try:
        clientes = conn.execute(
            "SELECT * FROM clientes_fiscales WHERE generacion_automatica = 1 "
            "AND modelos_fiscales IS NOT NULL AND papelera_en IS NULL"
        ).fetchall()
    finally:
        conn.close()

    for cliente in clientes:
        modelos = modelos_fiscales_de_cliente(cliente)
        if not modelos:
            continue
        for anio in (anio_actual - 1, anio_actual):
            for propuesta in generar_vencimientos_propuestos(modelos, anio, pais=cliente["pais"]):
                if _existe_vencimiento_fiscal(
                    cliente["tenant_id"], cliente["id"], propuesta["modelo"], propuesta["periodo"]
                ):
                    continue
                crear_vencimiento_fiscal(
                    cliente["tenant_id"], cliente["id"],
                    propuesta["modelo"], propuesta["periodo"], propuesta["fecha_limite"],
                )
                creados += 1
    return creados


def sanear_vencimientos_fuera_plazo() -> int:
    """Marca `fuera_plazo` cualquier vencimiento `pendiente` cuya
    fecha_limite ya pasó -- llamado por el mismo cron que
    generar_vencimientos_automaticos() (ver scripts/generar_vencimientos_fiscales.py).
    Antes de esto, `fuera_plazo` era un estado del CHECK constraint que
    nadie escribía nunca -- la UI ya lo pinta en rojo en caliente (ver
    app/rutas_fiscal.py:vencimientos()) sin depender de este saneo, pero
    sin él el ESTADO real en BD se quedaba `pendiente` para siempre, lo
    que rompe cualquier filtro/export por estado. Devuelve cuántas filas
    se han marcado."""
    conn = get_connection()
    try:
        hoy = now_iso()[:10]
        cur = conn.execute(
            "UPDATE vencimientos_fiscales SET estado = 'fuera_plazo', actualizado_en = ? "
            "WHERE estado = 'pendiente' AND papelera_en IS NULL AND fecha_limite < ?",
            (now_iso(), hoy),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# --- Portal de cliente (app/rutas_portal_cliente.py) -------------------------
# El "principal" aquí es un cliente_fiscal_id, no un usuario_id/tenant_id de
# empleado -- estas funciones nunca reciben tenant_id como filtro porque el
# propio cliente_fiscal_id/vencimiento_id ya identifica de forma única al
# dueño (igual que las funciones de arriba filtran por usuario_id).


def obtener_cliente_fiscal_por_id(cliente_fiscal_id: int) -> sqlite3.Row | None:
    """A diferencia de obtener_cliente_fiscal (que exige tenant_id porque
    lo llama personal ya autenticado en un tenant), el portal de cliente
    solo tiene cliente_fiscal_id en su sesión -- no hay tenant_id previo
    del que partir, es al revés: se lee de la fila devuelta."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM clientes_fiscales WHERE id = ? AND papelera_en IS NULL", (cliente_fiscal_id,),
        ).fetchone()
    finally:
        conn.close()


def clientes_fiscales_por_email(email: str) -> list[sqlite3.Row]:
    """A diferencia de obtener_cliente_fiscal_por_email (que ya sabe el
    tenant), esta busca en TODOS los tenants -- la usa /portal/entrar, que
    solo recibe un email sin contexto de tenant. Simplificación consciente
    de v1: si el mismo email está en varios tenants, se manda un enlace por
    cada fila (ver app/rutas_portal_cliente.py)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM clientes_fiscales WHERE LOWER(email) = ? AND papelera_en IS NULL",
            (email.strip().lower(),),
        ).fetchall()
    finally:
        conn.close()


def ultimo_acceso_solicitado_en(cliente_fiscal_id: int) -> str | None:
    """`creado_en` de la última solicitud de enlace de este cliente,
    exista o no la fila -- usado para el cooldown de 2 minutos por email
    en /portal/entrar (evita spamear la bandeja de alguien)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT creado_en FROM clientes_fiscales_accesos WHERE cliente_fiscal_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (cliente_fiscal_id,),
        ).fetchone()
        return fila["creado_en"] if fila else None
    finally:
        conn.close()


def crear_acceso_cliente_fiscal(cliente_fiscal_id: int, ip_solicitante: str | None) -> str:
    token = secrets.token_urlsafe(32)
    ahora = datetime.now()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO clientes_fiscales_accesos "
            "(cliente_fiscal_id, token, creado_en, expira_en, ip_solicitante) VALUES (?, ?, ?, ?, ?)",
            (
                cliente_fiscal_id, token, ahora.isoformat(timespec="seconds"),
                (ahora + timedelta(minutes=_MINUTOS_VIDA_ACCESO_PORTAL)).isoformat(timespec="seconds"),
                ip_solicitante,
            ),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def consumir_acceso_cliente_fiscal(token: str) -> int | None:
    """Valida y marca usado el token en la MISMA transacción (BEGIN
    IMMEDIATE) -- mismo cuidado de sección crítica que fichar() en
    fichajes: sin esto, dos peticiones casi simultáneas con el mismo
    token (el enlace abierto dos veces, p.ej. precarga del cliente de
    correo) podrían leer ambas "no usado todavía" antes de que ninguna
    marcara usado_en, y las dos entrarían con un token pensado para un
    solo uso. Devuelve cliente_fiscal_id si el token es válido y no
    caducado/usado, si no None."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute(
            "SELECT id, cliente_fiscal_id, expira_en, usado_en FROM clientes_fiscales_accesos WHERE token = ?",
            (token,),
        ).fetchone()
        if fila is None or fila["usado_en"] is not None:
            conn.rollback()
            return None
        if fila["expira_en"] < now_iso():
            conn.rollback()
            return None
        conn.execute(
            "UPDATE clientes_fiscales_accesos SET usado_en = ? WHERE id = ?",
            (now_iso(), fila["id"]),
        )
        conn.commit()
        return fila["cliente_fiscal_id"]
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


_MINUTOS_VIDA_ACCESO_FACTURACION = 1


def crear_acceso_facturacion(tenant_id: int, usuario_id: int) -> str:
    """Enlace de un solo uso para abrir facturacion.guildawork.com como el
    tenant del usuario actual -- ver app/rutas_facturacion_proxy.py."""
    token = secrets.token_urlsafe(32)
    ahora = datetime.now()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO facturacion_accesos (tenant_id, usuario_id, token, creado_en, expira_en) VALUES (?, ?, ?, ?, ?)",
            (
                tenant_id, usuario_id, token, ahora.isoformat(timespec="seconds"),
                (ahora + timedelta(minutes=_MINUTOS_VIDA_ACCESO_FACTURACION)).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def consumir_acceso_facturacion(token: str) -> int | None:
    """Mismo cuidado de sección crítica que consumir_acceso_cliente_fiscal
    (BEGIN IMMEDIATE, un solo uso). Devuelve tenant_id si el token es
    válido y no caducado/usado, si no None."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute(
            "SELECT id, tenant_id, expira_en, usado_en FROM facturacion_accesos WHERE token = ?",
            (token,),
        ).fetchone()
        if fila is None or fila["usado_en"] is not None:
            conn.rollback()
            return None
        if fila["expira_en"] < now_iso():
            conn.rollback()
            return None
        conn.execute(
            "UPDATE facturacion_accesos SET usado_en = ? WHERE id = ?",
            (now_iso(), fila["id"]),
        )
        conn.commit()
        return fila["tenant_id"]
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# "correo" = adjunto guardado desde un correo: interno, el cliente NO lo ve en el portal;
# "correo_compartido" = el mismo, pero el equipo ha decidido enseñárselo al cliente.
ORIGENES_DOCUMENTO_VENCIMIENTO = ("cliente", "justificante", "constancia", "correo", "correo_compartido")
ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO = ("correo",)


def subir_documento_vencimiento(
    vencimiento_id: int, nombre_archivo: str, tipo_mime: str, contenido: bytes, origen: str = "cliente",
) -> int:
    """Guarda primero como BLOB local (garantiza que el documento queda
    a salvo aunque Nextcloud falle a medias) y, solo si el tenant tiene
    Nextcloud configurado y la subida sale bien, promueve el archivo
    ahí y vacía el BLOB -- best-effort, mismo criterio que el resto de
    integraciones opcionales: un fallo aquí deja el documento como BLOB,
    nunca lo pierde ni rompe la subida."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO vencimientos_fiscales_documentos "
            "(vencimiento_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en, origen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vencimiento_id, nombre_archivo, tipo_mime, len(contenido), contenido, now_iso(),
             origen if origen in ORIGENES_DOCUMENTO_VENCIMIENTO else "cliente"),
        )
        documento_id = cur.lastrowid
        conn.commit()

        try:
            from . import nextcloud
            fila = conn.execute(
                """SELECT t.nombre AS tenant_nombre FROM vencimientos_fiscales v
                   JOIN tenants t ON t.id = v.tenant_id WHERE v.id = ?""",
                (vencimiento_id,),
            ).fetchone()
            if fila is not None:
                ruta = f"{fila['tenant_nombre']}/vencimientos-fiscales/{documento_id}-{nombre_archivo}"
                nextcloud.subir_archivo(ruta, contenido)
                conn.execute(
                    "UPDATE vencimientos_fiscales_documentos SET ruta_nextcloud = ?, contenido = NULL WHERE id = ?",
                    (ruta, documento_id),
                )
                conn.commit()
        except Exception:
            pass  # se queda como BLOB local, comportamiento de siempre
        return documento_id
    finally:
        conn.close()


def contenido_documento_vencimiento(documento: sqlite3.Row) -> bytes:
    """Sirve el contenido de un documento sea cual sea su almacenamiento
    (BLOB local o Nextcloud) -- para que las rutas no tengan que saber
    dónde vive cada documento. A diferencia de la subida, aquí SÍ deja
    propagar un fallo de Nextcloud (app.nextcloud.ErrorNextcloud): es la
    acción principal de esta llamada, no un efecto secundario -- quien
    llama decide cómo mostrarlo (ver app/rutas_fiscal.py)."""
    if documento["ruta_nextcloud"]:
        from . import nextcloud
        return nextcloud.descargar_archivo(documento["ruta_nextcloud"])
    return documento["contenido"]


def listar_documentos_vencimiento(
    vencimiento_id: int, origen: str | None = None, excluir_origenes: tuple[str, ...] = (),
) -> list[sqlite3.Row]:
    """Todos los documentos del vencimiento, o solo los de un `origen`
    ('cliente' = lo que ha subido el cliente desde el portal)."""
    conn = get_connection()
    try:
        sql = (
            "SELECT id, vencimiento_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en, origen "
            "FROM vencimientos_fiscales_documentos WHERE vencimiento_id = ?"
        )
        params: list = [vencimiento_id]
        if origen is not None:
            sql += " AND origen = ?"
            params.append(origen)
        if excluir_origenes:
            sql += f" AND origen NOT IN ({','.join('?' * len(excluir_origenes))})"
            params.extend(excluir_origenes)
        return conn.execute(sql + " ORDER BY creado_en, id", params).fetchall()
    finally:
        conn.close()


def eliminar_documentos_vencimiento_por_origen(vencimiento_id: int, origen: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM vencimientos_fiscales_documentos WHERE vencimiento_id = ? AND origen = ?",
            (vencimiento_id, origen),
        )
        conn.commit()
    finally:
        conn.close()


def vencimientos_para_recordatorio_portal(fecha_objetivo: str, dias_antes: int) -> list[sqlite3.Row]:
    """Vencimientos pendientes que vencen justo `fecha_objetivo` (YYYY-MM-DD),
    de clientes con email y recordatorios activos, y a los que todavía no se
    ha enviado el recordatorio de esta antelación. Cruza todos los tenants:
    solo la usa el hilo periódico del servidor."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT v.*, c.nombre AS cliente_nombre, c.email AS cliente_email, c.idioma AS cliente_idioma,
                      t.nombre AS tenant_nombre
               FROM vencimientos_fiscales v
               JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               JOIN tenants t ON t.id = v.tenant_id
               WHERE v.estado = 'pendiente' AND v.papelera_en IS NULL AND c.papelera_en IS NULL
                 AND c.recordatorios_portal = 1 AND c.email IS NOT NULL AND trim(c.email) <> ''
                 AND v.fecha_limite >= ? AND v.fecha_limite < ?
                 AND NOT EXISTS (SELECT 1 FROM vencimientos_recordatorios r
                                 WHERE r.vencimiento_id = v.id AND r.dias_antes = ?)""",
            (fecha_objetivo, _fecha_exclusiva(fecha_objetivo), dias_antes),
        ).fetchall()
    finally:
        conn.close()


def marcar_recordatorio_portal_enviado(vencimiento_id: int, dias_antes: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO vencimientos_recordatorios (vencimiento_id, dias_antes, enviado_en) VALUES (?, ?, ?)",
            (vencimiento_id, dias_antes, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_documento_vencimiento(documento_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM vencimientos_fiscales_documentos WHERE id = ?", (documento_id,),
        ).fetchone()
    finally:
        conn.close()


def crear_mensaje_vencimiento(vencimiento_id: int, autor: str, texto: str, usuario_id: int | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO vencimientos_fiscales_mensajes (vencimiento_id, autor, usuario_id, texto, creado_en) "
            "VALUES (?, ?, ?, ?, ?)",
            (vencimiento_id, autor, usuario_id, texto.strip(), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_mensajes_vencimiento(vencimiento_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT m.*, u.email AS usuario_email FROM vencimientos_fiscales_mensajes m "
            "LEFT JOIN usuarios u ON u.id = m.usuario_id "
            "WHERE m.vencimiento_id = ? ORDER BY m.creado_en",
            (vencimiento_id,),
        ).fetchall()
    finally:
        conn.close()


def marcar_mensajes_leidos(vencimiento_id: int, autor_que_lee: str) -> None:
    """Marca leídos los mensajes del OTRO autor -- si lee el cliente
    (autor_que_lee='cliente'), se marcan los de autor='empleado', y
    viceversa. Llamado al abrir la conversación desde cada lado."""
    otro_autor = "empleado" if autor_que_lee == "cliente" else "cliente"
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE vencimientos_fiscales_mensajes SET leido_en = ? "
            "WHERE vencimiento_id = ? AND autor = ? AND leido_en IS NULL",
            (now_iso(), vencimiento_id, otro_autor),
        )
        conn.commit()
    finally:
        conn.close()


def crear_solicitud_acceso_portal(nombre: str, email: str, nif: str | None = None, mensaje: str | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO solicitudes_acceso_portal (nombre, email, nif, mensaje, creado_en) VALUES (?, ?, ?, ?, ?)",
            (nombre.strip(), email.strip(), (nif or "").strip() or None, (mensaje or "").strip() or None, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_solicitudes_acceso_portal() -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM solicitudes_acceso_portal ORDER BY atendida ASC, creado_en DESC"
        ).fetchall()
    finally:
        conn.close()


def marcar_solicitud_atendida(solicitud_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE solicitudes_acceso_portal SET atendida = 1 WHERE id = ?", (solicitud_id,))
        conn.commit()
    finally:
        conn.close()


def listar_todos_los_clientes_fiscales() -> list[sqlite3.Row]:
    """Para el backoffice (admin, sin tenant fijo) -- a diferencia de
    listar_clientes_fiscales(tenant_id), esta cruza todos los tenants,
    con el nombre del tenant para que el admin sepa a cuál pertenece
    cada fila al vincular una solicitud de acceso."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT c.*, t.nombre AS tenant_nombre FROM clientes_fiscales c "
            "JOIN tenants t ON t.id = c.tenant_id WHERE c.papelera_en IS NULL ORDER BY t.nombre, c.nombre"
        ).fetchall()
    finally:
        conn.close()


# --- Correo (cuentas IMAP/POP3 + caché de mensajes) ---------------------------
# La lógica de red (conectar, sincronizar, enviar) vive en app/correo.py; aquí
# solo hay persistencia. La contraseña de cada cuenta NO se guarda en esta
# tabla — la gestiona app/correo.py directamente contra keyring.
# correo_carpetas/correo_mensajes/correo_adjuntos cuelgan de correo_cuentas
# (cuenta_id NOT NULL) y se aíslan por JOIN — no llevan usuario_id propio.

def crear_cuenta_correo(
    usuario_id: int,
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_cuentas
               (usuario_id, nombre, protocolo, host, puerto, usa_tls, usuario,
                smtp_host, smtp_puerto, smtp_tls, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, nombre.strip(), protocolo, host.strip(), puerto, int(usa_tls),
             usuario.strip(), (smtp_host or "").strip() or None, smtp_puerto,
             int(smtp_tls), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_cuentas_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_cuentas WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def obtener_cuenta_correo(usuario_id: int, cuenta_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def editar_cuenta_correo(
    usuario_id: int, cuenta_id: int,
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
) -> None:
    """Mismos campos que crear_cuenta_correo, pero UPDATE -- la
    contraseña NO se toca aquí (vive en keyring, ver
    app/correo.py:editar_cuenta), así que un error tipográfico de
    host/puerto ya no obliga a borrar y recrear la cuenta entera
    (que borraba también los mensajes en caché)."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas
               SET nombre = ?, protocolo = ?, host = ?, puerto = ?, usa_tls = ?, usuario = ?,
                   smtp_host = ?, smtp_puerto = ?, smtp_tls = ?
               WHERE id = ? AND usuario_id = ?""",
            (nombre.strip(), protocolo, host.strip(), puerto, int(usa_tls), usuario.strip(),
             (smtp_host or "").strip() or None, smtp_puerto, int(smtp_tls), cuenta_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_cuenta_correo(usuario_id: int, cuenta_id: int) -> None:
    """Borra la cuenta y sus mensajes/carpetas cacheados. Sin papelera: la
    credencial en keyring se borra aparte, desde app/correo.py, antes de
    llamar aquí."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_mensajes WHERE cuenta_id IN (SELECT id FROM correo_cuentas WHERE id = ? AND usuario_id = ?)",
            (cuenta_id, usuario_id),
        )
        conn.execute(
            "DELETE FROM correo_carpetas WHERE cuenta_id IN (SELECT id FROM correo_cuentas WHERE id = ? AND usuario_id = ?)",
            (cuenta_id, usuario_id),
        )
        conn.execute("DELETE FROM correo_cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def guardar_firma_correo(usuario_id: int, cuenta_id: int, firma_html: str | None, firma_en_nuevos: bool, firma_en_respuestas: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas SET firma_html = ?, firma_en_nuevos = ?, firma_en_respuestas = ?
               WHERE id = ? AND usuario_id = ?""",
            (firma_html, int(firma_en_nuevos), int(firma_en_respuestas), cuenta_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Carpetas IMAP (POP3 no tiene fila aquí, ver comentario del esquema) ------

def guardar_carpetas_correo(cuenta_id: int, carpetas: list[tuple[str, str]]) -> None:
    """`carpetas`: lista de (nombre, nombre_visible). Upsert — no borra
    carpetas que ya no aparezcan en el servidor, para no perder sus mensajes
    cacheados si es un fallo puntual de listado."""
    conn = get_connection()
    try:
        for nombre, nombre_visible in carpetas:
            conn.execute(
                """INSERT INTO correo_carpetas (cuenta_id, nombre, nombre_visible) VALUES (?, ?, ?)
                   ON CONFLICT (cuenta_id, nombre) DO UPDATE SET nombre_visible = excluded.nombre_visible""",
                (cuenta_id, nombre, nombre_visible),
            )
        conn.commit()
    finally:
        conn.close()


def listar_carpetas_correo(cuenta_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_carpetas WHERE cuenta_id = ? ORDER BY nombre_visible", (cuenta_id,)
        ).fetchall()
    finally:
        conn.close()


# --- Categorías de correo (propias de Guilda Work, no se sincronizan) --------

def crear_categoria_correo(usuario_id: int, nombre: str, color: str) -> int:
    """Lanza ValueError (mensaje legible, lo traduce app/correo.py a
    ErrorCorreo) si ya tienes una categoría de correo con ese nombre --
    antes era un IntegrityError sin capturar, 500 en crudo (revisión de
    lógica; la UNIQUE ahora es por (usuario_id, nombre), así que esto ya
    NUNCA salta por culpa de OTRO usuario, solo por repetir un nombre
    propio)."""
    conn = get_connection()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO correo_categorias (usuario_id, nombre, color, creada_en) VALUES (?, ?, ?, ?)",
                (usuario_id, nombre.strip(), color, now_iso()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya tienes una categoría de correo llamada '{nombre.strip()}'.") from None
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_categorias WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def eliminar_categoria_correo(usuario_id: int, categoria_id: int) -> None:
    """Los mensajes que la tuvieran asignada se quedan sin categoría
    (ON DELETE SET NULL en el esquema)."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


# --- Plantillas de respuesta guardadas (app/rutas_correo.py) ---------------

def crear_plantilla_correo(usuario_id: int, nombre: str, asunto: str | None, cuerpo: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO correo_plantillas (usuario_id, nombre, asunto, cuerpo, creada_en) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, nombre.strip(), (asunto or "").strip() or None, cuerpo, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_plantillas_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_plantillas WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def obtener_plantilla_correo(usuario_id: int, plantilla_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_plantillas WHERE id = ? AND usuario_id = ?", (plantilla_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def eliminar_plantilla_correo(usuario_id: int, plantilla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_plantillas WHERE id = ? AND usuario_id = ?", (plantilla_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


# --- Borradores al redactar (app/rutas_correo.py) --------------------------

def guardar_borrador_correo(
    usuario_id: int, borrador_id: int | None, *, cuenta_id: int | None, destinatarios: str,
    cc: str, bcc: str, asunto: str, cuerpo_html: str, en_respuesta_a: str | None,
) -> int:
    """Crea el borrador si `borrador_id` es None, si no lo actualiza --
    mismo id se reutiliza en guardados sucesivos del mismo compositor."""
    conn = get_connection()
    try:
        if borrador_id is not None:
            cur = conn.execute(
                """UPDATE correo_borradores SET cuenta_id = ?, destinatarios = ?, cc = ?, bcc = ?,
                   asunto = ?, cuerpo_html = ?, en_respuesta_a = ?, actualizado_en = ?
                   WHERE id = ? AND usuario_id = ?""",
                (cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a,
                 now_iso(), borrador_id, usuario_id),
            )
            conn.commit()
            if cur.rowcount:
                return borrador_id
        cur = conn.execute(
            """INSERT INTO correo_borradores
               (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a, actualizado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_borradores_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_borradores WHERE usuario_id = ? ORDER BY actualizado_en DESC", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def contar_borradores_correo(usuario_id: int) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM correo_borradores WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


def obtener_borrador_correo(usuario_id: int, borrador_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_borradores WHERE id = ? AND usuario_id = ?", (borrador_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def listar_adjuntos_borrador(usuario_id: int, borrador_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT a.id, a.nombre, a.tipo, length(a.contenido) AS tamano
               FROM correo_borradores_adjuntos a JOIN correo_borradores b ON b.id = a.borrador_id
               WHERE a.borrador_id = ? AND b.usuario_id = ? ORDER BY a.id""",
            (borrador_id, usuario_id),
        ).fetchall()
    finally:
        conn.close()


def adjuntos_borrador_para_enviar(usuario_id: int, borrador_id: int, ids: list[int]) -> list[dict]:
    """Contenido de los adjuntos guardados del borrador cuyos ids se indican."""
    if not ids:
        return []
    conn = get_connection()
    try:
        marcadores = ",".join("?" * len(ids))
        filas = conn.execute(
            f"""SELECT a.id, a.nombre, a.tipo, a.contenido FROM correo_borradores_adjuntos a
                JOIN correo_borradores b ON b.id = a.borrador_id
                WHERE a.borrador_id = ? AND b.usuario_id = ? AND a.id IN ({marcadores}) ORDER BY a.id""",
            [borrador_id, usuario_id, *ids],
        ).fetchall()
        return [{"nombre": f["nombre"], "tipo": f["tipo"], "bytes": bytes(f["contenido"])} for f in filas]
    finally:
        conn.close()


def copiar_adjuntos_envio_a_borrador(envio_id: int, borrador_id: int) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_borradores_adjuntos (borrador_id, nombre, tipo, contenido)
               SELECT ?, nombre, tipo, contenido FROM correo_envios_adjuntos WHERE envio_id = ? ORDER BY id""",
            (borrador_id, envio_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def eliminar_borrador_correo(usuario_id: int, borrador_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_borradores_adjuntos WHERE borrador_id IN "
            "(SELECT id FROM correo_borradores WHERE id = ? AND usuario_id = ?)", (borrador_id, usuario_id)
        )
        conn.execute(
            "DELETE FROM correo_borradores WHERE id = ? AND usuario_id = ?", (borrador_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def asignar_categoria_correo(usuario_id: int, mensaje_id: int, categoria_id: int | None) -> None:
    """`usuario_id` solo para comprobar que `categoria_id` es suya --
    quien llama ya tiene que haber comprobado por su cuenta que
    `mensaje_id` es del usuario (ver _mensaje_de_usuario_o_404 en
    rutas_correo.py), esta función no repite esa parte."""
    conn = get_connection()
    try:
        if categoria_id is not None:
            fila = conn.execute(
                "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
            ).fetchone()
            if fila is None:
                categoria_id = None
        conn.execute("UPDATE correo_mensajes SET categoria_id = ? WHERE id = ?", (categoria_id, mensaje_id))
        conn.commit()
    finally:
        conn.close()


def cliente_fiscal_id_por_email(tenant_id: int, email: str | None) -> int | None:
    """El cliente fiscal cuyo email coincide con `email` (sin distinguir
    mayúsculas), solo si es único en el despacho: con dos clientes con el mismo
    correo no se adivina y no se vincula ninguno."""
    email = (email or "").strip().lower()
    if not email:
        return None
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT id FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL AND LOWER(TRIM(email)) = ? LIMIT 2",
            (tenant_id, email),
        ).fetchall()
        return filas[0]["id"] if len(filas) == 1 else None
    finally:
        conn.close()


def mensajes_correo_sin_cliente(usuario_id: int, limite: int = 5000) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT m.id, m.remitente FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE c.usuario_id = ? AND m.cliente_fiscal_id IS NULL AND m.remitente IS NOT NULL
               ORDER BY m.id DESC LIMIT ?""",
            (usuario_id, limite),
        ).fetchall()
    finally:
        conn.close()


def asignar_cliente_fiscal_correo(tenant_id: int, mensaje_id: int, cliente_fiscal_id: int | None) -> None:
    """`tenant_id` solo para comprobar que `cliente_fiscal_id` es suyo --
    mismo criterio que asignar_categoria_correo, quien llama ya tiene
    que haber comprobado que `mensaje_id` es del usuario actual."""
    conn = get_connection()
    try:
        if cliente_fiscal_id is not None:
            fila = conn.execute(
                "SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL",
                (cliente_fiscal_id, tenant_id),
            ).fetchone()
            if fila is None:
                cliente_fiscal_id = None
        conn.execute(
            "UPDATE correo_mensajes SET cliente_fiscal_id = ? WHERE id = ?", (cliente_fiscal_id, mensaje_id)
        )
        conn.commit()
    finally:
        conn.close()


def listar_correos_de_cliente_fiscal(cliente_fiscal_id: int) -> list[sqlite3.Row]:
    """Correos vinculados manualmente a un cliente fiscal (ver
    asignar_cliente_fiscal_correo), para la sección "Correos
    relacionados" de su ficha (app/rutas_fiscal.py:ficha_cliente) --
    mismo criterio de agregación que listar_documentos_vencimiento."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_mensajes WHERE cliente_fiscal_id = ? ORDER BY fecha DESC",
            (cliente_fiscal_id,),
        ).fetchall()
    finally:
        conn.close()


# --- Remitentes de confianza (imágenes/adjuntos no se bloquean) --------------

def confiar_en_remitente(usuario_id: int, direccion: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_remitentes_confiables (usuario_id, direccion, creada_en)
               VALUES (?, ?, ?)
               ON CONFLICT (usuario_id, direccion) DO NOTHING""",
            (usuario_id, direccion.strip().lower(), now_iso()),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT id FROM correo_remitentes_confiables WHERE usuario_id = ? AND direccion = ?",
            (usuario_id, direccion.strip().lower()),
        ).fetchone()
        return fila["id"] if fila else cur.lastrowid
    finally:
        conn.close()


def listar_remitentes_confiables(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_remitentes_confiables WHERE usuario_id = ? ORDER BY direccion",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_remitente_confiable(usuario_id: int, remitente_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_remitentes_confiables WHERE id = ? AND usuario_id = ?",
            (remitente_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def es_remitente_confiable(usuario_id: int, direccion: str | None) -> bool:
    if not direccion:
        return False
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM correo_remitentes_confiables WHERE usuario_id = ? AND direccion = ?",
            (usuario_id, direccion.strip().lower()),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


# --- Reglas de categorización automática por remitente -----------------------

def crear_regla_categoria_correo(usuario_id: int, remitente_patron: str, categoria_id: int) -> int:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone()
        if fila is None:
            raise ValueError(f"La categoría de correo {categoria_id} no existe o no es tuya.")
        cur = conn.execute(
            """INSERT INTO correo_reglas_categoria (usuario_id, remitente_patron, categoria_id, creada_en)
               VALUES (?, ?, ?, ?)""",
            (usuario_id, remitente_patron.strip().lower(), categoria_id, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_reglas_categoria_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT r.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM correo_reglas_categoria r
               JOIN correo_categorias c ON c.id = r.categoria_id AND c.usuario_id = r.usuario_id
               WHERE r.usuario_id = ? ORDER BY r.remitente_patron""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_regla_categoria_correo(usuario_id: int, regla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_reglas_categoria WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def crear_regla_correo(
    usuario_id: int, remitente_patron: str | None = None, asunto_patron: str | None = None,
    categoria_id: int | None = None, marcar_leido: bool = False, destacar: bool = False,
    cliente_fiscal_id: int | None = None,
) -> int:
    """Regla avanzada. Necesita al menos una condición (remitente o asunto) y
    al menos una acción; categoría y cliente se validan contra el usuario."""
    remitente_patron = (remitente_patron or "").strip().lower() or None
    asunto_patron = (asunto_patron or "").strip().lower() or None
    if not remitente_patron and not asunto_patron:
        raise ValueError("Indica al menos una condición: remitente o asunto.")
    conn = get_connection()
    try:
        if categoria_id is not None and conn.execute(
            "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone() is None:
            raise ValueError("La categoría elegida no existe.")
        cliente_fiscal_id = _cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id)
        if categoria_id is None and not marcar_leido and not destacar and cliente_fiscal_id is None:
            raise ValueError("Elige al menos una acción para la regla.")
        cur = conn.execute(
            """INSERT INTO correo_reglas
               (usuario_id, remitente_patron, asunto_patron, categoria_id, marcar_leido, destacar, cliente_fiscal_id, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, remitente_patron, asunto_patron, categoria_id, 1 if marcar_leido else 0,
             1 if destacar else 0, cliente_fiscal_id, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_reglas_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT r.*, c.nombre AS categoria_nombre, c.color AS categoria_color, cf.nombre AS cliente_fiscal_nombre
               FROM correo_reglas r LEFT JOIN correo_categorias c ON c.id = r.categoria_id
               LEFT JOIN clientes_fiscales cf ON cf.id = r.cliente_fiscal_id
               WHERE r.usuario_id = ? ORDER BY r.id""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_regla_correo(usuario_id: int, regla_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM correo_reglas WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def reglas_correo_aplicables(usuario_id: int, direccion: str | None, asunto: str | None) -> list[sqlite3.Row]:
    """Reglas avanzadas cuyas condiciones (todas las indicadas) coinciden.
    Remitente: "@dominio.com" = dominio, "x@y.com" = exacto, otro texto = contiene.
    Asunto: contiene, sin distinguir mayúsculas."""
    direccion = (direccion or "").strip().lower()
    asunto_min = (asunto or "").lower()
    resultado = []
    for r in listar_reglas_correo(usuario_id):
        rp, ap = r["remitente_patron"], r["asunto_patron"]
        if rp:
            if rp.startswith("@"):
                ok = direccion.endswith(rp)
            elif "@" in rp:
                ok = direccion == rp
            else:
                ok = rp in direccion
            if not ok:
                continue
        if ap and ap not in asunto_min:
            continue
        resultado.append(r)
    return resultado


def categoria_id_por_remitente_correo(usuario_id: int, direccion: str | None) -> int | None:
    """Busca primero una regla de email exacto, luego una de dominio
    (`remitente_patron` empezando por "@")."""
    if not direccion:
        return None
    direccion = direccion.strip().lower()
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT categoria_id FROM correo_reglas_categoria
               WHERE usuario_id = ? AND remitente_patron = ?""",
            (usuario_id, direccion),
        ).fetchone()
        if fila:
            return fila["categoria_id"]
        dominio = "@" + direccion.split("@", 1)[1] if "@" in direccion else None
        if dominio:
            fila = conn.execute(
                """SELECT categoria_id FROM correo_reglas_categoria
                   WHERE usuario_id = ? AND remitente_patron = ?""",
                (usuario_id, dominio),
            ).fetchone()
            if fila:
                return fila["categoria_id"]
        return None
    finally:
        conn.close()


# --- Destinatarios recientes (para autocompletar al redactar) ----------------

def registrar_destinatario_reciente(usuario_id: int, direccion: str, nombre_mostrado: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO correo_destinatarios_recientes
               (usuario_id, direccion, nombre_mostrado, ultima_vez_en, veces_usado)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (usuario_id, direccion) DO UPDATE SET
                   nombre_mostrado = excluded.nombre_mostrado,
                   ultima_vez_en = excluded.ultima_vez_en,
                   veces_usado = veces_usado + 1""",
            (usuario_id, direccion.strip().lower(), nombre_mostrado, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def buscar_destinatarios_recientes(usuario_id: int, q: str | None = None, limite: int = 8) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        if q:
            patron = f"%{q.strip().lower()}%"
            return conn.execute(
                """SELECT * FROM correo_destinatarios_recientes
                   WHERE usuario_id = ? AND (direccion LIKE ? OR LOWER(nombre_mostrado) LIKE ?)
                   ORDER BY veces_usado DESC, ultima_vez_en DESC LIMIT ?""",
                (usuario_id, patron, patron, limite),
            ).fetchall()
        return conn.execute(
            """SELECT * FROM correo_destinatarios_recientes WHERE usuario_id = ?
               ORDER BY veces_usado DESC, ultima_vez_en DESC LIMIT ?""",
            (usuario_id, limite),
        ).fetchall()
    finally:
        conn.close()


# --- Preferencias generales de Correo (una fila por usuario) ------------------

DESHACER_ENVIO_OPCIONES = (0, 10, 30)
MAX_BYTES_ADJUNTOS_ENVIO = 25 * 1024 * 1024


def encolar_envio_correo(
    usuario_id: int, cuenta_id: int, destinatarios: str, cc: str, bcc: str, asunto: str,
    cuerpo_html: str, en_respuesta_a: str | None, adjuntos: list[dict], enviar_en: str,
    programado: bool = False,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_envios
               (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a,
                enviar_en, programado, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a,
             enviar_en, int(programado), now_iso()),
        )
        envio_id = cur.lastrowid
        for a in adjuntos:
            conn.execute(
                "INSERT INTO correo_envios_adjuntos (envio_id, nombre, tipo, contenido) VALUES (?, ?, ?, ?)",
                (envio_id, a["nombre"], a["tipo"], a["bytes"]),
            )
        conn.commit()
        return envio_id
    finally:
        conn.close()


def obtener_envio_correo(usuario_id: int, envio_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_envios WHERE id = ? AND usuario_id = ?", (envio_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def listar_envios_programados(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT * FROM correo_envios WHERE usuario_id = ? AND estado = 'pendiente' AND programado = 1
               ORDER BY enviar_en""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def contar_envios_programados(usuario_id: int) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_envios WHERE usuario_id = ? AND estado = 'pendiente' AND programado = 1",
            (usuario_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def cancelar_envio_correo(usuario_id: int, envio_id: int) -> bool:
    """True si seguía pendiente y queda cancelado; False si ya se ha
    enviado (o se está enviando) o no es del usuario."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE correo_envios SET estado = 'cancelado', procesado_en = ? "
            "WHERE id = ? AND usuario_id = ? AND estado = 'pendiente'",
            (now_iso(), envio_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def envios_correo_vencidos(ahora: str) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_envios WHERE estado = 'pendiente' AND enviar_en <= ? ORDER BY enviar_en, id LIMIT 50",
            (ahora,),
        ).fetchall()
    finally:
        conn.close()


def reclamar_envio_correo(envio_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE correo_envios SET estado = 'enviando', procesado_en = ? WHERE id = ? AND estado = 'pendiente'",
            (now_iso(), envio_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def adjuntos_envio_correo(envio_id: int) -> list[dict]:
    conn = get_connection()
    try:
        return [
            {"nombre": f["nombre"], "tipo": f["tipo"], "bytes": bytes(f["contenido"])}
            for f in conn.execute(
                "SELECT nombre, tipo, contenido FROM correo_envios_adjuntos WHERE envio_id = ? ORDER BY id", (envio_id,)
            ).fetchall()
        ]
    finally:
        conn.close()


def cerrar_envio_correo(envio_id: int, estado: str, error: str | None = None, borrar_adjuntos: bool = True) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE correo_envios SET estado = ?, error = ?, procesado_en = ? WHERE id = ?",
            (estado, error, now_iso(), envio_id),
        )
        if borrar_adjuntos:
            conn.execute("DELETE FROM correo_envios_adjuntos WHERE envio_id = ?", (envio_id,))
        conn.commit()
    finally:
        conn.close()


def rescatar_envios_atascados(antes_de: str) -> list[sqlite3.Row]:
    """Envíos que se quedaron en 'enviando' (el proceso murió a medias):
    se marcan como error para que el usuario no pierda el correo."""
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT * FROM correo_envios WHERE estado = 'enviando' AND procesado_en < ?", (antes_de,)
        ).fetchall()
        for f in filas:
            conn.execute(
                "UPDATE correo_envios SET estado = 'error', error = ? WHERE id = ?",
                ("El envío se interrumpió; no se sabe si llegó a salir.", f["id"]),
            )
        conn.commit()
        return filas
    finally:
        conn.close()


def purgar_envios_correo_antiguos(antes_de: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_envios WHERE estado IN ('enviado', 'cancelado', 'error') AND procesado_en < ?",
            (antes_de,),
        )
        conn.commit()
    finally:
        conn.close()


def _obtener_o_crear(conn: sqlite3.Connection, tabla: str, usuario_id: int) -> sqlite3.Row:
    """Fila de `tabla` (clave usuario_id), creándola con sus valores por defecto solo si no
    existe: leerla en cada petición no debe abrir una transacción de escritura."""
    fila = conn.execute(f"SELECT * FROM {tabla} WHERE usuario_id = ?", (usuario_id,)).fetchone()
    if fila is None:
        conn.execute(f"INSERT OR IGNORE INTO {tabla} (usuario_id) VALUES (?)", (usuario_id,))
        conn.commit()
        fila = conn.execute(f"SELECT * FROM {tabla} WHERE usuario_id = ?", (usuario_id,)).fetchone()
    return fila


def obtener_preferencias_correo(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        return _obtener_o_crear(conn, "correo_preferencias", usuario_id)
    finally:
        conn.close()


def guardar_preferencias_correo(
    usuario_id: int, densidad: str, marcar_leido_automatico: bool, limite_mensajes: int,
    deshacer_segundos: int | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO correo_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        if deshacer_segundos in DESHACER_ENVIO_OPCIONES:
            conn.execute(
                "UPDATE correo_preferencias SET deshacer_segundos = ? WHERE usuario_id = ?",
                (deshacer_segundos, usuario_id),
            )
        conn.execute(
            """UPDATE correo_preferencias
               SET densidad = ?, marcar_leido_automatico = ?, limite_mensajes = ? WHERE usuario_id = ?""",
            (densidad, int(marcar_leido_automatico), limite_mensajes, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def marcar_sincronizada_cuenta_correo(cuenta_id: int) -> None:
    """Anota la sincronización correcta y limpia el último error."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas
               SET ultima_sincronizacion = ?, ultimo_error_sincronizacion = NULL,
                   ultimo_error_sincronizacion_en = NULL
               WHERE id = ?""",
            (now_iso(), cuenta_id),
        )
        conn.commit()
    finally:
        conn.close()


def marcar_error_sincronizacion_cuenta_correo(cuenta_id: int, error: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE correo_cuentas SET ultimo_error_sincronizacion = ?, ultimo_error_sincronizacion_en = ? WHERE id = ?",
            (error[:300], now_iso(), cuenta_id),
        )
        conn.commit()
    finally:
        conn.close()


def registrar_latido(nombre: str, ok: bool, intervalo_segundos: int, detalle: str | None = None) -> None:
    """Anota que una tarea periódica ha terminado una pasada (bien o con error)."""
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO latidos (nombre, intervalo_segundos) VALUES (?, ?)", (nombre, intervalo_segundos))
        if ok:
            conn.execute(
                "UPDATE latidos SET ultimo_ok = ?, detalle = ?, intervalo_segundos = ? WHERE nombre = ?",
                (now_iso(), (detalle or None) and detalle[:300], intervalo_segundos, nombre),
            )
        else:
            conn.execute(
                "UPDATE latidos SET ultimo_error = ?, detalle = ?, intervalo_segundos = ? WHERE nombre = ?",
                (now_iso(), (detalle or None) and detalle[:300], intervalo_segundos, nombre),
            )
        conn.commit()
    finally:
        conn.close()


def listar_latidos() -> dict[str, sqlite3.Row]:
    conn = get_connection()
    try:
        return {f["nombre"]: f for f in conn.execute("SELECT * FROM latidos").fetchall()}
    finally:
        conn.close()


def alerta_salud_enviada(motivo: str, dia: str) -> bool:
    conn = get_connection()
    try:
        return conn.execute("SELECT 1 FROM salud_alertas WHERE motivo = ? AND dia = ?", (motivo, dia)).fetchone() is not None
    finally:
        conn.close()


def marcar_alerta_salud(motivo: str, dia: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO salud_alertas (motivo, dia, enviada_en) VALUES (?, ?, ?)", (motivo, dia, now_iso())
        )
        limite = (datetime.strptime(dia, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
        conn.execute("DELETE FROM salud_alertas WHERE dia < ?", (limite,))
        conn.commit()
    finally:
        conn.close()


def estado_cuentas_correo_global() -> list[sqlite3.Row]:
    """Todas las cuentas de correo con su última sincronización y error (panel de salud)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT c.id, c.nombre, u.email AS usuario_email, c.ultima_sincronizacion,
                      c.ultimo_error_sincronizacion, c.ultimo_error_sincronizacion_en
               FROM correo_cuentas c JOIN usuarios u ON u.id = c.usuario_id ORDER BY c.id"""
        ).fetchall()
    finally:
        conn.close()


def contar_entregas_webhook_fallidas(desde: str) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT COUNT(*) FROM webhooks_entregas
               WHERE entregado_en >= ? AND NOT (estado_http IS NOT NULL AND estado_http BETWEEN 200 AND 299)""",
            (desde,),
        ).fetchone()[0]
    finally:
        conn.close()


def contar_envios_correo_fallidos(desde: str) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_envios WHERE estado = 'error' AND procesado_en >= ?", (desde,)
        ).fetchone()[0]
    finally:
        conn.close()


def contar_envios_correo_atascados(vencidos_antes_de: str) -> int:
    """Envíos pendientes cuya hora pasó hace rato: el hilo de envíos no está trabajando."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_envios WHERE estado = 'pendiente' AND enviar_en < ?", (vencidos_antes_de,)
        ).fetchone()[0]
    finally:
        conn.close()


def listar_todas_las_cuentas_correo() -> list[sqlite3.Row]:
    """Cuentas de correo de TODOS los usuarios (id y usuario_id): las usa
    la sincronización automática del servidor, que no tiene un usuario
    concreto detrás."""
    conn = get_connection()
    try:
        return conn.execute("SELECT id, usuario_id FROM correo_cuentas ORDER BY id").fetchall()
    finally:
        conn.close()


def uids_existentes_correo(cuenta_id: int, carpeta: str = "INBOX") -> set[str]:
    """UIDs ya descargados para esa cuenta/carpeta — usado por la
    sincronización para pedir al servidor solo los mensajes que faltan."""
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT uid FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ?",
            (cuenta_id, carpeta),
        ).fetchall()
        return {f["uid"] for f in filas}
    finally:
        conn.close()


def obtener_ultimo_uid_sincronizado(cuenta_id: int, carpeta: str) -> str | None:
    """UID más alto ya sincronizado de esa carpeta -- permite pedirle al
    servidor solo "UID <n>:*" en vez de un SEARCH ALL completo. `None`
    significa que esta carpeta nunca se ha sincronizado todavía (primera
    sincronización, sigue haciendo falta un barrido completo)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT ultimo_uid_sincronizado FROM correo_carpetas WHERE cuenta_id = ? AND nombre = ?",
            (cuenta_id, carpeta),
        ).fetchone()
        return fila["ultimo_uid_sincronizado"] if fila else None
    finally:
        conn.close()


def actualizar_ultimo_uid_sincronizado(cuenta_id: int, carpeta: str, uid: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE correo_carpetas SET ultimo_uid_sincronizado = ? WHERE cuenta_id = ? AND nombre = ?",
            (uid, cuenta_id, carpeta),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_cuenta_correo_por_id(cuenta_id: int) -> sqlite3.Row | None:
    """Sin comprobar el usuario: solo para tareas internas (segundo plano) que ya parten de un mensaje del usuario."""
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_cuentas WHERE id = ?", (cuenta_id,)).fetchone()
    finally:
        conn.close()


_FTS_CORREO_COLUMNAS = "asunto, remitente, destinatarios, cuerpo_texto"


def _asegurar_fts_correo(conn: sqlite3.Connection) -> bool:
    """Índice de texto completo (FTS5) del correo: asunto, remitente, destinatarios y cuerpo,
    sin distinguir mayúsculas ni acentos y con búsqueda por prefijo. Es un índice «externo»:
    no duplica el texto, solo guarda el índice, y unos disparadores lo mantienen al día. Se
    crea y se rellena una sola vez; devuelve False si este SQLite no tiene FTS5 (entonces la
    búsqueda sigue usando LIKE)."""
    try:
        existia = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'correo_fts'").fetchone() is not None
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS correo_fts USING fts5({_FTS_CORREO_COLUMNAS}, "
            "content='correo_mensajes', content_rowid='id', tokenize='unicode61 remove_diacritics 2', prefix='2 3')"
        )
    except sqlite3.OperationalError:
        return False
    if not existia:
        # Primero el texto de los solo-HTML y la reconstrucción, SIN disparadores: un 'delete' de
        # una fila que el índice aún no contiene lo corrompería.
        for t in ("correo_fts_ai", "correo_fts_ad", "correo_fts_au"):
            conn.execute(f"DROP TRIGGER IF EXISTS {t}")
        _rellenar_texto_de_correos_html(conn)
        conn.execute("INSERT INTO correo_fts(correo_fts) VALUES ('rebuild')")
    nuevas = ", ".join(f"new.{c.strip()}" for c in _FTS_CORREO_COLUMNAS.split(","))
    viejas = ", ".join(f"old.{c.strip()}" for c in _FTS_CORREO_COLUMNAS.split(","))
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS correo_fts_ai AFTER INSERT ON correo_mensajes BEGIN "
                 f"INSERT INTO correo_fts(rowid, {_FTS_CORREO_COLUMNAS}) VALUES (new.id, {nuevas}); END")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS correo_fts_ad AFTER DELETE ON correo_mensajes BEGIN "
                 f"INSERT INTO correo_fts(correo_fts, rowid, {_FTS_CORREO_COLUMNAS}) VALUES ('delete', old.id, {viejas}); END")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS correo_fts_au AFTER UPDATE OF {_FTS_CORREO_COLUMNAS} ON correo_mensajes BEGIN "
                 f"INSERT INTO correo_fts(correo_fts, rowid, {_FTS_CORREO_COLUMNAS}) VALUES ('delete', old.id, {viejas}); "
                 f"INSERT INTO correo_fts(rowid, {_FTS_CORREO_COLUMNAS}) VALUES (new.id, {nuevas}); END")
    return True


def _rellenar_texto_de_correos_html(conn: sqlite3.Connection) -> None:
    """Los correos solo-HTML no tenían texto plano y por eso no se encontraban por su cuerpo: se
    les saca el texto del HTML (una sola vez, al crear el índice)."""
    from .texto_html import html_a_texto_indexable
    filas = conn.execute("SELECT id, cuerpo_html FROM correo_mensajes WHERE (cuerpo_texto IS NULL OR cuerpo_texto = '') AND cuerpo_html IS NOT NULL").fetchall()
    for f in filas:
        texto = html_a_texto_indexable(f["cuerpo_html"])
        if texto:
            conn.execute("UPDATE correo_mensajes SET cuerpo_texto = ? WHERE id = ?", (texto, f["id"]))


def reconstruir_indice_correo() -> int:
    """Vuelve a construir el índice de búsqueda del correo desde cero (por si se desincroniza)."""
    conn = get_connection()
    try:
        if not _asegurar_fts_correo(conn):
            return 0
        conn.execute("INSERT INTO correo_fts(correo_fts) VALUES ('rebuild')")
        conn.commit()
        return conn.execute("SELECT COUNT(*) FROM correo_mensajes").fetchone()[0]
    finally:
        conn.close()


def fts_correo_disponible() -> bool:
    conn = get_connection()
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'correo_fts'").fetchone() is not None
    finally:
        conn.close()


_TROZO_BUSQUEDA = re.compile(r'"([^"]+)"|(\S+)')


def consulta_fts(texto: str) -> str | None:
    """Texto escrito por el usuario -> expresión FTS5 segura. Cada palabra busca por prefijo
    («fact» encuentra «factura»), lo que va entre comillas busca la frase exacta, y se exigen
    todas. Todo va entre comillas para que ningún carácter se interprete como operador."""
    # Con símbolos que el índice descarta (% _ $ € # & /) o sin ninguna letra/dígito, el usuario
    # busca el texto literal: ahí se usa LIKE, que sí lo respeta («50%» no es «500»).
    if not re.search(r"[^\W_]", texto or "") or re.search(r"[%_$€#&/\\]", texto or ""):
        return None
    partes = []
    for m in _TROZO_BUSQUEDA.finditer(texto or ""):
        frase, palabra = m.group(1), m.group(2)
        if frase:
            partes.append('"' + frase.replace('"', '""') + '"')
        elif palabra:
            partes.append('"' + palabra.replace('"', '""') + '"*')
    return " ".join(partes) or None


def _crear_vista_participantes_todos(conn: sqlite3.Connection) -> None:
    """`tareas_participantes_todos`: quién puede ver/trabajar cada tarea, sumando a los
    participantes explícitos (tareas_participantes) los del PROYECTO compartido en que está la
    tarea: los miembros con su rol, el dueño del proyecto como colaborador y los supervisores del
    despacho como observadores. Solo para comprobar PERMISOS: las listas generales («Mis tareas»,
    «Mi día») siguen usando solo la tabla explícita, o se llenarían con todo lo del equipo.
    Siempre exige el mismo despacho que el dueño del proyecto (quien sale del despacho lo pierde)."""
    conn.execute("DROP VIEW IF EXISTS tareas_participantes_todos")
    conn.execute(
        """CREATE VIEW tareas_participantes_todos AS
           SELECT tarea_id, usuario_id, rol FROM tareas_participantes
           UNION
           SELECT t.id, m.usuario_id, m.rol
             FROM tareas_outlook t
             JOIN categorias c ON c.id = t.categoria_id AND c.proy_compartido = 1 AND c.papelera_en IS NULL
             JOIN proyecto_miembros m ON m.categoria_id = c.id
             JOIN usuarios um ON um.id = m.usuario_id
             JOIN usuarios uo ON uo.id = c.usuario_id
            WHERE um.tenant_id IS NOT NULL AND um.tenant_id = uo.tenant_id
           UNION
           SELECT t.id, c.usuario_id, 'colabora'
             FROM tareas_outlook t
             JOIN categorias c ON c.id = t.categoria_id AND c.proy_compartido = 1 AND c.papelera_en IS NULL
            WHERE t.usuario_id != c.usuario_id
           UNION
           SELECT t.id, us.id, 'observa'
             FROM tareas_outlook t
             JOIN categorias c ON c.id = t.categoria_id AND c.proy_compartido = 1 AND c.papelera_en IS NULL
             JOIN usuarios uo ON uo.id = c.usuario_id
             JOIN usuarios us ON us.tenant_id = uo.tenant_id AND us.supervisor_tenant = 1
            WHERE uo.tenant_id IS NOT NULL AND us.id != t.usuario_id AND us.id != c.usuario_id"""
    )


def estado_carpeta_correo(cuenta_id: int, carpeta: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_carpetas WHERE cuenta_id = ? AND nombre = ?", (cuenta_id, carpeta)
        ).fetchone()
    finally:
        conn.close()


def guardar_estado_carpeta_correo(cuenta_id: int, carpeta: str, **campos) -> None:
    """Actualiza uidvalidity, ultimo_uid_sincronizado, ultima_pasada_completa y descarga_pendiente."""
    permitidos = ("uidvalidity", "ultimo_uid_sincronizado", "ultima_pasada_completa", "descarga_pendiente")
    columnas = [c for c in campos if c in permitidos]
    if not columnas:
        return
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE correo_carpetas SET {', '.join(c + ' = ?' for c in columnas)} WHERE cuenta_id = ? AND nombre = ?",
            [campos[c] for c in columnas] + [cuenta_id, carpeta],
        )
        conn.commit()
    finally:
        conn.close()


def vaciar_carpeta_correo(cuenta_id: int, carpeta: str) -> None:
    """El servidor ha cambiado el UIDVALIDITY de la carpeta: los UID guardados ya no
    valen. Se borra lo cacheado de esa carpeta (se volverá a descargar) y las operaciones
    pendientes sobre ella."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ?", (cuenta_id, carpeta))
        conn.execute("DELETE FROM correo_operaciones WHERE cuenta_id = ? AND carpeta = ?", (cuenta_id, carpeta))
        conn.execute(
            "UPDATE correo_carpetas SET ultimo_uid_sincronizado = NULL, ultima_pasada_completa = NULL, descarga_pendiente = 0 "
            "WHERE cuenta_id = ? AND nombre = ?", (cuenta_id, carpeta),
        )
        conn.commit()
    finally:
        conn.close()


# --- Cola de cambios hacia el servidor (correo_operaciones) ---------------------------

MAX_INTENTOS_OPERACION_CORREO = 5


def encolar_operacion_correo(cuenta_id: int, carpeta: str, uid: str, operacion: str, uidvalidity: str | None = None) -> int:
    conn = get_connection()
    try:
        if uidvalidity is None:
            fila = conn.execute("SELECT uidvalidity FROM correo_carpetas WHERE cuenta_id = ? AND nombre = ?", (cuenta_id, carpeta)).fetchone()
            uidvalidity = fila["uidvalidity"] if fila else None
        cur = conn.execute(
            "INSERT INTO correo_operaciones (cuenta_id, carpeta, uid, uidvalidity, operacion, creada_en) VALUES (?, ?, ?, ?, ?, ?)",
            (cuenta_id, carpeta, uid, uidvalidity, operacion, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def operaciones_pendientes_correo(cuenta_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_operaciones WHERE cuenta_id = ? AND estado = 'pendiente' ORDER BY id", (cuenta_id,)
        ).fetchall()
    finally:
        conn.close()


def operaciones_por_mensaje_correo(cuenta_id: int, carpeta: str) -> dict[str, set[str]]:
    """{uid: {operaciones pendientes}} de una carpeta: la sincronización de entrada no
    pisa el estado de esos mensajes ni vuelve a descargar los que se están borrando."""
    conn = get_connection()
    try:
        resultado: dict[str, set[str]] = {}
        for f in conn.execute(
            "SELECT uid, operacion FROM correo_operaciones WHERE cuenta_id = ? AND carpeta = ? AND estado = 'pendiente'", (cuenta_id, carpeta)
        ):
            resultado.setdefault(f["uid"], set()).add(f["operacion"])
        return resultado
    finally:
        conn.close()


def cerrar_operacion_correo(operacion_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM correo_operaciones WHERE id = ?", (operacion_id,))
        conn.commit()
    finally:
        conn.close()


def fallar_operacion_correo(operacion_id: int, error: str) -> None:
    """Un intento fallido: se reintentará; tras MAX_INTENTOS_OPERACION_CORREO pasa a 'error'."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE correo_operaciones SET intentos = intentos + 1, ultimo_error = ?, "
            "estado = CASE WHEN intentos + 1 >= ? THEN 'error' ELSE estado END WHERE id = ?",
            (error[:300], MAX_INTENTOS_OPERACION_CORREO, operacion_id),
        )
        conn.commit()
    finally:
        conn.close()


def contar_operaciones_correo_con_error(usuario_id: int) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_operaciones o JOIN correo_cuentas c ON c.id = o.cuenta_id "
            "WHERE c.usuario_id = ? AND o.estado = 'error'", (usuario_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def mensaje_correo_por_uid(cuenta_id: int, carpeta: str, uid: str) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND uid = ?", (cuenta_id, carpeta, uid)
        ).fetchone()
    finally:
        conn.close()


def estados_mensajes_correo(cuenta_id: int, carpeta: str, uid_minimo: int | None = None) -> dict[str, tuple[int, int]]:
    """{uid: (leido, destacado)} de los mensajes cacheados, opcionalmente solo desde un UID."""
    conn = get_connection()
    try:
        sql = "SELECT uid, leido, destacado FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ?"
        params: list = [cuenta_id, carpeta]
        if uid_minimo is not None:
            sql += " AND CAST(uid AS INTEGER) >= ?"
            params.append(uid_minimo)
        return {f["uid"]: (f["leido"], f["destacado"]) for f in conn.execute(sql, params)}
    finally:
        conn.close()


def aplicar_estados_servidor_correo(cuenta_id: int, carpeta: str, cambios: list[tuple[str, int, int]]) -> None:
    """`cambios`: (uid, leido, destacado) que el servidor tiene distinto de lo cacheado."""
    if not cambios:
        return
    conn = get_connection()
    try:
        conn.executemany(
            "UPDATE correo_mensajes SET leido = ?, destacado = ? WHERE cuenta_id = ? AND carpeta = ? AND uid = ?",
            [(leido, destacado, cuenta_id, carpeta, uid) for uid, leido, destacado in cambios],
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_mensajes_correo_por_uid(cuenta_id: int, carpeta: str, uids: list[str]) -> int:
    """Quita de la caché los mensajes que ya no existen en el servidor."""
    if not uids:
        return 0
    conn = get_connection()
    try:
        total = 0
        for inicio in range(0, len(uids), 500):
            lote = uids[inicio:inicio + 500]
            cur = conn.execute(
                f"DELETE FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND uid IN ({','.join('?' * len(lote))})",
                [cuenta_id, carpeta, *lote],
            )
            total += cur.rowcount
        conn.commit()
        return total
    finally:
        conn.close()


_PREFIJOS_ASUNTO = re.compile(r"^\s*(?:(?:re|rv|fwd?|enc|res|aw|sv|tr)\s*(?:\[\d+\])?\s*:\s*)+", re.IGNORECASE)
_PATRON_ID_MENSAJE = re.compile(r"<[^<>\s]+>")


def normalizar_asunto(asunto: str | None) -> str:
    """Asunto sin prefijos de respuesta/reenvío (Re:, RE:, Rv:, Fwd:...),
    en minúsculas y con espacios colapsados: lo que comparten los mensajes
    de una misma conversación."""
    return " ".join(_PREFIJOS_ASUNTO.sub("", asunto or "").lower().split())


def _direccion_simple(texto: str | None) -> str:
    from email.utils import parseaddr
    return parseaddr(texto or "")[1].strip().lower()


def _clave_hilo_por_asunto(asunto, remitente, destinatarios, direccion_propia: str) -> str | None:
    """Sin cabeceras utilizables: asunto normalizado + contraparte (el
    remitente si no soy yo; si no, el primer destinatario). Así dos
    «Factura» de proveedores distintos no se mezclan. Asunto vacío = sin hilo."""
    norm = normalizar_asunto(asunto)
    if not norm:
        return None
    remitente_dir = _direccion_simple(remitente)
    if remitente_dir and remitente_dir != direccion_propia:
        contraparte = remitente_dir
    else:
        primero = (destinatarios or "").split(",")[0]
        contraparte = _direccion_simple(primero) or remitente_dir
    return f"{norm}|{contraparte}"[:300]


def calcular_hilo_clave(
    conn: sqlite3.Connection, cuenta_id: int, asunto, remitente, destinatarios,
    in_reply_to: str | None, referencias: str | None, direccion_propia: str,
) -> str | None:
    """Si el mensaje responde (In-Reply-To/References) a uno ya guardado de
    la misma cuenta, hereda su hilo; si no, se deduce del asunto y la contraparte."""
    ids = _PATRON_ID_MENSAJE.findall(in_reply_to or "") + _PATRON_ID_MENSAJE.findall(referencias or "")[::-1]
    for candidato in ids[:20]:
        fila = conn.execute(
            "SELECT hilo_clave FROM correo_mensajes WHERE cuenta_id = ? AND message_id = ? AND hilo_clave IS NOT NULL LIMIT 1",
            (cuenta_id, candidato),
        ).fetchone()
        if fila:
            return fila["hilo_clave"]
    return _clave_hilo_por_asunto(asunto, remitente, destinatarios, direccion_propia)


def _rellenar_hilos_correo(conn: sqlite3.Connection) -> None:
    """Migración idempotente: da clave de hilo a los mensajes que no la
    tienen (los guardados antes de existir las conversaciones)."""
    pendientes = conn.execute(
        """SELECT m.id, m.cuenta_id, m.asunto, m.remitente, m.destinatarios, lower(c.usuario) AS propia
           FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
           WHERE m.hilo_clave IS NULL AND m.asunto IS NOT NULL AND trim(m.asunto) <> ''"""
    ).fetchall()
    for f in pendientes:
        clave = _clave_hilo_por_asunto(f["asunto"], f["remitente"], f["destinatarios"], _direccion_simple(f["propia"]))
        if clave:
            conn.execute("UPDATE correo_mensajes SET hilo_clave = ? WHERE id = ?", (clave, f["id"]))
    conn.commit()


def contar_hilos_correo(cuenta_id: int, claves: list[str]) -> dict[str, int]:
    """Nº de mensajes de la cuenta (todas las carpetas) por clave de hilo."""
    claves = [c for c in dict.fromkeys(claves) if c]
    if not claves:
        return {}
    conn = get_connection()
    try:
        marcadores = ",".join("?" * len(claves))
        filas = conn.execute(
            f"""SELECT hilo_clave, COUNT(*) AS n FROM correo_mensajes
                WHERE cuenta_id = ? AND hilo_clave IN ({marcadores}) GROUP BY hilo_clave""",
            [cuenta_id, *claves],
        ).fetchall()
        return {f["hilo_clave"]: f["n"] for f in filas}
    finally:
        conn.close()


def mensajes_del_hilo_correo(cuenta_id: int, hilo_clave: str | None) -> list[sqlite3.Row]:
    if not hilo_clave:
        return []
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT id, carpeta, asunto, remitente, fecha, leido FROM correo_mensajes
               WHERE cuenta_id = ? AND hilo_clave = ? ORDER BY fecha ASC, id ASC LIMIT 100""",
            (cuenta_id, hilo_clave),
        ).fetchall()
    finally:
        conn.close()


def guardar_mensaje_correo(
    cuenta_id: int, uid: str, asunto: str | None, remitente: str | None,
    destinatarios: str | None, fecha: str | None, cuerpo_texto: str | None,
    cuerpo_html: str | None, carpeta: str = "INBOX", message_id: str | None = None,
    cc: str | None = None, in_reply_to: str | None = None, referencias: str | None = None,
    leido: bool = False, destacado: bool = False,
) -> int | None:
    """`leido`/`destacado`: el estado que ya tiene el mensaje en el servidor.
    Devuelve el id del mensaje (recién insertado, o el ya existente si
    `(cuenta_id, carpeta, uid)` ya estaba en caché) — para poder colgarle
    adjuntos justo después."""
    conn = get_connection()
    try:
        cuenta = conn.execute("SELECT usuario FROM correo_cuentas WHERE id = ?", (cuenta_id,)).fetchone()
        hilo = calcular_hilo_clave(
            conn, cuenta_id, asunto, remitente, destinatarios, in_reply_to, referencias,
            _direccion_simple(cuenta["usuario"]) if cuenta else "",
        )
        conn.execute(
            """INSERT OR IGNORE INTO correo_mensajes
               (cuenta_id, carpeta, uid, asunto, remitente, destinatarios,
                cc, fecha, cuerpo_texto, cuerpo_html, message_id, in_reply_to, referencias,
                hilo_clave, descargado_en, leido, destacado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cuenta_id, carpeta, uid, asunto, remitente, destinatarios,
             cc, fecha, cuerpo_texto, cuerpo_html, message_id,
             (in_reply_to or None) and in_reply_to[:1000], (referencias or None) and referencias[:4000],
             hilo, now_iso(), int(leido), int(destacado)),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT id FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND uid = ?",
            (cuenta_id, carpeta, uid),
        ).fetchone()
        return fila["id"] if fila else None
    finally:
        conn.close()


def _like_literal(texto: str) -> str:
    """Patrón LIKE que busca `texto` tal cual (sin que % y _ hagan de comodín)."""
    return "%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def listar_mensajes_correo(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 50, incluir_pospuestos: bool = False,
    con_adjuntos: bool = False, categoria_id: int | None = None, desde: str | None = None,
    hasta: str | None = None, solo_destacados: bool = False, cliente_fiscal_id: int | None = None,
) -> list[sqlite3.Row]:
    """`texto` busca en asunto, remitente, destinatarios y CUERPO del mensaje.
    Filtros: con adjuntos, categoría, rango de fechas (YYYY-MM-DD, `hasta`
    inclusive), destacados y cliente fiscal vinculado."""
    conn = get_connection()
    try:
        cond = ["cuenta_id = ?", "carpeta = ?"]
        params: list = [cuenta_id, carpeta]
        if solo_no_leidos:
            cond.append("leido = 0")
        if texto:
            expresion = consulta_fts(texto) if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'correo_fts'").fetchone() else None
            if expresion:
                # Índice de texto completo: instantáneo aunque haya decenas de miles de correos
                # (LIKE '%x%' recorría todos los cuerpos). Sin acentos ni mayúsculas, por prefijo.
                cond.append("id IN (SELECT rowid FROM correo_fts WHERE correo_fts MATCH ?)")
                params.append(expresion)
            else:
                cond.append(
                    "(asunto LIKE ? ESCAPE '\\' OR remitente LIKE ? ESCAPE '\\' OR destinatarios LIKE ? ESCAPE '\\' "
                    "OR cuerpo_texto LIKE ? ESCAPE '\\')"
                )
                params.extend([_like_literal(texto)] * 4)
        if con_adjuntos:
            cond.append("EXISTS (SELECT 1 FROM correo_adjuntos a WHERE a.mensaje_id = correo_mensajes.id)")
        if categoria_id is not None:
            cond.append("categoria_id = ?"); params.append(categoria_id)
        if cliente_fiscal_id is not None:
            cond.append("cliente_fiscal_id = ?"); params.append(cliente_fiscal_id)
        if solo_destacados:
            cond.append("destacado = 1")
        if desde:
            cond.append("fecha >= ?"); params.append(desde)
        if hasta:
            cond.append("fecha < ?"); params.append(_fecha_exclusiva(hasta))
        if not incluir_pospuestos:
            cond.append("(pospuesto_hasta IS NULL OR pospuesto_hasta <= ?)")
            params.append(now_iso())
        where = " AND ".join(cond)
        params.append(limite)
        return conn.execute(
            # "ORDER BY fecha DESC" basta: SQLite ya trata NULL como el valor
            # más pequeño, así que en DESC los mensajes sin fecha quedan al
            # final solos — no hace falta "(fecha IS NULL), fecha DESC" (esa
            # expresión extra impedía usar idx_correo_mensajes_cuenta_carpeta_fecha
            # para el propio ORDER BY, forzando un TEMP B-TREE en cada carga
            # de la bandeja).
            f"""SELECT * FROM correo_mensajes WHERE {where}
                ORDER BY fecha DESC LIMIT ?""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_mensaje_correo(mensaje_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_mensajes WHERE id = ?", (mensaje_id,)).fetchone()
    finally:
        conn.close()


def mensaje_correo_pertenece_a_usuario(usuario_id: int, mensaje_id: int) -> bool:
    """Comprueba que un mensaje cuelga de una cuenta del usuario, antes de
    dejarle leer/modificar un `mensaje_id` que le podrían pasar por URL."""
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT 1 FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE m.id = ? AND c.usuario_id = ?""",
            (mensaje_id, usuario_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def guardar_adjuntos_correo(mensaje_id: int, adjuntos: list[dict]) -> None:
    """`adjuntos` es una lista de {"nombre", "tipo", "bytes"}, tal como los
    devuelve app.correo._cuerpos()."""
    conn = get_connection()
    try:
        for a in adjuntos:
            conn.execute(
                """INSERT INTO correo_adjuntos
                   (mensaje_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (mensaje_id, a["nombre"], a["tipo"], len(a["bytes"]), a["bytes"], now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def listar_adjuntos_correo(mensaje_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, mensaje_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en "
            "FROM correo_adjuntos WHERE mensaje_id = ? ORDER BY id",
            (mensaje_id,),
        ).fetchall()
    finally:
        conn.close()


def obtener_adjunto_correo(adjunto_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM correo_adjuntos WHERE id = ?", (adjunto_id,)).fetchone()
    finally:
        conn.close()


def adjunto_correo_pertenece_a_usuario(usuario_id: int, adjunto_id: int) -> bool:
    conn = get_connection()
    try:
        fila = conn.execute(
            """SELECT 1 FROM correo_adjuntos a
               JOIN correo_mensajes m ON m.id = a.mensaje_id
               JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE a.id = ? AND c.usuario_id = ?""",
            (adjunto_id, usuario_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def marcar_leido_mensaje_correo(mensaje_id: int, leido: bool = True) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET leido = ? WHERE id = ?", (int(leido), mensaje_id))
        conn.commit()
    finally:
        conn.close()


def destacar_mensaje_correo(mensaje_id: int, destacado: bool, fecha_aviso: str | None = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE correo_mensajes SET destacado = ?, fecha_aviso = ? WHERE id = ?",
            (int(destacado), fecha_aviso if destacado else None, mensaje_id),
        )
        conn.commit()
    finally:
        conn.close()


def posponer_mensaje_correo(mensaje_id: int, hasta: str | None) -> None:
    """`hasta=None` quita el pospuesto (el mensaje vuelve a verse ya)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET pospuesto_hasta = ? WHERE id = ?", (hasta, mensaje_id))
        conn.commit()
    finally:
        conn.close()


def eliminar_mensaje_correo(mensaje_id: int) -> None:
    """Borra el mensaje de la caché local (no del servidor de correo). Si
    sigue en el buzón real, una futura sincronización volverá a descargarlo
    (su UID ya no está en la caché local) — borrarlo también en el servidor
    queda fuera de alcance de esta fase."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM correo_mensajes WHERE id = ?", (mensaje_id,))
        conn.commit()
    finally:
        conn.close()


def contar_no_leidos_correo(cuenta_id: int, carpeta: str = "INBOX") -> int:
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT COUNT(*) AS n FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND leido = 0",
            (cuenta_id, carpeta),
        ).fetchone()
        return fila["n"]
    finally:
        conn.close()


def contar_no_leidos_por_cuenta_y_carpeta(usuario_id: int) -> dict[int, dict[str, int]]:
    """Una sola consulta agregada para el rail de Correo (cuenta_id ->
    {carpeta: no_leidos}) -- antes _contexto_bandeja hacía una llamada a
    contar_no_leidos_correo() POR CADA cuenta (N+1), y esa función solo
    cuenta una carpeta a la vez (por defecto INBOX), así que el badge de
    cada cuenta reflejaba solo lo no leído en INBOX, nunca el total real
    de la cuenta ni el desglose por carpeta."""
    conn = get_connection()
    try:
        # Parte de las cuentas del usuario y cuenta sobre el índice parcial
        # idx_correo_no_leidos (solo no leídos, cubriente): O(no leídos) sin tocar las filas.
        filas = conn.execute(
            """SELECT cuenta_id, carpeta, COUNT(*) AS n FROM correo_mensajes
               WHERE leido = 0 AND cuenta_id IN (SELECT id FROM correo_cuentas WHERE usuario_id = ?)
               GROUP BY cuenta_id, carpeta""",
            (usuario_id,),
        ).fetchall()
        resultado: dict[int, dict[str, int]] = {}
        for fila in filas:
            resultado.setdefault(fila["cuenta_id"], {})[fila["carpeta"]] = fila["n"]
        return resultado
    finally:
        conn.close()


def contar_no_leidos_total_correo(usuario_id: int) -> int:
    """Total de mensajes no leídos en TODAS las cuentas y carpetas de un
    usuario (para el badge de "correo nuevo" del rail de iconos)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT COUNT(*) AS n FROM correo_mensajes
               WHERE leido = 0 AND cuenta_id IN (SELECT id FROM correo_cuentas WHERE usuario_id = ?)""",
            (usuario_id,),
        ).fetchone()["n"]
    finally:
        conn.close()


# --- Proyectos compartidos -----------------------------------------------------------------
#
# Un proyecto es una fila de `categorias`. Por defecto es personal; su dueño puede compartirlo con
# compañeros de SU despacho (rol «colabora» o «observa»). Los miembros ven las tareas del proyecto,
# y los que colaboran las crean, editan y completan; la tabla de miembros nunca cruza de despacho:
# `_rol_en_proyecto` exige el mismo tenant que el dueño cada vez que se consulta.

ESTADOS_PROYECTO = ("activo", "en_pausa", "completado", "archivado")
ROLES_PROYECTO = ("colabora", "observa")
MAX_MIEMBROS_PROYECTO = 50


def _rol_en_proyecto(conn: sqlite3.Connection, usuario_id: int, categoria_id: int | None) -> str | None:
    """'dueno', 'colabora', 'observa' o None. Un supervisor del despacho ve (solo lectura) todo proyecto compartido."""
    if categoria_id is None:
        return None
    c = conn.execute("SELECT usuario_id, proy_compartido FROM categorias WHERE id = ? AND papelera_en IS NULL", (categoria_id,)).fetchone()
    if c is None:
        return None
    if c["usuario_id"] == usuario_id:
        return "dueno"
    if not c["proy_compartido"]:
        return None
    m = conn.execute(
        """SELECT m.rol FROM proyecto_miembros m
           JOIN usuarios um ON um.id = m.usuario_id JOIN usuarios uo ON uo.id = ?
           WHERE m.categoria_id = ? AND m.usuario_id = ? AND um.tenant_id IS NOT NULL AND um.tenant_id = uo.tenant_id""",
        (c["usuario_id"], categoria_id, usuario_id),
    ).fetchone()
    if m is not None:
        return m["rol"]
    sup = conn.execute(
        """SELECT 1 FROM usuarios us JOIN usuarios uo ON uo.id = ?
           WHERE us.id = ? AND us.supervisor_tenant = 1 AND uo.tenant_id IS NOT NULL AND us.tenant_id = uo.tenant_id""",
        (c["usuario_id"], usuario_id),
    ).fetchone()
    return "observa" if sup else None


def rol_en_proyecto(usuario_id: int, categoria_id: int) -> str | None:
    conn = get_connection()
    try:
        return _rol_en_proyecto(conn, usuario_id, categoria_id)
    finally:
        conn.close()


def obtener_proyecto(usuario_id: int, categoria_id: int) -> dict | None:
    """El proyecto (con `rol` y el nombre de su dueño y de su responsable) si el usuario puede verlo."""
    conn = get_connection()
    try:
        rol = _rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None:
            return None
        f = conn.execute(
            """SELECT c.*, COALESCE(NULLIF(pd.nombre_mostrado, ''), ud.email) AS dueno_nombre,
                      COALESCE(NULLIF(pr.nombre_mostrado, ''), ur.email) AS responsable_nombre, cf.nombre AS cliente_nombre,
                      c.proy_estado AS estado, c.proy_descripcion AS descripcion, c.proy_fecha_objetivo AS fecha_objetivo,
                      c.proy_responsable_id AS responsable_id, c.proy_cliente_id AS cliente_fiscal_id, c.proy_compartido AS compartido
               FROM categorias c JOIN usuarios ud ON ud.id = c.usuario_id LEFT JOIN usuario_perfil pd ON pd.usuario_id = c.usuario_id
               LEFT JOIN usuarios ur ON ur.id = c.proy_responsable_id LEFT JOIN usuario_perfil pr ON pr.usuario_id = c.proy_responsable_id
               LEFT JOIN clientes_fiscales cf ON cf.id = c.proy_cliente_id
               WHERE c.id = ?""",
            (categoria_id,),
        ).fetchone()
        proyecto = dict(f)
        proyecto["rol"] = rol
        return proyecto
    finally:
        conn.close()


def listar_proyectos_compartidos_conmigo(usuario_id: int) -> list[dict]:
    """Proyectos de otros que el usuario puede ver: como miembro o, si es supervisor, todos los compartidos
    del despacho (solo lectura). Una sola consulta (se pide en el inicio); mismas reglas que _rol_en_proyecto."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT c.*, COALESCE(NULLIF(pd.nombre_mostrado, ''), ud.email) AS dueno_nombre, COALESCE(m.rol, 'observa') AS rol
               FROM categorias c
               JOIN usuarios ud ON ud.id = c.usuario_id LEFT JOIN usuario_perfil pd ON pd.usuario_id = c.usuario_id
               JOIN usuarios yo ON yo.id = ?
               LEFT JOIN proyecto_miembros m ON m.categoria_id = c.id AND m.usuario_id = yo.id
               WHERE c.proy_compartido = 1 AND c.papelera_en IS NULL AND c.usuario_id != yo.id AND c.proy_estado != 'archivado'
                 AND yo.tenant_id IS NOT NULL AND yo.tenant_id = ud.tenant_id
                 AND (m.usuario_id IS NOT NULL OR yo.supervisor_tenant = 1)
               ORDER BY c.nombre""",
            (usuario_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def listar_proyectos_usables(usuario_id: int) -> list[dict]:
    """Proyectos en los que se pueden poner tareas: los propios y los compartidos donde se colabora."""
    propios = [dict(c, propio=True, rol="dueno") for c in listar_categorias(usuario_id)]
    ajenos = [dict(c, propio=False) for c in listar_proyectos_compartidos_conmigo(usuario_id) if c["rol"] == "colabora"]
    return propios + ajenos


def miembros_de_proyecto(categoria_id: int) -> list[dict]:
    conn = get_connection()
    try:
        c = conn.execute("SELECT usuario_id FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
        if c is None:
            return []
        filas = conn.execute(
            """SELECT m.usuario_id, m.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre, u.email
               FROM proyecto_miembros m JOIN usuarios u ON u.id = m.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = m.usuario_id
               JOIN usuarios uo ON uo.id = ? WHERE m.categoria_id = ? AND u.tenant_id IS NOT NULL AND u.tenant_id = uo.tenant_id
               ORDER BY nombre""",
            (c["usuario_id"], categoria_id),
        ).fetchall()
        return [dict(f, es_dueno=False) for f in filas]
    finally:
        conn.close()


def compartir_proyecto(usuario_id: int, categoria_id: int, otro_id: int, rol: str = "colabora") -> bool:
    """El dueño añade (o cambia el rol de) un compañero de su despacho. False si no procede."""
    if rol not in ROLES_PROYECTO:
        return False
    conn = get_connection()
    try:
        if _rol_en_proyecto(conn, usuario_id, categoria_id) != "dueno":
            return False
        destino = _companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        ya = conn.execute("SELECT 1 FROM proyecto_miembros WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, destino)).fetchone()
        if ya is None and conn.execute("SELECT COUNT(*) FROM proyecto_miembros WHERE categoria_id = ?", (categoria_id,)).fetchone()[0] >= MAX_MIEMBROS_PROYECTO:
            return False
        conn.execute(
            """INSERT INTO proyecto_miembros (categoria_id, usuario_id, rol, anadido_en) VALUES (?, ?, ?, ?)
               ON CONFLICT (categoria_id, usuario_id) DO UPDATE SET rol = excluded.rol""",
            (categoria_id, destino, rol, now_iso()),
        )
        conn.execute("UPDATE categorias SET proy_compartido = 1 WHERE id = ?", (categoria_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def quitar_miembro_proyecto(usuario_id: int, categoria_id: int, otro_id: int) -> bool:
    """El dueño quita a quien quiera; cada miembro puede salirse. Sin miembros, el proyecto vuelve a ser personal."""
    conn = get_connection()
    try:
        rol = _rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None or (rol != "dueno" and otro_id != usuario_id):
            return False
        cur = conn.execute("DELETE FROM proyecto_miembros WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, otro_id))
        if conn.execute("SELECT COUNT(*) FROM proyecto_miembros WHERE categoria_id = ?", (categoria_id,)).fetchone()[0] == 0:
            conn.execute("UPDATE categorias SET proy_compartido = 0 WHERE id = ?", (categoria_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def actualizar_proyecto(
    usuario_id: int, categoria_id: int, estado: str | None = None, descripcion: str | None = None,
    fecha_objetivo: str | None = None, responsable_id: int | None = None, cliente_fiscal_id: int | None = None,
    cambiar_responsable: bool = False, cambiar_cliente: bool = False,
) -> bool:
    """Datos del proyecto (solo el dueño). `responsable_id` ha de ser el propio dueño o un miembro; el cliente, del despacho."""
    conn = get_connection()
    try:
        if _rol_en_proyecto(conn, usuario_id, categoria_id) != "dueno":
            return False
        campos: dict = {}
        if estado is not None:
            if estado not in ESTADOS_PROYECTO:
                return False
            campos["proy_estado"] = estado
        if descripcion is not None:
            campos["proy_descripcion"] = descripcion.strip()[:2000] or None
        if fecha_objetivo is not None:
            try:
                campos["proy_fecha_objetivo"] = datetime.strptime(fecha_objetivo.strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d") if fecha_objetivo.strip() else None
            except ValueError:
                return False
        if cambiar_responsable:
            if responsable_id is not None and responsable_id != usuario_id and conn.execute(
                "SELECT 1 FROM proyecto_miembros WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, responsable_id)
            ).fetchone() is None:
                return False
            campos["proy_responsable_id"] = responsable_id
        if cambiar_cliente:
            campos["proy_cliente_id"] = _cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id) if cliente_fiscal_id else None
        if not campos:
            return True
        conn.execute(f"UPDATE categorias SET {', '.join(c + ' = ?' for c in campos)} WHERE id = ?", [*campos.values(), categoria_id])
        conn.commit()
        return True
    finally:
        conn.close()


# --- secciones y tareas del proyecto ---

def listar_secciones(categoria_id: int) -> list[dict]:
    conn = get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM proyecto_secciones WHERE categoria_id = ? ORDER BY orden, id", (categoria_id,))]
    finally:
        conn.close()


def _puede_organizar_proyecto(conn: sqlite3.Connection, usuario_id: int, categoria_id: int) -> bool:
    return _rol_en_proyecto(conn, usuario_id, categoria_id) in ("dueno", "colabora")


def crear_seccion(usuario_id: int, categoria_id: int, nombre: str) -> int | None:
    nombre = (nombre or "").strip()[:80]
    conn = get_connection()
    try:
        if not nombre or not _puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
        siguiente = conn.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM proyecto_secciones WHERE categoria_id = ?", (categoria_id,)).fetchone()[0]
        cur = conn.execute("INSERT INTO proyecto_secciones (categoria_id, nombre, orden) VALUES (?, ?, ?)", (categoria_id, nombre, siguiente))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _categoria_de_seccion(conn: sqlite3.Connection, seccion_id: int) -> int | None:
    f = conn.execute("SELECT categoria_id FROM proyecto_secciones WHERE id = ?", (seccion_id,)).fetchone()
    return f["categoria_id"] if f else None


def renombrar_seccion(usuario_id: int, seccion_id: int, nombre: str) -> bool:
    nombre = (nombre or "").strip()[:80]
    conn = get_connection()
    try:
        categoria = _categoria_de_seccion(conn, seccion_id)
        if not nombre or categoria is None or not _puede_organizar_proyecto(conn, usuario_id, categoria):
            return False
        conn.execute("UPDATE proyecto_secciones SET nombre = ? WHERE id = ?", (nombre, seccion_id))
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_seccion(usuario_id: int, seccion_id: int) -> bool:
    """Borra la sección; sus tareas no se tocan (quedan «sin sección»)."""
    conn = get_connection()
    try:
        categoria = _categoria_de_seccion(conn, seccion_id)
        if categoria is None or not _puede_organizar_proyecto(conn, usuario_id, categoria):
            return False
        conn.execute("UPDATE tareas_outlook SET seccion_id = NULL WHERE seccion_id = ?", (seccion_id,))
        conn.execute("DELETE FROM proyecto_secciones WHERE id = ?", (seccion_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def mover_seccion(usuario_id: int, seccion_id: int, direccion: str) -> bool:
    conn = get_connection()
    try:
        categoria = _categoria_de_seccion(conn, seccion_id)
        if categoria is None or direccion not in ("arriba", "abajo") or not _puede_organizar_proyecto(conn, usuario_id, categoria):
            return False
        ids = [f["id"] for f in conn.execute("SELECT id FROM proyecto_secciones WHERE categoria_id = ? ORDER BY orden, id", (categoria,))]
        i = ids.index(seccion_id)
        j = i - 1 if direccion == "arriba" else i + 1
        if not 0 <= j < len(ids):
            return False
        ids[i], ids[j] = ids[j], ids[i]
        conn.executemany("UPDATE proyecto_secciones SET orden = ? WHERE id = ?", [(n, sid) for n, sid in enumerate(ids)])
        conn.commit()
        return True
    finally:
        conn.close()


def asignar_seccion_tarea(usuario_id: int, tarea_id: int, seccion_id: int | None) -> bool:
    """Mueve una tarea a una sección de SU proyecto (o la deja sin sección). Quien puede editar la tarea."""
    if not puede_editar_tarea(usuario_id, tarea_id):
        return False
    conn = get_connection()
    try:
        t = conn.execute("SELECT categoria_id FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        if t is None or t["categoria_id"] is None:
            return False
        if seccion_id is not None and _categoria_de_seccion(conn, seccion_id) != t["categoria_id"]:
            return False
        conn.execute("UPDATE tareas_outlook SET seccion_id = ? WHERE id = ?", (seccion_id, tarea_id))
        conn.commit()
        return True
    finally:
        conn.close()


def mover_tarea_en_proyecto(usuario_id: int, tarea_id: int, seccion_id: int | None, antes_de_id: int | None = None) -> bool:
    """Coloca una tarea en una sección (o sin sección) justo ANTES de otra tarea de esa sección, o al final si
    `antes_de_id` es None. Es lo que hace arrastrar y soltar en la lista del proyecto."""
    if not puede_editar_tarea(usuario_id, tarea_id):
        return False
    conn = get_connection()
    try:
        t = conn.execute("SELECT categoria_id FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        if t is None or t["categoria_id"] is None:
            return False
        categoria = t["categoria_id"]
        if seccion_id is not None and _categoria_de_seccion(conn, seccion_id) != categoria:
            return False
        ids = [f["id"] for f in conn.execute(
            """SELECT id FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL AND id != ?
               AND COALESCE(seccion_id, 0) = COALESCE(?, 0) ORDER BY orden_proyecto, id""",
            (categoria, tarea_id, seccion_id),
        )]
        if antes_de_id is not None and antes_de_id not in ids:
            return False
        posicion = ids.index(antes_de_id) if antes_de_id is not None else len(ids)
        ids.insert(posicion, tarea_id)
        conn.execute("UPDATE tareas_outlook SET seccion_id = ? WHERE id = ?", (seccion_id, tarea_id))
        conn.executemany("UPDATE tareas_outlook SET orden_proyecto = ? WHERE id = ?", [(n + 1, i) for n, i in enumerate(ids)])
        conn.commit()
        return True
    finally:
        conn.close()


def cambiar_fecha_tarea_proyecto(usuario_id: int, tarea_id: int, fecha: str | None) -> bool:
    """Cambia el DÍA de vencimiento conservando la hora si la tenía (arrastrar en el calendario). `fecha`: YYYY-MM-DD o None."""
    if not puede_editar_tarea(usuario_id, tarea_id):
        return False
    if fecha:
        try:
            fecha = datetime.strptime(fecha[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return False
    conn = get_connection()
    try:
        t = conn.execute("SELECT fecha_vencimiento FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        if t is None:
            return False
        antigua = t["fecha_vencimiento"] or ""
        nueva = (fecha + antigua[10:]) if fecha and len(antigua) > 10 else (fecha or None)
        conn.execute("UPDATE tareas_outlook SET fecha_vencimiento = ?, actualizada_en = ? WHERE id = ?", (nueva, now_iso(), tarea_id))
        conn.commit()
    finally:
        conn.close()
    registrar_actividad_tarea(usuario_id, tarea_id, "editada", f"vencimiento {fecha or '—'}")
    return True


def crear_tarea_en_proyecto(
    usuario_id: int, categoria_id: int, asunto: str, seccion_id: int | None = None, prioridad: str = "normal",
    fecha_vencimiento: str | None = None, asignada_a: int | None = None,
) -> int | None:
    """Alta de una tarea dentro de un proyecto: la puede crear el dueño o un colaborador. Hereda el cliente del proyecto."""
    conn = get_connection()
    try:
        if not _puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
        if seccion_id is not None and _categoria_de_seccion(conn, seccion_id) != categoria_id:
            seccion_id = None
        cliente = conn.execute("SELECT proy_cliente_id FROM categorias WHERE id = ?", (categoria_id,)).fetchone()["proy_cliente_id"]
        orden = conn.execute("SELECT COALESCE(MAX(orden_proyecto), 0) + 1 FROM tareas_outlook WHERE categoria_id = ?", (categoria_id,)).fetchone()[0]
    finally:
        conn.close()
    tarea_id = crear_tarea_outlook(
        usuario_id, asunto, prioridad=prioridad, fecha_vencimiento=fecha_vencimiento, categoria_id=categoria_id,
        cliente_fiscal_id=cliente, asignada_a=asignada_a,
    )
    conn = get_connection()
    try:
        conn.execute("UPDATE tareas_outlook SET seccion_id = ?, orden_proyecto = ? WHERE id = ?", (seccion_id, orden, tarea_id))
        conn.commit()
    finally:
        conn.close()
    return tarea_id


def tareas_de_proyecto(usuario_id: int, categoria_id: int, incluir_completadas: bool = True) -> list[dict]:
    """Todas las tareas del proyecto, sea quien sea su creador (si el usuario puede ver el proyecto)."""
    conn = get_connection()
    try:
        if _rol_en_proyecto(conn, usuario_id, categoria_id) is None:
            return []
        filas = conn.execute(
            f"""SELECT t.*, COALESCE(NULLIF(pc.nombre_mostrado, ''), uc.email) AS creador_nombre,
                       COALESCE(NULLIF(pa.nombre_mostrado, ''), ua.email) AS asignada_nombre,
                       (SELECT COUNT(*) FROM tarea_checklist i WHERE i.tarea_outlook_id = t.id) AS items_total,
                       (SELECT COALESCE(SUM(i.hecha), 0) FROM tarea_checklist i WHERE i.tarea_outlook_id = t.id) AS items_hechos
                FROM tareas_outlook t
                JOIN usuarios uc ON uc.id = t.usuario_id LEFT JOIN usuario_perfil pc ON pc.usuario_id = t.usuario_id
                LEFT JOIN usuarios ua ON ua.id = t.asignada_a LEFT JOIN usuario_perfil pa ON pa.usuario_id = t.asignada_a
                WHERE t.categoria_id = ? AND t.papelera_en IS NULL {'' if incluir_completadas else "AND t.estado != 'completada'"}
                ORDER BY (t.estado = 'completada'), t.orden_proyecto, (t.fecha_vencimiento IS NULL), t.fecha_vencimiento, t.id""",
            (categoria_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def resumen_proyecto(usuario_id: int, categoria_id: int) -> dict | None:
    """Cifras de la cabecera y del Resumen: progreso, vencidas, horas, próximo hito, carga por persona."""
    conn = get_connection()
    try:
        rol = _rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None:
            return None
        hoy = datetime.now().strftime("%Y-%m-%d")
        lunes = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
        t = conn.execute(
            """SELECT COUNT(*) AS total, COALESCE(SUM(estado = 'completada'), 0) AS hechas,
                      COALESCE(SUM(estado != 'completada' AND fecha_vencimiento IS NOT NULL AND substr(fecha_vencimiento, 1, 10) < ?), 0) AS vencidas
               FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL""",
            (hoy, categoria_id),
        ).fetchone()
        total, hechas = t["total"], int(t["hechas"])
        horas = conn.execute(
            """SELECT COALESCE(SUM(duracion_segundos), 0) AS total,
                      COALESCE(SUM(CASE WHEN substr(inicio_en, 1, 10) >= ? THEN duracion_segundos ELSE 0 END), 0) AS semana
               FROM tareas WHERE categoria_id = ? AND estado = 'finalizada' AND papelera_en IS NULL""",
            (lunes, categoria_id),
        ).fetchone()
        hito = conn.execute(
            """SELECT asunto, fecha_vencimiento FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL AND estado != 'completada'
               AND fecha_vencimiento IS NOT NULL AND substr(fecha_vencimiento, 1, 10) >= ? ORDER BY fecha_vencimiento LIMIT 1""",
            (categoria_id, hoy),
        ).fetchone()
        proyecto = conn.execute("SELECT proy_cliente_id AS cliente_fiscal_id FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
        vencimiento_cliente = None
        if proyecto["cliente_fiscal_id"]:
            vencimiento_cliente = conn.execute(
                """SELECT modelo, periodo, fecha_limite FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? AND estado = 'pendiente'
                   AND papelera_en IS NULL ORDER BY fecha_limite LIMIT 1""",
                (proyecto["cliente_fiscal_id"],),
            ).fetchone()
        carga = [dict(f) for f in conn.execute(
            """SELECT COALESCE(t.asignada_a, t.usuario_id) AS usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre, COUNT(*) AS abiertas
               FROM tareas_outlook t JOIN usuarios u ON u.id = COALESCE(t.asignada_a, t.usuario_id) LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id
               WHERE t.categoria_id = ? AND t.papelera_en IS NULL AND t.estado != 'completada' GROUP BY 1 ORDER BY abiertas DESC, nombre""",
            (categoria_id,),
        )]
        por_persona = []
        if rol in ("dueno", "observa"):
            # El desglose de horas por persona solo lo ven el dueño y los supervisores; el resto, los totales.
            por_persona = [dict(f) for f in conn.execute(
                """SELECT t.usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre, COALESCE(SUM(t.duracion_segundos), 0) AS segundos
                   FROM tareas t JOIN usuarios u ON u.id = t.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = t.usuario_id
                   WHERE t.categoria_id = ? AND t.estado = 'finalizada' AND t.papelera_en IS NULL GROUP BY t.usuario_id ORDER BY segundos DESC""",
                (categoria_id,),
            )] if (rol == "dueno" or conn.execute("SELECT supervisor_tenant FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()[0]) else []
        return {
            "total": total, "hechas": hechas, "abiertas": total - hechas, "vencidas": int(t["vencidas"]),
            "porcentaje": round(hechas * 100 / total) if total else 0,
            "segundos_total": horas["total"], "segundos_semana": horas["semana"],
            "proximo_hito": dict(hito) if hito else None, "vencimiento_cliente": dict(vencimiento_cliente) if vencimiento_cliente else None,
            "carga": carga, "horas_por_persona": por_persona,
        }
    finally:
        conn.close()


# --- Proyectos, fase 3: notas compartidas, actividad, plantillas y datos del cliente -----------

MAX_NOTAS_PROYECTO = 500
MAX_PLANTILLAS_TENANT = 50


def crear_nota_proyecto(usuario_id: int, categoria_id: int, texto: str) -> int | None:
    texto = (texto or "").strip()[:4000]
    conn = get_connection()
    try:
        if not texto or not _puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
        if conn.execute("SELECT COUNT(*) FROM proyecto_notas WHERE categoria_id = ?", (categoria_id,)).fetchone()[0] >= MAX_NOTAS_PROYECTO:
            return None
        cur = conn.execute(
            "INSERT INTO proyecto_notas (categoria_id, usuario_id, texto, creada_en) VALUES (?, ?, ?, ?)",
            (categoria_id, usuario_id, texto, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_notas_proyecto(usuario_id: int, categoria_id: int) -> list[dict]:
    """Notas del proyecto, fijadas primero y luego las más recientes. `puede_borrar`: su autor o el dueño."""
    conn = get_connection()
    try:
        rol = _rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None:
            return []
        filas = conn.execute(
            """SELECT n.*, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM proyecto_notas n JOIN usuarios u ON u.id = n.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
               WHERE n.categoria_id = ? ORDER BY n.fijada DESC, n.id DESC""",
            (categoria_id,),
        ).fetchall()
        return [dict(f, puede_borrar=rol == "dueno" or f["usuario_id"] == usuario_id, puede_fijar=rol in ("dueno", "colabora")) for f in filas]
    finally:
        conn.close()


def fijar_nota_proyecto(usuario_id: int, categoria_id: int, nota_id: int, fijada: bool) -> bool:
    conn = get_connection()
    try:
        if not _puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return False
        cur = conn.execute("UPDATE proyecto_notas SET fijada = ? WHERE id = ? AND categoria_id = ?", (1 if fijada else 0, nota_id, categoria_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def eliminar_nota_proyecto(usuario_id: int, categoria_id: int, nota_id: int) -> bool:
    """La borra su autor o el dueño del proyecto (y solo mientras siga pudiendo organizar)."""
    conn = get_connection()
    try:
        rol = _rol_en_proyecto(conn, usuario_id, categoria_id)
        n = conn.execute("SELECT usuario_id FROM proyecto_notas WHERE id = ? AND categoria_id = ?", (nota_id, categoria_id)).fetchone()
        if n is None or not (rol == "dueno" or (rol == "colabora" and n["usuario_id"] == usuario_id)):
            return False
        conn.execute("DELETE FROM proyecto_notas WHERE id = ?", (nota_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def actividad_proyecto(usuario_id: int, categoria_id: int, limite: int = 80) -> list[dict]:
    """Línea de tiempo del proyecto: lo que se hace en sus tareas (historial y comentarios) y sus notas.
    Cada entrada: `cuando`, `quien`, `tipo` ('actividad' | 'comentario' | 'nota'), `detalle`, `tarea_id`, `tarea`."""
    conn = get_connection()
    try:
        if _rol_en_proyecto(conn, usuario_id, categoria_id) is None:
            return []
        filas = conn.execute(
            """SELECT * FROM (
                 SELECT a.creado_en AS cuando, a.usuario_id AS uid, a.tipo AS subtipo, 'actividad' AS tipo, a.detalle AS detalle,
                        t.id AS tarea_id, t.asunto AS tarea
                 FROM tarea_actividad a JOIN tareas_outlook t ON t.id = a.tarea_id
                 WHERE t.categoria_id = ? AND t.papelera_en IS NULL AND a.tipo != 'comentario'
                 UNION ALL
                 SELECT c.creado_en, c.usuario_id, 'comentario', 'comentario', c.texto, t.id, t.asunto
                 FROM tarea_comentarios c JOIN tareas_outlook t ON t.id = c.tarea_id
                 WHERE t.categoria_id = ? AND t.papelera_en IS NULL
                 UNION ALL
                 SELECT n.creada_en, n.usuario_id, 'nota', 'nota', n.texto, NULL, NULL
                 FROM proyecto_notas n WHERE n.categoria_id = ?
               ) ORDER BY cuando DESC LIMIT ?""",
            (categoria_id, categoria_id, categoria_id, max(1, min(limite, 300))),
        ).fetchall()
        nombres = {
            f["id"]: f["nombre"] for f in conn.execute(
                "SELECT u.id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre FROM usuarios u LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id"
                " WHERE u.id IN (%s)" % ",".join("?" * len({f["uid"] for f in filas})),
                list({f["uid"] for f in filas}),
            )
        } if filas else {}
        return [dict(f, quien=nombres.get(f["uid"], "")) for f in filas]
    finally:
        conn.close()


def _estructura_valida(estructura) -> list[dict]:
    """Normaliza {secciones: [{nombre, tareas: [{asunto, dias}]}]} y descarta lo que no cuadre (máx. 20 secciones, 40 tareas cada una)."""
    resultado = []
    if not isinstance(estructura, list):
        return resultado
    for s in estructura[:20]:
        if not isinstance(s, dict):
            continue
        nombre = str(s.get("nombre") or "").strip()[:80]
        if not nombre:
            continue
        tareas = []
        for t in (s.get("tareas") if isinstance(s.get("tareas"), list) else [])[:40]:
            if not isinstance(t, dict):
                continue
            asunto = str(t.get("asunto") or "").strip()[:200]
            dias = t.get("dias")
            if asunto:
                tareas.append({"asunto": asunto, "dias": dias if isinstance(dias, int) and 0 <= dias <= 730 else None})
        resultado.append({"nombre": nombre, "tareas": tareas})
    return resultado


def aplicar_plantilla_proyecto(usuario_id: int, categoria_id: int, estructura, hoy: date | None = None) -> dict | None:
    """Añade al proyecto las secciones y tareas de una plantilla (nunca borra nada). Las fechas son «días desde hoy».
    Devuelve {'secciones': n, 'tareas': n} o None si no se puede organizar el proyecto."""
    hoy = hoy or date.today()
    estructura = _estructura_valida(estructura)
    conn = get_connection()
    try:
        if not _puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
    finally:
        conn.close()
    n_secciones = n_tareas = 0
    for s in estructura:
        seccion_id = crear_seccion(usuario_id, categoria_id, s["nombre"])
        if seccion_id is None:
            continue
        n_secciones += 1
        for t in s["tareas"]:
            fecha = (hoy + timedelta(days=t["dias"])).isoformat() if t["dias"] is not None else None
            if crear_tarea_en_proyecto(usuario_id, categoria_id, t["asunto"], seccion_id=seccion_id, fecha_vencimiento=fecha):
                n_tareas += 1
    return {"secciones": n_secciones, "tareas": n_tareas}


def guardar_plantilla_desde_proyecto(usuario_id: int, categoria_id: int, nombre: str) -> int | None:
    """Guarda las secciones y los asuntos de las tareas abiertas del proyecto como plantilla del despacho
    (sin fechas, personas ni comentarios). Solo el dueño."""
    nombre = (nombre or "").strip()[:80]
    conn = get_connection()
    try:
        u = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not nombre or u is None or u["tenant_id"] is None or _rol_en_proyecto(conn, usuario_id, categoria_id) != "dueno":
            return None
        if conn.execute("SELECT COUNT(*) FROM proyecto_plantillas WHERE tenant_id = ?", (u["tenant_id"],)).fetchone()[0] >= MAX_PLANTILLAS_TENANT:
            return None
        secciones = conn.execute("SELECT id, nombre FROM proyecto_secciones WHERE categoria_id = ? ORDER BY orden, id", (categoria_id,)).fetchall()
        tareas = conn.execute(
            """SELECT asunto, seccion_id FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL AND estado != 'completada'
               ORDER BY orden_proyecto, id""",
            (categoria_id,),
        ).fetchall()
        estructura = [{"nombre": s["nombre"], "tareas": [{"asunto": t["asunto"]} for t in tareas if t["seccion_id"] == s["id"]]} for s in secciones]
        sueltas = [{"asunto": t["asunto"]} for t in tareas if t["seccion_id"] is None]
        if sueltas:
            estructura.insert(0, {"nombre": nombre, "tareas": sueltas})
        estructura = _estructura_valida(estructura)
        if not estructura:
            return None
        cur = conn.execute(
            "INSERT INTO proyecto_plantillas (tenant_id, usuario_id, nombre, estructura, creada_en) VALUES (?, ?, ?, ?, ?)",
            (u["tenant_id"], usuario_id, nombre, json.dumps(estructura, ensure_ascii=False), now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_plantillas_proyecto(usuario_id: int) -> list[dict]:
    """Plantillas guardadas por el despacho del usuario (`estructura` ya como lista)."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT p.* FROM proyecto_plantillas p JOIN usuarios u ON u.tenant_id = p.tenant_id WHERE u.id = ? ORDER BY p.nombre""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()
    resultado = []
    for f in filas:
        try:
            resultado.append(dict(f, estructura=_estructura_valida(json.loads(f["estructura"]))))
        except (ValueError, TypeError):
            continue
    return resultado


def eliminar_plantilla_proyecto(usuario_id: int, plantilla_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM proyecto_plantillas WHERE id = ? AND tenant_id = (SELECT tenant_id FROM usuarios WHERE id = ?)",
            (plantilla_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def correos_de_cliente_para(usuario_id: int, cliente_fiscal_id: int, limite: int = 5) -> list[dict]:
    """Los últimos correos de SUS cuentas vinculados al cliente (el correo es privado: cada quien ve solo los suyos)."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """SELECT m.id, m.asunto, m.remitente, m.fecha, m.leido FROM correo_mensajes m
               JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE c.usuario_id = ? AND m.cliente_fiscal_id = ? ORDER BY m.fecha DESC, m.id DESC LIMIT ?""",
            (usuario_id, cliente_fiscal_id, max(1, min(limite, 20))),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


# --- Papelera ----------------------------------------------------------------

def papelera(usuario_id: int) -> list[dict]:
    """Proyectos, tareas/eventos y notas que están en la papelera, más recientes primero."""
    conn = get_connection()
    try:
        filas = conn.execute(
            """
            SELECT * FROM (
                SELECT 'menu' AS origen, c.id AS id, c.nombre AS texto, NULL AS tipo,
                       NULL AS categoria_nombre, NULL AS categoria_color, c.papelera_en AS papelera_en
                FROM categorias c
                WHERE c.usuario_id = ? AND c.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea' AS origen, t.id AS id, t.nombre AS texto, t.tipo AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, t.papelera_en AS papelera_en
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE t.usuario_id = ? AND t.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'nota' AS origen, n.id AS id, n.texto AS texto, NULL AS tipo,
                       c.nombre AS categoria_nombre, c.color AS categoria_color, n.papelera_en AS papelera_en
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE n.usuario_id = ? AND n.papelera_en IS NOT NULL

                UNION ALL

                SELECT 'tarea_outlook' AS origen, tk.id AS id, tk.asunto AS texto, NULL AS tipo,
                       COALESCE(ck.nombre, tk.categoria_outlook) AS categoria_nombre, ck.color AS categoria_color, tk.papelera_en AS papelera_en
                FROM tareas_outlook tk LEFT JOIN categorias ck ON ck.id = tk.categoria_id
                WHERE tk.usuario_id = ? AND tk.papelera_en IS NOT NULL
            )
            ORDER BY papelera_en DESC
            """,
            (usuario_id, usuario_id, usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def vaciar_papelera_antigua(dias: int = 30, usuario_id: int | None = None) -> None:
    """Purga definitivamente (sin posibilidad de recuperar) lo que lleva en
    la papelera más de `dias` días. Sin `usuario_id`, purga de TODOS los
    usuarios (uso interno: se llama al arrancar la app, igual que la copia
    de seguridad); con `usuario_id`, solo la papelera de ese usuario (uso
    desde la ruta web "Vaciar papelera", que actúa en nombre de quien la
    pulsa, no de todo el tenant). clientes_fiscales/vencimientos_fiscales se
    purgan siempre por tenant_id (ver más abajo), sin importar `usuario_id`
    -- no tienen ese campo, son datos de la gestoría, no de un usuario."""
    conn = get_connection()
    try:
        limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
        filtro_usuario = " AND usuario_id = ?" if usuario_id is not None else ""
        params = (limite, usuario_id) if usuario_id is not None else (limite,)
        ids_categorias = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM categorias WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_tareas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM tareas WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_notas = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM notas WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_tareas_outlook = [
            (r["id"], r["usuario_id"]) for r in conn.execute(
                f"SELECT id, usuario_id FROM tareas_outlook WHERE papelera_en IS NOT NULL AND papelera_en < ?{filtro_usuario}", params
            )
        ]
        ids_clientes_fiscales = [
            (r["id"], r["tenant_id"]) for r in conn.execute(
                "SELECT id, tenant_id FROM clientes_fiscales WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
        ids_vencimientos_fiscales = [
            (r["id"], r["tenant_id"]) for r in conn.execute(
                "SELECT id, tenant_id FROM vencimientos_fiscales WHERE papelera_en IS NOT NULL AND papelera_en < ?", (limite,)
            )
        ]
    finally:
        conn.close()

    for nid, uid in ids_notas:
        eliminar_nota_definitivamente(uid, nid)
    for tid, uid in ids_tareas:
        eliminar_tarea_definitivamente(uid, tid)
    for cid, uid in ids_categorias:
        eliminar_categoria_definitivamente(uid, cid)
    for tid, uid in ids_tareas_outlook:
        eliminar_tarea_outlook_definitivamente(uid, tid)
    for vid, tid in ids_vencimientos_fiscales:
        eliminar_vencimiento_fiscal_definitivamente(tid, vid)
    for cid, tid in ids_clientes_fiscales:
        eliminar_cliente_fiscal_definitivamente(tid, cid)


# --- Asistente IA (OpenRouter): preferencias y conversación -------------------

def obtener_preferencias_ia(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        return _obtener_o_crear(conn, "ia_preferencias", usuario_id)
    finally:
        conn.close()


def guardar_preferencias_ia(usuario_id: int, modelo: str, modo_autonomo: bool, solo_lectura: bool | None = None) -> None:
    """`solo_lectura` None = no tocar (los clientes antiguos no lo envían)."""
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            "UPDATE ia_preferencias SET modelo = ?, modo_autonomo = ? WHERE usuario_id = ?",
            (modelo, int(modo_autonomo), usuario_id),
        )
        if solo_lectura is not None:
            conn.execute(
                "UPDATE ia_preferencias SET solo_lectura = ? WHERE usuario_id = ?", (int(solo_lectura), usuario_id)
            )
        conn.commit()
    finally:
        conn.close()


# --- Perfil de usuario (Fase G1: espacio de ajustes de usuario) -------------
# Mismo patrón singleton usuario_id PRIMARY KEY que ia_preferencias -- ver
# CREATE TABLE usuario_perfil en init_db(). El avatar es un BLOB en la
# propia fila (igual que correo_adjuntos.contenido), sin filesystem aparte.

def obtener_perfil_usuario(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        # Solo se escribe la primera vez: un INSERT OR IGNORE en cada visita abría una
        # transacción de escritura por página vista aunque la fila ya existiera.
        fila = conn.execute("SELECT * FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,)).fetchone()
        if fila is None:
            conn.execute("INSERT OR IGNORE INTO usuario_perfil (usuario_id) VALUES (?)", (usuario_id,))
            conn.commit()
            fila = conn.execute("SELECT * FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,)).fetchone()
        return fila
    finally:
        conn.close()


def guardar_perfil_usuario(
    usuario_id: int,
    nombre_mostrado: str | None = None,
    notificar_push_vencimientos: bool | None = None,
    notificar_push_tiquets: bool | None = None,
    notificar_resumen_semanal: bool | None = None,
    notificar_push_correo: bool | None = None,
    notificar_push_portal_mensajes: bool | None = None,
) -> None:
    """Solo actualiza los campos que se pasan explícitos (no-None) -- así
    la ruta puede llamar con únicamente el nombre, o únicamente las
    notificaciones, sin pisar el resto con valores por defecto."""
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO usuario_perfil (usuario_id) VALUES (?)", (usuario_id,))
        asignaciones, valores = [], []
        if nombre_mostrado is not None:
            asignaciones.append("nombre_mostrado = ?")
            valores.append(nombre_mostrado.strip() or None)
        if notificar_push_vencimientos is not None:
            asignaciones.append("notificar_push_vencimientos = ?")
            valores.append(int(notificar_push_vencimientos))
        if notificar_push_tiquets is not None:
            asignaciones.append("notificar_push_tiquets = ?")
            valores.append(int(notificar_push_tiquets))
        if notificar_resumen_semanal is not None:
            asignaciones.append("notificar_resumen_semanal = ?")
            valores.append(int(notificar_resumen_semanal))
        if notificar_push_correo is not None:
            asignaciones.append("notificar_push_correo = ?")
            valores.append(int(notificar_push_correo))
        if notificar_push_portal_mensajes is not None:
            asignaciones.append("notificar_push_portal_mensajes = ?")
            valores.append(int(notificar_push_portal_mensajes))
        if asignaciones:
            conn.execute(
                f"UPDATE usuario_perfil SET {', '.join(asignaciones)} WHERE usuario_id = ?",
                [*valores, usuario_id],
            )
        conn.commit()
    finally:
        conn.close()


# Qué columna de usuario_perfil gobierna cada tipo de notificación real
# emitido por app/notificaciones.py -- un tipo sin entrada aquí (como
# "resumen_ia_semanal", que ya tiene su propio camino en
# usuarios_con_resumen_semanal_activo(), nunca pasa por aquí) se trata
# como "siempre activo".
_COLUMNAS_PREFERENCIA_NOTIFICACION = {
    "vencimiento_fiscal": "notificar_push_vencimientos",
    "tiquet_asignado": "notificar_push_tiquets",
    "correo_nuevo": "notificar_push_correo",
    "portal_mensaje_nuevo": "notificar_push_portal_mensajes",
}


def notificacion_tipo_activa(usuario_id: int, tipo: str) -> bool:
    """Antes de esta función, notificar_push_vencimientos/
    notificar_push_tiquets se podían editar desde /ajustes/perfil pero
    NINGÚN punto de emisión las comprobaba de verdad -- desactivarlas no
    hacía nada. Quien emite una notificación debe llamar a esto primero
    (ver app/main.py, app/rutas_portal_cliente.py, app/correo.py,
    app/rutas_tiquets.py)."""
    columna = _COLUMNAS_PREFERENCIA_NOTIFICACION.get(tipo)
    if columna is None:
        return True
    perfil = obtener_perfil_usuario(usuario_id)
    return bool(perfil[columna])


def guardar_avatar_usuario(usuario_id: int, contenido: bytes, tipo_mime: str) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO usuario_perfil (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            "UPDATE usuario_perfil SET avatar_contenido = ?, avatar_tipo_mime = ? WHERE usuario_id = ?",
            (contenido, tipo_mime, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_avatar_usuario(usuario_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE usuario_perfil SET avatar_contenido = NULL, avatar_tipo_mime = NULL WHERE usuario_id = ?",
            (usuario_id,),
        )
        conn.commit()
    finally:
        conn.close()


def crear_adjunto_ia(
    usuario_id: int, nombre_archivo: str, tipo_mime: str | None, contenido: bytes, origen: str = "usuario"
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO ia_adjuntos (usuario_id, nombre_archivo, tipo_mime, contenido, creado_en, origen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, nombre_archivo, tipo_mime, contenido, now_iso(), origen),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_adjunto_ia(usuario_id: int, adjunto_id: int) -> sqlite3.Row | None:
    """Filtra por usuario_id -- un adjunto es privado a quien lo subió, ni
    siquiera otro miembro del mismo tenant puede leerlo (a diferencia de
    tiquets, esto no es un tablero compartido)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM ia_adjuntos WHERE id = ? AND usuario_id = ?", (adjunto_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def usuarios_con_resumen_semanal_activo() -> list[int]:
    """Usados por el hilo _resumen_ia_semanal (app/main.py) -- quién ha
    activado la casilla correspondiente en su perfil (Fase G1)."""
    conn = get_connection()
    try:
        return [
            r["usuario_id"]
            for r in conn.execute(
                "SELECT usuario_id FROM usuario_perfil WHERE notificar_resumen_semanal = 1"
            ).fetchall()
        ]
    finally:
        conn.close()


def nombre_mostrado_usuario(usuario_id: int) -> str | None:
    """Atajo de solo lectura para el resto de la app (p.ej. sustituir el
    email crudo por el nombre elegido donde se muestre autoría) -- evita
    que cada sitio tenga que llamar a obtener_perfil_usuario() entero."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT nombre_mostrado FROM usuario_perfil WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        return fila["nombre_mostrado"] if fila else None
    finally:
        conn.close()


# --- IA local (Ollama/LM Studio): recordar el último proveedor/modelo usado --

def obtener_preferencias_ia_local(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        return _obtener_o_crear(conn, "ia_preferencias", usuario_id)
    finally:
        conn.close()


def guardar_preferencias_ia_local(usuario_id: int, proveedor: str, modelo: str) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            "UPDATE ia_preferencias SET proveedor_local = ?, modelo_local = ? WHERE usuario_id = ?",
            (proveedor, modelo, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---- Conversaciones del Asistente IA -----------------------------------------
#
# Todo el código del asistente (y la app móvil, vía la API) sigue trabajando
# con "la conversación del usuario": listar_mensajes_ia / agregar_mensaje_ia /
# vaciar_mensajes_ia operan sobre la conversación ACTIVA, así que añadir
# varias conversaciones no cambia ninguna de esas llamadas.

IA_MAX_CONVERSACIONES_POR_USUARIO = 50
IA_TITULO_MAX_CARACTERES = 60


def _titulo_desde_texto(texto: str | None) -> str | None:
    """Título automático: primera línea del primer mensaje, recortada."""
    if not texto:
        return None
    linea = " ".join(texto.strip().splitlines()[0].split()) if texto.strip() else ""
    if not linea:
        return None
    return linea if len(linea) <= IA_TITULO_MAX_CARACTERES else linea[: IA_TITULO_MAX_CARACTERES - 1].rstrip() + "…"


def _migrar_conversaciones_ia(conn: sqlite3.Connection) -> None:
    """Idempotente: los mensajes anteriores a las conversaciones (conversacion_id
    NULL) pasan a UNA conversación por usuario, que queda activa."""
    for fila in conn.execute(
        "SELECT usuario_id, MIN(creado_en) AS desde, MAX(creado_en) AS hasta FROM ia_mensajes "
        "WHERE conversacion_id IS NULL AND usuario_id IS NOT NULL GROUP BY usuario_id"
    ).fetchall():
        uid = fila["usuario_id"]
        primero = conn.execute(
            "SELECT contenido FROM ia_mensajes WHERE usuario_id = ? AND conversacion_id IS NULL AND rol = 'user' ORDER BY id LIMIT 1",
            (uid,),
        ).fetchone()
        activa = conn.execute(
            "SELECT 1 FROM ia_conversaciones WHERE usuario_id = ? AND activa = 1", (uid,)
        ).fetchone()
        cur = conn.execute(
            "INSERT INTO ia_conversaciones (usuario_id, titulo, creada_en, actualizada_en, activa) VALUES (?, ?, ?, ?, ?)",
            (uid, _titulo_desde_texto(primero["contenido"] if primero else None), fila["desde"], fila["hasta"], 0 if activa else 1),
        )
        conn.execute(
            "UPDATE ia_mensajes SET conversacion_id = ? WHERE usuario_id = ? AND conversacion_id IS NULL",
            (cur.lastrowid, uid),
        )


def _crear_conversacion_ia(conn: sqlite3.Connection, usuario_id: int) -> int:
    ahora = now_iso()
    conn.execute("UPDATE ia_conversaciones SET activa = 0 WHERE usuario_id = ?", (usuario_id,))
    cur = conn.execute(
        "INSERT INTO ia_conversaciones (usuario_id, titulo, creada_en, actualizada_en, activa) VALUES (?, NULL, ?, ?, 1)",
        (usuario_id, ahora, ahora),
    )
    # Tope: se descartan las más antiguas (nunca la activa).
    sobran = conn.execute(
        "SELECT COUNT(*) AS n FROM ia_conversaciones WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()["n"] - IA_MAX_CONVERSACIONES_POR_USUARIO
    if sobran > 0:
        for antigua in conn.execute(
            "SELECT id FROM ia_conversaciones WHERE usuario_id = ? AND activa = 0 ORDER BY actualizada_en, id LIMIT ?",
            (usuario_id, sobran),
        ).fetchall():
            conn.execute("DELETE FROM ia_mensajes WHERE conversacion_id = ?", (antigua["id"],))
            conn.execute("DELETE FROM ia_conversaciones WHERE id = ?", (antigua["id"],))
    return cur.lastrowid


def conversacion_ia_activa_id(usuario_id: int, crear: bool = True) -> int | None:
    """La conversación activa del usuario; si no tiene ninguna y `crear`, abre una."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT id FROM ia_conversaciones WHERE usuario_id = ? AND activa = 1", (usuario_id,)
        ).fetchone()
        if fila:
            return fila["id"]
        if not crear:
            return None
        nueva = _crear_conversacion_ia(conn, usuario_id)
        conn.commit()
        return nueva
    finally:
        conn.close()


def listar_conversaciones_ia(usuario_id: int) -> list[sqlite3.Row]:
    """Las conversaciones del usuario, la más reciente primero, con cuántos
    mensajes suyos tiene cada una (`mensajes`)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM ia_mensajes m WHERE m.conversacion_id = c.id AND m.rol = 'user') AS mensajes
               FROM ia_conversaciones c WHERE c.usuario_id = ? ORDER BY c.actualizada_en DESC, c.id DESC""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def crear_conversacion_ia(usuario_id: int) -> int:
    """Abre una conversación nueva y la deja activa. Si la activa todavía no
    tiene ningún mensaje se reutiliza (no se acumulan conversaciones vacías)."""
    conn = get_connection()
    try:
        activa = conn.execute(
            """SELECT c.id FROM ia_conversaciones c WHERE c.usuario_id = ? AND c.activa = 1
               AND NOT EXISTS (SELECT 1 FROM ia_mensajes m WHERE m.conversacion_id = c.id)""",
            (usuario_id,),
        ).fetchone()
        if activa:
            return activa["id"]
        nueva = _crear_conversacion_ia(conn, usuario_id)
        conn.commit()
        return nueva
    finally:
        conn.close()


def activar_conversacion_ia(usuario_id: int, conversacion_id: int) -> bool:
    conn = get_connection()
    try:
        if not conn.execute(
            "SELECT 1 FROM ia_conversaciones WHERE id = ? AND usuario_id = ?", (conversacion_id, usuario_id)
        ).fetchone():
            return False
        conn.execute("UPDATE ia_conversaciones SET activa = (id = ?) WHERE usuario_id = ?", (conversacion_id, usuario_id))
        conn.commit()
        return True
    finally:
        conn.close()


def renombrar_conversacion_ia(usuario_id: int, conversacion_id: int, titulo: str) -> bool:
    titulo = " ".join((titulo or "").split())
    if not titulo:
        raise ValueError("El título no puede estar vacío.")
    titulo = titulo[:IA_TITULO_MAX_CARACTERES]
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE ia_conversaciones SET titulo = ? WHERE id = ? AND usuario_id = ?", (titulo, conversacion_id, usuario_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def eliminar_conversacion_ia(usuario_id: int, conversacion_id: int) -> bool:
    """Borra la conversación y sus mensajes. Si era la activa, pasa a serlo la
    más reciente que quede (o ninguna: se abrirá una al escribir)."""
    conn = get_connection()
    try:
        fila = conn.execute(
            "SELECT activa FROM ia_conversaciones WHERE id = ? AND usuario_id = ?", (conversacion_id, usuario_id)
        ).fetchone()
        if fila is None:
            return False
        conn.execute("DELETE FROM ia_mensajes WHERE conversacion_id = ?", (conversacion_id,))
        conn.execute("DELETE FROM ia_conversaciones WHERE id = ?", (conversacion_id,))
        if fila["activa"]:
            reciente = conn.execute(
                "SELECT id FROM ia_conversaciones WHERE usuario_id = ? ORDER BY actualizada_en DESC, id DESC LIMIT 1",
                (usuario_id,),
            ).fetchone()
            if reciente:
                conn.execute("UPDATE ia_conversaciones SET activa = 1 WHERE id = ?", (reciente["id"],))
        conn.commit()
        return True
    finally:
        conn.close()


def listar_mensajes_ia(usuario_id: int, conversacion_id: int | None = None) -> list[sqlite3.Row]:
    """Mensajes de la conversación indicada o, por defecto, de la activa
    (lista vacía si el usuario no tiene ninguna todavía)."""
    if conversacion_id is None:
        conversacion_id = conversacion_ia_activa_id(usuario_id, crear=False)
        if conversacion_id is None:
            return []
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM ia_mensajes WHERE usuario_id = ? AND conversacion_id = ? ORDER BY id",
            (usuario_id, conversacion_id),
        ).fetchall()
    finally:
        conn.close()


def agregar_mensaje_ia(
    usuario_id: int,
    rol: str,
    contenido: str | None = None,
    tool_calls_json: str | None = None,
    tool_call_id: str | None = None,
    nombre_herramienta: str | None = None,
    fuentes_json: str | None = None,
) -> int:
    """Añade el mensaje a la conversación activa (abriéndola si no hay). El
    primer mensaje de la persona usuaria da título a la conversación."""
    conn = get_connection()
    try:
        activa = conn.execute(
            "SELECT id, titulo FROM ia_conversaciones WHERE usuario_id = ? AND activa = 1", (usuario_id,)
        ).fetchone()
        if activa is None:
            conversacion_id, titulo_actual = _crear_conversacion_ia(conn, usuario_id), None
        else:
            conversacion_id, titulo_actual = activa["id"], activa["titulo"]
        ahora = now_iso()
        cursor = conn.execute(
            """INSERT INTO ia_mensajes
               (usuario_id, conversacion_id, rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta,
                fuentes_json, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, conversacion_id, rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta,
             fuentes_json, ahora),
        )
        titulo = titulo_actual
        if not titulo and rol == "user":
            titulo = _titulo_desde_texto(contenido)
        conn.execute(
            "UPDATE ia_conversaciones SET actualizada_en = ?, titulo = ? WHERE id = ?", (ahora, titulo, conversacion_id)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


IA_MAX_ATAJOS = 20


def listar_atajos_ia(usuario_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM ia_atajos WHERE usuario_id = ? ORDER BY id", (usuario_id,)).fetchall()
    finally:
        conn.close()


def crear_atajo_ia(usuario_id: int, titulo: str, prompt: str) -> int:
    titulo, prompt = (titulo or "").strip()[:40], (prompt or "").strip()[:1000]
    if not titulo or not prompt:
        raise ValueError("El atajo necesita un título y un texto.")
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM ia_atajos WHERE usuario_id = ?", (usuario_id,)).fetchone()[0] >= IA_MAX_ATAJOS:
            raise ValueError(f"Máximo {IA_MAX_ATAJOS} atajos propios.")
        cur = conn.execute(
            "INSERT INTO ia_atajos (usuario_id, titulo, prompt, creado_en) VALUES (?, ?, ?, ?)",
            (usuario_id, titulo, prompt, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def eliminar_atajo_ia(usuario_id: int, atajo_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM ia_atajos WHERE id = ? AND usuario_id = ?", (atajo_id, usuario_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def vaciar_mensajes_ia(usuario_id: int) -> None:
    """"Nueva conversación": abre una conversación en blanco. La anterior NO se
    borra, queda en la lista de conversaciones del usuario."""
    crear_conversacion_ia(usuario_id)


# ---- Tiquets (soporte interno: errores/sugerencias, tablero compartido) ----

def crear_tiquet(usuario_id: int, tipo: str, titulo: str, descripcion: str | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tiquets (usuario_id, tipo, titulo, descripcion, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (usuario_id, tipo, titulo.strip(), (descripcion or "").strip() or None, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tiquets(
    estado: str | None = None, tipo: str | None = None,
    prioridad: str | None = None, usuario_asignado_id: int | None = None,
) -> list[sqlite3.Row]:
    """Todos los tiquets, de cualquier usuario -- tablero compartido, a
    diferencia de notas/tareas/correo que siempre filtran por
    usuario_id. Ordenados por prioridad (alta primero) y luego por id
    (orden de inclusión dentro de la misma prioridad)."""
    conn = get_connection()
    try:
        cond = []
        params: list = []
        if estado:
            cond.append("t.estado = ?"); params.append(estado)
        if tipo:
            cond.append("t.tipo = ?"); params.append(tipo)
        if prioridad:
            cond.append("t.prioridad = ?"); params.append(prioridad)
        if usuario_asignado_id:
            cond.append("t.usuario_asignado_id = ?"); params.append(usuario_asignado_id)
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        return conn.execute(
            f"""SELECT t.*, u.email AS autor_email, a.email AS asignado_email
                FROM tiquets t
                LEFT JOIN usuarios u ON u.id = t.usuario_id
                LEFT JOIN usuarios a ON a.id = t.usuario_asignado_id
                {where}
                ORDER BY CASE t.prioridad WHEN 'alta' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, t.id""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_tiquet(tiquet_id: int) -> sqlite3.Row | None:
    """Sin filtrar por usuario_id -- hay dos roles con distinto alcance
    (dueño / admin) y quien llama (rutas_tiquets.py, mcp_tools.py) es
    quien decide si el usuario actual puede verlo/tocarlo."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT t.*, u.email AS autor_email, a.email AS asignado_email
               FROM tiquets t
               LEFT JOIN usuarios u ON u.id = t.usuario_id
               LEFT JOIN usuarios a ON a.id = t.usuario_asignado_id
               WHERE t.id = ?""",
            (tiquet_id,),
        ).fetchone()
    finally:
        conn.close()


def editar_tiquet(usuario_id: int, tiquet_id: int, titulo: str, descripcion: str | None, tipo: str) -> bool:
    """Solo actualiza si `usuario_id` es el dueño Y el tiquet sigue en
    'sin_revisar' -- devuelve False sin tocar nada si no se cumple
    alguna de las dos condiciones (quien llama decide qué error mostrar)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """UPDATE tiquets SET titulo = ?, descripcion = ?, tipo = ?, actualizado_en = ?
               WHERE id = ? AND usuario_id = ? AND estado = 'sin_revisar'""",
            (titulo.strip(), (descripcion or "").strip() or None, tipo, now_iso(), tiquet_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def cambiar_estado_tiquet(tiquet_id: int, estado: str) -> None:
    """Sin chequeo de permisos aquí -- quien llama (ruta con
    @admin_required, o la tool de MCP tras comprobar db.es_admin) ya
    decidió que puede hacerlo."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tiquets SET estado = ?, actualizado_en = ? WHERE id = ?", (estado, now_iso(), tiquet_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tiquet(tiquet_id: int) -> None:
    """Sin chequeo de permisos aquí tampoco -- ver cambiar_estado_tiquet."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tiquets WHERE id = ?", (tiquet_id,))
        conn.commit()
    finally:
        conn.close()


def asignar_tiquet(tiquet_id: int, prioridad: str, usuario_asignado_id: int | None) -> None:
    """Sin chequeo de permisos aquí -- ver cambiar_estado_tiquet, mismo
    criterio (solo admin puede llamar, comprobado en la ruta)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tiquets SET prioridad = ?, usuario_asignado_id = ?, actualizado_en = ? WHERE id = ?",
            (prioridad, usuario_asignado_id, now_iso(), tiquet_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_adjunto_tiquet(tiquet_id: int, nombre_archivo: str, tipo_mime: str, contenido: bytes) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tiquets_adjuntos (tiquet_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tiquet_id, nombre_archivo, tipo_mime, len(contenido), contenido, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_adjuntos_tiquet(tiquet_id: int) -> list[sqlite3.Row]:
    """Sin el BLOB `contenido` -- para listar en tarjetas/edición no hace
    falta traer los bytes enteros de cada adjunto, solo al descargar uno
    en concreto (ver obtener_adjunto_tiquet)."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT id, tiquet_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en
               FROM tiquets_adjuntos WHERE tiquet_id = ? ORDER BY id""",
            (tiquet_id,),
        ).fetchall()
    finally:
        conn.close()


def obtener_adjunto_tiquet(adjunto_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM tiquets_adjuntos WHERE id = ?", (adjunto_id,)).fetchone()
    finally:
        conn.close()


def eliminar_adjunto_tiquet(adjunto_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tiquets_adjuntos WHERE id = ?", (adjunto_id,))
        conn.commit()
    finally:
        conn.close()


# --- Fichaje de trabajadores (registro horario, art. 34.9 ET) -------------

def obtener_fichaje_datos(usuario_id: int) -> sqlite3.Row:
    conn = get_connection()
    try:
        fila = conn.execute("SELECT * FROM fichaje_datos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        if fila is None:  # solo la primera vez (ver obtener_perfil_usuario)
            conn.execute("INSERT OR IGNORE INTO fichaje_datos (usuario_id) VALUES (?)", (usuario_id,))
            conn.commit()
            fila = conn.execute("SELECT * FROM fichaje_datos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        return fila
    finally:
        conn.close()


def guardar_fichaje_datos(
    usuario_id: int, nombre_completo: str, dni_nie: str, numero_afiliacion_ss: str | None = None,
    categoria_profesional: str | None = None, tipo_contrato: str | None = None,
    fecha_alta: str | None = None, jornada_semanal_horas: float | None = None,
    convenio_colectivo: str | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO fichaje_datos (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            """UPDATE fichaje_datos SET nombre_completo = ?, dni_nie = ?, numero_afiliacion_ss = ?,
               categoria_profesional = ?, tipo_contrato = ?, fecha_alta = ?, jornada_semanal_horas = ?,
               convenio_colectivo = ?, actualizado_en = ? WHERE usuario_id = ?""",
            (
                nombre_completo.strip() or None, dni_nie.strip().upper() or None, numero_afiliacion_ss or None,
                categoria_profesional or None, tipo_contrato or None, fecha_alta or None,
                jornada_semanal_horas, convenio_colectivo or None, now_iso(), usuario_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fichaje_datos_completos(usuario_id: int) -> bool:
    """True si el trabajador ya rellenó lo mínimo exigible (nombre + DNI/
    NIE) para identificarse ante una inspección -- se exige antes de dejar
    fichar por primera vez (ver app/rutas_fichaje.py)."""
    datos = obtener_fichaje_datos(usuario_id)
    return bool(datos["nombre_completo"]) and bool(datos["dni_nie"])


_FICHAJE_TRANSICIONES_VALIDAS = {
    "salida": {"entrada"},
    "entrada": {"pausa_inicio", "salida"},
    "pausa_inicio": {"pausa_fin", "salida"},
    "pausa_fin": {"pausa_inicio", "salida"},
}


def fichar(
    usuario_id: int, tenant_id: int | None, tipo: str, origen: str = "web", creado_por: int | None = None,
    corrige_a: int | None = None, nota: str | None = None,
    marca_tiempo: str | None = None, cliente_uuid: str | None = None,
    latitud: float | None = None, longitud: float | None = None,
) -> int:
    """Inserta un evento de fichaje, validando que la secuencia sea
    coherente (no se puede fichar salida sin una entrada abierta, ni una
    segunda entrada sin haber salido antes) -- lanza ValueError si no
    cuadra, mismo estilo que ErrorCorreo/ErrorBusqueda. `corrige_a` es
    para que un admin corrija un olvido sin tocar la fila original (ver
    comentario de la tabla `fichajes`).

    `marca_tiempo`/`cliente_uuid` son para la cola offline de la app móvil:
    si el evento se pulsó sin cobertura y se sincroniza más tarde,
    `marca_tiempo` conserva la hora real de la pulsación (si no se manda, se
    usa la hora del servidor como siempre) y `cliente_uuid` evita duplicar
    la fila si la sincronización se reintenta. Nota: la validación de
    secuencia sigue mirando el último evento por orden de inserción, no por
    `marca_tiempo` -- un evento offline que llega después de que ya se haya
    fichado algo más reciente puede quedar fuera de secuencia y rechazarse,
    algo inherente a fichar con retraso, no un bug de esta función."""
    if tipo not in ("entrada", "pausa_inicio", "pausa_fin", "salida"):
        raise ValueError(f"Tipo de fichaje no válido: {tipo!r}.")
    conn = get_connection()
    try:
        if cliente_uuid is not None:
            existente = conn.execute("SELECT id FROM fichajes WHERE cliente_uuid = ?", (cliente_uuid,)).fetchone()
            if existente is not None:
                return existente["id"]
        ahora = now_iso()
        if marca_tiempo is not None:
            limite_pasado = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
            if marca_tiempo > ahora or marca_tiempo < limite_pasado:
                raise ValueError("La hora del fichaje enviado no es válida (demasiado futura o de hace más de 7 días).")
        # A partir de aquí, todo el bloque (validación de secuencia +
        # lectura del último hash + INSERT) tiene que ser una sola sección
        # crítica: dos fichajes casi simultáneos (de cualquier usuario,
        # la cadena de hash es global -- ver verificar_integridad_fichajes)
        # podrían leer el mismo "último tipo"/"último hash" antes de que
        # ninguno haya insertado, y dejar la secuencia o la cadena rotas.
        # BEGIN IMMEDIATE adquiere el lock de escritura YA, en vez de
        # esperar a la primera escritura (comportamiento por defecto de
        # sqlite3): un segundo fichar() concurrente se queda esperando aquí
        # (hasta busy_timeout, ya en 5000ms en get_connection()) en vez de
        # leer datos que están a punto de quedar obsoletos.
        conn.execute("BEGIN IMMEDIATE")
        if corrige_a is not None:
            original = conn.execute("SELECT id FROM fichajes WHERE id = ? AND usuario_id = ?", (corrige_a, usuario_id)).fetchone()
            if original is None:
                raise ValueError(f"El fichaje {corrige_a} a corregir no existe o no es de este trabajador.")
        else:
            ultimo = conn.execute(
                "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
            ).fetchone()
            ultimo_tipo = ultimo["tipo"] if ultimo else "salida"  # sin fichajes previos = como si estuviera fuera
            if tipo not in _FICHAJE_TRANSICIONES_VALIDAS.get(ultimo_tipo, set()):
                raise ValueError(f"No se puede fichar '{tipo}' viniendo de '{ultimo_tipo}' — revisa tu último fichaje.")
        marca_tiempo_final = marca_tiempo or ahora
        creado_por_final = creado_por or usuario_id
        ultimo_hash = conn.execute("SELECT hash FROM fichajes ORDER BY id DESC LIMIT 1").fetchone()
        hash_anterior = ultimo_hash["hash"] if ultimo_hash and ultimo_hash["hash"] else _HASH_FICHAJE_GENESIS
        hash_fila = _hash_fichaje(hash_anterior, usuario_id, tipo, marca_tiempo_final, creado_por_final)
        cur = conn.execute(
            """INSERT INTO fichajes
               (usuario_id, tenant_id, tipo, marca_tiempo, origen, nota, corrige_a, creado_por, creado_en,
                cliente_uuid, hash, latitud, longitud)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, tenant_id, tipo, marca_tiempo_final, origen, nota, corrige_a, creado_por_final, ahora,
                cliente_uuid, hash_fila, latitud, longitud,
            ),
        )
        conn.commit()
        return cur.lastrowid
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def verificar_integridad_fichajes() -> dict:
    """Recorre TODA la cadena de hashes de `fichajes` (ver _hash_fichaje)
    y confirma que cada fila coincide con el hash recalculado a partir de
    la anterior -- expuesta en /fichaje/admin/verificar-integridad. Es una
    comprobación global (no por tenant): la cadena entrelaza filas de
    todos los tenants, así que verificarla entera es lo único que tiene
    sentido matemáticamente; cualquier admin/gestor puede pedirla, no
    revela contenido de otros tenants, solo si la cadena es íntegra o en
    qué fila se rompió."""
    conn = get_connection()
    try:
        filas = conn.execute(
            "SELECT id, usuario_id, tipo, marca_tiempo, creado_por, hash FROM fichajes ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    hash_anterior = _HASH_FICHAJE_GENESIS
    for fila in filas:
        esperado = _hash_fichaje(hash_anterior, fila["usuario_id"], fila["tipo"], fila["marca_tiempo"], fila["creado_por"])
        if fila["hash"] != esperado:
            return {"integra": False, "total_fichajes": len(filas), "primera_fila_rota": fila["id"]}
        hash_anterior = fila["hash"]
    return {"integra": True, "total_fichajes": len(filas), "primera_fila_rota": None}


def estado_actual_fichaje(usuario_id: int) -> str:
    """'fuera' | 'dentro' | 'en_pausa', según el último evento real (no
    cuenta si esa fila es en sí una corrección de otra anterior — el
    último evento cronológico manda igual)."""
    conn = get_connection()
    try:
        ultimo = conn.execute(
            "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
        ).fetchone()
        if ultimo is None or ultimo["tipo"] == "salida":
            return "fuera"
        if ultimo["tipo"] == "pausa_inicio":
            return "en_pausa"
        return "dentro"
    finally:
        conn.close()


def jornadas_abiertas_sin_aviso(entrada_antes_de: str) -> list[sqlite3.Row]:
    """Jornadas abiertas (el último evento del trabajador no es una salida)
    cuya última entrada es anterior a `entrada_antes_de` (ISO) y de las que
    todavía no se ha avisado."""
    conn = get_connection()
    try:
        return conn.execute(
            """SELECT e.id AS entrada_id, e.usuario_id, e.marca_tiempo
               FROM fichajes e
               WHERE e.tipo = 'entrada'
                 AND e.id = (SELECT MAX(id) FROM fichajes WHERE usuario_id = e.usuario_id AND tipo = 'entrada')
                 AND (SELECT tipo FROM fichajes WHERE usuario_id = e.usuario_id ORDER BY id DESC LIMIT 1) != 'salida'
                 AND e.marca_tiempo <= ?
                 AND NOT EXISTS (SELECT 1 FROM fichaje_avisos a WHERE a.usuario_id = e.usuario_id AND a.entrada_id = e.id)""",
            (entrada_antes_de,),
        ).fetchall()
    finally:
        conn.close()


def registrar_aviso_fichaje(usuario_id: int, entrada_id: int) -> bool:
    """True si es la primera vez que se avisa de esta jornada."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO fichaje_avisos (usuario_id, entrada_id, avisado_en) VALUES (?, ?, ?)",
            (usuario_id, entrada_id, now_iso()),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def entrada_abierta_fichaje(usuario_id: int) -> str | None:
    """Marca de tiempo de la entrada de la jornada abierta, o None si está fuera."""
    conn = get_connection()
    try:
        ultimo = conn.execute(
            "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
        ).fetchone()
        if ultimo is None or ultimo["tipo"] == "salida":
            return None
        entrada = conn.execute(
            "SELECT marca_tiempo FROM fichajes WHERE usuario_id = ? AND tipo = 'entrada' ORDER BY id DESC LIMIT 1",
            (usuario_id,),
        ).fetchone()
        return entrada["marca_tiempo"] if entrada else None
    finally:
        conn.close()


def ultimo_fichaje(usuario_id: int) -> sqlite3.Row | None:
    """La fila completa del último evento de fichaje -- a diferencia de
    estado_actual_fichaje() (que calcula el ESTADO a partir del mismo
    último evento pero descarta su marca_tiempo), esta sí expone la
    marca_tiempo, para poder mostrar "llevas X tiempo dentro/en pausa"
    en el panel del trabajador."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
        ).fetchone()
    finally:
        conn.close()


def listar_fichajes(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[sqlite3.Row]:
    """Historial de un trabajador -- se usa tanto para su propio
    historial como para el detalle que ve un admin de un trabajador
    concreto (mismos datos, distinto quién pregunta; el control de acceso
    vive en la ruta, no aquí)."""
    conn = get_connection()
    try:
        sql = "SELECT * FROM fichajes WHERE usuario_id = ?"
        params: list = [usuario_id]
        if desde:
            sql += " AND marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND marca_tiempo < ?"
            params.append(_fecha_exclusiva(hasta))
        sql += " ORDER BY marca_tiempo DESC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def fichajes_tenant_crudos(
    tenant_id: int | None, desde: str | None = None, hasta: str | None = None, usuario_id: int | None = None,
) -> list[sqlite3.Row]:
    """Eventos de fichaje en bruto de un tenant (con email/nombre/DNI del
    trabajador ya unidos), para que app/fichaje_export.py construya el
    CSV/PDF -- misma idea que db.historial() alimentando a export.py, la
    tabla en sí no sabe nada de formatos de salida."""
    conn = get_connection()
    try:
        sql = (
            "SELECT f.*, u.email, fd.nombre_completo, fd.dni_nie "
            "FROM fichajes f "
            "JOIN usuarios u ON u.id = f.usuario_id "
            "LEFT JOIN fichaje_datos fd ON fd.usuario_id = f.usuario_id "
            "WHERE (f.tenant_id = ? OR (? IS NULL AND f.tenant_id IS NULL))"
        )
        params: list = [tenant_id, tenant_id]
        if usuario_id:
            sql += " AND f.usuario_id = ?"
            params.append(usuario_id)
        if desde:
            sql += " AND f.marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND f.marca_tiempo < ?"
            params.append(_fecha_exclusiva(hasta))
        sql += " ORDER BY f.usuario_id, f.marca_tiempo"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def resumen_fichajes_tenant(tenant_id: int | None, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Horas trabajadas por cada trabajador del tenant en el periodo, para
    el panel de admin. Empareja entrada/salida y resta las pausas
    recorriendo el log en Python (no es un problema que encaje bien en
    SQL puro: es "diferencia entre eventos consecutivos de una serie")."""
    conn = get_connection()
    try:
        sql = (
            "SELECT f.*, u.email, fd.nombre_completo, fd.jornada_semanal_horas "
            "FROM fichajes f "
            "JOIN usuarios u ON u.id = f.usuario_id "
            "LEFT JOIN fichaje_datos fd ON fd.usuario_id = f.usuario_id "
            "WHERE (f.tenant_id = ? OR (? IS NULL AND f.tenant_id IS NULL))"
        )
        params: list = [tenant_id, tenant_id]
        if desde:
            sql += " AND f.marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND f.marca_tiempo < ?"
            params.append(_fecha_exclusiva(hasta))
        sql += " ORDER BY f.usuario_id, f.marca_tiempo"
        filas = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    por_usuario: dict[int, dict] = {}
    for f in filas:
        uid = f["usuario_id"]
        info = por_usuario.setdefault(uid, {
            "usuario_id": uid, "email": f["email"], "nombre_completo": f["nombre_completo"],
            "jornada_semanal_horas": f["jornada_semanal_horas"],
            "segundos_trabajados": 0, "segundos_pausa": 0, "num_fichajes": 0,
            "entrada_abierta": None, "pausa_abierta": None,
        })
        info["num_fichajes"] += 1
        marca = datetime.fromisoformat(f["marca_tiempo"])
        if f["tipo"] == "entrada":
            info["entrada_abierta"] = marca
        elif f["tipo"] == "pausa_inicio":
            info["pausa_abierta"] = marca
        elif f["tipo"] == "pausa_fin" and info["pausa_abierta"]:
            info["segundos_pausa"] += (marca - info["pausa_abierta"]).total_seconds()
            info["pausa_abierta"] = None
        elif f["tipo"] == "salida" and info["entrada_abierta"]:
            info["segundos_trabajados"] += (marca - info["entrada_abierta"]).total_seconds()
            info["entrada_abierta"] = None

    resultado = [
        {
            "usuario_id": info["usuario_id"],
            "email": info["email"],
            "nombre_completo": info["nombre_completo"],
            "horas_trabajadas": round(info["segundos_trabajados"] / 3600, 2),
            "horas_pausa": round(info["segundos_pausa"] / 3600, 2),
            "jornada_semanal_horas": info["jornada_semanal_horas"],
            "num_fichajes": info["num_fichajes"],
            "jornada_abierta": info["entrada_abierta"] is not None,
        }
        for info in por_usuario.values()
    ]
    return sorted(resultado, key=lambda r: r["nombre_completo"] or r["email"])

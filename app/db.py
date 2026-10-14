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
import random
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
-- Expediente del cliente: los documentos que el despacho guarda de un cliente (subidos a mano o archivados
-- desde un correo). Distintos de vencimientos_fiscales_documentos, que son los que sube el cliente por el portal.
CREATE TABLE IF NOT EXISTS cliente_documentos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id) ON DELETE CASCADE,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    categoria TEXT,
    origen TEXT NOT NULL DEFAULT 'subida' CHECK (origen IN ('subida', 'correo')),
    mensaje_correo_id INTEGER,
    asunto_origen TEXT,
    subido_por INTEGER REFERENCES usuarios(id),
    hash_sha256 TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cliente_documentos_cliente ON cliente_documentos(cliente_fiscal_id, creado_en);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cliente_documentos_unico ON cliente_documentos(cliente_fiscal_id, hash_sha256);
-- Quién ha mirado o tocado qué de un cliente (ficha, documentos, correos archivados): rastro para el despacho y el RGPD.
CREATE TABLE IF NOT EXISTS cliente_accesos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL,
    usuario_id INTEGER,
    accion TEXT NOT NULL,
    detalle TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cliente_accesos_cliente ON cliente_accesos(cliente_fiscal_id, id);
CREATE INDEX IF NOT EXISTS idx_cliente_accesos_fecha ON cliente_accesos(creado_en);
-- Reglas que crean una tarea por cada vencimiento fiscal pendiente de un modelo (p. ej. «Preparar el 303 de {cliente}»
-- 14 días antes de su fecha límite, con vencimiento 2 días antes). Cada vencimiento genera como mucho una tarea por regla.
CREATE TABLE IF NOT EXISTS tareas_por_vencimiento (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tenant_id INTEGER NOT NULL,
    modelo TEXT NOT NULL,
    asunto TEXT NOT NULL,
    crear_dias_antes INTEGER NOT NULL DEFAULT 14,
    vence_dias_antes INTEGER NOT NULL DEFAULT 2,
    categoria_id INTEGER,
    asignar_responsable INTEGER NOT NULL DEFAULT 1,
    estimacion_min INTEGER,
    prioridad TEXT NOT NULL DEFAULT 'normal',
    activa INTEGER NOT NULL DEFAULT 1,
    creada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tareas_por_vencimiento_generadas (
    regla_id INTEGER NOT NULL REFERENCES tareas_por_vencimiento(id) ON DELETE CASCADE,
    vencimiento_id INTEGER NOT NULL,
    tarea_id INTEGER,
    creada_en TEXT NOT NULL,
    PRIMARY KEY (regla_id, vencimiento_id)
);
-- Vistas guardadas de la lista de tareas: un conjunto de filtros con nombre, privado o compartido con el despacho.
CREATE TABLE IF NOT EXISTS tareas_vistas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tenant_id INTEGER,
    nombre TEXT NOT NULL,
    filtros TEXT NOT NULL,
    compartida INTEGER NOT NULL DEFAULT 0,
    creada_en TEXT NOT NULL,
    UNIQUE (usuario_id, nombre)
);
CREATE INDEX IF NOT EXISTS idx_tareas_vistas_tenant ON tareas_vistas(tenant_id, compartida);
-- «Avísame si no responde»: un correo enviado del que se espera contestación. Se cierra solo si llega una
-- respuesta (en el mismo hilo, de otra persona) y, si pasa el plazo sin ella, se avisa una vez.
CREATE TABLE IF NOT EXISTS correo_seguimientos (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    cuenta_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    asunto TEXT,
    destinatarios TEXT,
    creado_en TEXT NOT NULL,
    avisar_en TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'esperando' CHECK (estado IN ('esperando', 'respondido', 'sin_respuesta', 'cancelado')),
    cerrado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_correo_seguimientos_estado ON correo_seguimientos(estado, avisar_en);
CREATE INDEX IF NOT EXISTS idx_correo_seguimientos_usuario ON correo_seguimientos(usuario_id, estado);
-- Cómo recuerda cada despacho a sus clientes (portal): qué días antes/después del vencimiento, si avisa al equipo
-- cuando el cliente no ha entregado lo que se le pidió y, opcionalmente, su propio texto. Sin fila = valores de siempre (7 y 2 días).
CREATE TABLE IF NOT EXISTS portal_recordatorios_config (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    dias_antes TEXT NOT NULL DEFAULT '7,2',
    dias_despues TEXT NOT NULL DEFAULT '',
    avisar_equipo INTEGER NOT NULL DEFAULT 0,
    asunto TEXT,
    cuerpo TEXT,
    actualizado_en TEXT
);
-- Avisos internos ya hechos («el cliente no ha entregado lo pedido»), uno por vencimiento y antelación.
CREATE TABLE IF NOT EXISTS vencimientos_escalados (
    vencimiento_id INTEGER NOT NULL REFERENCES vencimientos_fiscales(id) ON DELETE CASCADE,
    dias_antes INTEGER NOT NULL,
    avisado_en TEXT NOT NULL,
    PRIMARY KEY (vencimiento_id, dias_antes)
);
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

-- Cola persistente de entregas de webhooks (ver app/eventos.py). Estados: pendiente, entregando, entregado, fallido.
CREATE TABLE IF NOT EXISTS webhooks_cola (
    id INTEGER PRIMARY KEY,
    webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    evento TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    intentos INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'entregando', 'entregado', 'fallido')),
    proximo_intento TEXT NOT NULL,
    reclamado_en TEXT,
    ultimo_error TEXT,
    creado_en TEXT NOT NULL,
    cerrado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_webhooks_cola_estado ON webhooks_cola(estado, proximo_intento);

-- Uso diario de cada token de API (llamadas y errores): para saber qué integración hace qué y detectar abusos.
CREATE TABLE IF NOT EXISTS tokens_api_uso (
    token_id INTEGER NOT NULL REFERENCES tokens_api(id) ON DELETE CASCADE,
    dia TEXT NOT NULL,
    llamadas INTEGER NOT NULL DEFAULT 0,
    errores INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (token_id, dia)
);

-- Uso y auditoría del servidor MCP: qué herramienta usó quién, con qué cliente y con qué resultado. De los argumentos solo se
-- guardan su forma (tipos y tamaños) y los ids numéricos, nunca textos libres (correos, notas...), por privacidad.
CREATE TABLE IF NOT EXISTS mcp_uso (
    dia TEXT NOT NULL,
    usuario_id INTEGER NOT NULL,
    herramienta TEXT NOT NULL,
    llamadas INTEGER NOT NULL DEFAULT 0,
    errores INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dia, usuario_id, herramienta)
);
CREATE TABLE IF NOT EXISTS mcp_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado_en TEXT NOT NULL,
    usuario_id INTEGER,
    tenant_id INTEGER,
    cliente TEXT NOT NULL,
    token_id INTEGER,
    herramienta TEXT NOT NULL,
    lectura INTEGER NOT NULL DEFAULT 0,
    resultado TEXT NOT NULL CHECK (resultado IN ('ok', 'error', 'denegado', 'limite')),
    detalle TEXT,
    argumentos TEXT,
    duracion_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mcp_auditoria_fecha ON mcp_auditoria(creado_en);
CREATE INDEX IF NOT EXISTS idx_mcp_auditoria_usuario ON mcp_auditoria(usuario_id, creado_en);

-- Claves de idempotencia de la API (cabecera Idempotency-Key en POST): una repetición devuelve la misma respuesta.
CREATE TABLE IF NOT EXISTS api_idempotencia (
    usuario_id INTEGER NOT NULL,
    clave TEXT NOT NULL,
    huella TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'en_curso' CHECK (estado IN ('en_curso', 'listo')),
    status INTEGER,
    cuerpo TEXT,
    creado_en TEXT NOT NULL,
    PRIMARY KEY (usuario_id, clave)
);

-- Consumo mensual de IA por despacho (consultas al modelo). El tope vive en tenants.ia_limite_mensual (NULL = ilimitado).
CREATE TABLE IF NOT EXISTS ia_consumo (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    mes TEXT NOT NULL,
    usadas INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, mes)
);

-- Consultas de soporte del asistente que no cuentan en el límite de IA: cupo diario por persona (app/ia_soporte.py).
CREATE TABLE IF NOT EXISTS ia_soporte_uso (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    dia TEXT NOT NULL,
    usadas INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (usuario_id, dia)
);

-- Modo mantenimiento (backoffice): tenant_id NULL = toda la plataforma. Los administradores globales pasan.
CREATE TABLE IF NOT EXISTS mantenimiento (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    mensaje TEXT NOT NULL DEFAULT '',
    hasta TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL,
    creado_por TEXT
);

-- "Ver como" (soporte): enlaces de un solo uso que emite el backoffice. Solo se guarda el hash.
CREATE TABLE IF NOT EXISTS ver_como_tokens (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    admin TEXT NOT NULL,
    motivo TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    expira_en TEXT NOT NULL,
    usado_en TEXT
);

-- Comunicados del backoffice a la plataforma (banner en la app). tenant_id NULL = todos los despachos.
CREATE TABLE IF NOT EXISTS comunicados (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL DEFAULT '',
    nivel TEXT NOT NULL DEFAULT 'info' CHECK (nivel IN ('info', 'aviso', 'critico')),
    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    desde TEXT,
    hasta TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comunicados_cerrados (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    comunicado_id INTEGER NOT NULL REFERENCES comunicados(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, comunicado_id)
);

-- Latidos de las tareas periódicas del servidor (panel de salud del backoffice).
CREATE TABLE IF NOT EXISTS latidos (
    nombre TEXT PRIMARY KEY,
    ultimo_ok TEXT,
    ultimo_error TEXT,
    detalle TEXT,
    intervalo_segundos INTEGER NOT NULL DEFAULT 0
);

-- Respuestas 5xx del servidor (panel de salud y alerta por ráfaga de errores). Solo se guarda la plantilla de la ruta, nunca
-- la URL con identificadores ni la consulta. Se purga a los 7 días.
CREATE TABLE IF NOT EXISTS errores_servidor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado_en TEXT NOT NULL,
    metodo TEXT NOT NULL,
    ruta TEXT NOT NULL,
    estado INTEGER NOT NULL,
    request_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_errores_servidor_fecha ON errores_servidor (creado_en);

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
        _asegurar_columna(conn, "webhooks", "origen", "TEXT NOT NULL DEFAULT 'backoffice'")
        # Referencia del sistema externo (ERP, CRM...) para sincronizar sin duplicar: única por dueño cuando existe.
        _asegurar_columna(conn, "clientes_fiscales", "referencia_externa", "TEXT")
        _asegurar_columna(conn, "tareas_outlook", "referencia_externa", "TEXT")
        _asegurar_columna(conn, "notas", "referencia_externa", "TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_fiscales_ref ON clientes_fiscales(tenant_id, referencia_externa) WHERE referencia_externa IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tareas_outlook_ref ON tareas_outlook(usuario_id, referencia_externa) WHERE referencia_externa IS NOT NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notas_ref ON notas(usuario_id, referencia_externa) WHERE referencia_externa IS NOT NULL")
        _asegurar_columna(conn, "tokens_api", "areas", "TEXT")
        _asegurar_columna(conn, "tokens_api", "caduca_en", "TEXT")
        _asegurar_columna(conn, "tokens_api", "ultima_ip", "TEXT")
        _asegurar_columna(conn, "tokens_api", "origenes_cors", "TEXT")
        _asegurar_columna(conn, "tokens_api", "ips_permitidas", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "in_reply_to", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "referencias", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "hilo_clave", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "destacado", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "correo_mensajes", "fecha_aviso", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "pospuesto_hasta", "TEXT")
        # Correo cifrado (app/correo_cifrado.py): 0 en claro, 1 sellado, 2 entrando (por sellar). Van aquí, antes del índice de texto, porque sus disparadores las leen.
        _asegurar_columna(conn, "correo_mensajes", "cifrado", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "correo_mensajes", "cifrado_nivel", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "sobre", "TEXT")
        _asegurar_columna(conn, "correo_mensajes", "datos", "BLOB")
        # Vínculo manual con un cliente fiscal (app/rutas_correo.py,
        # app/rutas_fiscal.py:ficha_cliente) -- nullable y opt-in, el
        # empleado lo rellena a mano desde la vista de un mensaje, sin
        # ningún intento de adivinarlo automáticamente por remitente.
        # Va ANTES de conn.executescript(INDICES) porque ese script crea
        # un índice sobre esta misma columna (mismo motivo que
        # tareas_outlook.tarea_recurrente_id más abajo).
        _asegurar_columna(conn, "correo_mensajes", "cliente_fiscal_id", "INTEGER REFERENCES clientes_fiscales(id)")
        _asegurar_columna(conn, "correo_cuentas", "auth_tipo", "TEXT NOT NULL DEFAULT 'password'")
        _asegurar_columna(conn, "correo_reglas", "archivar_adjuntos", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "correo_envios", "seguimiento_dias", "INTEGER")
        _asegurar_columna(conn, "correo_envios", "identidad_id", "INTEGER")
        conn.execute("""CREATE TABLE IF NOT EXISTS correo_identidades (
            id INTEGER PRIMARY KEY,
            cuenta_id INTEGER NOT NULL REFERENCES correo_cuentas(id) ON DELETE CASCADE,
            nombre TEXT NOT NULL,
            direccion TEXT NOT NULL,
            creada_en TEXT NOT NULL,
            UNIQUE (cuenta_id, direccion)
        )""")
        _asegurar_columna(conn, "correo_plantillas", "modelo", "TEXT")      # modelo fiscal al que se refiere (p. ej. 303)
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
        _asegurar_columna(conn, "tenants", "ia_limite_mensual", "INTEGER")
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
        # Perfil fiscal (app/perfil_fiscal.py): JSON {"tipo", "atributos"} de donde se deducen los modelos propuestos.
        _asegurar_columna(conn, "clientes_fiscales", "perfil_fiscal", "TEXT")
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
        # Vencimiento fiscal del que sale o al que sirve la tarea (las generadas por una regla `tareas_por_vencimiento` y las creadas desde su ficha): presentar el vencimiento
        # cierra las generadas por regla y la ficha del vencimiento lista sus tareas. Las generadas antes de existir esta columna se enlazan desde `tareas_por_vencimiento_generadas`.
        _asegurar_columna(conn, "tareas_outlook", "vencimiento_id", "INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tareas_outlook_vencimiento ON tareas_outlook(vencimiento_id) WHERE vencimiento_id IS NOT NULL")
        conn.execute("UPDATE tareas_outlook SET vencimiento_id = (SELECT g.vencimiento_id FROM tareas_por_vencimiento_generadas g WHERE g.tarea_id = tareas_outlook.id) "
                     "WHERE vencimiento_id IS NULL AND id IN (SELECT tarea_id FROM tareas_por_vencimiento_generadas WHERE tarea_id IS NOT NULL)")
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
        _crear_triggers_cambios(conn)
        _asegurar_orden_categorias(conn)

        usuario_id_local = _resolver_usuario_local(conn)
        _migrar_datos_sin_usuario(conn, usuario_id_local)
        _migrar_conversaciones_ia(conn)
        _migrar_preferencias_singleton(conn, usuario_id_local)
        _asegurar_columna(conn, "correo_preferencias", "deshacer_segundos", "INTEGER NOT NULL DEFAULT 10")
        for col, tipo in (("tam_letra", "TEXT NOT NULL DEFAULT 'normal'"), ("disposicion", "TEXT NOT NULL DEFAULT 'tres'"), ("ancho_lista", "INTEGER NOT NULL DEFAULT 0"),
                          ("vista_previa", "INTEGER NOT NULL DEFAULT 1")):      # vistas personalizables del correo (app/correo_vista.py)
            _asegurar_columna(conn, "correo_preferencias", col, tipo)
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
        _asegurar_columna(conn, "usuarios", "tema", "TEXT")                # system | light | dark (NULL = no elegido: manda el navegador)
        _asegurar_columna(conn, "usuarios", "densidad", "TEXT")            # normal | compacta
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
        # Perfil ampliado: cargo y teléfono (visibles en la ficha y firma de equipo) y «no molestar» (franja horaria sin push; la
        # notificación sigue en la app). Horas «HH:MM» en la zona horaria del despacho; si desde > hasta cruza la medianoche.
        _asegurar_columna(conn, "usuario_perfil", "cargo", "TEXT")
        _asegurar_columna(conn, "usuario_perfil", "telefono", "TEXT")
        _asegurar_columna(conn, "usuario_perfil", "silencio_desde", "TEXT")
        _asegurar_columna(conn, "usuario_perfil", "silencio_hasta", "TEXT")
        # Resumen diario de pendientes (app/resumen_pendientes.py): opt-in, a su hora, solo entre semana.
        _asegurar_columna(conn, "usuario_perfil", "resumen_diario", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "usuario_perfil", "resumen_diario_hora", "INTEGER NOT NULL DEFAULT 8")
        _asegurar_columna(conn, "usuario_perfil", "resumen_diario_email", "INTEGER NOT NULL DEFAULT 1")
        _asegurar_columna(conn, "usuario_perfil", "resumen_diario_ultimo", "TEXT")
        _asegurar_columna(conn, "correo_carpetas", "ultimo_uid_sincronizado", "TEXT")
        _asegurar_columna(conn, "correo_carpetas", "uidvalidity", "TEXT")
        _asegurar_columna(conn, "correo_carpetas", "ultima_pasada_completa", "TEXT")
        _asegurar_columna(conn, "correo_carpetas", "descarga_pendiente", "INTEGER NOT NULL DEFAULT 0")
        _asegurar_columna(conn, "correo_carpetas", "modseq", "TEXT")      # HIGHESTMODSEQ (CONDSTORE) de la última pasada
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
        _asegurar_columna(conn, "tareas_outlook", "estimacion_min", "INTEGER")        # tiempo estimado, en minutos
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tareas_outlook_proyecto ON tareas_outlook(categoria_id, seccion_id)")
        _crear_vista_participantes_todos(conn)
        from . import nucleo
        nucleo.crear_esquema(conn)            # clientes, expedientes, plazos, horas y verticales (app/nucleo.py)
        from . import ausencias
        ausencias.crear_esquema(conn)         # ausencias, vacaciones y permisos con saldo (app/ausencias.py)
        from . import turnos, bolsa_horas
        turnos.crear_esquema(conn)            # cuadrante de turnos (app/turnos.py)
        bolsa_horas.crear_esquema(conn)       # ajustes manuales de la bolsa de horas (app/bolsa_horas.py)
        from . import certificados
        certificados.crear_esquema(conn)      # inventario de certificados digitales X.509 (app/certificados.py)
        from . import auditoria
        auditoria.crear_esquema(conn)         # auditoría unificada, solo de anexado (app/auditoria.py)
        from . import fiscal_base
        fiscal_base.crear_esquema(conn)       # cimientos del control fiscal: unicidades, versión, fase, oficinas y permisos (app/fiscal_base.py)
        from . import correo_autorespuesta
        correo_autorespuesta.crear_esquema(conn)   # respuesta automática por cuenta de correo (app/correo_autorespuesta.py)
        from . import reglas_laborales
        reglas_laborales.crear_esquema(conn)  # reglas laborales aprobadas por el propietario, vacías al instalar (app/reglas_laborales.py)
        from . import laboral
        laboral.crear_esquema(conn)           # trabajadores de los clientes: gestión laboral, primera rebanada (app/laboral.py)
        from . import plantillas_cliente
        plantillas_cliente.crear_esquema(conn)  # plantillas de alta de cliente por tipo (app/plantillas_cliente.py)
        from . import traspasos
        traspasos.crear_esquema(conn)         # traspasos de clientes entre personas y oficinas, y responsable del cliente (app/traspasos.py)

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


_ULTIMO_ACCESO_ANOTADO: dict[int, float] = {}


# --- Tokens de la API (Fase 2, app móvil) -------------------------------
# Tokens opacos (no JWT): el valor en claro se genera una vez y se devuelve
# al cliente; aquí solo se guarda su hash SHA-256 (no generate_password_hash
# — el token ya tiene alta entropía propia y hace falta una búsqueda exacta
# rápida por igualdad, no una comparación tipo contraseña).


PERMISOS_TOKEN_API = ("completo", "solo_lectura")


TOKEN_API_DIAS_INACTIVIDAD = 90


_CACHE_ORIGENES: dict[str, tuple[float, bool]] = {}


# --- Log de auditoría del backoffice (app/rutas_backoffice.py) -------------


# ---- Registro de cambios para la sincronización incremental de la API (/api/v1/sync) ----------------------------
# Triggers de SQLite: cualquier alta, edición, papelera o borrado de notas, tareas, tareas de lista y proyectos deja
# una fila en `api_cambios`, pase por el código que pase (restaurar de la papelera, recálculos...). El cursor es el id
# de esa tabla: monótono y sin depender de relojes. Se conservan 30 días.

_ENTIDADES_CAMBIOS = (("notas", "notas"), ("tareas_outlook", "tareas_outlook"), ("categorias", "proyectos"), ("tareas", "tareas"))
CAMBIOS_RETENCION_DIAS = 30


# ---- Idempotencia de la API ------------------------------------------------------------------------------------

IDEMPOTENCIA_HORAS = 24


# ---- Referencias externas (sincronizar con otros sistemas sin duplicar) ---------------------------------------------

_DUENO_REFERENCIA = {"clientes_fiscales": "tenant_id", "tareas_outlook": "usuario_id", "notas": "usuario_id"}


# ---- Uso y auditoría del MCP --------------------------------------------------------------------------------------------

MCP_AUDITORIA_RETENCION_DIAS = 90


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


# --- Webhooks (ver app/eventos.py) --------------------------------------

_MAX_ENTREGAS_POR_WEBHOOK = 50


NOTA_TITULO_MAX_CARACTERES = 120
_SIN_CAMBIO = object()


# ---- Adjuntos de nota ---------------------------------------------------------

NOTAS_ADJUNTOS_MIME = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain", "text/csv",
}
NOTAS_ADJUNTOS_TAMANO_MAXIMO = 5 * 1024 * 1024
NOTAS_ADJUNTOS_MAXIMO_POR_NOTA = 5


# --- Frases favoritas (plantillas) ------------------------------------------
# Se aíslan a través de categoria_id (NOT NULL, siempre de un usuario ya
# validado por la ruta antes de llamar aquí) — no llevan usuario_id propio.


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
    "categoria_outlook", "categoria_id", "outlook_entry_id", "estimacion_min",
)


# --- Tareas recurrentes (app/rutas_tareas.py) --------------------------

PERIODICIDADES_RECURRENTES = ("diaria", "laborables", "semanal", "mensual", "trimestral", "anual")


# --- Tareas por vencimiento fiscal ---------------------------------------------------------------

MAX_REGLAS_POR_VENCIMIENTO = 40


ETIQUETAS_CAMPO_TAREA = {
    "asunto": "asunto", "cuerpo": "descripción", "prioridad": "prioridad", "estado": "estado",
    "fecha_inicio": "inicio", "fecha_vencimiento": "vencimiento", "cliente_fiscal_id": "cliente",
    "categoria_id": "proyecto", "categoria_outlook": "categoría", "estimacion_min": "estimación",
}


# ---- Compartir tareas con compañeros del tenant ---------------------------

ROLES_PARTICIPANTE = ("colabora", "observa")


# ---- Comentarios con menciones ---------------------------------------------

COMENTARIO_MAX_CARACTERES = 2000


# ---- Plantillas de tareas ---------------------------------------------------

PLANTILLA_MAX_ITEMS = 40


MAX_COMPARTIDOS_POR_MENSAJE = 10
MAX_NOTAS_INTERNAS_POR_MENSAJE = 100


NOTA_INTERNA_MAX_CARACTERES = 2000


# ---- Recordatorios por tarea ----------------------------------------------------

CANALES_RECORDATORIO = ("app", "correo", "ntfy")


HORAS_DIA_DEFECTO = 8.0
TAREAS_POR_CELDA = 6


# --- Vistas guardadas de la lista de tareas ---------------------------------------------------

MAX_VISTAS_TAREAS = 30
FILTROS_VISTA_TAREAS = ("vista", "estado", "prioridad", "categoria", "q", "completadas")


# --- Acciones en lote sobre tareas ---------------------------------------------------------------

MAX_TAREAS_LOTE = 200
ACCIONES_LOTE = ("completar", "estado", "prioridad", "fecha", "asignar", "proyecto", "seccion")


# ---- Checklist (subtareas) -------------------------------------------------

CHECKLIST_MAX_ITEMS = 50
CHECKLIST_MAX_CARACTERES = 200


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
    "facturascripts_cliente_codigo", "pais", "recordatorios_portal", "idioma", "perfil_fiscal", "oficina_id", "nif_duplicado_autorizado",
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


# --- Portal de cliente (app/rutas_portal_cliente.py) -------------------------
# El "principal" aquí es un cliente_fiscal_id, no un usuario_id/tenant_id de
# empleado -- estas funciones nunca reciben tenant_id como filtro porque el
# propio cliente_fiscal_id/vencimiento_id ya identifica de forma única al
# dueño (igual que las funciones de arriba filtran por usuario_id).


_MINUTOS_VIDA_ACCESO_FACTURACION = 1


# "correo" = adjunto guardado desde un correo: interno, el cliente NO lo ve en el portal;
# "correo_compartido" = el mismo, pero el equipo ha decidido enseñárselo al cliente.
ORIGENES_DOCUMENTO_VENCIMIENTO = ("cliente", "justificante", "constancia", "correo", "correo_compartido")
ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO = ("correo",)


CONFIG_RECORDATORIOS_DEFECTO = {"dias_antes": [7, 2], "dias_despues": [], "avisar_equipo": False, "asunto": "", "cuerpo": ""}
MAX_AVISOS_ANTES = 6
MAX_AVISOS_DESPUES = 4


# --- Correo (cuentas IMAP/POP3 + caché de mensajes) ---------------------------
# La lógica de red (conectar, sincronizar, enviar) vive en app/correo.py; aquí
# solo hay persistencia. La contraseña de cada cuenta NO se guarda en esta
# tabla — la gestiona app/correo.py directamente contra keyring.
# correo_carpetas/correo_mensajes/correo_adjuntos cuelgan de correo_cuentas
# (cuenta_id NOT NULL) y se aíslan por JOIN — no llevan usuario_id propio.


# --- Expediente del cliente (documentos) ----------------------------------------------------

MAX_DOCUMENTO_CLIENTE_BYTES = 15 * 1024 * 1024
MAX_DOCUMENTOS_POR_CLIENTE = 1000
CATEGORIAS_DOCUMENTO = ("Extractos", "Facturas emitidas", "Facturas recibidas", "Modelos presentados", "Contratos", "Otros")


# --- Registro de accesos a un cliente -------------------------------------------------------------

ACCIONES_ACCESO_CLIENTE = {
    "ficha_vista": "Ha abierto la ficha", "cliente_editado": "Ha editado los datos", "cliente_eliminado": "Ha enviado el cliente a la papelera",
    "documento_subido": "Ha subido un documento al expediente", "documento_descargado": "Ha descargado un documento del expediente",
    "documento_eliminado": "Ha eliminado un documento del expediente", "correo_archivado": "Ha archivado un correo en el expediente",
    "vencimiento_documento_descargado": "Ha descargado un documento de un vencimiento", "informe_mensual": "Ha generado el informe mensual",
    "laboral_visto": "Ha abierto la pestaña Laboral", "trabajador_creado": "Ha dado de alta a un trabajador", "trabajador_editado": "Ha editado a un trabajador",
    "trabajador_eliminado": "Ha eliminado a un trabajador",
}
RETENCION_ACCESOS_DIAS = 730
VENTANA_FICHA_VISTA_MINUTOS = 30


# --- Preferencias generales de Correo (una fila por usuario) ------------------

DESHACER_ENVIO_OPCIONES = (0, 10, 30)
MAX_BYTES_ADJUNTOS_ENVIO = 25 * 1024 * 1024


# --- «Avísame si no responde» ---------------------------------------------------------------

DIAS_SEGUIMIENTO_MAX = 30


ERRORES_SERVIDOR_RETENCION_DIAS = 7


_FTS_CORREO_COLUMNAS = "asunto, remitente, destinatarios, cuerpo_texto"


_TROZO_BUSQUEDA = re.compile(r'"([^"]+)"|(\S+)')


# --- Cola de cambios hacia el servidor (correo_operaciones) ---------------------------

MAX_INTENTOS_OPERACION_CORREO = 5


_PREFIJOS_ASUNTO = re.compile(r"^\s*(?:(?:re|rv|fwd?|enc|res|aw|sv|tr)\s*(?:\[\d+\])?\s*:\s*)+", re.IGNORECASE)
_PATRON_ID_MENSAJE = re.compile(r"<[^<>\s]+>")


# --- Proyectos compartidos -----------------------------------------------------------------
#
# Un proyecto es una fila de `categorias`. Por defecto es personal; su dueño puede compartirlo con
# compañeros de SU despacho (rol «colabora» o «observa»). Los miembros ven las tareas del proyecto,
# y los que colaboran las crean, editan y completan; la tabla de miembros nunca cruza de despacho:
# `_rol_en_proyecto` exige el mismo tenant que el dueño cada vez que se consulta.

ESTADOS_PROYECTO = ("activo", "en_pausa", "completado", "archivado")
ROLES_PROYECTO = ("colabora", "observa")
MAX_MIEMBROS_PROYECTO = 50


# --- Proyectos, fase 3: notas compartidas, actividad, plantillas y datos del cliente -----------

MAX_NOTAS_PROYECTO = 500
MAX_PLANTILLAS_TENANT = 50


# --- Perfil de usuario (Fase G1: espacio de ajustes de usuario) -------------
# Mismo patrón singleton usuario_id PRIMARY KEY que ia_preferencias -- ver
# CREATE TABLE usuario_perfil en init_db(). El avatar es un BLOB en la
# propia fila (igual que correo_adjuntos.contenido), sin filesystem aparte.


TEMAS_VALIDOS = ("system", "light", "dark")
DENSIDADES_VALIDAS = ("normal", "compacta")


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


# ---- Conversaciones del Asistente IA -----------------------------------------
#
# Todo el código del asistente (y la app móvil, vía la API) sigue trabajando
# con "la conversación del usuario": listar_mensajes_ia / agregar_mensaje_ia /
# vaciar_mensajes_ia operan sobre la conversación ACTIVA, así que añadir
# varias conversaciones no cambia ninguna de esas llamadas.

IA_MAX_CONVERSACIONES_POR_USUARIO = 50
IA_TITULO_MAX_CARACTERES = 60


IA_MAX_ATAJOS = 20


_FICHAJE_TRANSICIONES_VALIDAS = {
    "salida": {"entrada"},
    "entrada": {"pausa_inicio", "salida"},
    "pausa_inicio": {"pausa_fin", "salida"},
    "pausa_fin": {"pausa_inicio", "salida"},
}


# --- Dominios: partes de este módulo (app/db_*.py). Se cargan al final porque usan `db.<nombre>` para todo lo demás; las reexportamos para que `db.<nombre>` siga existiendo.
from .db_plataforma import (  # noqa: E402,F401
    crear_usuario,
    obtener_usuario_por_email,
    obtener_usuario,
    onboarding_visible,
    ocultar_onboarding,
    idioma_usuario,
    cambiar_idioma_usuario,
    listar_usuarios,
    es_admin,
    hacer_admin,
    es_gestor_fichajes,
    asignar_gestor_fichajes,
    es_supervisor_tenant,
    asignar_supervisor_tenant,
    usuario_pertenece_a_tenant,
    fijar_fichaje_geolocalizacion,
    quitar_admin,
    verificar_credenciales,
    usuario_por_kratos_id,
    vincular_kratos_id,
    crear_usuario_vinculado_a_kratos,
    crear_tenant,
    listar_tenants,
    listar_tenants_con_conteo,
    resumen_equipos_tenants,
    resumen_usuarios_backoffice,
    resumen_plataforma,
    listar_suscripciones_tenants,
    renombrar_tenant,
    alternar_activo_tenant,
    ultima_actividad_tenant,
    guardar_stripe_account_id,
    marcar_stripe_onboarding_completado,
    registrar_pago_vencimiento,
    pago_de_vencimiento,
    crear_plan_guilda,
    listar_planes_guilda,
    obtener_plan_guilda,
    editar_plan_guilda,
    guardar_stripe_price_id_plan,
    crear_extra_guilda,
    listar_extras_guilda,
    obtener_extra_guilda,
    guardar_stripe_price_id_extra,
    editar_extra_guilda,
    limpiar_stripe_price_id_plan,
    limpiar_stripe_price_id_extra,
    asignar_plan_tenant,
    guardar_stripe_customer_id,
    guardar_stripe_subscription_id,
    actualizar_suscripcion_estado,
    tenant_por_stripe_customer_id,
    activar_extra_tenant,
    listar_extras_activos_tenant,
    desactivar_extra_tenant,
    contar_fichajes_tenant,
    borrar_tenant,
    desasignar_tenant,
    obtener_tenant,
    ocultar_herramienta,
    mostrar_herramienta,
    herramientas_ocultas_de_tenant,
    herramientas_ocultas_de_tenants,
    adopcion_herramientas,
    guardar_facturascripts,
    guardar_facturascripts_api_key,
    guardar_documenso_api_key,
    guardar_paperless,
    guardar_baserow,
    guardar_calcom,
    guardar_calcom_api_key,
    guardar_listmonk,
    guardar_stalwart,
    guardar_ntfy,
    guardar_umami,
    obtener_tenant_por_nombre,
    asignar_tenant,
    guardar_datos_tenant,
    zona_horaria_valida,
    zona_horaria_tenant,
    guardar_zona_horaria_tenant,
    registrar_acceso,
    tenant_de_usuario,
    usuarios_de_tenant,
    usuario_local_id,
    _hash_token,
    crear_token_api,
    usuario_id_por_token,
    autenticar_token,
    autenticar_token_completo,
    origen_cors_conocido,
    registrar_uso_token,
    uso_de_token,
    listar_todos_los_tokens_api,
    revocar_token_api_cualquiera,
    id_de_token,
    revocar_token_api,
    listar_tokens_api,
    revocar_token_api_por_id,
    crear_lead_contacto,
    listar_leads_contacto,
    marcar_lead_atendido,
    registrar_dispositivo_push,
    eliminar_dispositivo_push,
    tokens_push_de_usuario,
    eliminar_tokens_push,
    crear_notificacion,
    listar_notificaciones,
    contar_notificaciones_no_leidas,
    marcar_notificaciones_leidas,
    eliminar_notificacion,
    eliminar_todas_notificaciones,
    _crear_triggers_cambios,
    _purgar_cambios,
    cursor_cambios_actual,
    _cursor_minimo_cero,
    cambios_desde,
    idempotencia_reservar,
    idempotencia_guardar,
    idempotencia_liberar,
    validar_referencia_externa,
    id_por_referencia_externa,
    fijar_referencia_externa,
    mcp_registrar_llamada,
    mcp_resumen,
    mcp_auditoria_listar,
    registrar_auditoria,
    listar_auditoria_backoffice,
    exportar_datos_tenant,
    crear_webhook,
    actualizar_webhook,
    rotar_secreto_webhook,
    cola_webhook_obtener,
    obtener_webhook,
    listar_webhooks,
    listar_todos_los_webhooks,
    borrar_webhook,
    webhooks_para_evento,
    cola_webhook_encolar,
    cola_webhook_reclamar,
    cola_webhook_cerrar,
    cola_webhook_reprogramar,
    cola_webhook_recuperar_atascados,
    cola_webhook_purgar,
    cola_webhook_resumen,
    cola_webhook_de,
    cola_webhook_reintentar,
    registrar_entrega_webhook,
    entregas_de_webhook,
    entregas_de_webhooks,
    papelera,
    vaciar_papelera_antigua,
    obtener_perfil_usuario,
    guardar_perfil_usuario,
    guardar_apariencia_usuario,
    apariencia_usuario,
    _hora_valida,
    en_horas_de_silencio,
    notificacion_tipo_activa,
    guardar_avatar_usuario,
    eliminar_avatar_usuario,
    crear_adjunto_ia,
    obtener_adjunto_ia,
    usuarios_con_resumen_semanal_activo, perfiles_con_resumen_diario, marcar_resumen_diario_entregado,
    nombre_mostrado_usuario,
)
from .db_tareas import (  # noqa: E402,F401
    crear_categoria,
    listar_categorias,
    _categoria_id_propio,
    mover_categoria,
    reordenar_categorias,
    alternar_favorito_categoria,
    obtener_categoria,
    renombrar_categoria,
    eliminar_categoria,
    restaurar_categoria,
    eliminar_categoria_definitivamente,
    contar_entradas_hoy_por_usuario,
    crear_tarea,
    _reindexar_tarea,
    _quitar_tarea_del_indice,
    importar_tarea,
    hubo_actividad_reciente,
    _segundos_pausados_cerrados,
    pausar_tarea,
    reanudar_tarea,
    finalizar_tarea,
    _emitir_evento,
    _emitir_evento_tarea_finalizada,
    tareas_activas,
    obtener_tarea,
    editar_tarea,
    editar_tiempos_tarea,
    eliminar_tarea,
    restaurar_tarea,
    eliminar_tarea_definitivamente,
    estimacion_valida,
    registrar_actividad_tarea,
    crear_tarea_outlook,
    _cliente_fiscal_id_del_tenant,
    _vencimiento_id_del_tenant,
    tareas_de_vencimiento,
    resumen_tareas_de_vencimiento,
    completar_tareas_de_vencimiento,
    _mensaje_correo_id_propio,
    _companero_del_tenant,
    listar_companeros_tenant,
    crear_tarea_recurrente,
    crear_regla_por_vencimiento,
    listar_reglas_por_vencimiento,
    alternar_regla_por_vencimiento,
    eliminar_regla_por_vencimiento,
    generar_tareas_por_vencimiento,
    listar_tareas_recurrentes,
    alternar_activa_tarea_recurrente,
    eliminar_tarea_recurrente,
    _existe_tarea_generada_este_periodo,
    generar_tareas_recurrentes,
    listar_tareas_outlook,
    obtener_tarea_outlook,
    obtener_tarea_outlook_visible,
    obtener_tarea_outlook_por_entry_id,
    upsert_tarea_outlook_por_entry_id,
    editar_tarea_outlook,
    completar_tarea_outlook,
    cambiar_estado_tarea_outlook,
    _es_colaborador,
    rol_en_tarea,
    puede_trabajar_tarea,
    puede_editar_tarea,
    compartir_tarea_outlook,
    dejar_de_compartir_tarea_outlook,
    participantes_de_tarea,
    participantes_de_tareas,
    personas_de_tarea,
    detectar_menciones,
    comentar_tarea_outlook,
    listar_comentarios_tarea,
    eliminar_comentario_tarea,
    contar_comentarios_tareas,
    parsear_items_plantilla,
    items_a_texto,
    crear_plantilla_tareas,
    _guardar_items_plantilla,
    editar_plantilla_tareas,
    eliminar_plantilla_tareas,
    listar_plantillas_tareas,
    obtener_plantilla_tareas,
    aplicar_plantilla_tareas,
    _depende_transitivamente,
    anadir_dependencia_tarea,
    quitar_dependencia_tarea,
    _asunto_tarea,
    dependencias_de_tarea,
    bloqueos_de_tareas,
    tarea_bloqueada,
    tareas_desbloqueadas_por,
    _canales_validos,
    anadir_recordatorio_tarea,
    recordatorio_relativo,
    listar_recordatorios_tarea,
    eliminar_recordatorio_tarea,
    posponer_recordatorio_tarea,
    recordatorios_de_tarea_pendientes_de_aviso,
    reservar_recordatorio_tarea,
    marcar_recordatorio_tarea_enviado,
    carga_equipo,
    _celda_vacia,
    _sumar_a_celda,
    carga_semanal,
    reasignar_tarea_outlook,
    filtros_vista_validos,
    crear_vista_tareas,
    listar_vistas_tareas,
    eliminar_vista_tareas,
    accion_en_lote,
    actividad_de_tarea,
    tiempo_equipo_tarea,
    asignar_tarea_outlook,
    iniciar_cronometro_tarea_outlook,
    cronometros_de_tareas_outlook,
    listar_checklist,
    resumen_checklist,
    _recalcular_porcentaje_checklist,
    agregar_item_checklist,
    alternar_item_checklist,
    eliminar_item_checklist,
    tareas_para_hoy,
    contar_mi_dia,
    eliminar_tarea_outlook,
    restaurar_tarea_outlook,
    eliminar_tarea_outlook_definitivamente,
    listar_categorias_outlook,
)
from .db_historial import (  # noqa: E402,F401
    historial,
    resumen_historial,
    estadisticas_por_categoria,
    estadisticas_por_dia,
    estadisticas_equipo_por_usuario,
    tiempo_medio_resolucion_vencimientos,
    crear_plantilla,
    listar_plantillas,
    eliminar_plantilla,
)
from .db_notas import (  # noqa: E402,F401
    crear_nota,
    _emitir_evento_nota_creada,
    _reindexar_nota,
    importar_nota,
    obtener_nota,
    rol_en_nota,
    obtener_nota_visible,
    compartir_nota,
    dejar_de_compartir_nota,
    participantes_de_nota,
    contar_participantes_notas,
    _titulo_nota,
    _tarea_outlook_id_propia,
    editar_nota,
    alternar_fijada_nota,
    listar_notas_fijadas,
    listar_notas,
    contar_notas,
    agregar_adjunto_nota,
    listar_adjuntos_nota,
    contar_adjuntos_notas,
    obtener_adjunto_nota,
    eliminar_adjunto_nota,
    eliminar_nota,
    _quitar_nota_del_indice,
    restaurar_nota,
    eliminar_nota_definitivamente,
)
from .db_fiscal import (  # noqa: E402,F401
    serializar_modelos_fiscales,
    modelos_fiscales_de_cliente,
    perfil_fiscal_de_cliente,
    vencimientos_por_cliente,
    crear_cliente_fiscal,
    _reindexar_cliente_fiscal,
    _quitar_cliente_fiscal_del_indice,
    listar_clientes_fiscales,
    paises_clientes_fiscales,
    obtener_cliente_fiscal,
    editar_cliente_fiscal,
    eliminar_cliente_fiscal,
    restaurar_cliente_fiscal,
    eliminar_cliente_fiscal_definitivamente,
    crear_vencimiento_fiscal,
    _reindexar_vencimiento_fiscal,
    _quitar_vencimiento_fiscal_del_indice,
    listar_vencimientos_fiscales,
    contar_vencimientos_fiscales,
    vencimiento_fiscal_existente,
    tenant_id_de_vencimiento_fiscal,
    obtener_vencimiento_fiscal,
    editar_vencimiento_fiscal,
    marcar_presentado_vencimiento_fiscal,
    eliminar_vencimiento_fiscal,
    restaurar_vencimiento_fiscal,
    eliminar_vencimiento_fiscal_definitivamente,
    marcar_recordatorio_vencimiento_fiscal_enviado,
    vencimientos_fiscales_proximos,
    papelera_fiscal,
    _existe_vencimiento_fiscal,
    generar_vencimientos_automaticos,
    generar_vencimientos_de_cliente,
    cerrar_tareas_al_presentar,
    sanear_vencimientos_fuera_plazo,
    _cliente_duplicado,
    obtener_cliente_fiscal_por_id,
    clientes_fiscales_por_email,
    ultimo_acceso_solicitado_en,
    crear_acceso_cliente_fiscal,
    consumir_acceso_cliente_fiscal,
    crear_acceso_facturacion,
    consumir_acceso_facturacion,
    subir_documento_vencimiento,
    contenido_documento_vencimiento,
    listar_documentos_vencimiento,
    eliminar_documentos_vencimiento_por_origen,
    _lista_de_dias,
    obtener_config_recordatorios,
    guardar_config_recordatorios,
    vencimientos_sin_documentos_del_cliente,
    marcar_vencimiento_escalado,
    destinatarios_aviso_vencimiento,
    vencimientos_para_recordatorio_portal,
    marcar_recordatorio_portal_enviado,
    obtener_documento_vencimiento,
    crear_mensaje_vencimiento,
    listar_mensajes_vencimiento,
    marcar_mensajes_leidos,
    crear_solicitud_acceso_portal,
    listar_solicitudes_acceso_portal,
    marcar_solicitud_atendida,
    listar_todos_los_clientes_fiscales,
    _nombre_de_archivo_seguro,
    archivar_documento_cliente,
    registrar_acceso_cliente,
    listar_accesos_cliente,
    purgar_accesos_antiguos,
    listar_documentos_cliente,
    obtener_documento_cliente,
    eliminar_documento_cliente,
    contar_documentos_cliente,
    listar_reglas_correo,
    eliminar_regla_correo,
    reglas_correo_aplicables,
    categoria_id_por_remitente_correo,
)
from .db_correo import (  # noqa: E402,F401
    _dueno_del_mensaje,
    rol_en_correo,
    _auditar_correo_equipo,
    registrar_lectura_correo_equipo,
    historial_correo_equipo,
    asignar_correo,
    compartir_correo,
    dejar_de_compartir_correo,
    cambiar_estado_correo_equipo,
    estado_correo_equipo,
    obtener_correo_equipo,
    listar_correo_equipo,
    contar_correo_asignado_abierto,
    anadir_nota_interna_correo,
    listar_notas_internas_correo,
    eliminar_nota_interna_correo,
    crear_cuenta_correo,
    listar_cuentas_correo,
    obtener_cuenta_correo,
    editar_cuenta_correo,
    eliminar_cuenta_correo,
    guardar_firma_correo,
    guardar_carpetas_correo,
    listar_carpetas_correo,
    renombrar_carpeta_correo,
    eliminar_carpeta_correo,
    crear_categoria_correo,
    crear_identidad_correo,
    listar_identidades_correo,
    obtener_identidad_correo,
    eliminar_identidad_correo,
    listar_categorias_correo,
    eliminar_categoria_correo,
    crear_plantilla_correo,
    editar_plantilla_correo,
    listar_plantillas_correo,
    obtener_plantilla_correo,
    eliminar_plantilla_correo,
    guardar_borrador_correo,
    listar_borradores_correo,
    contar_borradores_correo,
    obtener_borrador_correo,
    listar_adjuntos_borrador,
    adjuntos_borrador_para_enviar,
    copiar_adjuntos_envio_a_borrador,
    eliminar_borrador_correo,
    asignar_categoria_correo,
    cliente_fiscal_id_por_email,
    mensajes_correo_sin_cliente,
    asignar_cliente_fiscal_correo,
    listar_correos_de_cliente_fiscal,
    confiar_en_remitente,
    listar_remitentes_confiables,
    eliminar_remitente_confiable,
    es_remitente_confiable,
    crear_regla_categoria_correo,
    listar_reglas_categoria_correo,
    eliminar_regla_categoria_correo,
    crear_regla_correo,
    registrar_destinatario_reciente,
    buscar_destinatarios_recientes,
    encolar_envio_correo,
    seguimiento_dias_valido,
    crear_seguimiento_correo,
    listar_seguimientos_correo,
    seguimiento_de_mensaje,
    cancelar_seguimiento_correo,
    seguimientos_en_espera,
    cerrar_seguimiento_correo,
    respuesta_a_mensaje,
    mensaje_local_por_message_id,
    obtener_envio_correo,
    listar_envios_programados,
    contar_envios_programados,
    cancelar_envio_correo,
    envios_correo_vencidos,
    reclamar_envio_correo,
    adjuntos_envio_correo,
    cerrar_envio_correo,
    rescatar_envios_atascados,
    purgar_envios_correo_antiguos,
    _obtener_o_crear,
    obtener_preferencias_correo,
    guardar_preferencias_correo,
    marcar_sincronizada_cuenta_correo,
    marcar_error_sincronizacion_cuenta_correo,
    registrar_latido,
    registrar_error_servidor,
    resumen_errores_servidor,
    listar_latidos,
    alerta_salud_enviada,
    marcar_alerta_salud,
    estado_cuentas_correo_global,
    contar_entregas_webhook_fallidas,
    contar_envios_correo_fallidos,
    contar_envios_correo_atascados,
    listar_todas_las_cuentas_correo,
    uids_existentes_correo,
    obtener_ultimo_uid_sincronizado,
    actualizar_ultimo_uid_sincronizado,
    obtener_cuenta_correo_por_id,
    _asegurar_fts_correo,
    _rellenar_texto_de_correos_html,
    reconstruir_indice_correo,
    fts_correo_disponible,
    consulta_fts,
    _crear_vista_participantes_todos,
    estado_carpeta_correo,
    guardar_estado_carpeta_correo,
    vaciar_carpeta_correo,
    encolar_operacion_correo,
    operaciones_pendientes_correo,
    operaciones_por_mensaje_correo,
    cerrar_operacion_correo,
    fallar_operacion_correo,
    contar_operaciones_correo_con_error,
    operaciones_correo_con_error,
    reintentar_operaciones_correo,
    descartar_operaciones_correo,
    mensaje_correo_por_uid,
    estados_mensajes_correo,
    aplicar_estados_servidor_correo,
    eliminar_mensajes_correo_por_uid,
    normalizar_asunto,
    _direccion_simple,
    _clave_hilo_por_asunto,
    calcular_hilo_clave,
    _rellenar_hilos_correo,
    contar_hilos_correo,
    mensajes_del_hilo_correo,
    guardar_mensaje_correo,
    _like_literal,
    listar_mensajes_correo,
    obtener_mensaje_correo,
    mensaje_correo_pertenece_a_usuario,
    guardar_adjuntos_correo,
    listar_adjuntos_correo,
    obtener_adjunto_correo,
    adjunto_correo_pertenece_a_usuario,
    marcar_leido_mensaje_correo,
    destacar_mensaje_correo,
    posponer_mensaje_correo,
    eliminar_mensaje_correo,
    contar_no_leidos_correo,
    contar_no_leidos_por_cuenta_y_carpeta,
    contar_no_leidos_total_correo,
)
from .db_proyectos import (  # noqa: E402,F401
    _rol_en_proyecto,
    rol_en_proyecto,
    obtener_proyecto,
    listar_proyectos_compartidos_conmigo,
    listar_proyectos_usables,
    miembros_de_proyecto,
    compartir_proyecto,
    quitar_miembro_proyecto,
    actualizar_proyecto,
    listar_secciones,
    _puede_organizar_proyecto,
    crear_seccion,
    _categoria_de_seccion,
    renombrar_seccion,
    eliminar_seccion,
    mover_seccion,
    asignar_seccion_tarea,
    mover_tarea_en_proyecto,
    cambiar_fecha_tarea_proyecto,
    crear_tarea_en_proyecto,
    tareas_de_proyecto,
    resumen_proyecto,
    crear_nota_proyecto,
    listar_notas_proyecto,
    fijar_nota_proyecto,
    eliminar_nota_proyecto,
    actividad_proyecto,
    _estructura_valida,
    aplicar_plantilla_proyecto,
    guardar_plantilla_desde_proyecto,
    listar_plantillas_proyecto,
    eliminar_plantilla_proyecto,
    correos_de_cliente_para,
)
from .db_ia import (  # noqa: E402,F401
    obtener_preferencias_ia,
    guardar_preferencias_ia,
    obtener_preferencias_ia_local,
    guardar_preferencias_ia_local,
    _titulo_desde_texto,
    _migrar_conversaciones_ia,
    _crear_conversacion_ia,
    conversacion_ia_activa_id,
    listar_conversaciones_ia,
    crear_conversacion_ia,
    activar_conversacion_ia,
    renombrar_conversacion_ia,
    eliminar_conversacion_ia,
    listar_mensajes_ia,
    agregar_mensaje_ia,
    listar_atajos_ia,
    crear_atajo_ia,
    eliminar_atajo_ia,
    vaciar_mensajes_ia,
)
from .db_tiquets import (  # noqa: E402,F401
    crear_tiquet,
    listar_tiquets,
    obtener_tiquet,
    editar_tiquet,
    cambiar_estado_tiquet,
    eliminar_tiquet,
    asignar_tiquet,
    guardar_adjunto_tiquet,
    listar_adjuntos_tiquet,
    obtener_adjunto_tiquet,
    eliminar_adjunto_tiquet,
)
from .db_fichaje import (  # noqa: E402,F401
    obtener_fichaje_datos,
    guardar_fichaje_datos,
    fichaje_datos_completos,
    fichar,
    verificar_integridad_fichajes,
    estado_actual_fichaje,
    jornadas_abiertas_sin_aviso,
    registrar_aviso_fichaje,
    entrada_abierta_fichaje,
    ultimo_fichaje,
    listar_fichajes,
    fichajes_tenant_crudos,
    resumen_fichajes_tenant,
)

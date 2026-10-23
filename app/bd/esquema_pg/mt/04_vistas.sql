-- GENERADO por scripts/migracion/generar_esquema_pg.py a partir del esquema de SQLite. No editar a mano.
CREATE OR REPLACE VIEW tareas_participantes_todos AS
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
            WHERE uo.tenant_id IS NOT NULL AND us.id != t.usuario_id AND us.id != c.usuario_id;

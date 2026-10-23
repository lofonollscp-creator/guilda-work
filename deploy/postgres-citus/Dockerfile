# PostgreSQL 17 + Citus 14 + pgvector, para el ENSAYO de la migración (fase 1 de
# docs/plan-migracion-postgresql-citus.md). Las extensiones unaccent y pg_trgm ya
# vienen en el paquete contrib de la imagen base.
FROM citusdata/citus:14.2.0-pg17

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-17-pgvector \
 && rm -rf /var/lib/apt/lists/*

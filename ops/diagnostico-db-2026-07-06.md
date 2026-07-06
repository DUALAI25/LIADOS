---
title: "Permisos DB y bug db_connection — sesión 005"
date: 2026-07-06
type: troubleshooting
tags: [liados, db, postgresql, psycopg2]
---

# Liados — Permisos DB y bug db_connection (2026-07-06)

## Bugs encontrados y resueltos

### 1. `db_connection.py` — psycopg2 2.9+ hace `__exit__` read-only

**Síntoma**: `AttributeError: 'psycopg2.extensions.connection' object attribute '__exit__' is read-only`

**Causa**: el parche original (commit `886a1eb` o `f6a8603`, "C-3 fix") intentaba monkey-patch `conn.__exit__` para forzar `conn.close()` al salir del context manager. Esto funcionaba con `psycopg2<2.9` pero el upgrade a 2.9.12 hace ese atributo read-only.

**Fix**: usar un wrapper `_ConnCtx` con `__enter__/__exit__` que propaga el context manager y cierra la conexión. Mantiene API exacta: `with conn as c:` sigue funcionando sin cambios en los callers.

**Commit**: incluido en el commit de esta sesión.

### 2. `category_mapping` — usuario `desliado` sin permisos

**Síntoma**: `permission denied for table category_mapping` en `gmail_collector.py` → `db_writer.py:25` (subquery `SELECT cm.category_id FROM category_mapping cm`).

**Causa**: tabla creada por `postgres` (owner) pero sin `GRANT` para `desliado`. Solo `categories`, `vendors`, `invoices`, `lastapp_*`, `agent_logs`, `gmail_non_invoices`, `sync_control`, `user_overrides`, `orphan_payments` tienen permisos. Faltaban `category_mapping` y `_pre_limpieza_20260622` (la segunda es backup, no se usa).

**Fix** (comando, no código):
```sql
GRANT ALL PRIVILEGES ON TABLE category_mapping TO desliado;
```

Aplicado en VPS el 2026-07-06 09:15. Verificado con diag_perms.py.

## Resultado

- ✅ `gmail_collector --account principal` ejecuta limpio (0 mensajes nuevos en 7d, los anteriores ya estaban procesados)
- ✅ `run_all --skip-gmail` ejecuta `lastapp_sync` OK (10s)
- ✅ Dashboard health `200 ok`, version `5.1.0`, pool `{used:0, free:2}`
- ✅ Tests E2E: `OK -- todos los tests pasan`

## Pendiente (acción jefe)

- Reautorizar cuenta Gmail `secundaria` (mismo procedimiento que `principal`)
- Volver a ejecutar `gmail_collector --account secundaria` después

## Lecciones

1. **Permisos DB**: al crear tablas nuevas con `postgres`, hay que acordarse de hacer `GRANT` a `desliado`. **Acción preventiva**: crear una función `ensure_user_grants(table_name)` en `db_connection.py` que se ejecute al arranque y dé los permisos que falten. O documentar el patrón en `.env.example`.

2. **psycopg2 monkey-patching**: nunca asumas que puedes monkey-patch atributos built-in de una librería externa. Usar wrappers.

3. **Diagnóstico empírico primero**: 6 callbacks OAuth rechazados enseñaron que el bucle no es la respuesta. Aquí, el `db_writer.py` fallaba silenciosamente (1 error, 0 procesadas) y no era obvio a primera vista. El script de diagnóstico con `pg_tables` + `has_table_privilege` reveló los 2 problemas en 2 minutos.

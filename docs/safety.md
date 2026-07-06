# Safety Policy — Liados

## Purpose

This denylist defines paths and operations that **require explicit human approval** before any Loop Engineering L2 auto-fix or OpenCode agent can touch them. L1 (report-only) agents can read freely; L2+ agents must stop and request permission.

## Denylist — paths that require human review

| Path | Reason | Approver |
|------|--------|----------|
| `.env` / `.env.*` | DB credentials, OAuth client secrets, API keys | Antonio |
| `agente/credentials/*.json` | Gmail OAuth tokens, refresh tokens, MCP tokens | Antonio |
| `pgdata/` | Live Postgres data directory | Antonio |
| `data/invoices/raw/` | Ingested invoice PDFs (628 files, 92 MB) | Antonio |
| `data/invoices/processed/` | Processed invoice archive | Antonio |
| `minio_data/` | Object storage buckets | Antonio |
| `backups/db-*.sql.gz` | Database backups (encrypted at rest) | Antonio |
| `*.key` / `*.pem` / `*.p12` | TLS / signing material | Antonio |
| `docker-compose.yml` | Production container orchestration | Antonio |
| `ops/` | Cron wrappers, systemd units | Antonio |
| `/etc/cron.d/liados-*` | Production cron schedules | Antonio |
| `/etc/systemd/system/liados-*.service` | Production systemd units | Antonio |

## Operations that require human approval

- `git push` to `origin/main` (private repo, no force-push ever)
- `git push --force` to any branch
- `git reset --hard` on any branch
- `pg_dump` / `pg_restore` on production DB
- `systemctl restart liados-dashboard`
- `systemctl restart liados-gmail-collector`
- `crontab -e` changes
- `python3 -m agente.scripts.gmail_auth --force` (re-OAuth flow)
- Database migrations (`agente/scripts/migrate*.py` not yet reviewed)
- Drop / truncate on any `lastapp_*` or `invoices` table

## Allow-list (safe for L2 auto-fix)

- Source code under `agente/`, `dashboard/`, `scripts/`, `tests/`
- Documentation: `README.md`, `CONTRIBUTING.md`, `DEMO_MAÑANA.md`
- Loop Engineering files: `STATE.md`, `LOOP.md`, `AGENTS.md`, `opencode.json`
- `docs/` (this file + future runbooks)
- Non-secret templates: `.env.example`, `*.sql.example`

## Verification protocol for L2+ changes

1. Create a `git worktree` under `/tmp/worktree-<branch>/`
2. Implement only the requested minimal fix
3. Run `tests/run_e2e.sh` — must show 62/62 PASS (or more)
4. Dispatch `verifier` subagent to review the diff
5. Wait for `APPROVE` from verifier before proposing merge
6. **Never** push without explicit human `git push` command
7. **Never** merge directly to `main` — open PR for review

## Escalation

If a fix touches any denylisted path or requires any operation in the
approval list, stop immediately, summarize the request in `STATE.md`
under "Human action required", and wait for Antonio's input.

Last updated: 2026-07-06 (Loop Engineering L1 triage)

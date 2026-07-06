# Cron de monitor Gmail — instalar manualmente

```bash
# Subir a /etc/cron.d/
sudo cp ops/liados-gmail-age.cron /etc/cron.d/liados-gmail-age
sudo chmod 644 /etc/cron.d/liados-gmail-age

# Verificar
ls -la /etc/cron.d/liados-gmail-age
```

## Qué hace

- Corre diario a las 08:00 AM
- Llama a `check_gmail_token_age.py` con flag `--quiet` (solo warnings)
- Log: `/var/log/liados-gmail-age.log`
- Exit code 0 = OK, 1 = hay cuentas que requieren acción

## Por qué este horario

- 06:00 AM: `run_all.py` ejecuta el sync Gmail principal
- 08:00 AM: monitor de edad (2 horas después, ya pasó el sync)
- Si el sync falló a las 06:00 por token muerto, el monitor confirma el problema a las 08:00 y avisa por Telegram

## Relación con check_gmail_health.py

| Script | Qué hace | Cuándo | Acción |
|---|---|---|---|
| `check_gmail_health.py` | Prueba refresh de token | 5:55 AM diario | Purgar si INVALID_GRANT, alerta Telegram |
| `check_gmail_token_age.py` | Calcula edad del token | 8:00 AM diario | Avisa 2 días antes de morir |

Ambos se complementan: health detecta tokens que ya murieron, age detecta tokens que están por morir.

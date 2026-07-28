# Runbook: Dominio fijo para Liados (Named Tunnel)

> **Tiempo estimado**: 30 minutos
> **Lo que consigues**: una URL estable tipo `https://liados.tu-dominio.com` que no cambia con cada reinicio del VPS.

## Por qué

El dashboard actual usa **cloudflared quick-tunnel**, que genera URLs aleatorias tipo `https://random-name.trycloudflare.com` que cambian con cada reinicio.

Con un **named tunnel** + tu dominio en Cloudflare, la URL queda fija para siempre.

## Pasos resumidos

1. Crear cuenta en Cloudflare (si no tienes) y añadir tu dominio
2. Apuntar dominio a Cloudflare (cambiar nameservers en tu proveedor)
3. Crear named tunnel en Cloudflare One (red Networks > Tunnels) — obtienes un TOKEN
4. Configurar routing: subdomain `liados` -> service `https://localhost:9121`
5. En el VPS:
   - Instalar cloudflared si no esta
   - Guardar token en `/etc/cloudflared/token` (chmod 600)
   - Crear `/etc/cloudflared/config.yml` con tunnel ID + ingress
   - `cloudflared service install`
   - `systemctl enable --now cloudflared`
6. Verificar: `curl https://liados.tu-dominio.com/api/health`

## Comandos clave VPS

```bash
ssh root@100.87.20.4

# Ver IP del VPS
curl ifconfig.me

# Crear config
cat > /etc/cloudflared/config.yml << 'EOF'
tunnel: liados-prod
credentials-file: /etc/cloudflared/token
ingress:
  - hostname: liados.tu-dominio.com
    service: https://localhost:9121
    originRequest:
      noTLSVerify: true
  - service: http_status:404
EOF

# Instalar servicio
useradd -r -s /usr/sbin/nologin cloudflared
chown cloudflared:cloudflared /etc/cloudflared/token /etc/cloudflared/config.yml
cloudflared service install
systemctl enable --now cloudflared

# Desactivar quick-tunnel (una vez verificado)
systemctl --user stop liados-tunnel.service
systemctl --user disable liados-tunnel.service
```

## Rollback

Si falla:
- `systemctl stop cloudflared` y volver al quick-tunnel: `systemctl --user start liados-tunnel.service`
- Logs: `journalctl -u cloudflared -n 50 --no-pager`

## Resultado

- **Antes**: URL aleatoria que cambia con reinicios
- **Después**: `https://liados.tu-dominio.com` estable
- **Coste**: $0 (Cloudflare free tier)
- **Tiempo**: 30 min

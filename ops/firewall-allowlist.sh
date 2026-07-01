#!/bin/bash
# firewall-allowlist.sh — Configura iptables para cerrar puertos a internet
# Uso: bash firewall-allowlist.sh <PUERTO> [--persist]
set -e
PORT="${1:?puerto requerido}"
shift
PERSIST=false
[ "$1" = "--persist" ] && PERSIST=true

CIRD_TAILSCALE="100.64.0.0/10"

# Limpiar reglas anteriores
iptables -D INPUT -p tcp --dport "$PORT" -s "$CIRD_TAILSCALE" -j ACCEPT 2>/dev/null || true
iptables -D INPUT -p tcp --dport "$PORT" -s 127.0.0.1 -j ACCEPT 2>/dev/null || true
iptables -D INPUT -p tcp --dport "$PORT" -j DROP 2>/dev/null || true

# Aplicar reglas (orden importa)
iptables -A INPUT -p tcp --dport "$PORT" -s "$CIRD_TAILSCALE" -j ACCEPT -m comment --comment "liados-tailscale"
iptables -A INPUT -p tcp --dport "$PORT" -s 127.0.0.1 -j ACCEPT -m comment --comment "liados-loopback"
iptables -A INPUT -p tcp --dport "$PORT" -j DROP -m comment --comment "liados-deny-all"

if [ "$PERSIST" = true ]; then
    mkdir -p /etc/iptables
    iptables-save > /etc/iptables/rules.v4
    cat > /etc/systemd/system/iptables-restore.service << 'UNIT'
[Unit]
Description=Restore iptables firewall rules
Before=network-pre.target
DefaultDependencies=no

[Service]
Type=oneshot
ExecStart=/sbin/iptables-restore /etc/iptables/rules.v4
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
    systemctl enable iptables-restore.service 2>&1
fi

echo "OK: puerto $PORT firewall-allowlist aplicado"
iptables -L INPUT -n | grep "dpt:$PORT"

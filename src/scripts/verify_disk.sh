#!/usr/bin/env bash
# Confirma que o ponto de montagem voltou a ter folga.
# Uso: verify_disk.sh <ponto_de_montagem> [limite_pct]
# Saída: 0 saudável · 1 ainda acima do limite · 3 argumento ausente
set -uo pipefail
MOUNT="${1:-}"; LIMITE="${2:-85}"
[ -n "$MOUNT" ] || { echo "uso: $(basename "$0") <ponto_de_montagem> [limite_pct]" >&2; exit 3; }
USO=$(df --output=pcent "$MOUNT" 2>/dev/null | tail -1 | tr -dc '0-9')
[ -n "${USO:-}" ] || { echo "não foi possível ler o uso de $MOUNT" >&2; exit 3; }
echo "uso de $MOUNT: ${USO}% (limite ${LIMITE}%)"
[ "$USO" -lt "$LIMITE" ]

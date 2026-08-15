#!/usr/bin/env bash
# Confirma que o uso de CPU voltou a patamar normal.
# Uso: verify_cpu.sh [limite_pct]
# Saída: 0 saudável · 1 ainda acima do limite
set -uo pipefail
LIMITE="${1:-70}"
# Segunda amostra: a primeira do `top` é a média desde o boot e não reflete o momento.
OCIOSO=$(top -bn2 -d 1 | awk '/^%Cpu/ {gsub(/,/,".",$8); ocioso=$8} END {print ocioso}')
[ -n "${OCIOSO:-}" ] || { echo "não foi possível ler o uso de CPU" >&2; exit 3; }
USO=$(awk -v o="$OCIOSO" 'BEGIN {printf "%d", 100 - o}')
echo "uso de CPU: ${USO}% (limite ${LIMITE}%)"
[ "$USO" -lt "$LIMITE" ]

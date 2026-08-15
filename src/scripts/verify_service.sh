#!/usr/bin/env bash
# Confirma que o serviço está ativo. Consulta estado e não exige privilégio elevado.
# Uso: verify_service.sh <nome_do_servico>
# Saída: 0 ativo · 1 inativo · 3 argumento ausente
set -uo pipefail
SERVICO="${1:-}"
[ -n "$SERVICO" ] || { echo "uso: $(basename "$0") <nome_do_servico>" >&2; exit 3; }
ESTADO=$(systemctl is-active "$SERVICO" 2>/dev/null || true)
echo "$SERVICO: $ESTADO"
[ "$ESTADO" = "active" ]

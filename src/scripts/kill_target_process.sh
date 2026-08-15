#!/usr/bin/env bash
# Encerra o processo de maior consumo de CPU, restrito a uma lista de nomes autorizados.
#
# Uso: kill_target_process.sh <nome1,nome2,...>
# Saída: 0 encerrado · 1 não foi possível encerrar · 2 candidato fora da lista · 3 sem candidato
set -uo pipefail

PERMITIDOS="${1:-}"
[ -n "$PERMITIDOS" ] || { echo "uso: $(basename "$0") <lista_de_nomes>" >&2; exit 3; }

# O %CPU do `ps` é a média desde o início do processo: uma carga iniciada há trinta segundos pode
# não aparecer no topo, enquanto um processo antigo aparece. A segunda amostra do `top` reflete o
# intervalo corrente.
LINHA=$(top -bn2 -d 1 -o %CPU | awk '/^ *[0-9]+ / {print $1, $9, $12}' | tail -n +1 | sort -k2 -nr | head -1)
PID=$(echo "$LINHA" | awk '{print $1}')
PCPU=$(echo "$LINHA" | awk '{print $2}')
COMANDO=$(echo "$LINHA" | awk '{print $3}')

[ -n "${PID:-}" ] || { echo "nenhum processo candidato identificado" >&2; exit 3; }

if ! printf '%s' "$PERMITIDOS" | tr ',' '\n' | grep -qxF "$COMANDO"; then
  echo "candidato '$COMANDO' (pid $PID, ${PCPU}% de CPU) fora da lista autorizada: $PERMITIDOS" >&2
  exit 2
fi

echo "encerrando $COMANDO (pid $PID, ${PCPU}% de CPU)"
kill -TERM "$PID" 2>/dev/null

for _ in $(seq 1 10); do
  kill -0 "$PID" 2>/dev/null || { echo "encerrado com SIGTERM"; exit 0; }
  sleep 1
done

echo "SIGTERM ignorado; enviando SIGKILL"
kill -KILL "$PID" 2>/dev/null
sleep 1
if kill -0 "$PID" 2>/dev/null; then
  echo "não foi possível encerrar $COMANDO (pid $PID)" >&2
  exit 1
fi
echo "encerrado com SIGKILL"

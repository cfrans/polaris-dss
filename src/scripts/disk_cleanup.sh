#!/usr/bin/env bash
# Libera espaço no ponto de montagem informado.
#
# Uso: disk_cleanup.sh <ponto_de_montagem>
# Saída: 0 concluído · 2 caminho não permitido · 3 argumento ausente
set -uo pipefail

MOUNT="${1:-}"
[ -n "$MOUNT" ] || { echo "uso: $(basename "$0") <ponto_de_montagem>" >&2; exit 3; }

# Só atua em caminhos previstos. Encher ou esvaziar a raiz por engano inutiliza o host.
case "$MOUNT" in
  /mnt/polaris_test|/var/log) ;;
  *) echo "ponto de montagem não permitido: $MOUNT" >&2; exit 2 ;;
esac

[ -d "$MOUNT" ] || { echo "ponto de montagem inexistente: $MOUNT" >&2; exit 2; }

echo "uso antes: $(df -h --output=pcent "$MOUNT" | tail -1 | tr -d ' ')"

# Com o sistema de arquivos cheio, o logrotate não consegue escrever e falha justamente no cenário
# para o qual existe. Remover o comprimido mais antigo abre a folga de que ele precisa.
OLDEST=$(find "$MOUNT" -type f -name '*.gz' -printf '%T@ %p\n' 2>/dev/null | sort -n | head -1 | cut -d' ' -f2-)
if [ -n "${OLDEST:-}" ]; then
  echo "liberando folga: $OLDEST"
  rm -f -- "$OLDEST"
fi

if [ -x /usr/sbin/logrotate ] && [ -f /etc/logrotate.conf ]; then
  /usr/sbin/logrotate -f /etc/logrotate.conf 2>&1 | sed 's/^/logrotate: /' || true
fi

REMOVIDOS=$(find "$MOUNT" -type f -name '*.gz' -mtime +7 -print -delete 2>/dev/null | wc -l)
echo "arquivos comprimidos com mais de 7 dias removidos: $REMOVIDOS"

echo "uso depois: $(df -h --output=pcent "$MOUNT" | tail -1 | tr -d ' ')"

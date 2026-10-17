# R001 · Volume quase cheio

**Alerta:** `FS [/mnt/polaris_test]: Disk space is critically low` no Zabbix.
**Objetivo:** voltar o uso de `/mnt/polaris_test` para menos de 85% sem apagar dado necessário.

## 1. Conferir o uso

```bash
df -h /mnt/polaris_test
```

## 2. Ver o que ocupa o volume

```bash
ls -lh --time-style=long-iso /mnt/polaris_test
```

Só são candidatos a limpeza logs regulares de root: `*.log.gz` antigos (remover) ou `*.log`
fechados (comprimir). Qualquer outro arquivo fica como está.

## 3a. Remover log comprimido antigo

Listar os `.log.gz` com mais de sete dias:

```bash
find /mnt/polaris_test -maxdepth 1 -type f -name '*.log.gz' -mtime +7 -user root -ls
```

Remover somente o arquivo listado, pelo nome exato:

```bash
rm /mnt/polaris_test/polaris_r001_lab.log.gz
```

## 3b. Comprimir log fechado

Aplicável apenas a um `.log` que nenhum processo esteja escrevendo e quando o espaço livre do
passo 1 for maior que o tamanho do log (o gzip precisa de espaço temporário). Substitua o nome:

```bash
gzip /mnt/polaris_test/<arquivo>.log
```

O `gzip` só apaga o original depois de gravar o `.gz`.

## 4. Confirmar

```bash
df -h /mnt/polaris_test
```

O uso deve ficar abaixo de 85%. Em seguida, conferir no Zabbix que o problema fechou.

## Nota do experimento

O cenário de laboratório enche o volume a 96% com `enchimento.bin`, que é o defeito injetado:
**não remover**. O único candidato é `polaris_r001_lab.log.gz`, com oito dias. Como não há `.log`
e o espaço livre é menor que qualquer log útil, a compressão (3b) não se aplica nas rodadas da
coleta: todas usam a remoção (3a). A compressão foi validada num ensaio separado, fora da coleta.

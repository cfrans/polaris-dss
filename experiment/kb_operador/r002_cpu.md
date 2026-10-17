# R002 · CPU alta por processo

**Alerta:** `Polaris: High CPU utilization (over 90% for 2m)` no Zabbix.
**Objetivo:** identificar o processo que causa o consumo e encerrá-lo somente se for autorizado.

## 1. Listar os maiores consumidores

```bash
top -b -n 2 -d 1 -o %CPU -w 120 | awk '/^top -/{n++} n==2' | sed -n '1,12p'
```

Duas amostras com um segundo de intervalo; a segunda mostra o consumo atual, ordenado por CPU.
Não usar `ps ... %cpu` neste alvo: no container ele mostra média desde o início do processo e não
aponta o consumidor atual.

## 2. Encerrar o processo autorizado

Autorizados: `stress-ng`, `stress`, `stress-ng-cpu`. Só encerrar se o primeiro da lista for um
deles. Substitua pelo PID mostrado:

```bash
kill <PID>
```

`kill` sem opção envia SIGTERM. Se o processo continuar após dez segundos, repetir o passo 1 e,
apenas para o mesmo PID e nome, usar:

```bash
kill -KILL <PID>
```

## 3. Confirmar

```bash
top -b -n 2 -d 1 -o %CPU -w 120 | awk '/^top -/{n++} n==2' | sed -n '1,12p'
```

O processo não deve aparecer e o `%Cpu(s)` deve ter `id` (ocioso) alto. O problema no Zabbix
fecha depois de novas coletas abaixo do limite; isso pode levar alguns minutos.

# Base de conhecimento do operador (braço baseline)

Procedimentos que o operador humano usa no braço **baseline** do experimento, no lugar do
cartão do Polaris. Representam a base de conhecimento interna que uma equipe de operação mantém:
o mesmo conhecimento da base de regras do Polaris, entregue como documento para ler, copiar e
executar à mão.

| Cenário | Documento | Uso no baseline |
|:---|:---|:---|
| R001 · disco cheio | [r001_disco.md](r001_disco.md) | KB aberto; comandos copiados |
| R002 · CPU alta | [r002_cpu.md](r002_cpu.md) | KB aberto; comandos copiados |
| R003 · nginx parado | [r003_nginx.md](r003_nginx.md) | de memória, digitado; o KB é só referência |

## Regras de uso (decisão de 17/Out/2026)

- A regra vale igual em todas as rodadas baseline do mesmo cenário.
- Em R001 e R002, o KB fica aberto antes do alerta. Abrir ou rolar o KB para achar o comando conta
  como passo de navegação; cada comando colado e executado conta como passo.
- Em R003, o operador digita de memória. Consultar o KB durante o atendimento é desvio e precisa
  ser registrado na avaliação da rodada.
- Sem pesquisa na web nem uso de IA durante o atendimento.
- O atendimento começa pelo alerta real no Zabbix (*Monitoring → Problems*), nunca pela saída do
  controlador. O card do Polaris é ignorado no baseline.
- Os comandos foram conferidos no alvo do laboratório em 17/Out/2026.

## Acesso ao alvo

```bash
ssh cfrans@192.168.0.200
```
```bash
ssh root@192.168.0.152
```

O primeiro comando entra no bastion; o segundo, a partir do bastion, entra no alvo.

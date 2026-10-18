# Ordem de execução da coleta oficial

Sorteada uma única vez em 17/Out/2026, antes da primeira rodada oficial, com a versão
`v1.0.0-experimento`; vale para a `v1.0.1-experimento`, que a substituiu antes de qualquer rodada oficial. Desenho em **blocos permutados**: cinco blocos; em cada bloco, as seis
combinações cenário × braço aparecem uma vez, em ordem aleatória. Isso espalha os dois braços ao
longo da coleta, para que aprendizado, fadiga e variação do laboratório não se concentrem num braço,
e mantém pares completos se a coleta for interrompida ao fim de um bloco.

**Reinício em 18/Out/2026:** a coleta v1.0.1-experimento foi interrompida integralmente após um
defeito no diagnóstico por reconciliação. A v1.0.2-experimento conserva este sorteio, sem
ressortear em função dos resultados. Depois de validar a prontidão, iniciar novamente pela
ordem 1, bloco 1, repetição 1, com novos IDs e evidências separadas da amostra interrompida.

Siga a tabela em ordem. A coluna **repetição** é o valor de `--repetition` no `lab.py run`.
Rodada inválida é descartada com motivo e **repetida na mesma posição** antes de seguir; falha válida
de remediação é resultado e não se repete. Desvios da ordem são registrados com o motivo.

| Ordem | Bloco | Cenário | Braço | Repetição |
|:---|:---|:---|:---|:---|
| 1 | 1 | `cpu_high` (R002) | `hitl` | 1 |
| 2 | 1 | `disk_full` (R001) | `hitl` | 1 |
| 3 | 1 | `service_down` (R003) | `hitl` | 1 |
| 4 | 1 | `cpu_high` (R002) | `baseline` | 1 |
| 5 | 1 | `disk_full` (R001) | `baseline` | 1 |
| 6 | 1 | `service_down` (R003) | `baseline` | 1 |
| 7 | 2 | `cpu_high` (R002) | `hitl` | 2 |
| 8 | 2 | `disk_full` (R001) | `baseline` | 2 |
| 9 | 2 | `service_down` (R003) | `baseline` | 2 |
| 10 | 2 | `disk_full` (R001) | `hitl` | 2 |
| 11 | 2 | `service_down` (R003) | `hitl` | 2 |
| 12 | 2 | `cpu_high` (R002) | `baseline` | 2 |
| 13 | 3 | `cpu_high` (R002) | `hitl` | 3 |
| 14 | 3 | `service_down` (R003) | `baseline` | 3 |
| 15 | 3 | `cpu_high` (R002) | `baseline` | 3 |
| 16 | 3 | `disk_full` (R001) | `hitl` | 3 |
| 17 | 3 | `disk_full` (R001) | `baseline` | 3 |
| 18 | 3 | `service_down` (R003) | `hitl` | 3 |
| 19 | 4 | `disk_full` (R001) | `hitl` | 4 |
| 20 | 4 | `service_down` (R003) | `baseline` | 4 |
| 21 | 4 | `disk_full` (R001) | `baseline` | 4 |
| 22 | 4 | `service_down` (R003) | `hitl` | 4 |
| 23 | 4 | `cpu_high` (R002) | `baseline` | 4 |
| 24 | 4 | `cpu_high` (R002) | `hitl` | 4 |
| 25 | 5 | `service_down` (R003) | `baseline` | 5 |
| 26 | 5 | `cpu_high` (R002) | `hitl` | 5 |
| 27 | 5 | `disk_full` (R001) | `baseline` | 5 |
| 28 | 5 | `disk_full` (R001) | `hitl` | 5 |
| 29 | 5 | `cpu_high` (R002) | `baseline` | 5 |
| 30 | 5 | `service_down` (R003) | `hitl` | 5 |

## Reprodução do sorteio

Semente gerada por `secrets.randbits(64)`: `10335905870492488623`. Com Python 3, o código abaixo reproduz a
tabela (`random.Random` é determinístico para a mesma semente):

```python
SEED = 10335905870492488623
import random
COMBOS = [(c, a) for c in ("service_down", "cpu_high", "disk_full") for a in ("baseline", "hitl")]
rng = random.Random(SEED)
order = []
for block in range(1, 6):
    combos = COMBOS[:]
    rng.shuffle(combos)
    order += [(block, c, a) for c, a in combos]
```

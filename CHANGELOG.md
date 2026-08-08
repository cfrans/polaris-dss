# Changelog

Todas as mudanças relevantes deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento segue
[Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Motor de inferência completo, executável sem Zabbix, sem banco e sem interface: carga e validação
  da base de conhecimento, casamento de alertas por expressão regular e limiar, ordenação
  determinística de regras candidatas e cálculo do índice de confiança.
- Cálculo de confiança com cinco fatores de corroboração, todos limitados a 1,00: a confiança-base
  é o teto atribuído pelo especialista à regra e o motor apenas desconta quando a evidência é
  parcial ou o histórico é adverso. Os multiplicadores ficam em `confidence_config.json`, fora do
  código.
- Registro de explicabilidade (*trace*) com as evidências observadas, cada fator aplicado com o
  motivo, as regras candidatas descartadas e as versões da base e do motor vigentes — o suficiente
  para recalcular qualquer decisão passada.
- Detecção de recorrência: incidentes repetidos no mesmo host reduzem a confiança e passam a
  recomendar investigação manual, em vez de repetir a mesma remediação.
- Interface de linha de comando (`python -m src.engine.cli`) que aplica a base de conhecimento a um
  alerta e imprime o diagnóstico, as evidências, os fatores, a ação sugerida e o plano de reversão.
- Tabela `experiment_run` no esquema do banco, com cenário, braço, rodada e marcos temporais; e
  views de KPI comparando remediação manual e assistida, incluindo a decomposição do MTTR.
- Suíte de testes com 55 casos cobrindo validação da base, casamento de regras, critérios de
  desempate, os exemplos resolvidos do modelo de confiança e rejeição de parâmetros perigosos.

### Corrigido
- `schema.json` não validava o `rules.json`: declarava o topo como *array*, exigia um campo
  inexistente e desconhecia os parâmetros de regra. Nenhuma regra passaria pela validação.
- `config.py` interrompia a importação do módulo por exigir uma variável ausente do `.env.example`,
  e resolvia o caminho da base de conhecimento a partir do diretório de trabalho.
- Base de conhecimento: `nome_servico` estava declarado como condição, e não como parâmetro de
  remediação; regras sem verificador de restabelecimento; ausência de `versao_kb`.
- Dependências duplicadas de driver PostgreSQL e versão do FastAPI divergente da anunciada.

### Segurança
- Valores de parâmetro de regra passam por *allowlist* de caracteres e rejeição de travessia de
  diretório antes de qualquer substituição em linha de comando. Nada vindo do alerta é interpolado.
- Placeholder sem parâmetro correspondente falha na carga da base de conhecimento, e não na hora de
  executar a remediação.

### Modificado
- O Zabbix passou a ser **opcional**, isolado no profile `zabbix` do Compose. Por padrão,
  `docker compose up -d` sobe apenas o banco de auditoria do Polaris; para um Zabbix local de
  laboratório, use `docker compose --profile zabbix up -d`. Ambientes que já operam Zabbix apontam o
  Polaris para a instância existente via `ZABBIX_URL`.
- O banco de auditoria (`polaris-db`) ficou independente do banco do Zabbix, que agora tem instância
  própria. Antes as duas aplicações compartilhavam a mesma instância PostgreSQL, o que impedia o uso
  com um Zabbix externo.
- A porta publicada pelo banco passou a ser configurável (`POLARIS_DB_PORT`), evitando colisão com um
  PostgreSQL já instalado na máquina.
- O schema de auditoria é aplicado automaticamente na criação do volume, dispensando a execução
  manual de `psql`.

## [0.1.0] — 2026-08-08

### Adicionado
- Estrutura inicial do projeto: `src/` (engine, api, web, db, knowledge_base, scripts, tests),
  `infra/`, `experiment/`.
- `README.md`, `LICENSE` (MIT), `.gitignore`, `.env.example`, `requirements.txt`.
- Rascunho da base de conhecimento com três regras heurísticas (R001 disco, R002 CPU,
  R003 serviço) e JSON Schema de validação.
- Rascunho do schema PostgreSQL de auditoria com views de KPI (`vw_kpi_mttr`, `vw_kpi_accuracy`).
- `docker-compose.yml` com PostgreSQL, Zabbix Server, Zabbix Web e Zabbix Agent.

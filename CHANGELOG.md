# Changelog

Todas as mudanças relevantes deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento segue
[Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Não lançado]        <!-- alvo: v0.5.0 telemetria · v0.6.0 remediação -->

### Adicionado
- Executor remoto de remediação sobre SSH, com timeout por regra, captura de saída padrão, erro e
  código de retorno, e confirmação do restabelecimento pelo verificador do cenário. A lógica é
  independente do transporte, o que permite exercitá-la sem host remoto.
- Scripts de remediação e de verificação para os três cenários. O de limpeza de disco recusa
  qualquer caminho fora dos previstos e libera folga antes de rotacionar, já que com o sistema de
  arquivos cheio o `logrotate` não consegue escrever. O de encerramento de processo identifica o
  candidato pela segunda amostra do `top` — a média desde o início do processo, que o `ps` reporta,
  apontaria o processo errado — e só age se o nome constar da lista autorizada.
- Registro do comando de verificação na trilha de auditoria, ao lado do comando de remediação: a
  trilha guarda o que foi executado, e regra editada depois não altera o registro do passado.
- Seleção automática do executor: sem `TARGET_SSH_HOST` configurado, o sistema usa o executor
  simulado e não toca em máquina alguma.
- Recepção de eventos do Zabbix em `POST /webhook/zabbix`, autenticada por `X-Polaris-Token` com
  comparação em tempo constante. Evento reentregue devolve o incidente existente em vez de duplicar,
  e evento sem regra compatível é registrado como `no_match` — reconhecer que não há heurística
  formalizada é resultado, não falha.
- Normalização de eventos do Zabbix 7.0: severidade em código ou rótulo, valor numérico extraído de
  textos como `97.4 %` ou `up (1)`, data em epoch ou nos formatos das macros, e classificação do
  incidente pela tag `polaris_tipo` com heurística por chave de item como reserva.
- Cliente JSON-RPC (`ZabbixClient`) com autenticação por token de API ou por usuário e senha, e
  consulta de problemas em aberto já enriquecida com o host de origem.
- Laço de reconciliação (`python -m src.engine.reconciliacao`), que recupera eventos não entregues
  pelo webhook e encerra incidentes cujo problema deixou de existir na origem.
- Estado `encerrado_na_origem` na trilha de auditoria, distinto de remediação bem-sucedida: sem
  decisão humana e sem execução, não entra na taxa de acerto das heurísticas.
- `infra/zabbix/polaris-mediatype.yaml`, importável direto na interface do Zabbix, com as instruções
  de configuração da mídia e da ação.
- Conteinerização da aplicação (`polaris-api`) via `Dockerfile`, permitindo subir banco, API e
  interface com `docker compose up -d --build`. O esquema do banco continua sendo aplicado
  explicitamente, com `docker compose exec polaris-api python -m src.db.migrate`.
- `.dockerignore`, sem o qual o contexto de build empacotaria o `.env` com credenciais dentro de uma
  camada da imagem: o `.gitignore` não é considerado por builds Docker.
- Verificação de saúde do container da API e execução sob usuário sem privilégios.

### Segurança
- O container passou a receber apenas a chave SSH dedicada à remediação, montada em somente leitura,
  em vez do diretório `~/.ssh` inteiro do operador. Expor todas as chaves privadas do usuário
  contradiz o princípio de menor privilégio que o sistema exige do host alvo.
- A imagem deixou de rodar como root.
- Removidos endereços de rede interna dos valores padrão do Compose.

### Corrigido
- O container da API não recebia `POLARIS_CONFIDENCE_HISTORY`, `POLARIS_DEBUG`,
  `POLARIS_WEBHOOK_TOKEN`, `ZABBIX_USER`, `ZABBIX_PASSWORD` nem `TARGET_SSH_KEY_PATH`. A ausência da
  primeira era a mais grave: os fatores de confiança dependentes de histórico permaneceriam ativos
  durante a coleta de dados mesmo com a variável desligada no `.env`, comprometendo a comparabilidade
  entre rodadas sem emitir qualquer sinal.
- `ZABBIX_URL` tinha valor padrão sem o caminho `/api_jsonrpc.php`, o que impediria a comunicação
  com a API JSON-RPC.

## [0.4.0] — 2026-08-08

### Adicionado
- API REST em FastAPI cobrindo o ciclo do incidente: listagem, detalhe, marcação de exibição,
  decisão humana, resultado, base de conhecimento, recarga da base e KPIs. Documentação interativa
  em `/docs`.
- Interface Human-in-the-Loop em HTML, CSS e JavaScript puros, sem etapa de build, servida pelo
  mesmo processo da API. Apresenta o incidente com a banda de confiança em destaque, o diagnóstico,
  **as evidências que dispararam a regra**, **cada fator que descontou a confiança com o respectivo
  motivo**, o comando e o plano de reversão — o registro de explicabilidade chega ao operador
  legível, e não como JSON bruto.
- Banda de confiança baixa não oferece aprovação em um clique: exibe alerta e exige confirmação
  adicional. Incidente recorrente ganha aviso próprio recomendando investigação manual. Nenhuma
  banda executa automaticamente.
- Endpoint de simulação de alertas (`POST /debug/simulate-alert`), disponível apenas com
  `POLARIS_DEBUG` habilitado, que permite exercitar o sistema inteiro sem Zabbix.
- `/health` passou a informar a versão da base de conhecimento, o estado do banco e o modo de
  depuração.
- Executor simulado no fluxo da API até a chegada do executor real.

### Corrigido
- A interface detectava o modo de depuração sondando o endpoint de simulação, o que criava um
  incidente a cada carregamento da página e contaminaria a trilha de auditoria. A informação passou
  a vir de `/health`.


## [0.3.0] — 2026-08-08

### Adicionado
- Camada de persistência da auditoria: criação do incidente, marcação de exibição, registro da
  decisão humana e do resultado da execução, com os cinco marcos temporais do ciclo de vida.
- Imposição da invariante do trabalho em `engine/service.py`: a execução relê a aprovação já
  persistida antes de agir e recusa incidente sem decisão humana registrada, em vez de confiar em
  quem a chamou. A decisão é gravada e a transação concluída **antes** de qualquer execução.
- Fatores de confiança F3 (histórico da regra) e F4 (recorrência no host) alimentados por consultas
  reais ao `audit_log`, atrás da chave `POLARIS_CONFIDENCE_HISTORY`.
- Ciclo completo executável contra o banco (`python -m src.db.ciclo`), com executor simulado e
  verificação da recusa de execução não autorizada.
- Funções de instrumentação do experimento: criação e conclusão de rodada, descarte com
  justificativa e leitura das views de KPI.
- Testes de integração da persistência, que são pulados quando não há PostgreSQL disponível.
- Migrações versionadas do esquema do banco (`python -m src.db.migrate`). Cada arquivo é aplicado
  uma única vez, dentro de uma transação, e registrado em `schema_migrations` com o seu checksum.
  Migração já aplicada cujo arquivo tenha sido editado depois faz a execução abortar, garantindo que
  o esquema que gerou os dados de um experimento seja exatamente reconstruível.
- `--status` e `--dry-run` no aplicador de migrações.

### Corrigido
- Conexão ao banco passou a falhar em 5 segundos em vez de esperar o padrão do libpq, que fazia a
  suíte de testes parecer travada em máquina sem Docker.

### Modificado
- O esquema deixou de ser um arquivo único reaplicado e passou a ser a migração
  `001_esquema_inicial.sql`. `CREATE TABLE IF NOT EXISTS` cria a tabela ausente mas **não altera**
  uma existente: reaplicar o arquivo num banco já criado rodava sem erro e não fazia nada.
- O esquema não é mais montado em `docker-entrypoint-initdb.d`, que só executa na primeira criação
  do volume e deixaria bancos existentes para trás em silêncio. A aplicação passa a ser explícita,
  com o mesmo caminho para banco novo e banco existente.

## [0.2.0] — 2026-08-08

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
- Tabela `experiment_run` com cenário, braço, rodada e marcos temporais; e views de KPI comparando
  remediação manual e assistida, incluindo a decomposição do MTTR.
- Suíte de testes cobrindo validação da base, casamento de regras, critérios de desempate, os
  exemplos resolvidos do modelo de confiança e rejeição de parâmetros perigosos.

### Segurança
- Valores de parâmetro de regra passam por *allowlist* de caracteres e rejeição de travessia de
  diretório antes de qualquer substituição em linha de comando. Nada vindo do alerta é interpolado.
- Placeholder sem parâmetro correspondente falha na carga da base de conhecimento, e não na hora de
  executar a remediação.

## [0.1.1] — 2026-08-08

### Corrigido
- `schema.json` não validava o `rules.json`: declarava o topo como *array*, exigia um campo
  inexistente e desconhecia os parâmetros de regra. Nenhuma das três regras passaria pela validação.
- `config.py` interrompia a importação do módulo por exigir uma variável ausente do `.env.example`,
  e resolvia o caminho da base de conhecimento a partir do diretório de trabalho.
- Base de conhecimento: `nome_servico` estava declarado como condição, e não como parâmetro de
  remediação; regras sem verificador de restabelecimento; ausência de `versao_kb`.
- Dependências duplicadas de driver PostgreSQL e versão do FastAPI divergente da anunciada.

### Modificado
- Zabbix passou a ser **opcional**, isolado no profile `zabbix` do Compose. Por padrão,
  `docker compose up -d` sobe apenas o banco de auditoria do Polaris. Ambientes que já operam Zabbix
  apontam o Polaris para a instância existente via `ZABBIX_URL`.
- O banco de auditoria ficou independente do banco do Zabbix, que agora tem instância própria. Antes
  as duas aplicações compartilhavam a mesma instância, o que impedia o uso com um Zabbix externo.
- A porta publicada pelo banco passou a ser configurável (`POLARIS_DB_PORT`), evitando colisão com
  um PostgreSQL já instalado na máquina.

### Removido
- `infra/init-db.sh`, desnecessário desde que o banco de auditoria passou a subir com base própria.

## [0.1.0] — 2026-08-08

### Adicionado
- Estrutura inicial do projeto: `src/` (engine, api, web, db, knowledge_base, scripts, tests),
  `infra/`, `experiment/`.
- `README.md`, `LICENSE` (MIT), `.gitignore`, `.env.example`, `requirements.txt`.
- Rascunho da base de conhecimento com três regras heurísticas (R001 disco, R002 CPU,
  R003 serviço) e JSON Schema de validação.
- Rascunho do esquema PostgreSQL de auditoria com views de KPI.
- `docker-compose.yml` com PostgreSQL, Zabbix Server, Zabbix Web e Zabbix Agent.

[Não lançado]: https://github.com/cfrans/polaris-dss/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/cfrans/polaris-dss/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/cfrans/polaris-dss/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/cfrans/polaris-dss/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/cfrans/polaris-dss/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/cfrans/polaris-dss/releases/tag/v0.1.0

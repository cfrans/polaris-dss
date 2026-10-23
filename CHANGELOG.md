# Changelog

Todas as mudanças relevantes deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento segue
[Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Configuração interativa de Zabbix e SSH com teste obrigatório antes de salvar e avançar,
  importação opcional do ambiente sem devolver segredos, chave SSH dedicada gerada no servidor
  e confirmação independente da identidade do alvo. Cópias usam somente ícone acessível.
- Cofre Fernet com chave mestra em volume separado, escrita atômica e acesso administrativo
  inicializado no terminal. Sessões curtas, HTTPS fora de loopback, origem protegida e recibos
  de teste vinculados à sessão/configuração, com validade e uso único.
- Assistente de configuração inicial com seis etapas, comandos copiáveis, confirmação manual
  distinta de verificação automática e consultas de leitura sob demanda. Layout responsivo
  preserva a identidade visual e respeita movimento reduzido.
- Guia ordenado de instalação e downloads de quatro artefatos públicos da imagem instalada,
  por identificadores fixos; sem expor configuração real, provisionar infraestrutura ou remediar.
- Percurso sem alvo real conferido também em clone limpo do GitHub e banco novo, com dez
  migrações idempotentes e downloads idênticos ao checkout; limites externos documentados.

### Modificado
- API e reconciliador recarregam conexões cifradas; intervalo pode ser ativado pelo assistente.
  Alterações de conexões recusam incidentes abertos, DB indisponível e operações concorrentes.
  Mutações da API exigem sessão quando o cofre está habilitado; aprovação humana por incidente
  permanece obrigatória. Código compartilhado não identifica individualmente o operador.
- Compose padrão usa volumes de cofre/chave e dispensa arquivos SSH vazios. Instalações que
  mantêm chave em arquivo devem incluir compose.ssh-env.yml em todos os comandos Compose.
- Validação local ampliada: 627 testes Python e 50 JavaScript aprovados, seis opcionais pulados;
  persistência após recriação, JSON-RPC simulado e SSH restrito a true em rede Docker isolada.
  Integração externa/entrega de Action/remediação não foram repetidas neste lote.
- API identifica o desenvolvimento posterior à coleta como 1.1.0-dev; a tag e os dados da
  v1.0.3-experimento permanecem preservados. Nenhuma migração de banco ou mudança da fórmula
  de confiança/base de regras.

## [1.0.3-experimento] — 2026-10-18

Corrige o enriquecimento do polling revelado no ensaio CPU com webhook pausado.
Notas em [v1.0.3-experimento](docs/release-notes/v1.0.3-experimento.md).

### Corrigido
- Reconciliação passa a consultar a chave do item associado ao gatilho, além de tags, texto,
  severidade, horário e identidade do host. Eventos sem polaris_tipo podem usar o mesmo fallback
  de classificação do webhook, incluindo CPU oficial/system.cpu.util, disco e nginx.
- Valor da métrica é consultado no histórico até o clock/ns do evento; nunca usa lastvalue atual
  como se fosse medição da detecção. Item/host ambíguo, histórico ausente ou sem permissão mantém
  evidência parcial, sem escolher o primeiro item nem inventar valor. A allowlist de métricas é
  preservada mesmo quando a tag explícita contradiz a chave real.

Validação: 603 testes Python aprovados em Linux/PostgreSQL isolado, dois gráficos opcionais
pulados. Quinze regressões novas usam respostas de problem/event/host/trigger/history, conferem
paridade dos campos normalizados com o webhook e persistência de R001/R002/R003 sem aprovação.
Código candidato leu eventos históricos reais 739/743/745 sem alterar auditoria: classificou
R001/R003/R002 e recuperou valores de 96,000239%, 0 e 100%, respectivamente. Ensaio físico do
polling enriquecido permanece [NÃO VERIFICADO] até execução pelo operador.

## [1.0.2-experimento] — 2026-10-18

Substitui a coleta interrompida na v1.0.1-experimento; nova amostra após validação de prontidão.
Notas em [v1.0.2-experimento](docs/release-notes/v1.0.2-experimento.md).

### Corrigido
- Reconciliação recebia alertas sem alvo/chave SSH e criava incidentes sem plano, bloqueando
  a aprovação se chegasse antes do webhook. API e reconciliador passam a compartilhar alvo,
  usuário e montagens de chave/known_hosts em leitura apenas para diagnóstico de R001/R002/R003;
  remediação permanece condicionada à aprovação humana persistida na API.
- Lançador recusa nova injeção quando API/reconciliador divergem na identidade SSH, nas montagens
  ou quando os arquivos não são legíveis nos containers. Plano ausente desabilita aprovação
  e oferece atualização explícita no card; ausência de evidência não deixa diagnóstico real
  indefinidamente em coleta nem libera uma ação genérica.

Validação: 588 testes Python aprovados em Linux/PostgreSQL descartável, dois gráficos opcionais
pulados por Matplotlib ausente; 43 testes JavaScript aprovados. Inclui R001/R002/R003 por ambos
os caminhos de ingestão, duplicata durante inspeção, sete recusas de configuração e recuperação
do card sem plano. Leituras SSH reais dos três cenários aprovadas na API e no reconciliador
implantados no 151, com paridade de configuração/montagens aprovada e diagnóstico 5/5. O ensaio
físico com injeção e aprovação pós-correção ainda está [NÃO VERIFICADO]; não é substituído por
leituras de ambiente saudável ou por testes automatizados.

## [1.0.1-experimento] — 2026-10-18

Substitui a v1.0.0-experimento antes de qualquer rodada oficial; nenhuma amostra foi coletada com a
versão anterior. Notas em [v1.0.1-experimento](docs/release-notes/v1.0.1-experimento.md).

### Corrigido
- A saída da remoção e da compressão informava o uso do volume de antes da liberação (ensaio de
  fumaça 18: 97% depois de remover 400 MiB), porque media o volume com o próprio arquivo ainda
  aberto pelo executor. O uso passa a ser lido depois de fechar o arquivo, com `sync` e espera de
  até 3 s pela liberação esperada; se ela ainda não aparecer, a saída avisa em vez de mostrar o
  valor antigo como atual. Teste do comportamento com amostras atrasadas.

## [1.0.0-experimento] — 2026-10-17

Código congelado para a coleta do experimento ([notas](docs/release-notes/v1.0.0-experimento.md)).
API 1.0.0-experimento, motor 0.3.0, base de conhecimento 1.0.2, migrações 001–010. Reúne o trabalho
de telemetria, remediação central e instrumentação posterior à v0.4.0, sem tags intermediárias.
Suíte completa em Linux com PostgreSQL 16.15: 570 testes aprovados e 2 opcionais pulados; 40 testes
JavaScript aprovados. Seis ensaios gerais no laboratório em 17/Out (três cenários nos dois braços),
todos descartados como ensaio. Itens marcados **[NÃO VERIFICADO]** foram escritos antes desses
ensaios e mantêm a marca onde o comportamento específico não foi observado no laboratório.

### Adicionado
- Base de conhecimento do operador para o braço baseline (`experiment/kb_operador/`): R001 e R002
  executados a partir do KB com comandos copiados, R003 de memória. Inclui remoção de gzip antigo
  e compressão de log fechado em R001 e listagem por `top` em modo batch em R002. Comandos
  conferidos no alvo do laboratório; a compressão não se aplica ao fixture da coleta.
- Saída da ação de arquivo informa o resultado: na compressão, origem e destino com os tamanhos
  antes e depois; na remoção, o espaço liberado; nas duas, o uso do volume como o `df` (percentual
  e espaço livre). O cartão preenche o horário de fim assim que a execução termina, sem recarregar.
  Altera o hash do catálogo de scripts: planos pendentes pedem novo diagnóstico. Testes aprovados
  (filesystem em Linux como root); Verificação de 18/Out/2026: saída observada no laboratório (fumaça 19: 400,1 MiB liberados, volume a 75%; a leitura do volume foi corrigida na v1.0.1). Fim sem recarregar validado pelo autor no laboratório em 18/Out/2026.
- Ao aprovar ou rejeitar, o botão mostra um indicador giratório e "Executando…" enquanto a
  requisição de decisão, que inclui a execução aprovada, não retorna; o estado "executando" do
  resultado também exibe o indicador. Em erro, o botão volta ao rótulo original. Teste web
  aprovado; Verificação de 18/Out/2026: indicador observado pelo autor no laboratório (rodada 14).
- Comando do plano mostra por padrão um resumo de uma linha (o comando systemctl, ou o que será
  excluído, comprimido ou encerrado, com o tamanho); o procedimento completo com guardas fica em
  "Ver execução detalhada". Tamanhos na inspeção de leitura em unidades binárias legíveis (KiB,
  MiB, GiB); o alvo aprovado mantém também a contagem exata de bytes. Testes web e prévia
  ilustrativa aprovados; Verificação de 18/Out/2026: resumo e detalhe recolhido observados no laboratório (captura da rodada 14); tamanhos da inspeção de R001 validado pelo autor no laboratório em 18/Out/2026.
- Ações oferecidas pelo plano aparecem como cartões selecionáveis com marcador de rádio,
  confiança e estado selecionado destacado, navegáveis por setas, em lugar da lista nativa.
  A execução detalhada separa explicação em prosa dos comandos, exibidos em blocos com cores
  para programa, opções e argumentos; nomes literais no texto ficam em fonte monoespaçada.
  Testes web e prévia ilustrativa a 800 e 390 px aprovados; Verificação de 18/Out/2026: observado no laboratório e aprovado visualmente pelo autor (rodadas 10 a 14).
- Verificação global, reset e `run` exibem no terminal a espera entre as duas inspeções como
  contagem `decorrido/total s` reescrita na mesma linha, em stderr; eventos JSON continuam em
  stdout. Conferido no laboratório em check global real (0/60 a 60/60 s).
- Inspeção de leitura destacada, alternativas visíveis com contagem e explicação da execução
  com operação systemctl ou procedimentos Python e suas guardas, em lugar do payload Base64.
  Coletor inclui resultado/código de saída e horário de inatividade do nginx registrados pelo
  systemd, sem atribuir causa-raiz. Corrigida sobreposição do selo de evidência; início/fim em
  duas colunas sem caixa. Testes web e Linux isolados aprovados; revisão visual humana pendente.
- Caixa de evidências acompanha a altura do diagnóstico; cards de confirmação ocupam o espaço
  disponível com conteúdo centralizado verticalmente. Conferido em prévia ilustrativa e implantado
  no laboratório com CSS confirmado por hash HTTP; revisão visual humana permanece pendente.
- Corrigido fechamento HTML da seção de datas que comprometia a estrutura do cartão; datas ao lado
  do título em telas largas, confiança à direita e conteúdo seguinte sem vazios. Fundos das caixas
  suavizados e estilos responsivos corrigidos. Validado em prévia local ilustrativa a 1915, 1265 e
  390 px e nos 32 testes web. Implantado no laboratório: API/banco saudáveis e hashes HTTP
  conferidos; Verificação de 18/Out/2026: cartão real revisado pelo autor nas sessões de 16 e 17/Out.
- Cartão de incidente ajustado: início e fim ficam empilhados numa caixa única compacta;
  confiança, faixa, teto e explicação ficam no canto superior direito; a explicação preserva a dica
  por hover/foco e também abre em modal por clique; evidências em duas colunas, adaptadas a telas estreitas. Verificação de 18/Out/2026: superado em parte em 17/Out: início e fim passaram a duas colunas sem caixa, no cartão aprovado pelo autor.
- Preferências permitem definir o período (1–365 dias, padrão 30) da contagem de ocorrências da
  mesma regra no mesmo host, exibida no cartão do incidente. A configuração não altera a confiança
  nem invalida planos pendentes. Verificação de 18/Out/2026: contagem e período padrão exibidos no laboratório (incidente 313: 8 ocorrências em 30 dias); alteração do período **[NÃO VERIFICADO]**, não exercitada para não mudar a configuração antes da coleta.
- Cartão de incidente mais compacto, retorno animado entre preferências e tela anterior,
  ícone de preferências e estilos próprios para campos numéricos e listas suspensas. Verificação: validado pelo autor no laboratório em 18/Out/2026.
- Preferências exibidas em tela própria, agrupadas em recomendações e histórico de incidentes;
  detalhes do incidente reorganizados em duas colunas, com host/IP, horários com segundos e histórico
  filtrado por host, regra e período configurado. Verificação de 18/Out/2026: host/IP, horários com segundos e ocorrências por host, regra e período observados no laboratório (captura da rodada 14 e API); tela de preferências validado pelo autor no laboratório em 18/Out/2026.
- Link do host para a interface do Zabbix disponível somente quando `event.get` retorna
  um único host com identificador válido; link abre em nova aba e não impede o cartão quando indisponível. Verificação de 18/Out/2026: link presente no detalhe do laboratório (`zabbix_host_url` com o hostid do vm-alvo); abertura em nova aba validado pelo autor no laboratório em 18/Out/2026.
- Explicação da confiança aparece como dica flutuante com ícone informativo; ocorrências
  abrem em modal com cada registro selecionável para consultar seu cartão. Verificação: validado pelo autor no laboratório em 18/Out/2026.
- Cinco verificações de diagnóstico são apresentadas em cards horizontais, com a
  quantidade de colunas adaptada à largura disponível. Verificação de 18/Out/2026: observado na captura da tela de diagnóstico do laboratório.
- Abertura e fechamento animados para ciência de scripts, aviso de segurança, preferências,
  diagnóstico e cartões, respeitando a opção de movimento reduzido do sistema. Verificação: validado pelo autor no laboratório em 18/Out/2026.
- Novo fluxo completo de remediação com planos, escolhas e
  preferências. Verificação de 18/Out/2026: ensaios 10, 11 e 14 e fumaças 18 e 19, com preferência padrão de desempate.
- Diagnóstico SSH limitado e somente de leitura antes da apresentação de R001/R002/R003,
  com metadados de arquivos, identidade de processo e padrões conhecidos de erros do nginx.
  Incidente persistido antes da coleta; tempo diagnóstico incluído no processamento/MTTR.
- Planos específicos com opções aplicáveis, alvo visível, hash e escolha persistidos antes da
  execução; recusa de plano expirado/alterado e de troca de arquivo/processo/estado do serviço.
  R001 usa compressão individual ou exclusão de log gzip com retenção mínima, sem logrotate global.
- Menu Preferências persistido pela migração 009: desempate por escolha como padrão, desconto
  opcional limitado e modo desligado. Histórico de sucesso por operação e preferência explicados
  separadamente; ambos desativados com POLARIS_CONFIDENCE_HISTORY=false. Base JSON 1.0.2.
- Catálogo inclui coletor e executor Python fixos; seleção de parâmetros por snapshot validado,
  sem comandos livres recebidos do cliente. Scripts históricos permanecem para reprodução.
- Documentação pública de operação, arquitetura/limites de segurança e catálogo físico
  PostgreSQL, com índice e seis diagramas editáveis em Mermaid e exportados em SVG/PNG.
  Catálogo conferido contra oito migrações em banco descartável: seis tabelas, quatro views,
  atributos e FKs. Imagens renderizadas e revisadas; não substituem ensaio/instalação real.
- Histórico operacional de decisões na home, com barras de aprovações/rejeições, períodos
  de 24 horas, 7 e 30 dias e tabela acessível dos valores. Endpoint GET
  `/api/v1/historico-decisoes` agrega decisões persistidas por horário UTC, preenche intervalos
  vazios e distingue falha de consulta de ausência de decisões. Não calcula KPIs experimentais.
  Validado em PostgreSQL descartável e prévia identificada com dados sintéticos;
  Verificação de 18/Out/2026: rota implantada; a série de sete dias coincide com a contagem direta no banco (3, 7 e 2 decisões por dia).
- Relógio local com segundos/data no cabeçalho da interface e do laboratório, com fuso
  indicado no tooltip. Painel compacto de CPU/memória do servidor via GET `/api/v1/servidor`
  e host técnico explícito em `POLARIS_ZABBIX_HOST`; somente leitura de itens no Zabbix,
  sem SSH ou eventos. Amostras inválidas/ausentes/antigas não viram zero ou estado saudável.
  Testes com dependências simuladas aprovados; endpoint implantado no laboratório em
  13/Out/2026, com métricas reais confirmadas pela API e exibidas na prévia da interface.
  Agente/host do servidor e coleta dos dois itens também confirmados.
  Regressão Linux com PostgreSQL 16.15 descartável: 497 testes aprovados e dois testes
  opcionais de gráficos pulados por Matplotlib ausente; 22 testes JavaScript aprovados.
- Endpoint `/api/v1/conectividade` para indicadores do cabeçalho: consulta somente `SELECT 1`
  no banco e acesso autenticado à API do Zabbix, com timeouts curtos, estados independentes,
  latência e horário UTC. Não chama SSH, coleta eventos ou devolve configuração/erros brutos.
  Casos de token inválido, senha, rede, banco e configuração ausente validados com dependências
  simuladas; endpoint implantado e consulta real confirmou banco/Zabbix em ok em 13/Out/2026.
- Tela de laboratório com etapas de preparação, condução, registro e preservação/reset;
  seleção de cenário/braço, comandos prontos, diagnóstico sob demanda e avaliação JSON com
  resultado e passos humanos explícitos. Sem injeção, aprovação ou escrita de rodadas via HTTP.
  Helper de host `experiment/lab.py` reúne as CLIs existentes em containers temporários,
  fixa a imagem imutável da API e monta a chave administrativa somente nas ações administrativas.
  Recusa chave de serviço reutilizada, modo de arquivo amplo e condições de execução divergentes;
  exige histórico/debug desligados antes de injetar. Backup e relatório persistem no host, sem
  sobrescrita; análise montada somente no processo temporário. Roteiro público incluído.
  Testes offline com Docker falso e geração de comandos/avaliação aprovados;
  Verificação de 18/Out/2026: `lab.py` e montagens Compose usados em todas as rodadas de 17 e 18/Out; a tela de laboratório não foi usada nos ensaios.
- Checklist global do experimento e reset administrativo explícito por ID de rodada: lock
  compartilhado por alvo, recusa de rodada não avaliada/incidente aberto e inspeção dos três
  cenários em duas amostras separadas por 60 s. Check de mount vazio não prepara nem remove
  arquivos; reset restaura somente o cenário avaliado/descartado e confere os demais, sem
  reparar sujeira alheia ou mudar avaliação/timestamps/aprovação. NTP, rearme, cinco minutos,
  versões e efeitos colaterais continuam em checklist manual explícito. Runbooks atualizados.
  Suite local com PostgreSQL descartável: 430 aprovados, sem pulos; shells/SSH simulados.
  Verificação de 18/Out/2026: checklist e reset usados em todas as rodadas de 17 e 18/Out; o intervalo passou a 30 s.
- Relatório descritivo do experimento: resumos de MTTR e passos por cenário/braço com média,
  desvio amostral, mínimo/máximo, contagens e lacunas; redução entre braços e comparação por
  repetições pareadas. Acerto humano agregado por contagens; decomposição somente com vínculo
  único e seis horários completos/ordenados, terminando no t5 independente. Snapshot PostgreSQL
  REPEATABLE READ READ ONLY ou entrada CSV, com exportação bruta, tabelas, Markdown e manifesto
  de hashes, sem sobrescrita. Figuras PNG/PDF com Matplotlib opcional restrito à análise;
  dados sintéticos identificados, sem imputação de medições nem alteração do runtime.
  Validação local com banco descartável e dados sintéticos; nenhum resultado experimental coletado.
- Controladores experimentais R001/R002 para baseline/HITL, reutilizando gestão de rodadas e
  coordenação R003. Disco somente no mount isolado de 2 GB: preparação de gzip descartável,
  manifesto de dispositivo/inodes, recusa de dados alheios/links, pressão confirmada e reset dos
  arquivos rastreados. CPU com uma CPU disponível e um worker em unidade transitória dedicada,
  sem restart, com expiração de segurança superior ao deadline máximo de observação.
  Observadores sem sudo: disco abaixo de 85%; CPU abaixo de 70% por janela amostrada de 30 s,
  seguida de três checks qualificadores. Registro só de t5; avaliação humana e aprovação preservadas.
  Locks e t0/t5 testados no PostgreSQL local descartável; scripts testados com utilitários falsos.
  Verificação de 18/Out/2026: R001 e R002 ensaiados nos dois braços (rodadas 11, 14, 16 e 17).
  Runbooks e CLIs documentados; análise/checklist global implementados em continuidade, com ensaio integrado pendente.
- Controlador experimental R003 para baseline/HITL: checks de nginx e registros anteriores,
  espera de 60 s, commit de t0 antes de armar observador e injetar, com lock por alvo e conexão
  própria no observador. Injeção e reset explícitos usam identidade administrativa distinta;
  reset exige avaliação/descarte e recusa interferência com outra rodada ou incidente aberto no alvo.
  Nenhuma aprovação automática ou remediação pelo controlador; timestamps/auditoria preservados.
  Observador cancelável; erros e IDs mantidos para avaliação. CLI documentada para checkout ou
  imagem sem Git. Testes simulados e shell com comandos falsos aprovados;
  Verificação de 18/Out/2026: R003 ensaiado nos dois braços (rodadas 10 e 15); a espera passou a 30 s. Locks compartilhados
  validados localmente no PostgreSQL descartável em continuidade. t0 inclui o
  despacho da instrumentação anterior à parada; esse atraso ainda deve ser observado no ensaio.
- Gestão das rodadas do experimento: registro de t0 confirmado antes de um callback de injeção,
  associação explícita de incidente/evento, avaliação humana e descarte com motivo sem apagar
  evidências. Valida alvo, versão da base, horários e aprovação do incidente para avaliação HITL
  de sucesso; regras divergentes e falhas sem incidente permanecem registráveis. O observador
  recusa gravar t5 após avaliação humana. Testes simulados locais aprovados;
  Verificação de 18/Out/2026: vínculo, avaliação, descarte e reset usados em todas as rodadas de 17 e 18/Out. Controlador R003 e
  reset explícito preparados em continuidade; controladores CPU/disco preparados posteriormente,
  checklist global implementado em continuidade; ensaio integrado pendente.
- Tela de ciência apresenta finalidade e efeitos dos cinco scripts padrão, mantendo o nome
  técnico e o código integral. Destaque de sintaxe Bash opcional, sem bibliotecas externas,
  com texto inserido por nós DOM para impedir interpretação do código como HTML.
- Preparação da instrumentação de R003: observador independente para rodadas `service_down`
  existentes, usando o verificador SSH sem sudo, e runbook manual do braço baseline. O observador
  exige falha observada seguida de três verificações saudáveis e grava apenas o horário da primeira,
  com proteção contra observadores concorrentes e sobrescrita de rodadas descartadas ou medidas.
- Exportação CSV das rodadas com metadados, timestamps UTC e MTTR em segundos, preservando rodadas
  incompletas e descartadas e recusando substituir arquivos existentes. Verificação local com
  respostas simuladas; Verificação de 18/Out/2026: relatórios gerados no laboratório antes e depois de cada descarte; o
  relatório reproduzido do snapshot da fumaça 19 em banco descartável, com a imagem v1.0.1-experimento,
  saiu byte a byte idêntico nos sete arquivos. Demais cenários e análise foram implementados em continuidade;
  não houve coleta experimental. O acerto humano foi preparado em continuidade; a view do servidor
  sem migração 007 ainda usa desfechos aprovados e não equivale ao acerto do protocolo.

### Corrigido
- R002 deixava de oferecer o encerramento quando o processo identificado media 89,99% numa
  amostra de 1 s (incidente 305), porque comparava um processo com o limiar de 90% do host. A
  inspeção passa a usar amostra de três segundos e a oferecer encerrar o maior consumidor
  permitido com pelo menos 50% de uma CPU. Testes com os valores reais dos incidentes 303 e 305;
  altera o hash do catálogo. Verificação de 18/Out/2026: opção oferecida no laboratório na rodada 14 (stress-ng-cpu, PID 226249).
- Marcos operacionais de `audit_log` (`ts_criacao`, `ts_exibicao`, `ts_aprovacao`,
  `ts_conclusao`) e `evento_ingestao.registrado_em` passam a usar
  `clock_timestamp()` em `src/db/queries.py` em vez de `NOW()` congelado no início da transação.
  Corrige `ts_conclusao` quase simultâneo a `ts_aprovacao` quando `service.executar` abria a
  transação em `obter_incidente` antes do executor SSH e verificador remoto; preserva a
  invariante de aprovação humana, registros históricos e o `t5` experimental independente
  (`experiment_run.ts_verificado_ok`). Validado nos testes unitários e no PostgreSQL 16.15
  descartável (`18 passed` em `test_persistencia.py`; regressão completa Linux/PostgreSQL com
  `527 passed, 2 skipped` em `12,12s`); Verificação de 18/Out/2026: implantado; conclusão registrada 2,6 s após a aprovação nos incidentes 300 e 301 (P-54 encerrada).
- Janelas F3/F4 usam `statement_timestamp()`, com limite fixo por consulta e compatível com
  condições temporais de índice. O teste de conclusão compara `ts_conclusao` com o relógio do
  PostgreSQL capturado ao final do executor simulado, incluindo atraso anterior à execução
  para impedir falso positivo com `NOW()`. Validado em PostgreSQL 16.15 descartável:
  `18 passed` em persistência; controle negativo com `NOW()` rejeitado pelo teste revisado,
  embora a asserção anterior passasse; suíte completa Linux com `527 passed, 2 skipped`
  (Matplotlib opcional ausente) em `11,83s`. Implantação no laboratório permanece pendente.
- Manual público do laboratório (`experiment/laboratorio.md`,
  `experiment/scenarios/reset_environment.md`) e runbooks (`experiment/runbook_baseline.md`,
  `experiment/runbook_resources.md`) harmonizados quanto ao reaproveitamento do check global
  embutido no `reset` explícito para rodadas subsequentes de serviço/CPU (mantendo `check`
  explícito na primeira rodada, em retomadas e após `prepare` de disco) e à fronteira de
  contagem de passos manuais (preparação pré-alerta vs. conexão SSH pós-alerta, seleção/cópia e
  `Ctrl+C` antes de Enter vs. comandos submetidos, troca de aba/refresh com nova informação vs.
  leitura passiva e limpeza administrativa pós-atendimento).
- Runbooks atualizados para usar o observador já armado pelo controlador, sem iniciar outro
  depois da falha. Três controladores, transações locais, identidade por IP, início por alerta
  real, contagem de ações e distinção entre ensaio e coleta passam a refletir o comportamento
  atual. README deixa de afirmar redução de MTTR medida ou supressão automática da sugestão
  por baixa confiança. Integração do laboratório continua pendente.
- IP do alvo preservado do webhook até audit_log, inclusive em alertas sem regra; o
  reconciliador consulta a interface principal de agente por IP para eventos de um único host.
  Endereços inválidos/ambíguos ficam ausentes, sem DNS ou inferência pelo nome. O detalhe HTTP
  expõe o campo opcional já existente no banco. Corrige bloqueio do vínculo experimental quando
  o alvo é configurado por IP; não altera destino SSH, aprovação ou registros históricos.
  240 testes selecionados aprovados em PostgreSQL descartável, incluindo os dois caminhos reais
  de ingestão até o vínculo. Regressão completa Linux/PostgreSQL em 14/Out: 525 aprovados,
  dois gráficos opcionais pulados por Matplotlib ausente, um aviso de depreciação Starlette.
  Verificação de 18/Out/2026: IP 192.168.0.152 preservado e vínculo com a regra esperada em todas as rodadas HITL.
- Views de MTTR, passos e decomposição alinhadas ao relatório descritivo pela migração 008:
  exigem avaliação humana e preservam falhas válidas; MTTR com apenas um braço informa a
  amostra existente e mantém medidas/redução ausentes como nulas. Decomposição exige vínculo
  único e horários completos/ordenados, terminando no t5 independente para que as fases somem
  o total. Campos atuais da API, KPI 03 e dados primários preservados. Validação com PostgreSQL
  descartável e rodadas sintéticas. Implantação 008 confirmada em 13/Out/2026, com oito migrações
  e cinco dependências em ok. Conferência com amostra preenchida de ensaio ainda pendente.
- Cursor de mão padronizado nos links, botões e demais controles clicáveis; controles
  desabilitados indicam indisponibilidade. Explicação dos scripts abre e fecha com transição
  curta de altura, respeitando a preferência de movimento reduzido e cliques durante a animação.
  Conferido em prévia local e validado pelo autor no laboratório em 18/Out/2026.
- Tela de ciência compacta: finalidade e efeitos ficam recolhidos ao abrir/reabrir,
  com expansão por clique ou teclado. A opção de colorir sintaxe fica menor e à direita,
  na mesma linha da explicação recolhida. Código integral, rolagem e navegação preservados.
- KPI 03 passa a usar a avaliação humana das rodadas HITL por cenário, incluindo falhas sem
  incidente e regras divergentes no denominador, excluindo rodadas não avaliadas ou descartadas.
  Exportador de acerto com CSV sem sobrescrita; migração 007 preparada para substituir a view,
  retirando o agrupamento/coluna `regra_disparada`. Validação local em PostgreSQL 16.15 descartável: sete
  migrações aplicadas, view equivalente ao cálculo Python e resposta da API conferida com casos
  sintéticos de falha sem incidente, exclusão e arredondamento. Percentual na API como string JSON.
  Migração 007 aplicada no PCT 151 em 08/Out/2026, com sete migrações e nenhuma pendente;
  endpoint respondeu com listas vazias. Comparação das contagens com rodadas elegíveis no
  banco implantado ainda **[NÃO VERIFICADA NO LABORATÓRIO]**.
- Base de conhecimento 1.0.1: o diagnóstico e o aviso de reversão de R001 explicam a remoção
  inicial do arquivo `.gz` mais antigo, independentemente da idade, seguida da limpeza dos demais
  comprimidos antigos. A interface informa que não há restauração automática e que a seleção não
  verifica o conteúdo dos arquivos; a política de limpeza e os comandos permanecem os mesmos.
- R002 consulta o nome completo do processo pelo PID antes de compará-lo com a lista permitida;
  a coluna `COMMAND` do `top` podia abreviar `stress-ng-cpu` como `stress-+` e recusar a ação.
- A interface passa a servir HTML, JavaScript e CSS sem cache persistente e a recarregar o catálogo
  ao abrir "Scripts e ciência", evitando misturar código antigo do navegador com a API atual.
- R002 passou a consumir o trigger `Linux: High CPU utilization` do template oficial, eliminando o
  segundo item calculado e o problema duplicado de CPU criado pelo template complementar. O
  payload bruto do evento oficial capturado no Zabbix 7.0 foi incorporado às fixtures e aos testes.
- O gatilho R001 agora descobre sistemas de arquivos montados, em vez de existir somente para
  `/mnt/polaris_test`. A correspondência de métricas impede que um volume não autorizado receba o
  comando de limpeza reservado ao ponto de montagem allowlisted na base de conhecimento. O
  payload bruto do evento 239 capturado no laboratório foi incorporado às fixtures e aos testes.
- Idempotência global por `EVENT.ID`, inclusive para alertas sem regra compatível. O
  reconciliador deixa de gravar o mesmo `no_match` a cada ciclo; duplicatas históricas
  permanecem preservadas na auditoria e a primeira ingestão vira a referência canônica.

### Removido
- `kill_target_process.sh` saiu do catálogo e do repositório pelo mesmo motivo: a R002 já executa
  `apply_action.py` com o PID aprovado, e o script escolhia o candidato só na execução. Testes do
  executor passaram a usar `apply_action.py`; os testes exclusivos do script foram removidos.
- `disk_cleanup.sh` saiu do catálogo de scripts e do repositório. Ele removia o `.gz` mais antigo
  do volume de qualquer idade e podia rodar `logrotate` global; a R001 já usava `apply_action.py`
  com alvo aprovado desde a base 1.0.2. Política nova adotada para a coleta por decisão do autor
  (P-55). Visualizador de scripts, página do laboratório e runbook apontam para o KB do operador;
  o hash do catálogo muda.

### Alterado
- Falha da confirmação global após um reset passa a nomear a verificação que falhou (por exemplo,
  `cpu_high is not healthy`), em vez de apenas `ScenarioError`; exceções externas continuam só com
  o tipo. Motivado por falha passageira, não diagnosticada, após o reset da rodada 16.
- Baseline manual definido como o procedimento habitual do operador (Zabbix, bastion, alvo e
  comandos administrativos comuns), sem o coletor nem o executor do Polaris; a política de
  alvos continua limitando o que a remediação manual pode alterar. Registrado no runbook após o
  ensaio do baseline de R003.
- Segundo clique de ação destrutiva ou de confiança baixa vira etapa explícita: caixa
  "Confirmação necessária" acima dos botões com o motivo, botão "Confirmar e executar" e
  "Cancelar", que volta sem registrar decisão; Rejeitar fica oculto durante a etapa. Teste web e
  prévia ilustrativa aprovados.
- Botão de aprovação que exige segundo clique informa o motivo: "Aprovar ação destrutiva" ou
  "Aprovar com confiança baixa", no lugar de "Aprovar mesmo assim"; a mensagem de confirmação
  explica cada motivo presente. Tela de diagnóstico com título "Diagnóstico" e descrição em uma
  linha. Testes web aprovados.
- Laboratório: R002 passa a ser alimentada por gatilho de host `Polaris: High CPU utilization`
  (mesma métrica `system.cpu.util`, janela de 2 min, tag `polaris=enabled`), com o gatilho oficial
  de 5 min desativado só no host alvo. Configuração aplicada no Zabbix e documentada em
  `docs/operations.md`; Verificação de 18/Out/2026: eventos reais do gatilho novo nas rodadas 13, 14 e 17 (detecção entre 1 min 55 s e 3 min 30 s).
- t5 do cenário de CPU passa a ser a primeira amostra saudável da janela de 30 s, gravada só
  depois de a janela e os três checks a confirmarem; antes era a primeira amostra após a janela,
  o que somava cerca de 30 s ao MTTR. Serviço e disco, sem janela, não mudam. Testes do
  observador atualizados; Verificação de 18/Out/2026: observado nas rodadas 14 e 17.
- Intervalo entre as duas amostras de saúde antes da injeção e nas verificações globais reduzido
  de 60 s para 30 s, em constante única (`STABILITY_WAIT_S`). Os itens do Zabbix são coletados a
  cada 10 s; a espera é instrumentação, fora de t0..t5. Manual do laboratório e contratos dos
  controladores atualizados. Verificação de 18/Out/2026: contagem 30/30 s observada em todas as rodadas de 17 e 18/Out.
- Registros recentes ocultam por padrão alertas sem regra atribuída. Checkbox no canto inferior direito,
  ao lado dos ocultos, permite incluí-los e lembra a escolha no navegador; filtro SQL é aplicado antes do limite de seis
  registros, inclusive quando um alerta sem regra foi encerrado na origem. Auditoria, fila
  pendente e KPIs permanecem disponíveis. API preserva o padrão anterior para outros clientes.
  Regressão desta etapa: 99 testes Python de API/persistência/Zabbix e 27 testes JavaScript
  aprovados; aparência/conversão de períodos e preferência conferidas na prévia local.
- Página inicial mostra decisões pendentes, execuções em andamento, conexão da API/banco,
  última reconciliação e até seis registros recentes com filtro por estado. Fila vazia ocupa
  a largura disponível; falha de consulta aparece como indisponibilidade. Consultas de fundo
  não abrem incidentes nem registram sua exibição. Marca vetorial original e título retornam
  à home; cabeçalho compacto reúne ferramentas em menu e exibe a versão declarada pela API,
  inclusive no laboratório. Navegação e 20 testes JavaScript conferidos localmente;
  Verificação de 18/Out/2026: implantado e em uso pelo autor nos ensaios; versão declarada exibida no cabeçalho.
- Cabeçalho permanece fixo e reduz a altura ao rolar, com vidro fosco. Indicadores discretos
  de Zabbix/banco e estados verdes, âmbar, vermelhos ou cinza distinguem conexão confirmada,
  atenção, falha e consulta indisponível. Engrenagem abre menu com ícones e transição; painéis
  respeitam movimento reduzido e ficam inertes quando recolhidos. Fundo espacial vetorial
  estático e sutil, sem bibliotecas ou recursos externos. Prévia conferida em desktop e mobile.
- Registros recentes podem ser ocultos e restaurados numa área própria. Preferência local do
  navegador guarda identificação/metadados, sem persistir estado de execução como atual e sem
  alterar auditoria, contagens ou fila de decisões. Armazenamento indisponível limita a preferência
  à sessão e informa isso ao operador. Persistência/restauração conferidas localmente.
- Reconciliação mantém resumo e contagens visíveis, com atividade registrada recolhida em
  painel de altura limitada e rolagem. O botão do topo expande/recolhe o painel com transição,
  sem trocar a tela nem o incidente selecionado, e recebe destaque correspondente ao painel.
  Botão Atualizar consulta novamente os dados; histórico
  preserva horários, contagens e erros como texto literal. Falha na atualização limpa valores
  antigos para não apresentá-los como atuais. A interface informa que o histórico contém
  até 20 atividades significativas, sem prometer log completo. Prévia local e testes JavaScript
  conferidos; implantado e validado pelo autor no laboratório em 18/Out/2026.
- A chave pública validada do host alvo passa a persistir em `secrets/known_hosts` e é montada em
  leitura apenas no container; recriar a API não apaga a confiança SSH. Hosts desconhecidos ou com
  chave alterada continuam recusados.
- A remediação passa a enviar os scripts padrão da imagem pela entrada SSH, sem cópias permanentes
  no host alvo. A aprovação grava o hash do conjunto apresentado; uma versão divergente impede a
  decisão. A interface apresenta os scripts e o aviso de responsabilidade no primeiro acesso.
- Corrigida a referência obsoleta à fixture de disco em cinco testes de reconciliação.
- Distribuição-base explícita Debian 13 Trixie: `python:3.12-slim-trixie` para API e
  reconciliador e `postgres:16-trixie` para os bancos do Compose. As tags preservam a
  distribuição, mas continuam recebendo atualizações de pacotes.
- Build local ARM64 com as tags Trixie validado: Debian 13.6, quatro migrações e
  180 testes aprovados com PostgreSQL descartável; API saudável e intervalo zero verificado.
- Implantação das tags Trixie no servidor confirmada pelo operador em 08/Set/2026:
  API e banco saudáveis, quatro migrações aplicadas e Debian 13.6 identificado.
  As imagens da coleta oficial ainda devem ser reconfirmadas quando ela ocorrer.

### Adicionado
- Template complementar importável para Zabbix 7.0, com os itens, triggers, limiares e tags dos
  cenários R001 e R003 e integração com o trigger oficial de R002. O vínculo em massa aplica a
  integração a múltiplos hosts sem cadastro manual host a host nem alerta duplicado de CPU.
- Serviço `polaris-reconciler` separado no Docker Compose, que operacionaliza um único laço de
  reconciliação sem criar um processo por worker da API. O intervalo continua configurável por
  `POLARIS_POLLING_SEGUNDOS`, e o valor zero desativa o serviço sem exigir acesso ao Zabbix.
- Estado persistido do último ciclo e histórico enxuto de reconciliações com recuperação,
  encerramento ou transição de erro. A interface apresenta badge operacional, horário e resultado
  do último ciclo, contagens por estado e atividade recente; repetições sem mudança não acumulam
  linhas no histórico.
- Endpoint `GET /api/v1/reconciliacao` para consultar a configuração somente leitura, detectar ciclo
  atrasado e alimentar a visualização operacional.
- Tela de diagnóstico e configuração na interface, e o endpoint `GET /api/v1/diagnostico` que a
  alimenta. Verifica banco de auditoria, esquema aplicado, base de conhecimento, API do Zabbix e
  host alvo por SSH, cada um com estado e latência próprios. Dependência não configurada aparece
  como tal, e não como falha.
- A tela exibe a configuração em vigor com os **segredos mascarados**: informa que um valor está
  definido e o seu tamanho, nunca o valor.
- Botão para recarregar a base de regras a partir da própria tela; base inválida é recusada com o
  erro de validação, e a base anterior permanece ativa.
- A verificação do esquema compara as migrações em disco com as registradas no banco, o que revela
  o caso em que o container executa uma imagem anterior à migração criada.
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
- O teste de recorrência consultava `vm-alvo-01`, embora a fixture persistida use `vm-alvo`, e por
  isso falhava apenas quando os testes de integração eram executados com PostgreSQL disponível.
- `--intervalo 0` era substituído pelo valor do ambiente por causa da avaliação booleana e não
  desativava o loop como documentado; a execução única também devolvia sucesso após falha do Zabbix.
- O horário enviado por `{EVENT.DATE} {EVENT.TIME}` chegava sem deslocamento de fuso e fazia o
  Polaris registrar o horário de São Paulo como UTC, acrescentando três horas falsas à latência.
  Como `{EVENT.TIMESTAMP}` existe somente a partir do Zabbix 7.2 e a stack usa a versão 7.0 LTS, o
  webhook agora enriquece o evento consultando o campo `clock` autoritativo pela API a partir do
  `event_id`. O payload R003 capturado no laboratório foi incorporado às fixtures e aos testes.
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

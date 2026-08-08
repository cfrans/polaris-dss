-- Polaris DSS — esquema de auditoria e instrumentação do experimento.
-- Idempotente: pode ser aplicado mais de uma vez sem erro.
-- Aplicado automaticamente na criação do volume do container polaris-db.

-- ---------------------------------------------------------------------------
-- experiment_run: metadados da pesquisa.
-- Separada da trilha operacional de propósito: o sistema não precisa saber que está num
-- experimento para funcionar. É aqui que ficam cenário, braço e rodada — sem isso não há
-- comparação possível entre remediação manual e assistida.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS experiment_run (
    id                BIGSERIAL PRIMARY KEY,

    cenario           VARCHAR(32) NOT NULL
                      CHECK (cenario IN ('disk_full', 'cpu_high', 'service_down')),
    braco             VARCHAR(16) NOT NULL
                      CHECK (braco IN ('baseline', 'hitl')),
    rodada            SMALLINT NOT NULL CHECK (rodada > 0),
    descartada        BOOLEAN NOT NULL DEFAULT FALSE,
    motivo_descarte   TEXT,

    -- Reprodutibilidade: permite descobrir na análise, e não na defesa, que alguma rodada
    -- acabou executando em versão diferente do restante da amostra.
    versao_sistema    VARCHAR(32),
    commit_sha        VARCHAR(40),
    versao_kb         VARCHAR(16),
    host_alvo         VARCHAR(128),
    operador          VARCHAR(64),

    ts_injecao        TIMESTAMPTZ NOT NULL,
    ts_verificado_ok  TIMESTAMPTZ,

    passos_manuais    SMALLINT,
    comandos_usados   TEXT,
    resolvido         BOOLEAN,
    observacoes       TEXT,

    mttr              INTERVAL GENERATED ALWAYS AS (ts_verificado_ok - ts_injecao) STORED
);

COMMENT ON TABLE  experiment_run IS 'Instrumentação do experimento; vazia em operação normal';
COMMENT ON COLUMN experiment_run.braco IS 'baseline = remediação manual; hitl = assistida';
COMMENT ON COLUMN experiment_run.ts_injecao IS 't0: gravado pelo script de injeção antes de agir';
COMMENT ON COLUMN experiment_run.ts_verificado_ok IS 't5: primeiro retorno saudável do verificador';
COMMENT ON COLUMN experiment_run.descartada IS 'Dado primário não se apaga: marca-se e justifica-se';
COMMENT ON COLUMN experiment_run.mttr IS 'MTTR da pesquisa, medido desde a injeção da falha';

CREATE UNIQUE INDEX IF NOT EXISTS uq_run_cenario_braco_rodada
    ON experiment_run (cenario, braco, rodada) WHERE descartada = FALSE;
CREATE INDEX IF NOT EXISTS idx_run_cenario_braco ON experiment_run (cenario, braco);

-- ---------------------------------------------------------------------------
-- audit_log: trilha operacional. Existiria mesmo sem experimento nenhum.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id                  BIGSERIAL PRIMARY KEY,

    id_evento           VARCHAR(64) NOT NULL,
    hostname            VARCHAR(128),
    ip_address          INET,
    severidade          VARCHAR(16) CHECK (severidade IN ('baixa', 'media', 'alta', 'critica')),

    regra_disparada     VARCHAR(16),
    confianca_calculada NUMERIC(5,4) CHECK (confianca_calculada BETWEEN 0 AND 1),
    banda_confianca     VARCHAR(8) CHECK (banda_confianca IN ('alta', 'media', 'baixa')),
    explicabilidade     JSONB,
    versao_kb           VARCHAR(16),
    versao_motor        VARCHAR(16),

    decisao_humana      BOOLEAN,
    operador            VARCHAR(64),
    motivo_rejeicao     TEXT,

    status_execucao     VARCHAR(16) NOT NULL DEFAULT 'pendente'
                        CHECK (status_execucao IN ('pendente', 'executando', 'sucesso',
                                                   'falha', 'timeout', 'rejeitado', 'no_match')),
    comando_executado   TEXT,
    exit_code           INTEGER,
    output_execucao     TEXT,
    output_erro         TEXT,

    ts_deteccao         TIMESTAMPTZ,
    ts_criacao          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts_exibicao         TIMESTAMPTZ,
    ts_aprovacao        TIMESTAMPTZ,
    ts_conclusao        TIMESTAMPTZ,

    mttr_calculado      INTERVAL GENERATED ALWAYS AS (ts_conclusao - ts_criacao) STORED,

    experiment_run_id   BIGINT REFERENCES experiment_run(id) ON DELETE SET NULL
);

COMMENT ON COLUMN audit_log.id_evento IS 'EVENT.ID do Zabbix; chave natural de idempotência';
COMMENT ON COLUMN audit_log.explicabilidade IS 'Trace completo do cálculo de confiança';
COMMENT ON COLUMN audit_log.decisao_humana IS 'true = aprovado, false = rejeitado, null = pendente';
COMMENT ON COLUMN audit_log.status_execucao IS 'no_match = nenhuma regra compatível; é resultado, não falha';
COMMENT ON COLUMN audit_log.mttr_calculado IS 'MTTR operacional (Mean Time To Repair), da ingestão à conclusão';

-- Um mesmo evento não pode ter dois incidentes abertos: reentrega do webhook é ignorada.
CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_evento_aberto
    ON audit_log (id_evento) WHERE status_execucao IN ('pendente', 'executando');

CREATE INDEX IF NOT EXISTS idx_audit_ts_criacao ON audit_log (ts_criacao DESC);
CREATE INDEX IF NOT EXISTS idx_audit_regra      ON audit_log (regra_disparada);
CREATE INDEX IF NOT EXISTS idx_audit_status     ON audit_log (status_execucao);
CREATE INDEX IF NOT EXISTS idx_audit_evento     ON audit_log (id_evento);
-- Suporta as consultas dos fatores F3 (histórico da regra) e F4 (recorrência no host).
CREATE INDEX IF NOT EXISTS idx_audit_host_regra_ts
    ON audit_log (hostname, regra_disparada, ts_criacao DESC);

-- ---------------------------------------------------------------------------
-- Views de KPI
-- ---------------------------------------------------------------------------

-- KPI 01 — MTTR por cenário e braço, com a redução percentual entre eles.
CREATE OR REPLACE VIEW vw_kpi01_mttr AS
WITH agregado AS (
    SELECT cenario, braco,
           COUNT(*)                              AS n,
           AVG(EXTRACT(EPOCH FROM mttr))         AS mttr_med_s,
           STDDEV_SAMP(EXTRACT(EPOCH FROM mttr)) AS mttr_desvio_s,
           MIN(EXTRACT(EPOCH FROM mttr))         AS mttr_min_s,
           MAX(EXTRACT(EPOCH FROM mttr))         AS mttr_max_s
    FROM experiment_run
    WHERE descartada = FALSE AND ts_verificado_ok IS NOT NULL
    GROUP BY cenario, braco
)
SELECT b.cenario,
       b.n                                AS n_baseline,
       h.n                                AS n_hitl,
       ROUND(b.mttr_med_s::numeric, 1)    AS mttr_baseline_s,
       ROUND(h.mttr_med_s::numeric, 1)    AS mttr_hitl_s,
       ROUND(b.mttr_desvio_s::numeric, 1) AS desvio_baseline_s,
       ROUND(h.mttr_desvio_s::numeric, 1) AS desvio_hitl_s,
       ROUND(((b.mttr_med_s - h.mttr_med_s) / NULLIF(b.mttr_med_s, 0) * 100)::numeric, 1)
                                          AS reducao_pct
FROM agregado b
JOIN agregado h ON h.cenario = b.cenario AND h.braco = 'hitl'
WHERE b.braco = 'baseline';

-- KPI 02 — passos manuais por incidente.
CREATE OR REPLACE VIEW vw_kpi02_passos AS
SELECT cenario, braco,
       COUNT(*)                               AS n,
       ROUND(AVG(passos_manuais)::numeric, 2) AS passos_medio,
       MIN(passos_manuais)                    AS passos_min,
       MAX(passos_manuais)                    AS passos_max
FROM experiment_run
WHERE descartada = FALSE AND passos_manuais IS NOT NULL
GROUP BY cenario, braco
ORDER BY cenario, braco;

-- KPI 03 — taxa de acerto das heurísticas. Só o braço assistido produz este dado.
CREATE OR REPLACE VIEW vw_kpi03_acerto AS
SELECT r.cenario,
       a.regra_disparada,
       COUNT(*)                                                       AS tentativas,
       SUM(CASE WHEN a.status_execucao = 'sucesso' THEN 1 ELSE 0 END) AS sucessos,
       ROUND(SUM(CASE WHEN a.status_execucao = 'sucesso' THEN 1 ELSE 0 END)::numeric
             / NULLIF(COUNT(*), 0) * 100, 1)                          AS taxa_acerto_pct
FROM experiment_run r
JOIN audit_log a ON a.experiment_run_id = r.id
WHERE r.descartada = FALSE AND r.braco = 'hitl' AND a.decisao_humana = TRUE
GROUP BY r.cenario, a.regra_disparada
ORDER BY r.cenario;

-- Decomposição do MTTR: onde o tempo foi gasto em cada rodada assistida.
-- O componente de decisão humana é o custo deliberado da governança, e reportá-lo separadamente
-- é o que permite discutir o trade-off entre agilidade e controle em termos quantitativos.
CREATE OR REPLACE VIEW vw_decomposicao_mttr AS
SELECT r.cenario, r.rodada,
       EXTRACT(EPOCH FROM (a.ts_deteccao      - r.ts_injecao))  AS deteccao_s,
       EXTRACT(EPOCH FROM (a.ts_criacao       - a.ts_deteccao)) AS ingestao_s,
       EXTRACT(EPOCH FROM (a.ts_exibicao      - a.ts_criacao))  AS inferencia_s,
       EXTRACT(EPOCH FROM (a.ts_aprovacao     - a.ts_exibicao)) AS decisao_humana_s,
       EXTRACT(EPOCH FROM (a.ts_conclusao     - a.ts_aprovacao)) AS execucao_s,
       EXTRACT(EPOCH FROM (r.ts_verificado_ok - r.ts_injecao))  AS mttr_total_s
FROM experiment_run r
JOIN audit_log a ON a.experiment_run_id = r.id
WHERE r.descartada = FALSE AND r.braco = 'hitl'
ORDER BY r.cenario, r.rodada;

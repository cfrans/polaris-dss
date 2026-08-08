-- PostgreSQL Schema for Polaris DSS Audit Log

-- Tabela audit_log
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    id_evento VARCHAR(64) NOT NULL,
    regra_disparada VARCHAR(16),
    severidade VARCHAR(16) CHECK (severidade IN ('baixa', 'media', 'alta', 'critica')),
    explicabilidade JSONB,
    confianca_calculada NUMERIC(5,4) CHECK (confianca_calculada >= 0 AND confianca_calculada <= 1),
    decisao_humana BOOLEAN,
    status_execucao VARCHAR(16) DEFAULT 'pendente' CHECK (status_execucao IN ('pendente', 'sucesso', 'falha')),
    comando_executado TEXT,
    output_execucao TEXT,
    ts_criacao TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts_exibicao TIMESTAMPTZ,
    ts_aprovacao TIMESTAMPTZ,
    ts_conclusao TIMESTAMPTZ,
    mttr_calculado INTERVAL GENERATED ALWAYS AS (ts_conclusao - ts_criacao) STORED,
    hostname VARCHAR(128),
    ip_address INET
);

-- Comments on columns
COMMENT ON COLUMN audit_log.id_evento IS 'Zabbix alert ID ou identificador de evento único';
COMMENT ON COLUMN audit_log.regra_disparada IS 'ID da regra heurística disparada, ex: R001';
COMMENT ON COLUMN audit_log.decisao_humana IS 'true = aprovado, false = rejeitado, null = pendente';
COMMENT ON COLUMN audit_log.mttr_calculado IS 'Tempo total entre a detecção e a conclusão da remediação';

-- Indexes
CREATE INDEX idx_audit_log_ts_criacao ON audit_log (ts_criacao);
CREATE INDEX idx_audit_log_regra ON audit_log (regra_disparada);
CREATE INDEX idx_audit_log_status ON audit_log (status_execucao);

-- View: KPI MTTR (Mean Time To Recovery per rule)
CREATE OR REPLACE VIEW vw_kpi_mttr AS
SELECT 
    regra_disparada,
    COUNT(*) as total_eventos,
    AVG(mttr_calculado) as avg_mttr,
    MIN(mttr_calculado) as min_mttr,
    MAX(mttr_calculado) as max_mttr
FROM audit_log
WHERE status_execucao = 'sucesso' 
  AND decisao_humana = TRUE
  AND ts_conclusao IS NOT NULL
GROUP BY regra_disparada;

-- View: KPI Accuracy (Heuristic accuracy / success rate)
CREATE OR REPLACE VIEW vw_kpi_accuracy AS
SELECT 
    regra_disparada,
    COUNT(*) as total_tentativas,
    SUM(CASE WHEN status_execucao = 'sucesso' THEN 1 ELSE 0 END) as sucessos,
    SUM(CASE WHEN status_execucao = 'falha' THEN 1 ELSE 0 END) as falhas,
    ROUND(
        SUM(CASE WHEN status_execucao = 'sucesso' THEN 1 ELSE 0 END)::numeric / 
        NULLIF(COUNT(*), 0) * 100, 
    2) as success_rate_percent
FROM audit_log
WHERE decisao_humana = TRUE
GROUP BY regra_disparada;

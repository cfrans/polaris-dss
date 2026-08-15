-- Novo estado para incidentes cujo problema deixou de existir no Zabbix antes de haver decisão
-- humana. Não conta como acerto de heurística: não houve aprovação nem execução.
--
-- A coluna precisa ser alargada para comportar o novo rótulo, e o PostgreSQL não altera o tipo de
-- coluna referenciada por view — daí a view de KPI 03 ser derrubada e recriada aqui.

DROP VIEW IF EXISTS vw_kpi03_acerto;

ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_status_execucao_check;

ALTER TABLE audit_log ALTER COLUMN status_execucao TYPE VARCHAR(24);

ALTER TABLE audit_log ADD CONSTRAINT audit_log_status_execucao_check
    CHECK (status_execucao IN ('pendente', 'executando', 'sucesso', 'falha',
                               'timeout', 'rejeitado', 'no_match', 'encerrado_na_origem'));

COMMENT ON COLUMN audit_log.status_execucao IS
    'no_match = nenhuma regra compatível; encerrado_na_origem = o problema deixou de existir no Zabbix antes da decisão';

CREATE VIEW vw_kpi03_acerto AS
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

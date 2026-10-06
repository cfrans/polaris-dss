-- KPI 03: uma tentativa por rodada HITL avaliada, inclusive sem incidente.
-- A regra operacional deixa de ser agrupamento: regra errada pertence à tentativa do cenário.
-- Não altera dados primários nem migrações anteriores.
DROP VIEW vw_kpi03_acerto;

CREATE VIEW vw_kpi03_acerto AS
SELECT cenario,
       COUNT(*) AS tentativas,
       COUNT(*) FILTER (WHERE resolvido = TRUE) AS sucessos,
       ROUND((COUNT(*) FILTER (WHERE resolvido = TRUE))::numeric
             / NULLIF(COUNT(*), 0) * 100, 1) AS taxa_acerto_pct
FROM experiment_run
WHERE descartada = FALSE AND braco = 'hitl' AND resolvido IS NOT NULL
GROUP BY cenario
ORDER BY cenario;

COMMENT ON VIEW vw_kpi03_acerto IS
    'Acerto avaliado pelo operador por cenário: inclui falhas sem incidente; exclui não avaliadas e descartadas';

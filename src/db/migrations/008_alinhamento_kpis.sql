-- Alinha a elegibilidade das views ao relatório descritivo.
-- Não altera rodadas, auditoria nem os campos existentes da API.
CREATE OR REPLACE VIEW vw_kpi01_mttr AS
WITH agregado AS (
    SELECT cenario, braco,
           COUNT(*) AS n,
           AVG(EXTRACT(EPOCH FROM mttr)) AS mttr_med_s,
           STDDEV_SAMP(EXTRACT(EPOCH FROM mttr)) AS mttr_desvio_s
    FROM experiment_run
    WHERE descartada = FALSE
      AND resolvido IS NOT NULL
      AND ts_verificado_ok IS NOT NULL
    GROUP BY cenario, braco
)
SELECT COALESCE(b.cenario, h.cenario) AS cenario,
       COALESCE(b.n, 0::bigint) AS n_baseline,
       COALESCE(h.n, 0::bigint) AS n_hitl,
       ROUND(b.mttr_med_s::numeric, 1) AS mttr_baseline_s,
       ROUND(h.mttr_med_s::numeric, 1) AS mttr_hitl_s,
       ROUND(b.mttr_desvio_s::numeric, 1) AS desvio_baseline_s,
       ROUND(h.mttr_desvio_s::numeric, 1) AS desvio_hitl_s,
       ROUND(((b.mttr_med_s - h.mttr_med_s) / NULLIF(b.mttr_med_s, 0) * 100)::numeric, 1)
           AS reducao_pct
FROM (SELECT * FROM agregado WHERE braco = 'baseline') b
FULL JOIN (SELECT * FROM agregado WHERE braco = 'hitl') h ON h.cenario = b.cenario
ORDER BY COALESCE(b.cenario, h.cenario);

CREATE OR REPLACE VIEW vw_kpi02_passos AS
SELECT cenario, braco,
       COUNT(*) AS n,
       ROUND(AVG(passos_manuais)::numeric, 2) AS passos_medio,
       MIN(passos_manuais) AS passos_min,
       MAX(passos_manuais) AS passos_max
FROM experiment_run
WHERE descartada = FALSE
  AND resolvido IS NOT NULL
  AND passos_manuais IS NOT NULL
GROUP BY cenario, braco
ORDER BY cenario, braco;

CREATE OR REPLACE VIEW vw_decomposicao_mttr AS
WITH vinculo_unico AS (
    SELECT experiment_run_id
    FROM audit_log
    WHERE experiment_run_id IS NOT NULL
    GROUP BY experiment_run_id
    HAVING COUNT(*) = 1
)
SELECT r.cenario, r.rodada,
       EXTRACT(EPOCH FROM (a.ts_deteccao - r.ts_injecao)) AS deteccao_s,
       EXTRACT(EPOCH FROM (a.ts_criacao - a.ts_deteccao)) AS ingestao_s,
       EXTRACT(EPOCH FROM (a.ts_exibicao - a.ts_criacao)) AS inferencia_s,
       EXTRACT(EPOCH FROM (a.ts_aprovacao - a.ts_exibicao)) AS decisao_humana_s,
       EXTRACT(EPOCH FROM (r.ts_verificado_ok - a.ts_aprovacao)) AS execucao_s,
       EXTRACT(EPOCH FROM (r.ts_verificado_ok - r.ts_injecao)) AS mttr_total_s
FROM experiment_run r
JOIN vinculo_unico u ON u.experiment_run_id = r.id
JOIN audit_log a ON a.experiment_run_id = r.id
WHERE r.descartada = FALSE
  AND r.braco = 'hitl'
  AND r.resolvido IS NOT NULL
  AND r.ts_injecao <= a.ts_deteccao
  AND a.ts_deteccao <= a.ts_criacao
  AND a.ts_criacao <= a.ts_exibicao
  AND a.ts_exibicao <= a.ts_aprovacao
  AND a.ts_aprovacao <= r.ts_verificado_ok
ORDER BY r.cenario, r.rodada;

COMMENT ON VIEW vw_kpi01_mttr IS
    'MTTR de rodadas avaliadas e não descartadas com t5; braço ausente tem n=0 e medidas NULL';
COMMENT ON VIEW vw_kpi02_passos IS
    'Passos registrados em rodadas avaliadas e não descartadas, inclusive falhas; ausência não vale zero';
COMMENT ON VIEW vw_decomposicao_mttr IS
    'Decomposição HITL avaliada, vínculo único e t0..t5 completos/ordenados; última fase termina no t5 independente';

-- Idempotência global por EVENT.ID, inclusive para resultados no_match.
--
-- Duplicatas históricas são preservadas no audit_log. O menor ID representa a
-- primeira ingestão e passa a ser devolvido nas reentregas futuras.

CREATE TABLE IF NOT EXISTS evento_ingestao (
    id_evento      VARCHAR(64) PRIMARY KEY,
    incidente_id   BIGINT NOT NULL REFERENCES audit_log(id),
    registrado_em  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE evento_ingestao IS
    'Registro global de idempotência: um EVENT.ID do Zabbix aponta para sua primeira ingestão';

INSERT INTO evento_ingestao (id_evento, incidente_id, registrado_em)
SELECT id_evento, MIN(id), MIN(ts_criacao)
  FROM audit_log
 GROUP BY id_evento
ON CONFLICT (id_evento) DO NOTHING;

# Physical PostgreSQL catalog

Reviewed on 2026-10-14 against all eight migrations in disposable PostgreSQL 16.15.
This catalog contains schema metadata only, not laboratory records. Diagram types group SQL
families for readability; the exact SQL types and constraints are listed below.

## Tables

### `audit_log`

| Column | SQL type | Nullable | Stored generated |
|:--|:--|:--|:--|
| `id` | `bigint` | No | No |
| `id_evento` | `character varying(64)` | No | No |
| `hostname` | `character varying(128)` | Yes | No |
| `ip_address` | `inet` | Yes | No |
| `severidade` | `character varying(16)` | Yes | No |
| `regra_disparada` | `character varying(16)` | Yes | No |
| `confianca_calculada` | `numeric(5,4)` | Yes | No |
| `banda_confianca` | `character varying(8)` | Yes | No |
| `explicabilidade` | `jsonb` | Yes | No |
| `versao_kb` | `character varying(16)` | Yes | No |
| `versao_motor` | `character varying(16)` | Yes | No |
| `decisao_humana` | `boolean` | Yes | No |
| `operador` | `character varying(64)` | Yes | No |
| `motivo_rejeicao` | `text` | Yes | No |
| `status_execucao` | `character varying(24)` | No | No |
| `comando_executado` | `text` | Yes | No |
| `exit_code` | `integer` | Yes | No |
| `output_execucao` | `text` | Yes | No |
| `output_erro` | `text` | Yes | No |
| `ts_deteccao` | `timestamp with time zone` | Yes | No |
| `ts_criacao` | `timestamp with time zone` | No | No |
| `ts_exibicao` | `timestamp with time zone` | Yes | No |
| `ts_aprovacao` | `timestamp with time zone` | Yes | No |
| `ts_conclusao` | `timestamp with time zone` | Yes | No |
| `mttr_calculado` | `interval` | Yes | Yes |
| `experiment_run_id` | `bigint` | Yes | No |
| `comando_verificacao` | `text` | Yes | No |
| `versao_scripts` | `character(64)` | Yes | No |

Constraints:

```sql
-- audit_log_banda_confianca_check
CHECK (((banda_confianca)::text = ANY ((ARRAY['alta'::character varying, 'media'::character varying, 'baixa'::character varying])::text[])))
-- audit_log_confianca_calculada_check
CHECK (((confianca_calculada >= (0)::numeric) AND (confianca_calculada <= (1)::numeric)))
-- audit_log_experiment_run_id_fkey
FOREIGN KEY (experiment_run_id) REFERENCES experiment_run(id) ON DELETE SET NULL
-- audit_log_pkey
PRIMARY KEY (id)
-- audit_log_severidade_check
CHECK (((severidade)::text = ANY ((ARRAY['baixa'::character varying, 'media'::character varying, 'alta'::character varying, 'critica'::character varying])::text[])))
-- audit_log_status_execucao_check
CHECK (((status_execucao)::text = ANY ((ARRAY['pendente'::character varying, 'executando'::character varying, 'sucesso'::character varying, 'falha'::character varying, 'timeout'::character varying, 'rejeitado'::character varying, 'no_match'::character varying, 'encerrado_na_origem'::character varying])::text[])))
```

Operational timestamps (`ts_criacao`, `ts_exibicao`, `ts_aprovacao`, `ts_conclusao`) and
`evento_ingestao.registrado_em` are written by `src/db/queries.py` using `clock_timestamp()`
rather than transaction-frozen `NOW()`, so `ts_conclusao` and `mttr_calculado` reflect the actual
wall-clock instant after remote execution and verification. Experimental `t5` and `mttr` remain in
`experiment_run` (`ts_verificado_ok` and `mttr`).

F3/F4 history windows use `statement_timestamp()`: their cutoff is current at the start of
each query and constant across its rows, allowing temporal index conditions. They do not use
the transaction start time or a cutoff that moves during the scan.

### `evento_ingestao`

| Column | SQL type | Nullable | Stored generated |
|:--|:--|:--|:--|
| `id_evento` | `character varying(64)` | No | No |
| `incidente_id` | `bigint` | No | No |
| `registrado_em` | `timestamp with time zone` | No | No |

Constraints:

```sql
-- evento_ingestao_incidente_id_fkey
FOREIGN KEY (incidente_id) REFERENCES audit_log(id)
-- evento_ingestao_pkey
PRIMARY KEY (id_evento)
```

### `experiment_run`

| Column | SQL type | Nullable | Stored generated |
|:--|:--|:--|:--|
| `id` | `bigint` | No | No |
| `cenario` | `character varying(32)` | No | No |
| `braco` | `character varying(16)` | No | No |
| `rodada` | `smallint` | No | No |
| `descartada` | `boolean` | No | No |
| `motivo_descarte` | `text` | Yes | No |
| `versao_sistema` | `character varying(32)` | Yes | No |
| `commit_sha` | `character varying(40)` | Yes | No |
| `versao_kb` | `character varying(16)` | Yes | No |
| `host_alvo` | `character varying(128)` | Yes | No |
| `operador` | `character varying(64)` | Yes | No |
| `ts_injecao` | `timestamp with time zone` | No | No |
| `ts_verificado_ok` | `timestamp with time zone` | Yes | No |
| `passos_manuais` | `smallint` | Yes | No |
| `comandos_usados` | `text` | Yes | No |
| `resolvido` | `boolean` | Yes | No |
| `observacoes` | `text` | Yes | No |
| `mttr` | `interval` | Yes | Yes |

Constraints:

```sql
-- experiment_run_braco_check
CHECK (((braco)::text = ANY ((ARRAY['baseline'::character varying, 'hitl'::character varying])::text[])))
-- experiment_run_cenario_check
CHECK (((cenario)::text = ANY ((ARRAY['disk_full'::character varying, 'cpu_high'::character varying, 'service_down'::character varying])::text[])))
-- experiment_run_pkey
PRIMARY KEY (id)
-- experiment_run_rodada_check
CHECK ((rodada > 0))
```

### `reconciliacao_estado`

| Column | SQL type | Nullable | Stored generated |
|:--|:--|:--|:--|
| `id` | `smallint` | No | No |
| `status` | `character varying(16)` | No | No |
| `intervalo_segundos` | `integer` | No | No |
| `recuperados` | `integer` | No | No |
| `ja_conhecidos` | `integer` | No | No |
| `encerrados_na_origem` | `integer` | No | No |
| `mensagem_erro` | `text` | Yes | No |
| `ts_inicio` | `timestamp with time zone` | No | No |
| `ts_conclusao` | `timestamp with time zone` | No | No |

Constraints:

```sql
-- reconciliacao_estado_encerrados_na_origem_check
CHECK ((encerrados_na_origem >= 0))
-- reconciliacao_estado_id_check
CHECK ((id = 1))
-- reconciliacao_estado_intervalo_segundos_check
CHECK ((intervalo_segundos >= 0))
-- reconciliacao_estado_ja_conhecidos_check
CHECK ((ja_conhecidos >= 0))
-- reconciliacao_estado_pkey
PRIMARY KEY (id)
-- reconciliacao_estado_recuperados_check
CHECK ((recuperados >= 0))
-- reconciliacao_estado_status_check
CHECK (((status)::text = ANY ((ARRAY['sucesso'::character varying, 'erro'::character varying])::text[])))
```

### `reconciliacao_historico`

| Column | SQL type | Nullable | Stored generated |
|:--|:--|:--|:--|
| `id` | `bigint` | No | No |
| `status` | `character varying(16)` | No | No |
| `recuperados` | `integer` | No | No |
| `ja_conhecidos` | `integer` | No | No |
| `encerrados_na_origem` | `integer` | No | No |
| `mensagem_erro` | `text` | Yes | No |
| `ts_inicio` | `timestamp with time zone` | No | No |
| `ts_conclusao` | `timestamp with time zone` | No | No |

Constraints:

```sql
-- reconciliacao_historico_encerrados_na_origem_check
CHECK ((encerrados_na_origem >= 0))
-- reconciliacao_historico_ja_conhecidos_check
CHECK ((ja_conhecidos >= 0))
-- reconciliacao_historico_pkey
PRIMARY KEY (id)
-- reconciliacao_historico_recuperados_check
CHECK ((recuperados >= 0))
-- reconciliacao_historico_status_check
CHECK (((status)::text = ANY ((ARRAY['sucesso'::character varying, 'erro'::character varying])::text[])))
```

### `schema_migrations`

| Column | SQL type | Nullable | Stored generated |
|:--|:--|:--|:--|
| `versao` | `character varying(8)` | No | No |
| `nome` | `text` | No | No |
| `checksum` | `character(64)` | No | No |
| `aplicada_em` | `timestamp with time zone` | No | No |

Constraints:

```sql
-- schema_migrations_pkey
PRIMARY KEY (versao)
```

## Derived views

Views are queries, not independent measurement records. `ts_conclusao` remains operational;
the recovery endpoint for experiment MTTR is `experiment_run.ts_verificado_ok`. Eligibility,
missing phases and human correctness are explicit in the definitions. No failed or missing
measurement is imputed as zero. See [analysis](../experiment/analysis/report.md).

### `vw_decomposicao_mttr`

```sql
WITH vinculo_unico AS (
         SELECT audit_log.experiment_run_id
           FROM audit_log
          WHERE audit_log.experiment_run_id IS NOT NULL
          GROUP BY audit_log.experiment_run_id
         HAVING count(*) = 1
        )
 SELECT r.cenario,
    r.rodada,
    EXTRACT(epoch FROM a.ts_deteccao - r.ts_injecao) AS deteccao_s,
    EXTRACT(epoch FROM a.ts_criacao - a.ts_deteccao) AS ingestao_s,
    EXTRACT(epoch FROM a.ts_exibicao - a.ts_criacao) AS inferencia_s,
    EXTRACT(epoch FROM a.ts_aprovacao - a.ts_exibicao) AS decisao_humana_s,
    EXTRACT(epoch FROM r.ts_verificado_ok - a.ts_aprovacao) AS execucao_s,
    EXTRACT(epoch FROM r.ts_verificado_ok - r.ts_injecao) AS mttr_total_s
   FROM experiment_run r
     JOIN vinculo_unico u ON u.experiment_run_id = r.id
     JOIN audit_log a ON a.experiment_run_id = r.id
  WHERE r.descartada = false AND r.braco::text = 'hitl'::text AND r.resolvido IS NOT NULL AND r.ts_injecao <= a.ts_deteccao AND a.ts_deteccao <= a.ts_criacao AND a.ts_criacao <= a.ts_exibicao AND a.ts_exibicao <= a.ts_aprovacao AND a.ts_aprovacao <= r.ts_verificado_ok
  ORDER BY r.cenario, r.rodada;
```

### `vw_kpi01_mttr`

```sql
WITH agregado AS (
         SELECT experiment_run.cenario,
            experiment_run.braco,
            count(*) AS n,
            avg(EXTRACT(epoch FROM experiment_run.mttr)) AS mttr_med_s,
            stddev_samp(EXTRACT(epoch FROM experiment_run.mttr)) AS mttr_desvio_s
           FROM experiment_run
          WHERE experiment_run.descartada = false AND experiment_run.resolvido IS NOT NULL AND experiment_run.ts_verificado_ok IS NOT NULL
          GROUP BY experiment_run.cenario, experiment_run.braco
        )
 SELECT COALESCE(b.cenario, h.cenario) AS cenario,
    COALESCE(b.n, 0::bigint) AS n_baseline,
    COALESCE(h.n, 0::bigint) AS n_hitl,
    round(b.mttr_med_s, 1) AS mttr_baseline_s,
    round(h.mttr_med_s, 1) AS mttr_hitl_s,
    round(b.mttr_desvio_s, 1) AS desvio_baseline_s,
    round(h.mttr_desvio_s, 1) AS desvio_hitl_s,
    round((b.mttr_med_s - h.mttr_med_s) / NULLIF(b.mttr_med_s, 0::numeric) * 100::numeric, 1) AS reducao_pct
   FROM ( SELECT agregado.cenario,
            agregado.braco,
            agregado.n,
            agregado.mttr_med_s,
            agregado.mttr_desvio_s
           FROM agregado
          WHERE agregado.braco::text = 'baseline'::text) b
     FULL JOIN ( SELECT agregado.cenario,
            agregado.braco,
            agregado.n,
            agregado.mttr_med_s,
            agregado.mttr_desvio_s
           FROM agregado
          WHERE agregado.braco::text = 'hitl'::text) h ON h.cenario::text = b.cenario::text
  ORDER BY (COALESCE(b.cenario, h.cenario));
```

### `vw_kpi02_passos`

```sql
SELECT cenario,
    braco,
    count(*) AS n,
    round(avg(passos_manuais), 2) AS passos_medio,
    min(passos_manuais) AS passos_min,
    max(passos_manuais) AS passos_max
   FROM experiment_run
  WHERE descartada = false AND resolvido IS NOT NULL AND passos_manuais IS NOT NULL
  GROUP BY cenario, braco
  ORDER BY cenario, braco;
```

### `vw_kpi03_acerto`

```sql
SELECT cenario,
    count(*) AS tentativas,
    count(*) FILTER (WHERE resolvido = true) AS sucessos,
    round(count(*) FILTER (WHERE resolvido = true)::numeric / NULLIF(count(*), 0)::numeric * 100::numeric, 1) AS taxa_acerto_pct
   FROM experiment_run
  WHERE descartada = false AND braco::text = 'hitl'::text AND resolvido IS NOT NULL
  GROUP BY cenario
  ORDER BY cenario;
```

## Applied migrations

| Version | Name | SHA-256 |
|:--|:--|:--|
| 001 | `esquema_inicial` | `eb5fc7d647a2ac866afb9e60d53a543f7f8dba8945426b69e8dd1654fa8df341` |
| 002 | `estado_encerrado_na_origem` | `2b7604ada6e88f4e3001d8901656fcc462a3b3f5013b20949cba24b7aeb656a8` |
| 003 | `comando_verificacao` | `7c83085a170300bf10954b5384cf5eaed87f1ee1e55cf6741512d58489515933` |
| 004 | `observabilidade_reconciliacao` | `e3d07215e98c5cc836e2074a4d347484d097fe524dcb898097d339879505b4c3` |
| 005 | `idempotencia_global_evento` | `965b826550c444fc4bee2bfcd48357352f3b02b53eb2f5a7e5ecad287a60d05d` |
| 006 | `versao_scripts_aprovados` | `52ca53d137b997b8141f45724f327e28641d2196d6d1bf813a90238883a71dc5` |
| 007 | `acerto_avaliacao_humana` | `4451a40182396bab6d136cb86b0f5c7e5a5139ba46dc254e2b5fa1f1015444c9` |
| 008 | `alinhamento_kpis` | `1adfa9d5a3b16d33bc20c72e3a59e97592e01415db87f09020a3fea821ad2a0a` |

The optional `audit_log.experiment_run_id` and `evento_ingestao.incidente_id` are physical
foreign keys. A round can have multiple incident rows at schema level; the controlled CLI
refuses an ambiguous or replacement link. Reconciliation state/history and migration tracking
have no physical foreign keys to audit rows. Global event ingestion identity is maintained by
`evento_ingestao`; the older audit uniqueness rule alone does not cover every unmatched event.

The human-approval execution guard is application logic, not a database privilege boundary.
Use [migrations](../src/db/migrations/README.md) rather than manually copying this catalog as DDL.

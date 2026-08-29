-- Estado operacional e histórico significativo da reconciliação com o Zabbix.

CREATE TABLE IF NOT EXISTS reconciliacao_estado (
    id                     SMALLINT PRIMARY KEY CHECK (id = 1),
    status                 VARCHAR(16) NOT NULL CHECK (status IN ('sucesso', 'erro')),
    intervalo_segundos     INTEGER NOT NULL CHECK (intervalo_segundos >= 0),
    recuperados            INTEGER NOT NULL DEFAULT 0 CHECK (recuperados >= 0),
    ja_conhecidos          INTEGER NOT NULL DEFAULT 0 CHECK (ja_conhecidos >= 0),
    encerrados_na_origem   INTEGER NOT NULL DEFAULT 0 CHECK (encerrados_na_origem >= 0),
    mensagem_erro          TEXT,
    ts_inicio              TIMESTAMPTZ NOT NULL,
    ts_conclusao           TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE reconciliacao_estado IS
    'Último ciclo do reconciliador; a linha única é atualizada mesmo quando nada muda';

CREATE TABLE IF NOT EXISTS reconciliacao_historico (
    id                     BIGSERIAL PRIMARY KEY,
    status                 VARCHAR(16) NOT NULL CHECK (status IN ('sucesso', 'erro')),
    recuperados            INTEGER NOT NULL DEFAULT 0 CHECK (recuperados >= 0),
    ja_conhecidos          INTEGER NOT NULL DEFAULT 0 CHECK (ja_conhecidos >= 0),
    encerrados_na_origem   INTEGER NOT NULL DEFAULT 0 CHECK (encerrados_na_origem >= 0),
    mensagem_erro          TEXT,
    ts_inicio              TIMESTAMPTZ NOT NULL,
    ts_conclusao           TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE reconciliacao_historico IS
    'Ciclos com alteração ou erro; ciclos vazios atualizam somente reconciliacao_estado';

CREATE INDEX IF NOT EXISTS idx_reconciliacao_historico_conclusao
    ON reconciliacao_historico (ts_conclusao DESC);

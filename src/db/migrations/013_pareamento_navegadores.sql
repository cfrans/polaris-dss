-- Pareamento opcional de navegadores por HTTP na rede local (POLARIS_PAREAMENTO_HTTP).
-- O código nasce no terminal do servidor e vale uma vez; o navegador recebe um token próprio.
-- Somente hashes SHA-256 são guardados. Não substitui login, sessão nem aprovação humana.
CREATE TABLE IF NOT EXISTS pareamentos (
 id BIGSERIAL PRIMARY KEY,
 codigo_hash CHAR(64) NOT NULL UNIQUE,
 ts_criacao TIMESTAMPTZ NOT NULL DEFAULT now(),
 ts_expiracao_codigo TIMESTAMPTZ NOT NULL,
 token_hash CHAR(64) UNIQUE,
 ts_pareamento TIMESTAMPTZ,
 ts_expiracao TIMESTAMPTZ,
 origem VARCHAR(64),
 CHECK ((token_hash IS NULL) = (ts_pareamento IS NULL)),
 CHECK ((token_hash IS NULL) = (ts_expiracao IS NULL))
);

-- Identidade individual posterior à coleta: não altera avaliações históricas.
CREATE TABLE usuarios (
 id BIGSERIAL PRIMARY KEY,
 login VARCHAR(64) NOT NULL UNIQUE CHECK (login ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'),
 nome VARCHAR(100) NOT NULL,
 senha_hash TEXT NOT NULL,
 perfil VARCHAR(16) NOT NULL CHECK (perfil IN ('admin','operador')),
 ativo BOOLEAN NOT NULL DEFAULT TRUE,
 ts_criacao TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE sessoes (
 token_hash CHAR(64) PRIMARY KEY,
 usuario_id BIGINT NOT NULL REFERENCES usuarios(id),
 ts_criacao TIMESTAMPTZ NOT NULL DEFAULT now(),
 ts_atividade TIMESTAMPTZ NOT NULL DEFAULT now(),
 ts_expiracao TIMESTAMPTZ NOT NULL
);
CREATE INDEX sessoes_usuario_idx ON sessoes(usuario_id);
CREATE TABLE ciencia_scripts (
 usuario_id BIGINT NOT NULL REFERENCES usuarios(id),
 versao CHAR(64) NOT NULL,
 ts_ciencia TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (usuario_id, versao)
);
CREATE TABLE auth_limite (
 id INTEGER PRIMARY KEY CHECK (id = 1),
 janela TIMESTAMPTZ NOT NULL DEFAULT now(),
 tentativas INTEGER NOT NULL DEFAULT 0
);
INSERT INTO auth_limite(id) VALUES (1);

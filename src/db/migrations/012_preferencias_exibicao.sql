-- Preferências pessoais da interface; não altera registros do experimento.
CREATE TABLE IF NOT EXISTS preferencias_exibicao (
    usuario_id BIGINT PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    configuracao JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(configuracao) = 'object'),
    filtros_auditoria JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(filtros_auditoria) = 'object'),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

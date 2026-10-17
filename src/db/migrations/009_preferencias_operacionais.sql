-- Preferências globais persistidas; não representam autorização de remediação.
CREATE TABLE IF NOT EXISTS preferencias_operacionais (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    modo_preferencia TEXT NOT NULL DEFAULT 'desempate'
        CHECK (modo_preferencia IN ('desempate', 'desconto', 'desligado')),
    desconto_maximo NUMERIC NOT NULL DEFAULT 0.10
        CHECK (desconto_maximo >= 0 AND desconto_maximo <= 0.25),
    minimo_escolhas INTEGER NOT NULL DEFAULT 5 CHECK (minimo_escolhas BETWEEN 1 AND 100),
    versao INTEGER NOT NULL DEFAULT 1,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO preferencias_operacionais(id) VALUES (1) ON CONFLICT DO NOTHING;

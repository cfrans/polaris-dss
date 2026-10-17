-- Período operacional usado para mostrar recorrências no cartão do incidente.
ALTER TABLE preferencias_operacionais
    ADD COLUMN IF NOT EXISTS periodo_ocorrencias_dias INTEGER NOT NULL DEFAULT 30
        CHECK (periodo_ocorrencias_dias BETWEEN 1 AND 365);

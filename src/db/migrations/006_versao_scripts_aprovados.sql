ALTER TABLE audit_log ADD COLUMN versao_scripts CHAR(64);

COMMENT ON COLUMN audit_log.versao_scripts IS
    'SHA-256 do conjunto de scripts apresentado na decisão e enviado ao alvo';

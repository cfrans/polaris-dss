-- O comando de verificação usado para confirmar o restabelecimento passa a ser registrado junto do
-- comando de remediação. A trilha guarda o que foi de fato executado nas duas etapas, e não apenas
-- o que a base de conhecimento diz hoje: regra editada depois não altera o registro do passado.

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS comando_verificacao TEXT;

COMMENT ON COLUMN audit_log.comando_verificacao IS
    'Comando que confirmou o restabelecimento do serviço; define ts_conclusao';

"""Testes do runner de migrações que não dependem de um banco de pé.

A aplicação efetiva contra o PostgreSQL é exercitada manualmente ao subir o ambiente; o que se
protege aqui é a lógica de descoberta e, principalmente, a de integridade — que é o que impede o
esquema do banco divergir silenciosamente dos arquivos versionados.
"""

import pytest

from src.db.migrate import MigrationError, descobrir, verificar_integridade


def test_descobre_a_migracao_inicial():
    migracoes = descobrir()
    assert migracoes, "nenhuma migração encontrada"
    assert migracoes[0].versao == "001"
    assert migracoes[0].nome == "esquema_inicial"


def test_migracoes_em_ordem_crescente():
    versoes = [m.versao for m in descobrir()]
    assert versoes == sorted(versoes)


def test_checksum_estavel_e_independente_de_fim_de_linha(tmp_path):
    """O projeto roda em Windows e macOS: CRLF não pode fazer migração aplicada parecer alterada."""
    (tmp_path / "001_teste.sql").write_bytes(b"SELECT 1;\nSELECT 2;\n")
    lf = descobrir(tmp_path)[0].checksum
    (tmp_path / "001_teste.sql").write_bytes(b"SELECT 1;\r\nSELECT 2;\r\n")
    crlf = descobrir(tmp_path)[0].checksum
    assert lf == crlf


def test_nome_fora_do_padrao_e_rejeitado(tmp_path):
    (tmp_path / "adiciona-coluna.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="fora do padrão"):
        descobrir(tmp_path)


def test_numero_duplicado_e_rejeitado(tmp_path):
    (tmp_path / "001_um.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "001_dois.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(MigrationError, match="duplicado"):
        descobrir(tmp_path)


def test_diretorio_inexistente_e_rejeitado(tmp_path):
    with pytest.raises(MigrationError, match="não encontrado"):
        descobrir(tmp_path / "nao_existe")


def test_migracao_alterada_apos_aplicada_aborta(tmp_path):
    (tmp_path / "001_teste.sql").write_text("SELECT 1;", encoding="utf-8")
    migracoes = descobrir(tmp_path)
    with pytest.raises(MigrationError, match="alterada depois de aplicada"):
        verificar_integridade(migracoes, {"001": "checksum-de-antes-da-edicao"})


def test_banco_a_frente_do_repositorio_aborta(tmp_path):
    (tmp_path / "001_teste.sql").write_text("SELECT 1;", encoding="utf-8")
    migracoes = descobrir(tmp_path)
    registradas = {migracoes[0].versao: migracoes[0].checksum, "002": "qualquer"}
    with pytest.raises(MigrationError, match="à frente do repositório"):
        verificar_integridade(migracoes, registradas)


def test_estado_consistente_passa(tmp_path):
    (tmp_path / "001_teste.sql").write_text("SELECT 1;", encoding="utf-8")
    migracoes = descobrir(tmp_path)
    verificar_integridade(migracoes, {m.versao: m.checksum for m in migracoes})


def test_migracao_nao_aplicada_ainda_passa(tmp_path):
    (tmp_path / "001_teste.sql").write_text("SELECT 1;", encoding="utf-8")
    verificar_integridade(descobrir(tmp_path), {})

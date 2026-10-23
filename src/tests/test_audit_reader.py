"""Audit filtering, bounded exports and preservation of persisted incident facts."""
import csv
import io
from datetime import datetime, timezone

import pytest
from psycopg.types.json import Jsonb

WINDOW = {'inicio': '2026-10-01T00:00:00Z', 'fim': '2026-11-01T00:00:00Z'}


def record(conn, event='audit-event', host='Host-a', operator=None, decision=None,
           status='pendente', created='2026-10-15T12:00:00+00:00', rule='R003', output=None):
    return conn.execute('''INSERT INTO audit_log(id_evento,hostname,operador,decisao_humana,
        status_execucao,ts_criacao,regra_disparada,comando_executado,output_execucao,explicabilidade)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (event, host, operator, decision, status, created, rule, 'true', output,
         Jsonb({'diagnostico': 'Historical evidence', 'acao_escolhida': {'nome': 'Historical action'}}))).fetchone()['id']


def listing(client, **filters):
    response = client.get('/api/v1/auditoria', params={**WINDOW, **filters})
    assert response.status_code == 200, response.text
    return response.json()


def test_filtering_pagination_and_total_use_persisted_values(cliente, conn):
    first = record(conn, 'one', operator='Caio', decision=True, status='falha')
    second = record(conn, 'two', host='Host-b', operator='caio', decision=False, status='rejeitado')
    third = record(conn, 'three', host='literal%_host', rule=None, status='encerrado_na_origem')
    record(conn, 'before', created='2026-09-30T23:59:59+00:00')
    record(conn, 'end', created='2026-11-01T00:00:00+00:00')
    conn.commit()
    page = listing(cliente, limit=1, offset=1)
    assert page['total'] == 3 and page['itens'][0]['id'] == second
    assert listing(cliente, offset=99)['total'] == 3
    assert listing(cliente, host='host-A', operador='CAI', regra='R003', decisao='aprovada', status='falha')['itens'][0]['id'] == first
    assert listing(cliente, decisao='rejeitada')['itens'][0]['id'] == second
    assert listing(cliente, host='%_', decisao='sem_decisao')['itens'][0]['id'] == third
    assert listing(cliente, host="' OR true --")['total'] == 0
    assert listing(cliente, regra='R999')['total'] == 0


def test_detail_exports_and_list_do_not_mutate_or_contact_external_services(cliente, conn, monkeypatch):
    from src.api import routes
    def unexpected(*args, **kwargs):
        raise AssertionError('Audit must not contact Zabbix or execute actions')
    monkeypatch.setattr(routes, 'ZabbixClient', unexpected)
    monkeypatch.setattr(routes, 'executar', unexpected)
    incident = record(conn, output='<script>invalidMarkup()</script>', decision=True, status='falha')
    record(conn, 'unmatched', rule=None, status='no_match')
    conn.commit()
    before = conn.execute('SELECT * FROM audit_log ORDER BY id').fetchall()
    runs = conn.execute('SELECT * FROM experiment_run ORDER BY id').fetchall()
    assert listing(cliente)['total'] == 2
    detail = cliente.get(f'/api/v1/auditoria/{incident}').json()
    assert detail['decisao_humana'] is True and detail['status_execucao'] == 'falha'
    assert detail['ts_exibicao'] is None and detail['ts_aprovacao'] is None
    assert detail['explicabilidade']['acao_escolhida']['nome'] == 'Historical action'
    assert 'nome_regra' not in detail
    for format in ['csv', 'json']:
        response = cliente.get('/api/v1/auditoria/exportar', params={**WINDOW, 'formato': format})
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'attachment' in response.headers['content-disposition']
    assert cliente.get('/api/v1/auditoria/999999').status_code == 404
    assert conn.execute('SELECT * FROM audit_log ORDER BY id').fetchall() == before
    assert conn.execute('SELECT * FROM experiment_run ORDER BY id').fetchall() == runs


def test_export_csv_protects_formula_cells_and_json_preserves_original(cliente, conn):
    raw = '\t =HYPERLINK("https://example.invalid")\nsecond line'
    record(conn, host='@host', operator='-operator', output=raw)
    conn.commit()
    csv_response = cliente.get('/api/v1/auditoria/exportar', params={**WINDOW, 'formato': 'csv'})
    assert csv_response.content.startswith(b'\xef\xbb\xbf')
    row = list(csv.DictReader(io.StringIO(csv_response.content.decode('utf-8-sig'))))[0]
    assert row['hostname'] == "'@host" and row['operador'] == "'-operator"
    assert row['output_execucao'] == "'" + raw
    exported = cliente.get('/api/v1/auditoria/exportar', params={**WINDOW, 'formato': 'json'}).json()
    assert exported['itens'][0]['output_execucao'] == raw and exported['total'] == 1
    assert exported['filtros']['inicio'].endswith('+00:00')


def test_export_is_filtered_complete_and_explicitly_rejects_excess(cliente, conn, monkeypatch):
    for n in range(501):
        record(conn, str(n))
    conn.commit()
    path = '/api/v1/auditoria/exportar'
    assert cliente.get(path, params={**WINDOW, 'formato': 'json'}).status_code == 413
    assert cliente.get(path, params={**WINDOW, 'formato': 'json', 'host': 'missing'}).json()['total'] == 0
    from src.api import audit_routes
    monkeypatch.setattr(audit_routes, 'EXPORT_BYTES', 32)
    assert cliente.get(path, params={**WINDOW, 'formato': 'csv', 'host': 'missing'}).status_code == 413


@pytest.mark.parametrize('params', [
    {'inicio': '2026-10-01T00:00:00'}, {'fim': 'invalid'},
    {'inicio': '2026-11-01T00:00:00Z'}, {'inicio': '2020-01-01T00:00:00Z'},
    {'status': 'invented'}, {'decisao': 'yes'}, {'limit': 101}, {'limit': 0},
    {'offset': -1}, {'offset': 100001}, {'host': 'a'*129},
])
def test_invalid_filters_are_rejected(cliente, params):
    assert cliente.get('/api/v1/auditoria', params={**WINDOW, **params}).status_code == 422


def test_offsets_are_normalized_to_utc_and_defaults_are_bounded(cliente):
    data = listing(cliente, inicio='2026-09-30T21:00:00-03:00')
    assert data['filtros']['inicio'] == '2026-10-01T00:00:00+00:00'
    defaults = cliente.get('/api/v1/auditoria').json()['filtros']
    assert (datetime.fromisoformat(defaults['fim']) - datetime.fromisoformat(defaults['inicio'])).days == 30


def test_free_search_reads_all_matching_records_before_pagination_and_exports(cliente, conn):
    for n in range(30): record(conn,str(n),output='Other data')
    target=record(conn,'needle',output='Literal %_ & special; recuperação correta')
    conn.commit()
    found=listing(cliente,q='%_ &',limit=10)
    assert found['total']==1 and found['itens'][0]['id']==target
    assert listing(cliente,q="' OR true --")['total']==0
    assert listing(cliente,q='RECUPERAÇÃO')['total']==1
    assert listing(cliente,q='Historical action')['total']==31
    assert listing(cliente,q='Sem decisão')['total']==31
    assert listing(cliente,q='15/10/2026')['total']==31
    exported=cliente.get('/api/v1/auditoria/exportar',params={**WINDOW,'formato':'json','q':'%_ &'}).json()
    assert exported['total']==1 and exported['itens'][0]['id']==target
    assert exported['filtros']['q']=='%_ &'


@pytest.mark.parametrize('column', ['id','criacao','host','regra','decisao','status','operador'])
def test_sorting_is_global_stable_and_exported_in_selected_order(cliente, conn, column):
    record(conn,'sort-1',host='zeta',operator='zoe',decision=False,status='rejeitado',rule='R003',created='2026-10-17T00:00:00Z')
    record(conn,'sort-2',host='Alpha',operator='Ana',decision=True,status='falha',rule='R001',created='2026-10-15T00:00:00Z')
    record(conn,'sort-3',host='beta',operator='Bruno',decision=None,status='sucesso',rule='R002',created='2026-10-16T00:00:00Z')
    conn.commit()
    ascending=listing(cliente,ordenar=column,direcao='asc')['itens']
    descending=listing(cliente,ordenar=column,direcao='desc')['itens']
    assert [r['id'] for r in ascending]==[r['id'] for r in reversed(descending)]
    assert listing(cliente,ordenar=column,direcao='asc',limit=1,offset=1)['itens'][0]['id']==ascending[1]['id']
    exported=cliente.get('/api/v1/auditoria/exportar',params={**WINDOW,'formato':'json','ordenar':column,'direcao':'asc'}).json()
    assert [r['id'] for r in exported['itens']]==[r['id'] for r in ascending]


@pytest.mark.parametrize('params',[{'q':'a'*201},{'ordenar':'id; DROP TABLE audit_log'},{'direcao':'ASC NULLS FIRST'}])
def test_search_and_sort_validation_reject_unbounded_or_executable_input(cliente,params):
    assert cliente.get('/api/v1/auditoria',params={**WINDOW,**params}).status_code==422

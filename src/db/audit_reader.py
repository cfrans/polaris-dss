"""Bounded operational audit queries, independent of experimental measurements."""

SUMMARY_COLUMNS = (
    "id, id_evento, hostname, ip_address, regra_disparada, status_execucao, "
    "decisao_humana, operador, confianca_calculada, ts_criacao, ts_aprovacao, ts_conclusao"
)
DETAIL_COLUMNS = SUMMARY_COLUMNS + (
    ", severidade, banda_confianca, explicabilidade, versao_kb, versao_motor, versao_scripts, "
    "motivo_rejeicao, comando_executado, comando_verificacao, exit_code, output_execucao, "
    "output_erro, ts_deteccao, ts_exibicao, experiment_run_id"
)


def audit_where(filters):
    clauses = ["ts_criacao >= %s", "ts_criacao < %s"]
    params = [filters['inicio'], filters['fim']]
    for key, column in [('host', 'hostname'), ('operador', 'operador')]:
        if filters[key]:
            clauses.append(f"strpos(lower(COALESCE({column}, '')), lower(%s)) > 0")
            params.append(filters[key])
    for key, column in [('regra', 'regra_disparada'), ('status', 'status_execucao')]:
        if filters[key]:
            clauses.append(f"{column} = %s")
            params.append(filters[key])
    decision = filters['decisao']
    if decision:
        clauses.append({'aprovada': 'decisao_humana IS TRUE',
                        'rejeitada': 'decisao_humana IS FALSE',
                        'sem_decisao': 'decisao_humana IS NULL'}[decision])
    return ' AND '.join(clauses), params


def list_audit(conn, filters, limit=25, offset=0, *, complete=False):
    where, params = audit_where(filters)
    columns = DETAIL_COLUMNS if complete else SUMMARY_COLUMNS
    with conn.cursor() as cur:
        cur.execute(f"SELECT {columns} FROM audit_log WHERE {where} "
                    "ORDER BY ts_criacao DESC, id DESC LIMIT %s OFFSET %s",
                    (*params, limit, offset))
        rows = cur.fetchall()
    return rows


def count_audit(conn, filters):
    where, params = audit_where(filters)
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS total FROM audit_log WHERE {where}", params)
        return cur.fetchone()['total']


def audit_detail(conn, incident_id):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {DETAIL_COLUMNS} FROM audit_log WHERE id=%s", (incident_id,))
        return cur.fetchone()

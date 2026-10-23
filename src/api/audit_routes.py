"""Read persisted incident facts without changing their lifecycle or contacting targets."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from ..db import audit_reader
from .routes import get_conn

router = APIRouter(prefix='/api/v1/auditoria', tags=['auditoria'])
EXPORT_LIMIT = 500
EXPORT_BYTES = 8 * 1024 * 1024


def audit_filters(
    inicio: datetime | None = None, fim: datetime | None = None,
    host: str = Query('', max_length=128), regra: str = Query('', max_length=16),
    operador: str = Query('', max_length=64),
    status: Literal['', 'pendente', 'executando', 'sucesso', 'falha', 'timeout',
                    'rejeitado', 'no_match', 'encerrado_na_origem'] = '',
    decisao: Literal['', 'aprovada', 'rejeitada', 'sem_decisao'] = '',
    q: str = Query('', max_length=200),
    ordenar: Literal['id', 'criacao', 'host', 'regra', 'decisao', 'status', 'operador'] = 'criacao',
    direcao: Literal['asc', 'desc'] = 'desc',
):
    end = fim or datetime.now(timezone.utc)
    start = inicio or end - timedelta(days=30)
    if start.utcoffset() is None or end.utcoffset() is None:
        raise HTTPException(422, 'Informe o fuso horário nas datas.')
    if start >= end or end - start > timedelta(days=366):
        raise HTTPException(422, 'Escolha um período válido de até 366 dias.')
    return {'inicio': start.astimezone(timezone.utc), 'fim': end.astimezone(timezone.utc),
            'host': host, 'regra': regra, 'operador': operador, 'status': status, 'decisao': decisao,
            'q': q.strip(), 'ordenar': ordenar, 'direcao': direcao}


def encode(data):
    return jsonable_encoder(data, custom_encoder={
        datetime: lambda value: value.astimezone(timezone.utc).isoformat()})


@router.get('')
def audit_list(filters=Depends(audit_filters), limit: int = Query(25, ge=1, le=100),
               offset: int = Query(0, ge=0, le=100000), conn=Depends(get_conn)):
    rows = audit_reader.list_audit(conn, filters, limit, offset)
    return encode({'itens': rows, 'total': audit_reader.count_audit(conn, filters),
                   'limit': limit, 'offset': offset, 'filtros': filters})


def csv_cell(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value)
    # Quoting alone does not prevent formula execution when a CSV is opened in a spreadsheet.
    if text.lstrip('\ufeff \t\r\n\v\f').startswith(('=', '+', '-', '@')):
        text = "'" + text
    return text


@router.get('/exportar')
def audit_export(formato: Literal['csv', 'json'], filters=Depends(audit_filters),
                 conn=Depends(get_conn)):
    rows = encode(audit_reader.list_audit(conn, filters, EXPORT_LIMIT + 1, complete=True))
    if len(rows) > EXPORT_LIMIT:
        raise HTTPException(413, 'A exportação permite até 500 registros. Refine os filtros.')
    if formato == 'json':
        content = json.dumps({'gerado_em': datetime.now(timezone.utc).isoformat(),
                              'filtros': encode(filters), 'total': len(rows), 'itens': rows},
                             ensure_ascii=False).encode('utf-8')
        media_type = 'application/json'
    else:
        stream = io.StringIO(newline='')
        columns = [column.strip() for column in audit_reader.DETAIL_COLUMNS.split(',')]
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows([[csv_cell(row.get(column)) for column in columns] for row in rows])
        content = ('\ufeff' + stream.getvalue()).encode('utf-8')
        media_type = 'text/csv'
    if len(content) > EXPORT_BYTES:
        raise HTTPException(413, 'O arquivo excede 8 MiB. Refine os filtros.')
    return Response(content, media_type=media_type, headers={
        'Content-Disposition': f'attachment; filename="polaris-auditoria.{formato}"'})


@router.get('/{incident_id}')
def audit_record(incident_id: int = Path(ge=1), conn=Depends(get_conn)):
    row = audit_reader.audit_detail(conn, incident_id)
    if row is None:
        raise HTTPException(404, 'Registro de auditoria não encontrado.')
    return encode(row)

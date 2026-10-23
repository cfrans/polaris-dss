"""Personal presentation settings, separate from shared operational preferences."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.types.json import Jsonb

from ..db.connection import conectar
from . import auth

router = APIRouter(prefix='/api/v1/auth/exibicao', tags=['exibição'])


class DisplayInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    density: Literal['comfortable', 'compact'] = 'comfortable'
    page_size: Literal[10, 25, 50, 100] = 25
    remember_filters: bool = False
    time_zone: Literal['local', 'utc'] = 'local'
    motion: Literal['system', 'reduced'] = 'system'


class AuditState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: date | None = None
    end: date | None = None
    host: str = Field(default='', max_length=128)
    regra: str = Field(default='', max_length=16)
    operador: str = Field(default='', max_length=64)
    status: Literal['', 'pendente', 'executando', 'sucesso', 'falha', 'timeout',
                    'rejeitado', 'no_match', 'encerrado_na_origem'] = ''
    decisao: Literal['', 'aprovada', 'rejeitada', 'sem_decisao'] = ''
    q: str = Field(default='', max_length=200)
    ordenar: Literal['id', 'criacao', 'host', 'regra', 'decisao', 'status', 'operador'] = 'criacao'
    direcao: Literal['asc', 'desc'] = 'desc'

    @model_validator(mode='after')
    def valid_window(self):
        if bool(self.start) != bool(self.end):
            raise ValueError('Informe as duas datas do filtro.')
        if self.start and (self.start > self.end or (self.end-self.start).days > 365):
            raise ValueError('Período de auditoria inválido.')
        return self


def read_settings(conn, user_id):
    row = conn.execute('SELECT configuracao,filtros_auditoria FROM preferencias_exibicao WHERE usuario_id=%s', (user_id,)).fetchone()
    settings = DisplayInput.model_validate(row['configuracao'] if row else {}).model_dump()
    return {**settings, 'audit': row['filtros_auditoria'] if row and settings['remember_filters'] else {}}


@router.get('')
def get_display(request: Request):
    user = auth.authenticate(request)
    with conectar() as conn:
        return read_settings(conn, user['id'])


@router.put('')
def save_display(request: Request, body: DisplayInput):
    user = auth.authenticate(request)
    with conectar() as conn:
        conn.execute('''INSERT INTO preferencias_exibicao(usuario_id,configuracao)
            VALUES(%s,%s) ON CONFLICT(usuario_id) DO UPDATE SET
            configuracao=excluded.configuracao,
            filtros_auditoria=CASE WHEN %s THEN preferencias_exibicao.filtros_auditoria ELSE '{}'::jsonb END,
            atualizado_em=clock_timestamp()''', (user['id'], Jsonb(body.model_dump()), body.remember_filters))
        conn.commit()
        return read_settings(conn, user['id'])


@router.put('/auditoria')
def save_audit_state(request: Request, body: AuditState):
    user = auth.authenticate(request)
    with conectar() as conn:
        # The condition is checked on the locked row; a concurrent opt-out cannot restore filters.
        row = conn.execute('''UPDATE preferencias_exibicao SET filtros_auditoria=%s,
            atualizado_em=clock_timestamp() WHERE usuario_id=%s
            AND configuracao->>'remember_filters'='true' RETURNING usuario_id''',
            (Jsonb(body.model_dump(mode='json')), user['id'])).fetchone()
        conn.commit()
    return {'saved': row is not None}

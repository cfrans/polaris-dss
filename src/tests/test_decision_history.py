"""Operational charts read persisted decisions, never execution outcomes or experiment KPIs."""

from datetime import datetime, timedelta, timezone

import pytest

from src.db import queries

NOW = datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)


def record(conn, event, decision=None, decided_at=None, *, rule="R003", status="pendente", created_at=None):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO audit_log (id_evento, hostname, regra_disparada, decisao_humana,
                       ts_aprovacao, status_execucao, ts_criacao)
               VALUES (%s, 'test-host', %s, %s, %s, %s, %s) RETURNING id""",
            (event, rule, decision, decided_at, status, created_at or NOW),
        )
        return cur.fetchone()["id"]


def test_history_uses_decision_time_and_boolean_independent_of_current_execution_state(conn):
    record(conn, "approved-failed", True, NOW - timedelta(hours=1), status="falha",
           created_at=NOW - timedelta(days=40))
    record(conn, "approved-running", True, NOW - timedelta(hours=1), status="executando")
    record(conn, "rejected", False, NOW - timedelta(hours=1), status="rejeitado")
    record(conn, "no-match", rule=None, status="no_match")
    record(conn, "closed-without-decision", rule=None, status="encerrado_na_origem")
    record(conn, "missing-decision-time", True, None, status="sucesso")
    record(conn, "missing-decision-boolean", None, NOW - timedelta(hours=1))
    data = queries.read_decision_history(conn, "24h", now=NOW)
    assert data["totais"] == {"aprovadas": 2, "rejeitadas": 1}
    assert sum(row["aprovadas"] for row in data["series"]) == 2
    assert data["series"][-2]["rejeitadas"] == 1
    assert data["series"][-1]["aprovadas"] == 0


@pytest.mark.parametrize("period,days,unit,length", [("24h", 1, "hour", 25), ("7d", 7, "day", 8), ("30d", 30, "day", 31)])
def test_history_window_is_start_inclusive_end_exclusive_and_fills_zero_buckets(conn, period, days, unit, length):
    start = NOW - timedelta(days=days)
    record(conn, "inside-start", True, start)
    record(conn, "before-start", True, start - timedelta(microseconds=1))
    record(conn, "at-end", False, NOW)
    record(conn, "future", True, NOW + timedelta(days=1))
    data = queries.read_decision_history(conn, period, now=NOW)
    assert data["inicio"] == start
    assert data["fim"] == NOW
    assert data["agrupamento"] == unit
    assert len(data["series"]) == length
    assert data["series"][0]["aprovadas"] == 1
    assert data["totais"] == {"aprovadas": 1, "rejeitadas": 0}


def test_history_utc_buckets_do_not_depend_on_database_session_timezone(conn):
    with conn.cursor() as cur:
        cur.execute("SET LOCAL TIME ZONE 'America/Sao_Paulo'")
    record(conn, "utc-midnight", False, datetime(2026, 10, 14, 0, 15, tzinfo=timezone.utc))
    data = queries.read_decision_history(conn, "7d", now=NOW)
    assert data["series"][-1]["inicio"] == datetime(2026, 10, 14, tzinfo=timezone.utc)
    assert data["series"][-1]["rejeitadas"] == 1


def test_recent_filter_excludes_missing_rules_before_limit_including_closed_no_match(conn):
    expected = record(conn, "matched-older", rule="R003", created_at=NOW - timedelta(days=1))
    for index in range(8):
        record(conn, f"unmatched-{index}", rule=None,
               status="no_match" if index % 2 else "encerrado_na_origem")
    unknown = record(conn, "unknown-rule", rule="R999")
    filtered = queries.listar_incidentes(conn, status=None, limite=6, include_unmatched=False)
    assert {row["id"] for row in filtered} == {expected, unknown}
    assert all(row["regra_disparada"] is not None for row in filtered)
    assert len(queries.listar_incidentes(conn, status=None, limite=6)) == 6
    assert len(queries.listar_incidentes(conn, status="no_match", include_unmatched=True)) == 4


def test_read_only_endpoints_preserve_audit_rows_and_do_not_mark_cards_viewed(cliente, conn):
    record(conn, "unmatched", rule=None, status="no_match")
    record(conn, "approved", True, datetime.now(timezone.utc) - timedelta(hours=1), status="falha")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM audit_log ORDER BY id")
        before = cur.fetchall()
    assert cliente.get("/api/v1/incidentes?status=&include_unmatched=false").json()["total"] == 1
    assert cliente.get("/api/v1/incidentes?status=").json()["total"] == 2
    for period in ("24h", "7d", "30d"):
        response = cliente.get(f"/api/v1/historico-decisoes?period={period}")
        assert response.status_code == 200
        assert response.json()["totais"] == {"aprovadas": 1, "rejeitadas": 0}
        assert response.json()["fuso"] == "UTC"
    assert cliente.get("/api/v1/historico-decisoes?period=365d").status_code == 422
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM audit_log ORDER BY id")
        assert cur.fetchall() == before

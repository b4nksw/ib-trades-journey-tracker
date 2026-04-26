import pytest
from pathlib import Path
from datetime import datetime, timezone
from db import init_db, insert_execution, insert_dividend, upsert_position, \
    insert_portfolio_snapshot, get_executions_for_symbol, get_all_symbols, \
    get_all_positions, get_dividends_for_symbol, get_last_sync, set_last_sync


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def _exec(ib_exec_id="exec_001", symbol="TSLA", action="BUY", qty=5, price=10.0):
    return {
        "symbol": symbol, "action": action, "quantity": qty, "price": price,
        "commission": 1.0, "executed_at": "2024-01-15T10:00:00",
        "exchange": "NASDAQ", "ib_exec_id": ib_exec_id,
    }


def test_init_creates_tables(conn):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"executions", "dividends", "positions", "portfolio_snapshots", "sync_log"} <= tables


def test_insert_execution_dedup(conn):
    insert_execution(conn, _exec("e1"))
    insert_execution(conn, _exec("e1"))  # duplicate
    conn.commit()
    count = conn.execute("SELECT count(*) FROM executions").fetchone()[0]
    assert count == 1


def test_get_executions_for_symbol(conn):
    insert_execution(conn, _exec("e1", symbol="TSLA"))
    insert_execution(conn, _exec("e2", symbol="AAPL"))
    conn.commit()
    rows = get_executions_for_symbol(conn, "TSLA")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "TSLA"


def test_get_all_symbols(conn):
    insert_execution(conn, _exec("e1", symbol="TSLA"))
    insert_execution(conn, _exec("e2", symbol="AAPL"))
    conn.commit()
    symbols = get_all_symbols(conn)
    assert set(symbols) == {"TSLA", "AAPL"}


def test_upsert_position_replaces(conn):
    pos = {"symbol": "TSLA", "quantity": 5, "ib_avg_cost": 10.0, "adj_avg_cost": 10.0,
           "market_value": 60.0, "unrealized_pnl_ib": 10.0, "unrealized_pnl_adj": 10.0,
           "realized_pnl": 0.0, "last_updated": "2024-01-15T17:00:00"}
    upsert_position(conn, pos)
    conn.commit()
    pos["market_value"] = 70.0
    upsert_position(conn, pos)
    conn.commit()
    row = conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert row == 1
    mv = conn.execute("SELECT market_value FROM positions WHERE symbol='TSLA'").fetchone()[0]
    assert mv == 70.0


def test_sync_log(conn):
    assert get_last_sync(conn, "executions") is None
    now = datetime.now(timezone.utc)
    set_last_sync(conn, "executions", now)
    conn.commit()  # add this line
    result = get_last_sync(conn, "executions")
    assert abs((result - now).total_seconds()) < 1


def test_insert_dividend(conn):
    div = {"symbol": "TSLA", "amount": 2.50, "ex_date": "2024-03-01", "pay_date": "2024-03-15"}
    insert_dividend(conn, div)
    conn.commit()
    rows = get_dividends_for_symbol(conn, "TSLA")
    assert len(rows) == 1
    assert rows[0]["amount"] == 2.50

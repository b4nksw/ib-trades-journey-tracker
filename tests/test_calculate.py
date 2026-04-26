import pytest
from pathlib import Path
from datetime import datetime, timezone
from db import init_db, insert_execution
from calculate import compute_adj_avg, compute_positions, compute_portfolio_snapshot


def _exec(ib_exec_id, action, qty, price, dt, symbol="TSLA"):
    return {"symbol": symbol, "action": action, "quantity": qty, "price": price,
            "commission": 1.0, "executed_at": dt, "exchange": "NASDAQ",
            "ib_exec_id": ib_exec_id}


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


# --- compute_adj_avg ---

def test_simple_buy():
    execs = [_exec("e1", "BUY", 5, 10.0, "2024-01-01T10:00:00")]
    adj_avg, realized, qty = compute_adj_avg(execs)
    assert qty == 5
    assert adj_avg == pytest.approx(10.0)
    assert realized == 0.0


def test_sell_above_avg_lowers_adj_avg():
    """Your core formula: 5@10, sell 3@15 → adj_avg = (50-45)/2 = 2.50"""
    execs = [
        _exec("e1", "BUY",  5, 10.0, "2024-01-01"),
        _exec("e2", "SELL", 3, 15.0, "2024-06-01"),
    ]
    adj_avg, realized, qty = compute_adj_avg(execs)
    assert qty == 2
    assert adj_avg == pytest.approx(2.5)
    assert realized == pytest.approx(15.0)  # (15-10)*3


def test_sell_below_avg_raises_adj_avg():
    """5@10, sell 3@8 → adj_avg = (50-24)/2 = 13.0"""
    execs = [
        _exec("e1", "BUY",  5, 10.0, "2024-01-01"),
        _exec("e2", "SELL", 3,  8.0, "2024-06-01"),
    ]
    adj_avg, realized, qty = compute_adj_avg(execs)
    assert qty == 2
    assert adj_avg == pytest.approx(13.0)
    assert realized == pytest.approx(-6.0)  # (8-10)*3


def test_negative_adj_avg_position_is_free():
    """5@10, sell 4@15 → adj_avg = (50-60)/1 = -10.0 (remaining share is 'free')"""
    execs = [
        _exec("e1", "BUY",  5, 10.0, "2024-01-01"),
        _exec("e2", "SELL", 4, 15.0, "2024-06-01"),
    ]
    adj_avg, realized, qty = compute_adj_avg(execs)
    assert qty == 1
    assert adj_avg == pytest.approx(-10.0)
    assert realized == pytest.approx(20.0)  # (15-10)*4


def test_close_and_reopen_resets_adj_avg():
    """Sell all, then buy again — new position starts fresh."""
    execs = [
        _exec("e1", "BUY",  5, 10.0, "2024-01-01"),
        _exec("e2", "SELL", 5, 15.0, "2024-06-01"),
        _exec("e3", "BUY",  3,  8.0, "2024-12-01"),
    ]
    adj_avg, realized, qty = compute_adj_avg(execs)
    assert qty == 3
    assert adj_avg == pytest.approx(8.0)
    assert realized == pytest.approx(25.0)  # (15-10)*5


def test_multiple_buys_weighted_avg():
    """5@10, 3@8 → (50+24)/8 = 9.25"""
    execs = [
        _exec("e1", "BUY", 5, 10.0, "2024-01-01"),
        _exec("e2", "BUY", 3,  8.0, "2024-03-01"),
    ]
    adj_avg, realized, qty = compute_adj_avg(execs)
    assert qty == 8
    assert adj_avg == pytest.approx(9.25)
    assert realized == 0.0


def test_chronological_ordering():
    """compute_adj_avg sorts by executed_at regardless of input order."""
    execs = [
        _exec("e2", "SELL", 3, 15.0, "2024-06-01"),  # listed first
        _exec("e1", "BUY",  5, 10.0, "2024-01-01"),  # listed second
    ]
    adj_avg, realized, qty = compute_adj_avg(execs)
    assert qty == 2
    assert adj_avg == pytest.approx(2.5)


# --- compute_positions ---

def test_compute_positions_writes_to_db(conn):
    insert_execution(conn, _exec("e1", "BUY",  5, 10.0, "2024-01-15T10:00:00"))
    insert_execution(conn, _exec("e2", "SELL", 3, 15.0, "2024-06-20T14:00:00"))
    conn.commit()

    ib_pos = {"TSLA": {"ib_avg_cost": 10.0, "market_value": 24.0}}
    compute_positions(conn, ib_pos)

    row = dict(conn.execute("SELECT * FROM positions WHERE symbol='TSLA'").fetchone())
    assert row["quantity"] == pytest.approx(2.0)
    assert row["adj_avg_cost"] == pytest.approx(2.5)
    assert row["ib_avg_cost"] == 10.0
    assert row["realized_pnl"] == pytest.approx(15.0)
    assert row["unrealized_pnl_adj"] == pytest.approx(24.0 - 2.5 * 2)  # 19.0


# --- compute_portfolio_snapshot ---

def test_compute_portfolio_snapshot(conn):
    conn.execute("""
        INSERT INTO positions (symbol, quantity, ib_avg_cost, adj_avg_cost,
            market_value, unrealized_pnl_ib, unrealized_pnl_adj, realized_pnl, last_updated)
        VALUES ('TSLA', 2, 10.0, 2.5, 24.0, 4.0, 19.0, 15.0, '2024-06-20T17:00:00')
    """)
    conn.commit()

    compute_portfolio_snapshot(conn, {"total_nav": 50000.0, "cash_balance": 15000.0})

    snap = dict(conn.execute(
        "SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone())
    assert snap["cash_balance"] == 15000.0
    assert snap["invested_value"] == pytest.approx(24.0)
    assert snap["largest_position_symbol"] == "TSLA"
    assert snap["investment_ratio"] == pytest.approx(24.0 / 50000.0, abs=0.0001)

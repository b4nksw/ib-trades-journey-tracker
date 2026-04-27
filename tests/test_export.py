import pytest
from pathlib import Path
from db import init_db, insert_execution, upsert_position, insert_portfolio_snapshot, insert_dividend
from export import export_stock_journal, export_portfolio_summary, build_env

TEMPLATES = Path(__file__).parent.parent / "templates"


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    insert_execution(c, {"symbol": "TSLA", "action": "BUY", "quantity": 5,
        "price": 10.0, "commission": 1.0, "executed_at": "2024-01-15T10:00:00",
        "exchange": "NASDAQ", "ib_exec_id": "e1"})
    insert_execution(c, {"symbol": "TSLA", "action": "SELL", "quantity": 3,
        "price": 15.0, "commission": 1.0, "executed_at": "2024-06-20T14:00:00",
        "exchange": "NASDAQ", "ib_exec_id": "e2"})
    upsert_position(c, {"symbol": "TSLA", "quantity": 2, "ib_avg_cost": 10.0,
        "adj_avg_cost": 2.5, "market_value": 24.0, "unrealized_pnl_ib": 4.0,
        "unrealized_pnl_adj": 19.0, "realized_pnl": 15.0,
        "last_updated": "2024-06-20T17:00:00"})
    insert_dividend(c, {"symbol": "TSLA", "amount": 2.50,
        "ex_date": "2024-03-01", "pay_date": "2024-03-15"})
    insert_portfolio_snapshot(c, {"snapshot_date": "2024-06-20", "total_nav": 50000.0,
        "cash_balance": 15000.0, "invested_value": 24.0, "investment_ratio": 0.0005,
        "cash_ratio": 0.30, "largest_position_symbol": "TSLA",
        "largest_position_value": 24.0, "total_unrealized_pnl_ib": 4.0,
        "total_unrealized_pnl_adj": 19.0, "total_realized_pnl": 15.0})
    c.commit()
    return c


def test_stock_journal_contains_key_fields(conn, tmp_path):
    env = build_env(TEMPLATES)
    export_stock_journal(conn, "TSLA", env, tmp_path / "journal")
    content = (tmp_path / "journal" / "TSLA.md").read_text()
    assert "# TSLA" in content
    assert "$10.00" in content   # IB avg cost
    assert "$2.50" in content    # adj avg cost
    assert "BUY" in content
    assert "SELL" in content
    assert "$2.50" in content    # dividend amount


def test_stock_journal_shows_adj_avg_after_each_trade(conn, tmp_path):
    env = build_env(TEMPLATES)
    export_stock_journal(conn, "TSLA", env, tmp_path / "journal")
    content = (tmp_path / "journal" / "TSLA.md").read_text()
    assert "| 2024-01-15 | BUY | 5.0 | $10.00 | $1.00 | $10.00 |" in content
    assert "| 2024-06-20 | SELL | 3.0 | $15.00 | $1.00 | $2.50 |" in content


def test_pnl_filter_negative_value():
    from export import _pnl
    assert _pnl(-5.0) == "-$5.00"
    assert _pnl(15.0) == "+$15.00"
    assert _pnl(None) == "N/A"


def test_portfolio_summary_shows_health(conn, tmp_path):
    env = build_env(TEMPLATES)
    export_portfolio_summary(conn, env, tmp_path / "journal")
    content = (tmp_path / "journal" / "portfolio_summary.md").read_text()
    assert "TSLA" in content
    assert "$50,000.00" in content
    assert "$15,000.00" in content

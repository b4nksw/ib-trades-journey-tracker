import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader
from db import get_all_symbols, get_executions_for_symbol, get_dividends_for_symbol, get_all_positions
from calculate import compute_adj_avg

TEMPLATES_DIR = Path(__file__).parent / "templates"
JOURNAL_DIR = Path(__file__).parent / "journal"


def _currency(value) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _pnl(value) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}${value:,.2f}"


def build_env(templates_dir: Path = TEMPLATES_DIR) -> Environment:
    env = Environment(loader=FileSystemLoader(str(templates_dir)), keep_trailing_newline=True)
    env.filters["currency"] = _currency
    env.filters["pnl"] = _pnl
    return env


def export_stock_journal(
    conn: sqlite3.Connection,
    symbol: str,
    env: Environment,
    journal_dir: Path = JOURNAL_DIR,
) -> None:
    executions = get_executions_for_symbol(conn, symbol)
    dividends = get_dividends_for_symbol(conn, symbol)

    trades_with_avg = []
    for i, ex in enumerate(executions):
        adj_avg, _, _ = compute_adj_avg(executions[: i + 1])
        trades_with_avg.append({**ex, "adj_avg_after": adj_avg})

    pos_row = conn.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
    pos = dict(pos_row) if pos_row else {}

    context = {
        "symbol": symbol,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "quantity": pos.get("quantity", 0),
        "ib_avg_cost": pos.get("ib_avg_cost"),
        "adj_avg_cost": pos.get("adj_avg_cost"),
        "market_value": pos.get("market_value"),
        "unrealized_pnl_ib": pos.get("unrealized_pnl_ib"),
        "unrealized_pnl_adj": pos.get("unrealized_pnl_adj"),
        "realized_pnl": pos.get("realized_pnl"),
        "trades": trades_with_avg,
        "dividends": dividends,
    }

    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / f"{symbol}.md").write_text(env.get_template("stock.md.j2").render(**context))


def export_portfolio_summary(
    conn: sqlite3.Connection,
    env: Environment,
    journal_dir: Path = JOURNAL_DIR,
) -> None:
    snap_row = conn.execute(
        "SELECT * FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 1"
    ).fetchone()
    snap = dict(snap_row) if snap_row else {}
    positions = get_all_positions(conn)
    active_positions = [p for p in positions if (p.get("quantity") or 0) > 0]

    invested_value = snap.get("invested_value") or 0.0
    largest_value = snap.get("largest_position_value") or 0.0
    largest_pct = (largest_value / invested_value * 100) if invested_value > 0 else 0.0

    inv_ratio = snap.get("investment_ratio") or 0.0
    if abs(inv_ratio - 0.70) <= 0.05:
        health_status = "✓ On target"
    elif inv_ratio > 0.70:
        health_status = "⚠ Over-invested"
    else:
        health_status = "⚠ Under-invested"

    context = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total_nav": snap.get("total_nav"),
        "cash_balance": snap.get("cash_balance"),
        "invested_value": invested_value,
        "investment_ratio": snap.get("investment_ratio") or 0.0,
        "cash_ratio": snap.get("cash_ratio") or 0.0,
        "positions": active_positions,
        "largest_symbol": snap.get("largest_position_symbol"),
        "largest_value": largest_value,
        "largest_pct": largest_pct,
        "health_status": health_status,
    }

    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / "portfolio_summary.md").write_text(
        env.get_template("portfolio.md.j2").render(**context)
    )


def export_all(conn: sqlite3.Connection, journal_dir: Path = JOURNAL_DIR) -> None:
    env = build_env()
    for symbol in get_all_symbols(conn):
        export_stock_journal(conn, symbol, env, journal_dir)
    export_portfolio_summary(conn, env, journal_dir)

import sqlite3
from datetime import datetime, timezone
from db import (
    get_all_symbols, get_executions_for_symbol, get_all_positions,
    upsert_position, insert_portfolio_snapshot,
)


def compute_adj_avg(executions: list[dict]) -> tuple[float, float, float]:
    """
    Replays executions in chronological order.
    Returns (adj_avg_cost, realized_pnl, current_qty).
    adj_avg_cost can be negative — that means total sale proceeds exceeded total cost;
    remaining shares are 'free' on a net-cash basis.
    """
    adj_avg = 0.0
    realized_pnl = 0.0
    qty = 0.0

    for ex in sorted(executions, key=lambda x: x["executed_at"]):
        if ex["action"] == "BUY":
            new_qty = qty + ex["quantity"]
            adj_avg = (qty * adj_avg + ex["quantity"] * ex["price"]) / new_qty
            qty = new_qty
        elif ex["action"] == "SELL":
            realized_pnl += (ex["price"] - adj_avg) * ex["quantity"]
            new_qty = qty - ex["quantity"]
            adj_avg = (qty * adj_avg - ex["quantity"] * ex["price"]) / new_qty if new_qty > 0 else 0.0
            qty = new_qty

    return adj_avg, realized_pnl, qty


def compute_positions(conn: sqlite3.Connection, ib_positions: dict[str, dict]) -> None:
    """
    Recomputes adj_avg_cost and realized_pnl for every symbol in executions table.
    Merges with ib_positions for IB avg cost and market value.
    ib_positions format: {symbol: {"ib_avg_cost": float, "market_value": float}}
    """
    now = datetime.now(timezone.utc).isoformat()

    for symbol in get_all_symbols(conn):
        adj_avg, realized_pnl, qty = compute_adj_avg(get_executions_for_symbol(conn, symbol))

        ib = ib_positions.get(symbol, {})
        ib_avg_cost = ib.get("ib_avg_cost")
        market_value = ib.get("market_value")

        unrealized_pnl_ib = (
            (market_value - ib_avg_cost * qty)
            if (market_value is not None and ib_avg_cost is not None and qty > 0)
            else None
        )
        unrealized_pnl_adj = (
            (market_value - adj_avg * qty)
            if (market_value is not None and qty > 0)
            else None
        )

        upsert_position(conn, {
            "symbol": symbol, "quantity": qty,
            "ib_avg_cost": ib_avg_cost, "adj_avg_cost": adj_avg,
            "market_value": market_value,
            "unrealized_pnl_ib": unrealized_pnl_ib,
            "unrealized_pnl_adj": unrealized_pnl_adj,
            "realized_pnl": realized_pnl,
            "last_updated": now,
        })

    conn.commit()


def compute_portfolio_snapshot(conn: sqlite3.Connection, account_data: dict) -> None:
    """Computes and stores a daily portfolio health snapshot."""
    positions = get_all_positions(conn)
    today = datetime.now(timezone.utc).date().isoformat()

    invested_value = sum(p["market_value"] or 0.0 for p in positions)
    total_nav = account_data.get("total_nav") or 0.0
    cash_balance = account_data.get("cash_balance") or 0.0

    investment_ratio = invested_value / total_nav if total_nav > 0 else 0.0
    cash_ratio = cash_balance / total_nav if total_nav > 0 else 0.0

    valued_positions = [p for p in positions if p["market_value"] is not None]
    largest = max(valued_positions, key=lambda p: p["market_value"], default=None)

    insert_portfolio_snapshot(conn, {
        "snapshot_date": today,
        "total_nav": total_nav,
        "cash_balance": cash_balance,
        "invested_value": invested_value,
        "investment_ratio": round(investment_ratio, 4),
        "cash_ratio": round(cash_ratio, 4),
        "largest_position_symbol": largest["symbol"] if largest else None,
        "largest_position_value": largest["market_value"] if largest else None,
        "total_unrealized_pnl_ib": sum(p["unrealized_pnl_ib"] or 0.0 for p in positions),
        "total_unrealized_pnl_adj": sum(p["unrealized_pnl_adj"] or 0.0 for p in positions),
        "total_realized_pnl": sum(p["realized_pnl"] or 0.0 for p in positions),
    })
    conn.commit()

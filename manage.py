#!/usr/bin/env python3
"""
CLI for manually managing trades in the DB.

Usage:
    python manage.py add-trade SYMBOL BUY|SELL QTY PRICE DATE [--commission N]
    python manage.py list-trades SYMBOL
    python manage.py delete-trade ID
"""

import argparse
import sys
from datetime import datetime
from db import init_db, insert_execution, get_executions_for_symbol


def cmd_add_trade(args) -> None:
    symbol = args.symbol.upper()
    action = args.action.upper()
    qty    = args.qty
    price  = args.price
    commission = args.commission

    if action not in ("BUY", "SELL"):
        print(f"Error: action must be BUY or SELL, got '{args.action}'")
        sys.exit(1)
    if qty <= 0:
        print(f"Error: qty must be positive, got {qty}")
        sys.exit(1)
    if price <= 0:
        print(f"Error: price must be positive, got {price}")
        sys.exit(1)

    try:
        dt = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"Error: date must be YYYY-MM-DD, got '{args.date}'")
        sys.exit(1)

    executed_at = dt.strftime("%Y-%m-%dT00:00:00")
    # Unique ID: prefix + symbol + action + date + microsecond timestamp
    ib_exec_id = f"manual_{symbol}_{action}_{dt.strftime('%Y%m%d')}_{datetime.now().strftime('%f')}"

    conn = init_db()
    insert_execution(conn, {
        "symbol":      symbol,
        "action":      action,
        "quantity":    qty,
        "price":       price,
        "commission":  commission,
        "executed_at": executed_at,
        "exchange":    "MANUAL",
        "ib_exec_id":  ib_exec_id,
    })
    conn.commit()

    print(f"Added: [{action}] {qty} {symbol} @ ${price:.2f} on {args.date}  (id: {ib_exec_id})")
    print(f"Run 'python main.py' to recompute positions and journals.")


def cmd_list_trades(args) -> None:
    symbol = args.symbol.upper()
    conn = init_db()
    execs = get_executions_for_symbol(conn, symbol)

    if not execs:
        print(f"No trades found for {symbol}.")
        return

    print(f"\n{'ID':<6}  {'Date':<12}  {'Action':<6}  {'Qty':>8}  {'Price':>10}  {'Commission':>10}  {'Source'}")
    print("-" * 75)
    for e in execs:
        source = "manual" if str(e["ib_exec_id"]).startswith("manual_") else "flex"
        print(
            f"{e['id']:<6}  {e['executed_at'][:10]:<12}  {e['action']:<6}  "
            f"{e['quantity']:>8.2f}  ${e['price']:>9.2f}  ${e['commission']:>9.2f}  {source}"
        )

    buys  = sum(e["quantity"] for e in execs if e["action"] == "BUY")
    sells = sum(e["quantity"] for e in execs if e["action"] == "SELL")
    print(f"\nNet qty: {buys - sells:.2f}  (bought {buys:.2f}, sold {sells:.2f})")


def cmd_delete_trade(args) -> None:
    conn = init_db()
    row = conn.execute("SELECT * FROM executions WHERE id = ?", (args.id,)).fetchone()
    if not row:
        print(f"Error: no trade found with id {args.id}")
        sys.exit(1)

    row = dict(row)
    print(f"About to delete: [{row['action']}] {row['quantity']} {row['symbol']} "
          f"@ ${row['price']:.2f} on {row['executed_at'][:10]}  (exec_id: {row['ib_exec_id']})")
    confirm = input("Confirm delete? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    conn.execute("DELETE FROM executions WHERE id = ?", (args.id,))
    conn.commit()
    print(f"Deleted trade id {args.id}. Run 'python main.py' to recompute.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage trades in the IB tracker database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python manage.py add-trade AAPL BUY 7 142.50 2023-08-10
    python manage.py add-trade NVDA BUY 5 480.00 2023-11-20 --commission 1.00
    python manage.py list-trades AAPL
    python manage.py delete-trade 42
""",
    )
    sub = parser.add_subparsers(dest="command")

    # add-trade
    p_add = sub.add_parser("add-trade", help="Add a historical trade manually")
    p_add.add_argument("symbol",     help="Ticker symbol, e.g. AAPL")
    p_add.add_argument("action",     help="BUY or SELL")
    p_add.add_argument("qty",        type=float, help="Number of shares (positive)")
    p_add.add_argument("price",      type=float, help="Price per share")
    p_add.add_argument("date",       help="Trade date in YYYY-MM-DD format")
    p_add.add_argument("--commission", type=float, default=0.0, help="Commission paid (default: 0)")

    # list-trades
    p_list = sub.add_parser("list-trades", help="List all trades for a symbol")
    p_list.add_argument("symbol", help="Ticker symbol, e.g. AAPL")

    # delete-trade
    p_del = sub.add_parser("delete-trade", help="Delete a trade by its DB id")
    p_del.add_argument("id", type=int, help="Trade id (see list-trades)")

    args = parser.parse_args()

    if args.command == "add-trade":
        cmd_add_trade(args)
    elif args.command == "list-trades":
        cmd_list_trades(args)
    elif args.command == "delete-trade":
        cmd_delete_trade(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

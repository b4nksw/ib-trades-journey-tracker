import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "trades.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    action      TEXT NOT NULL,
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    commission  REAL NOT NULL,
    executed_at DATETIME NOT NULL,
    exchange    TEXT,
    ib_exec_id  TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS dividends (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol   TEXT NOT NULL,
    amount   REAL NOT NULL,
    ex_date  DATE NOT NULL,
    pay_date DATE,
    UNIQUE(symbol, ex_date)
);
CREATE TABLE IF NOT EXISTS positions (
    symbol              TEXT PRIMARY KEY,
    quantity            REAL NOT NULL,
    ib_avg_cost         REAL,
    adj_avg_cost        REAL,
    market_value        REAL,
    unrealized_pnl_ib   REAL,
    unrealized_pnl_adj  REAL,
    realized_pnl        REAL,
    last_updated        DATETIME
);
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date            DATE UNIQUE NOT NULL,
    total_nav                REAL,
    cash_balance             REAL,
    invested_value           REAL,
    investment_ratio         REAL,
    cash_ratio               REAL,
    largest_position_symbol  TEXT,
    largest_position_value   REAL,
    total_unrealized_pnl_ib  REAL,
    total_unrealized_pnl_adj REAL,
    total_realized_pnl       REAL
);
CREATE TABLE IF NOT EXISTS sync_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type      TEXT UNIQUE NOT NULL,
    last_synced_at DATETIME
);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def get_last_sync(conn: sqlite3.Connection, data_type: str) -> datetime | None:
    row = conn.execute(
        "SELECT last_synced_at FROM sync_log WHERE data_type = ?", (data_type,)
    ).fetchone()
    if row is None:
        return None
    return datetime.fromisoformat(row["last_synced_at"])


def set_last_sync(conn: sqlite3.Connection, data_type: str, dt: datetime) -> None:
    conn.execute(
        "INSERT INTO sync_log (data_type, last_synced_at) VALUES (?, ?) "
        "ON CONFLICT(data_type) DO UPDATE SET last_synced_at = excluded.last_synced_at",
        (data_type, dt.isoformat()),
    )


def insert_execution(conn: sqlite3.Connection, exec_dict: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO executions "
        "(symbol, action, quantity, price, commission, executed_at, exchange, ib_exec_id) "
        "VALUES (:symbol, :action, :quantity, :price, :commission, "
        ":executed_at, :exchange, :ib_exec_id)",
        exec_dict,
    )


def insert_dividend(conn: sqlite3.Connection, div_dict: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO dividends (symbol, amount, ex_date, pay_date) "
        "VALUES (:symbol, :amount, :ex_date, :pay_date)",
        div_dict,
    )


def upsert_position(conn: sqlite3.Connection, pos_dict: dict) -> None:
    conn.execute(
        "INSERT INTO positions "
        "(symbol, quantity, ib_avg_cost, adj_avg_cost, market_value, "
        "unrealized_pnl_ib, unrealized_pnl_adj, realized_pnl, last_updated) "
        "VALUES (:symbol, :quantity, :ib_avg_cost, :adj_avg_cost, :market_value, "
        ":unrealized_pnl_ib, :unrealized_pnl_adj, :realized_pnl, :last_updated) "
        "ON CONFLICT(symbol) DO UPDATE SET "
        "quantity=excluded.quantity, ib_avg_cost=excluded.ib_avg_cost, "
        "adj_avg_cost=excluded.adj_avg_cost, market_value=excluded.market_value, "
        "unrealized_pnl_ib=excluded.unrealized_pnl_ib, "
        "unrealized_pnl_adj=excluded.unrealized_pnl_adj, "
        "realized_pnl=excluded.realized_pnl, last_updated=excluded.last_updated",
        pos_dict,
    )


def insert_portfolio_snapshot(conn: sqlite3.Connection, snap: dict) -> None:
    conn.execute(
        "INSERT INTO portfolio_snapshots "
        "(snapshot_date, total_nav, cash_balance, invested_value, investment_ratio, "
        "cash_ratio, largest_position_symbol, largest_position_value, "
        "total_unrealized_pnl_ib, total_unrealized_pnl_adj, total_realized_pnl) "
        "VALUES (:snapshot_date, :total_nav, :cash_balance, :invested_value, "
        ":investment_ratio, :cash_ratio, :largest_position_symbol, "
        ":largest_position_value, :total_unrealized_pnl_ib, "
        ":total_unrealized_pnl_adj, :total_realized_pnl) "
        "ON CONFLICT(snapshot_date) DO UPDATE SET "
        "total_nav=excluded.total_nav, cash_balance=excluded.cash_balance, "
        "invested_value=excluded.invested_value, "
        "investment_ratio=excluded.investment_ratio, cash_ratio=excluded.cash_ratio, "
        "largest_position_symbol=excluded.largest_position_symbol, "
        "largest_position_value=excluded.largest_position_value, "
        "total_unrealized_pnl_ib=excluded.total_unrealized_pnl_ib, "
        "total_unrealized_pnl_adj=excluded.total_unrealized_pnl_adj, "
        "total_realized_pnl=excluded.total_realized_pnl",
        snap,
    )


def get_executions_for_symbol(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM executions WHERE symbol = ? ORDER BY executed_at ASC", (symbol,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_symbols(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT symbol FROM executions").fetchall()
    return [r["symbol"] for r in rows]


def get_all_positions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM positions ORDER BY market_value DESC NULLS LAST"
    ).fetchall()
    return [dict(r) for r in rows]


def get_dividends_for_symbol(conn: sqlite3.Connection, symbol: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM dividends WHERE symbol = ? ORDER BY ex_date DESC", (symbol,)
    ).fetchall()
    return [dict(r) for r in rows]

import logging
import sqlite3
from datetime import datetime, timezone
from ib_insync import IB
from db import set_last_sync

logger = logging.getLogger(__name__)


def connect_ib(host: str, port: int, client_id: int) -> IB:
    ib = IB()
    ib.connect(host, port, clientId=client_id, readonly=True)
    ib.sleep(2)  # wait for initial account data push from Gateway
    return ib


def fetch_positions(ib: IB, conn: sqlite3.Connection) -> dict[str, dict]:
    """
    Fetches current portfolio from IB Gateway.
    Returns {symbol: {"ib_avg_cost": float, "market_value": float}}.
    ib.portfolio() returns PortfolioItem objects: contract, position, marketPrice,
    marketValue, averageCost, unrealizedPNL, realizedPNL, account.
    """
    result = {}
    for item in ib.portfolio():
        symbol = item.contract.symbol
        result[symbol] = {
            "ib_avg_cost": item.averageCost,
            "market_value": item.marketValue,
        }

    set_last_sync(conn, "positions", datetime.now(timezone.utc))
    conn.commit()
    logger.info(f"Fetched {len(result)} positions from IB Gateway")
    return result


def fetch_account_summary(ib: IB) -> dict:
    """
    Fetches cash balance and net asset value from IB account summary.
    accountSummary() returns AccountValue objects with .tag and .value fields.
    """
    summary = {item.tag: item.value for item in ib.accountSummary()}
    return {
        "total_nav": float(summary.get("NetLiquidation", 0.0)),
        "cash_balance": float(summary.get("TotalCashValue", 0.0)),
    }

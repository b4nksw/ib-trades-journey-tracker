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

    ib_insync calls reqPositions() automatically on connect, so ib.positions()
    is already populated after the initial sleep — use it for avg cost.
    Market values require reqAccountUpdates(), which pushes updatePortfolio events.
    """
    result = {}

    # avg cost: available immediately from the auto-requested positions
    for pos in ib.positions():
        symbol = pos.contract.symbol
        result[symbol] = {"ib_avg_cost": pos.avgCost, "market_value": None}

    # market value: request account updates and wait for portfolio push
    accounts = ib.managedAccounts()
    if accounts:
        ib.reqAccountUpdates(accounts[0])  # ib_insync handles the subscribe=True internally
        ib.sleep(5)
        for item in ib.portfolio():
            symbol = item.contract.symbol
            if symbol in result:
                result[symbol]["market_value"] = item.marketValue
            else:
                result[symbol] = {"ib_avg_cost": item.averageCost, "market_value": item.marketValue}

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

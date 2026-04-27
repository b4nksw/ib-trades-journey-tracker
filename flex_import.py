import time
import sqlite3
import xml.etree.ElementTree as ET
import requests
from db import insert_execution, insert_dividend

_SEND_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
_GET_URL  = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"


def fetch_flex_xml(token: str, query_id: str) -> str:
    """Requests a Flex Query report from IB and returns the raw XML string."""
    resp = requests.get(_SEND_URL, params={"t": token, "q": query_id, "v": 3}, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    ref_code = root.findtext("ReferenceCode")
    if not ref_code:
        raise RuntimeError(f"Flex Query request failed: {resp.text[:200]}")

    time.sleep(3)  # IB needs time to generate the report

    resp2 = requests.get(_GET_URL, params={"t": token, "q": ref_code, "v": 3}, timeout=60)
    resp2.raise_for_status()
    return resp2.text


def parse_flex_xml(xml_text: str) -> tuple[list[dict], list[dict]]:
    """
    Parses Flex Query XML into (trades, dividends) lists.
    Handles IB's dateTime format: '20240115;100000' -> '2024-01-15T10:00:00'
    """
    root = ET.fromstring(xml_text)
    trades = []
    dividends = []

    for trade in root.iter("Trade"):
        raw_dt = trade.get("dateTime", "")
        action = "BUY" if trade.get("buySell", "").upper() == "BUY" else "SELL"
        commission_raw = trade.get("ibCommission", "0")
        trades.append({
            "symbol": trade.get("symbol", "").split()[0],
            "action": action,
            "quantity": float(trade.get("quantity", 0)),
            "price": float(trade.get("tradePrice", 0)),
            "commission": abs(float(commission_raw)),
            "executed_at": _parse_ib_datetime(raw_dt),
            "exchange": trade.get("exchange", ""),
            "ib_exec_id": trade.get("tradeID", ""),
        })

    for ct in root.iter("CashTransaction"):
        if ct.get("type") != "Dividends":
            continue
        raw_dt = ct.get("dateTime", "")
        raw_settle = ct.get("settleDate", "")
        dividends.append({
            "symbol": ct.get("symbol", "").split()[0],
            "amount": float(ct.get("amount", 0)),
            "ex_date": _parse_ib_date(raw_dt),
            "pay_date": _parse_ib_date(raw_settle) if raw_settle else None,
        })

    return trades, dividends


def import_flex_data(conn: sqlite3.Connection, xml_text: str) -> tuple[int, int]:
    """
    Inserts parsed trades and dividends into the DB.
    Returns (new_trade_count, new_dividend_count).
    INSERT OR IGNORE ensures idempotency.
    """
    trades, dividends = parse_flex_xml(xml_text)

    before_t = conn.execute("SELECT count(*) FROM executions").fetchone()[0]
    for t in trades:
        insert_execution(conn, t)

    before_d = conn.execute("SELECT count(*) FROM dividends").fetchone()[0]
    for d in dividends:
        insert_dividend(conn, d)

    conn.commit()

    after_t = conn.execute("SELECT count(*) FROM executions").fetchone()[0]
    after_d = conn.execute("SELECT count(*) FROM dividends").fetchone()[0]
    return after_t - before_t, after_d - before_d


def _parse_ib_datetime(raw: str) -> str:
    """'20240115;100000' -> '2024-01-15T10:00:00'"""
    raw = raw.replace(";", "").replace(" ", "")
    if len(raw) >= 14:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}T{raw[8:10]}:{raw[10:12]}:{raw[12:14]}"
    if len(raw) >= 8:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}T00:00:00"
    return raw


def _parse_ib_date(raw: str) -> str:
    """'20240301' or '20240301;093000' -> '2024-03-01'"""
    raw = raw.split(";")[0].strip()
    if len(raw) == 8:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw

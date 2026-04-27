import logging
import sys
from pathlib import Path
from db import init_db
from flex_import import fetch_flex_xml, import_flex_data
from sync import connect_ib, fetch_positions, fetch_account_summary
from calculate import compute_positions, compute_portfolio_snapshot
from export import export_all
import config

LOG_DIR = Path(__file__).parent / "logs"
logger = logging.getLogger(__name__)


def run() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "sync.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not config.FLEX_TOKEN or not config.FLEX_QUERY_ID:
        logger.error("FLEX_TOKEN and FLEX_QUERY_ID must be set in config.py")
        sys.exit(1)

    logger.info("=== Sync started ===")
    conn = init_db()
    try:
        # Import trades + dividends from Flex Query (idempotent)
        try:
            xml = fetch_flex_xml(config.FLEX_TOKEN, config.FLEX_QUERY_ID)
            n_trades, n_divs = import_flex_data(conn, xml)
            logger.info(f"Flex import: {n_trades} new trades, {n_divs} new dividends")
        except Exception as e:
            logger.error(f"Flex Query import failed: {e}")
            sys.exit(1)

        # Fetch live positions + account data from IB Gateway
        ib = None
        try:
            ib = connect_ib(config.IB_HOST, config.IB_PORT, config.IB_CLIENT_ID)
            ib_positions = fetch_positions(ib, conn)
            account_data = fetch_account_summary(ib)
        except Exception as e:
            logger.warning(f"IB Gateway unavailable — positions/account data skipped: {e}")
            ib_positions = {}
            account_data = {}
        finally:
            if ib:
                ib.disconnect()

        compute_positions(conn, ib_positions)
        compute_portfolio_snapshot(conn, account_data)
        export_all(conn)

        snap = conn.execute(
            "SELECT investment_ratio FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        ratio_str = f"{snap[0] * 100:.1f}%" if snap else "N/A"
        logger.info(f"Done. Portfolio: {ratio_str} invested.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()

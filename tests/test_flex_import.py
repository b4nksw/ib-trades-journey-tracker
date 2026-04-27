import pytest
from pathlib import Path
from db import init_db, get_executions_for_symbol, get_dividends_for_symbol
from flex_import import parse_flex_xml, import_flex_data

FIXTURE = Path(__file__).parent / "fixtures" / "sample_flex.xml"


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_parse_flex_xml_trades():
    xml_text = FIXTURE.read_text()
    trades, dividends = parse_flex_xml(xml_text)
    assert len(trades) == 3
    tsla_buy = next(t for t in trades if t["symbol"] == "TSLA" and t["action"] == "BUY")
    assert tsla_buy["quantity"] == 5.0
    assert tsla_buy["price"] == 10.0
    assert tsla_buy["ib_exec_id"] == "111"


def test_parse_flex_xml_dividends():
    xml_text = FIXTURE.read_text()
    _, dividends = parse_flex_xml(xml_text)
    assert len(dividends) == 1
    assert dividends[0]["symbol"] == "TSLA"
    assert dividends[0]["amount"] == 2.50
    assert dividends[0]["ex_date"] == "2024-03-01"


def test_parse_sell_action():
    xml_text = FIXTURE.read_text()
    trades, _ = parse_flex_xml(xml_text)
    tsla_sell = next(t for t in trades if t["symbol"] == "TSLA" and t["action"] == "SELL")
    assert tsla_sell["price"] == 15.0
    assert tsla_sell["ib_exec_id"] == "222"


def test_import_flex_data_inserts_all(conn):
    xml_text = FIXTURE.read_text()
    n_trades, n_divs = import_flex_data(conn, xml_text)
    assert n_trades == 3
    assert n_divs == 1
    tsla_execs = get_executions_for_symbol(conn, "TSLA")
    assert len(tsla_execs) == 2


def test_import_flex_data_idempotent(conn):
    xml_text = FIXTURE.read_text()
    import_flex_data(conn, xml_text)
    n_trades, n_divs = import_flex_data(conn, xml_text)  # second run
    assert n_trades == 0  # all already exist
    count = conn.execute("SELECT count(*) FROM executions").fetchone()[0]
    assert count == 3

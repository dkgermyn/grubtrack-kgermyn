"""Regressions for the 2026-10-24 data-layer review: each test reproduces one finding."""

import datetime as dt
import json
import sqlite3

import pytest

from foodcore import intel, ledger

TODAY = dt.date.today().isoformat()
ALB = "Albertsons Store #12, 2200 W Oak Ave, Springfield, IL 62704"


def add(cli, **kw):
    return cli("add", "--json", json.dumps(kw)).stdout.strip()


def obs(con, item_id):
    return [(r["price"], r["date"], r["source"], r["supersededBy"]) for r in con.execute(
        "SELECT * FROM purchases WHERE itemId = ? ORDER BY date, createdAt", (item_id,))]


def receipt(cli, tmp_path, lines, total=None, name="r.json", **kw):
    f = tmp_path / name
    f.write_text(json.dumps({"store": ALB, "date": kw.pop("date", "2026-10-21"),
                             "total": total if total is not None else round(sum(l["price"] for l in lines), 2),
                             "tax": 0, "lines": lines, **kw}))
    return cli("receipt-add", "--file", f, ok=False)


# 1. a priced restock is a new purchase, filed under today, never under the old trip
def test_restock_after_receipt_is_a_new_purchase(cli, con, tmp_path):
    iid = add(cli, name="Siggi's skyr", storage="fridge")
    r = receipt(cli, tmp_path, [{"raw": "SIGGIS YOGURT", "name": "Siggi's skyr", "price": 7.49, "itemId": iid}])
    assert r.returncode == 0
    assert add(cli, name="Siggi's skyr", storage="fridge", price=8.99) == iid  # merged restock
    rows = obs(con, iid)
    assert (8.99, TODAY, "item", None) in rows and (7.49, "2026-10-21", "receipt", None) in rows
    it = con.execute("SELECT price, receiptId, purchaseDate FROM items WHERE id = ?", (iid,)).fetchone()
    assert (it["price"], it["receiptId"], it["purchaseDate"]) == (8.99, None, TODAY)
    book = {p["name"]: p for p in intel.price_book(con)}
    assert book["Siggi's skyr"]["last"]["price"] == 8.99
    # relinking the old receipt line must not drag the row back to the older price
    pid = con.execute("SELECT id FROM purchases WHERE source = 'receipt'").fetchone()[0]
    cli("receipt-link", "--line", pid, "--item", iid)
    assert con.execute("SELECT price FROM items WHERE id = ?", (iid,)).fetchone()[0] == 8.99


def test_restock_keeps_earlier_dated_observation(cli, con):
    iid = add(cli, name="Disaronno", storage="cupboard", price=24.99, purchaseDate="2026-10-01")
    add(cli, name="Disaronno", storage="cupboard", price=26.49)
    assert sorted(o[:2] for o in obs(con, iid)) == [(24.99, "2026-10-01"), (26.49, TODAY)]


def test_same_price_restock_is_still_recorded(cli, con):
    iid = add(cli, name="Lemons", storage="fridge", price=1.78, purchaseDate="2026-10-01")
    add(cli, name="Lemons", storage="fridge", price=1.78)
    assert sorted(o[:2] for o in obs(con, iid)) == [(1.78, "2026-10-01"), (1.78, TODAY)]


def test_receipt_without_price_does_not_inherit_old_price(cli, con):
    iid = add(cli, name="Kefir", storage="fridge", price=6.99)
    con.execute("INSERT INTO receipts (id, date, store, total) VALUES ('rc_next', ?, 'Target', 50)", (TODAY,))
    con.commit()
    add(cli, name="Kefir", storage="fridge", receiptId="rc_next")
    assert [o for o in obs(con, iid) if o[0] == 6.99 and o[1] == TODAY and o[2] == "item"].__len__() == 1
    assert con.execute("SELECT COUNT(*) FROM purchases WHERE receiptId = 'rc_next'").fetchone()[0] == 0


# 2. a correction the next day is the same purchase
def test_next_day_correction_updates_in_place(cli, con):
    iid = add(cli, name="Sourdough bread", storage="counter", price=4.99, createdAt="2026-10-23T09:00:00-07:00")
    cli("update", "--id", iid, "--set", json.dumps({"price": 5.49}))
    assert obs(con, iid) == [(5.49, "2026-10-23", "item", None)]


# 3. one bad value never breaks the sweep, the analytics or a receipt import
def test_text_prices_and_quantities_are_contained(cli, con, tmp_path):
    iid = add(cli, name="Hummus", storage="fridge", price=3.89, quantity="1/2")
    r = cli("update", "--id", iid, "--set", json.dumps({"price": "$4.29"}))
    assert con.execute("SELECT price FROM items WHERE id = ?", (iid,)).fetchone()[0] == 4.29
    assert "number" in cli("update", "--id", iid, "--set", json.dumps({"price": "four"}), ok=False).stderr
    # raw SQL writing text where a number belongs
    con.execute("UPDATE items SET price = '$13.49', purchaseDate = 'yesterday' WHERE id = ?", (iid,))
    con.execute("INSERT INTO receipts (id, date, store, total, tax) VALUES ('rx', 'Oct 20', 'Target', 'about 40', 'n/a')")
    con.commit()
    r = cli("add", "--name", "Tofu", "--storage", "fridge")
    assert "sweep" not in r.stderr
    assert not any(isinstance(p, str) for p, *_ in obs(con, iid))
    for fn in (intel.price_book, intel.overview, intel.stores, intel.cadence, intel.inflation):
        fn(con)
    intel.spend(con)
    rep = json.loads(receipt(cli, tmp_path, [{"raw": "TOFU", "name": "Extra-firm tofu", "price": 2.29}]).stdout)
    assert "sweepError" not in rep


def test_add_with_unreadable_json_price_still_logs_the_item(cli, con):
    r = cli("add", "--json", json.dumps({"name": "Pita", "storage": "pantry", "price": "a few bucks"}))
    assert r.returncode == 0 and "ignored unreadable price" in r.stderr
    assert con.execute("SELECT price FROM items WHERE name = 'Pita'").fetchone()[0] is None


def test_shell_eaten_dollar_is_refused(cli, con):
    r = cli("add", "--name", "Lime", "--storage", "fridge", "--price", ".99", ok=False)
    assert r.returncode != 0 and "cut off" in r.stderr
    assert con.execute("SELECT COUNT(*) FROM items WHERE name = 'Lime'").fetchone()[0] == 0
    assert cli("add", "--name", "Lime", "--storage", "fridge", "--price", "0.99").returncode == 0


# 4. the CLI's flags behave exactly as before for everything that existed before
def test_baseline_abbreviations_still_work(cli, con):
    cli("add", "--name", "Greek yogurt", "--storage", "fridge", "--cat", "dairy")
    assert con.execute("SELECT category FROM items WHERE name = 'Greek yogurt'").fetchone()[0] == "dairy"
    assert cli("list", "--li", "5").returncode == 0
    assert cli("find", "--q", "yogurt", "--al").returncode == 0          # --all ("--a" was ambiguous before too)
    iid = con.execute("SELECT id FROM items").fetchone()[0]
    assert cli("update", "--i", iid, "--se", json.dumps({"notes": "x"})).returncode == 0  # --id, --set
    assert cli("add", "--name", "Oats", "--storage", "pantry", "--no-", "--p", "2026-10-01").returncode == 0
    assert con.execute("SELECT purchaseDate FROM items WHERE name = 'Oats'").fetchone()[0] == "2026-10-01"
    pid = con.execute("SELECT productId FROM items WHERE name = 'Greek yogurt'").fetchone()[0]
    assert cli("set-cat", "--product", pid, "--category", "dairy.yogurt").returncode == 0


# 5. merging never leaves anything pointing at a deleted product
def test_merge_chains_survive(cli, con):
    ts = "2026-10-01T00:00:00"
    for pid in ("pA", "pB", "pC"):
        con.execute("INSERT INTO products (id, key, name, createdAt, updatedAt) VALUES (?,?,?,?,?)", (pid, pid, pid, ts, ts))
    con.execute("INSERT INTO stores (id, chain, name, createdAt, updatedAt) VALUES ('s1','Albertsons','A',?,?)", (ts, ts))
    rows = [("pA", "X"), ("pA", "X"), ("pB", "X"), ("pB", "Y"), ("pB", "Y"), ("pC", "Y")]
    for i, (pid, code) in enumerate(rows):
        con.execute("INSERT INTO purchases (id, source, storeId, date, productId, code, price, createdAt, updatedAt)"
                    " VALUES (?,?,?,?,?,?,?,?,?)", (f"pu{i}", "receipt", "s1", "2026-10-01", pid, code, 1.0, ts, ts))
    con.execute("INSERT INTO items (id, createdAt, updatedAt, name, productId) VALUES ('i1', ?, ?, 'thing', 'pC')", (ts, ts))
    con.commit()
    ledger.sweep(con)
    live = {r[0] for r in con.execute("SELECT id FROM products")}
    assert {r[0] for r in con.execute("SELECT DISTINCT productId FROM purchases")} <= live
    assert {r[0] for r in con.execute("SELECT productId FROM product_aliases")} <= live
    ledger.sweep(con)  # and it stays healthy


# 6. the same trip twice is one receipt
def test_duplicate_receipt_is_refused_then_replaced(cli, con, tmp_path):
    lines = [{"raw": "CELERY", "name": "Celery", "price": 1.99}]
    assert receipt(cli, tmp_path, lines).returncode == 0
    r = receipt(cli, tmp_path, lines)
    assert r.returncode != 0 and "already recorded" in r.stderr
    assert receipt(cli, tmp_path, lines + [{"raw": "TAX FIX", "name": "x", "price": 0.0}], total=1.99) \
        .returncode != 0
    r = receipt(cli, tmp_path, [{"raw": "CELERY MEDIUM", "name": "Celery", "price": 1.99}], name="r2.json")
    assert r.returncode != 0  # same store, date and total without --replace
    f = tmp_path / "r3.json"
    f.write_text(json.dumps({"store": ALB, "date": "2026-10-21", "total": 1.99, "tax": 0,
                             "lines": [{"raw": "CELERY MEDIUM", "name": "Celery", "price": 1.99}]}))
    assert cli("receipt-add", "--file", f, "--replace").returncode == 0
    assert con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1
    assert con.execute("SELECT raw FROM purchases").fetchone()[0] == "CELERY MEDIUM"


# 7. links survive --replace, and unlinking undoes what linking did
def test_links_survive_replace_and_unlink_restores(cli, con, tmp_path):
    iid = add(cli, name="Hummus", storage="fridge", price=1.98)  # the voice guess
    rep = json.loads(receipt(cli, tmp_path, [{"raw": "ORGANIC ORIGINAL", "name": "Organic hummus", "price": 3.89}],
                             date=TODAY).stdout)
    rid = rep["receiptId"]
    line = con.execute("SELECT id FROM purchases WHERE source = 'receipt'").fetchone()[0]
    cli("receipt-link", "--line", line, "--item", iid)
    assert con.execute("SELECT price FROM items WHERE id = ?", (iid,)).fetchone()[0] == 3.89
    assert obs(con, iid)[0][3] == rid or any(o[3] == rid for o in obs(con, iid))  # guess superseded, kept
    f = tmp_path / "again.json"
    f.write_text(json.dumps({"id": rid, "store": ALB, "date": TODAY, "total": 3.89, "tax": 0,
                             "lines": [{"raw": "ORGANIC ORIGINAL", "name": "Organic hummus", "price": 3.89}]}))
    cli("receipt-add", "--file", f, "--replace")
    assert con.execute("SELECT itemId FROM purchases WHERE source = 'receipt'").fetchone()[0] == iid
    line = con.execute("SELECT id FROM purchases WHERE source = 'receipt'").fetchone()[0]
    cli("receipt-link", "--line", line, "--item", "none")
    it = con.execute("SELECT price, receiptId FROM items WHERE id = ?", (iid,)).fetchone()
    assert (it["price"], it["receiptId"]) == (1.98, None)
    assert [o[:3] for o in obs(con, iid) if o[3] is None] == [(1.98, TODAY, "item")]


# 8. coupon and refund lines don't break the store analytics
def test_negative_lines_are_money_not_prices(cli, con, tmp_path):
    receipt(cli, tmp_path, [{"raw": "KEFIR", "name": "Lifeway kefir", "price": 4.59},
                            {"raw": "COUPON", "name": "Lifeway kefir", "price": -1.00}], date="2026-10-03",
            store="Target Springfield Westgate, 3200 Westgate Dr, Springfield, IL 62711")
    receipt(cli, tmp_path, [{"raw": "KEFIR", "name": "Lifeway kefir", "price": 6.99}], name="b.json")
    intel.store_index(con)
    intel.inflation(con)
    assert intel.spend(con)["months"][-1]["total"] == pytest.approx(10.58)


# 9. a locked or racing migration doesn't take plain commands down
def test_migration_tolerates_duplicate_columns(con):
    from foodcore import schema
    con.execute("PRAGMA user_version = 0")
    assert schema.migrate(con) == schema.VERSION  # every ALTER hits an existing column


def test_v1_database_gets_v2_triggers(con):
    from foodcore import schema
    con.execute("PRAGMA user_version = 1")
    assert schema.migrate(con) == schema.VERSION == 3
    sql = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")}
    assert set(sql) == {"gt_items_price_ins", "gt_items_price_upd"}
    assert all("%f" in v for v in sql.values())

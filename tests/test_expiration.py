"""Deterministic expiration estimates shared by the CLI and web application."""

import datetime as dt
import json


def _add(cli, **item):
    result = cli("add", "--json", json.dumps(item))
    return result.stdout.strip()


def _item(con, item_id):
    return dict(con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


def test_migration_seeds_reviewable_rule_table(con):
    assert con.execute("PRAGMA user_version").fetchone()[0] == 4
    count = con.execute("SELECT count(*) FROM expiration_rules WHERE source = 'built-in'").fetchone()[0]
    assert count >= 50


def test_v3_migration_backfills_active_undated_rows_from_logged_date(con):
    from foodcore import schema

    con.execute(
        """INSERT INTO items (id, createdAt, updatedAt, name, storage)
           VALUES ('legacy-banana', '2026-10-30T18:00:00-06:00',
                   '2026-10-30T18:00:00-06:00', 'Bananas', 'counter')"""
    )
    con.execute("PRAGMA user_version = 2")

    assert schema.migrate(con) == 4
    item = _item(con, "legacy-banana")
    assert item["expirationDate"] == "2026-11-04"
    assert item["expirationSource"] == "estimated"
    assert item["expirationRuleId"] == "banana-counter"


def test_banana_and_lettuce_use_specific_rules(cli, con):
    banana = _item(con, _add(cli, name="Bananas", storage="counter", purchaseDate="2026-10-30"))
    lettuce = _item(con, _add(cli, name="Green lettuce", storage="fridge", purchaseDate="2026-10-30"))

    assert banana["expirationDate"] == "2026-11-04"
    assert banana["expirationSource"] == "estimated"
    assert banana["expirationRuleId"] == "banana-counter"
    assert lettuce["expirationDate"] == "2026-11-06"
    assert lettuce["expirationRuleId"] == "lettuce-fridge"


def test_banana_in_pantry_uses_product_rule_not_yearlong_fallback(cli, con):
    banana = _item(con, _add(
        cli, name="Bananas", storage="pantry", purchaseDate="2026-10-30",
    ))
    assert banana["expirationDate"] == "2026-11-04"
    assert banana["expirationRuleId"] == "banana-any"


def test_v4_migration_refreshes_existing_fallback_estimate(con):
    from foodcore import schema

    con.execute(
        """INSERT INTO items
           (id, createdAt, updatedAt, name, storage, expirationDate,
            expirationSource, expirationRuleId)
           VALUES ('v3-banana', '2026-10-30T18:00:00-06:00',
                   '2026-10-30T18:00:00-06:00', 'Bananas', 'pantry',
                   '2027-10-30', 'estimated', 'fallback-pantry')"""
    )
    con.execute("DELETE FROM expiration_rules WHERE id = 'banana-any'")
    con.execute("PRAGMA user_version = 3")

    assert schema.migrate(con) == 4
    item = _item(con, "v3-banana")
    assert item["expirationDate"] == "2026-11-04"
    assert item["expirationRuleId"] == "banana-any"


def test_explicit_date_always_wins(cli, con):
    item = _item(con, _add(
        cli, name="Bananas", storage="counter", purchaseDate="2026-10-30",
        expirationDate="2026-12-25",
    ))
    assert item["expirationDate"] == "2026-12-25"
    assert item["expirationSource"] == "explicit"
    assert item["expirationRuleId"] is None


def test_higher_priority_household_rule_overrides_seed(cli, con):
    con.execute(
        """INSERT INTO expiration_rules
           (id, generic, category, storage, days, priority, enabled, source)
           VALUES ('household-banana', 'banana', NULL, 'counter', 2, 100, 1, 'custom')"""
    )
    con.commit()
    item = _item(con, _add(
        cli, name="Organic bananas", storage="counter", purchaseDate="2026-10-30",
    ))
    assert item["expirationDate"] == "2026-11-01"
    assert item["expirationRuleId"] == "household-banana"


def test_unknown_product_uses_storage_fallback(cli, con):
    item = _item(con, _add(
        cli, name="Unknown test product", storage="cupboard", purchaseDate="2026-01-01",
    ))
    assert item["expirationDate"] == (dt.date(2026, 1, 1) + dt.timedelta(days=365)).isoformat()
    assert item["expirationRuleId"] == "fallback-cupboard"


def test_high_risk_refrigerated_food_uses_conservative_rule(cli, con):
    item = _item(con, _add(
        cli, name="Ground beef", storage="fridge", purchaseDate="2026-10-30",
    ))
    assert item["expirationDate"] == "2026-11-01"
    assert item["expirationRuleId"] == "ground-beef-fridge"


def test_missing_rule_fails_instead_of_creating_undated_item(cli, con):
    con.execute("UPDATE expiration_rules SET enabled = 0")
    con.commit()

    result = cli(
        "add", "--json",
        json.dumps({"name": "Unknown test product", "storage": "cupboard"}),
        ok=False,
    )

    assert result.returncode != 0
    assert con.execute("SELECT count(*) FROM items").fetchone()[0] == 0

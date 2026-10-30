"""Deterministic expiration estimates shared by the CLI and web application."""

import datetime as dt
import json


def _add(cli, **item):
    result = cli("add", "--json", json.dumps(item))
    return result.stdout.strip()


def _item(con, item_id):
    return dict(con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


def test_migration_seeds_reviewable_rule_table(con):
    assert con.execute("PRAGMA user_version").fetchone()[0] == 5
    count = con.execute("SELECT count(*) FROM expiration_rules WHERE source = 'built-in'").fetchone()[0]
    assert count >= 50


def test_migration_leaves_active_legacy_rows_undated(con):
    from foodcore import schema

    con.execute(
        """INSERT INTO items (id, createdAt, updatedAt, name, storage)
           VALUES ('legacy-banana', '2026-10-30T18:00:00-06:00',
                   '2026-10-30T18:00:00-06:00', 'Bananas', 'counter')"""
    )
    con.execute("PRAGMA user_version = 2")

    assert schema.migrate(con) == 5
    item = _item(con, "legacy-banana")
    assert item["expirationDate"] is None
    assert item["expirationSource"] is None
    assert item["expirationRuleId"] is None


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


def test_migration_does_not_refresh_existing_estimates(con):
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

    assert schema.migrate(con) == 5
    item = _item(con, "v3-banana")
    assert item["expirationDate"] == "2027-10-30"
    assert item["expirationRuleId"] == "fallback-pantry"


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


def test_missing_rule_logs_an_undated_item(cli, con):
    con.execute("UPDATE expiration_rules SET enabled = 0")
    con.commit()

    result = cli(
        "add", "--json",
        json.dumps({"name": "Unknown test product", "storage": "cupboard"}),
    )
    item = _item(con, result.stdout.strip())
    assert item["expirationDate"] is None
    assert item["expirationSource"] is None
    assert "logging without a date" in result.stderr


def test_undated_restock_never_replaces_an_explicit_date(cli, con):
    item_id = _add(
        cli, name="Milk", storage="fridge", purchaseDate="2026-10-30",
        expirationDate="2026-11-20",
    )
    assert _add(cli, name="Milk", storage="fridge", purchaseDate="2026-10-31") == item_id
    item = _item(con, item_id)
    assert item["expirationDate"] == "2026-11-20"
    assert item["expirationSource"] == "explicit"
    assert item["expirationRuleId"] is None


def test_explicit_restock_replaces_an_estimate(cli, con):
    item_id = _add(cli, name="Milk", storage="fridge", purchaseDate="2026-10-30")
    assert _add(
        cli, name="Milk", storage="fridge", purchaseDate="2026-10-31",
        expirationDate="2026-11-20",
    ) == item_id
    item = _item(con, item_id)
    assert item["expirationDate"] == "2026-11-20"
    assert item["expirationSource"] == "explicit"
    assert item["expirationRuleId"] is None


def test_nonexpiring_categories_are_labeled_without_a_fake_date(cli, con):
    spirit = _item(con, _add(cli, name="Bourbon", storage="pantry", category="bar.whiskey"))
    spice = _item(con, _add(cli, name="Black pepper", storage="pantry", category="pantry.spices"))
    for item, rule in ((spirit, "bar-no-estimate"), (spice, "spices-no-estimate")):
        assert item["expirationDate"] is None
        assert item["expirationSource"] == "not_applicable"
        assert item["expirationRuleId"] == rule


def test_rule_refresh_is_preview_only_until_explicitly_applied(cli, con):
    item_id = _add(cli, name="Blueberry bagel", storage="pantry", purchaseDate="2026-10-30")
    con.execute(
        "UPDATE items SET expirationDate='2027-10-30', expirationRuleId='fallback-pantry' WHERE id=?",
        (item_id,),
    )
    con.commit()

    preview = json.loads(cli("expiration-refresh").stdout)
    assert preview["applied"] is False
    assert preview["changes"] == [{
        "id": item_id, "name": "Blueberry bagel",
        "oldDate": "2027-10-30", "newDate": "2026-11-06",
        "oldSource": "estimated", "newSource": "estimated",
        "oldRuleId": "fallback-pantry", "newRuleId": "bagel-any",
    }]
    assert _item(con, item_id)["expirationDate"] == "2027-10-30"

    applied = json.loads(cli("expiration-refresh", "--apply").stdout)
    assert applied["applied"] is True
    assert applied["count"] == 1
    assert _item(con, item_id)["expirationDate"] == "2026-11-06"

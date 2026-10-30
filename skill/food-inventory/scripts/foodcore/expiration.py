"""Deterministic shelf-life estimates for pantry rows without an explicit date.

Rules live in SQLite so a household can inspect and override them. Seed rows are
inserted only when their stable id is absent; a custom rule with a higher
priority wins without modifying application code.
"""

from __future__ import annotations

import datetime as dt

from .taxonomy import classify


DEFAULT_RULES = (
    # Exact produce rules first. Days are intentionally conservative estimates.
    ("banana-counter", "banana", None, "counter", 5),
    ("banana-fridge", "banana", None, "fridge", 7),
    ("banana-any", "banana", None, "*", 5),
    ("avocado-counter", "avocado", None, "counter", 4),
    ("avocado-fridge", "avocado", None, "fridge", 7),
    ("lettuce-fridge", "lettuce", None, "fridge", 7),
    ("spring-mix-fridge", "spring mix", None, "fridge", 5),
    ("spinach-fridge", "spinach", None, "fridge", 7),
    ("arugula-fridge", "arugula", None, "fridge", 5),
    ("kale-fridge", "kale", None, "fridge", 7),
    ("strawberry-fridge", "strawberry", None, "fridge", 5),
    ("blueberry-fridge", "blueberry", None, "fridge", 7),
    ("raspberry-fridge", "raspberry", None, "fridge", 4),
    ("blackberry-fridge", "blackberry", None, "fridge", 4),
    ("apple-fridge", "apple", None, "fridge", 21),
    ("apple-counter", "apple", None, "counter", 7),
    ("mushroom-fridge", "mushroom", None, "fridge", 7),
    ("asparagus-fridge", "asparagus", None, "fridge", 5),
    ("broccoli-fridge", "broccoli", None, "fridge", 7),
    ("cauliflower-fridge", "cauliflower", None, "fridge", 7),
    ("cucumber-fridge", "cucumber", None, "fridge", 7),
    ("tomato-counter", "tomato", None, "counter", 7),
    ("tomato-fridge", "tomato", None, "fridge", 7),
    ("bagel-any", "bagel", None, "*", 7),

    # Category rules cover the rest of the existing taxonomy.
    ("produce-greens-fridge", None, "produce.greens", "fridge", 7),
    ("produce-saladkits-fridge", None, "produce.saladkits", "fridge", 5),
    ("produce-herbs-fridge", None, "produce.herbs", "fridge", 7),
    ("produce-fruit-fridge", None, "produce.fruit", "fridge", 10),
    ("produce-fruit-counter", None, "produce.fruit", "counter", 5),
    ("produce-vegetables-fridge", None, "produce.vegetables", "fridge", 10),
    ("produce-vegetables-counter", None, "produce.vegetables", "counter", 7),
    ("produce-aromatics-fridge", None, "produce.aromatics", "fridge", 14),
    ("produce-aromatics-pantry", None, "produce.aromatics", "pantry", 30),
    ("ground-beef-fridge", "ground beef", None, "fridge", 2),
    ("ground-chicken-fridge", "ground chicken", None, "fridge", 2),
    ("ground-turkey-fridge", "ground turkey", None, "fridge", 2),
    ("meat-poultry-fridge", None, "meat.poultry", "fridge", 2),
    ("meat-beef-fridge", None, "meat.beef", "fridge", 3),
    ("meat-pork-fridge", None, "meat.pork", "fridge", 3),
    ("meat-sausage-fridge", None, "meat.sausage", "fridge", 2),
    ("meat-seafood-fridge", None, "meat.seafood", "fridge", 2),
    ("meat-plant-fridge", None, "meat.plant", "fridge", 5),
    ("meat-freezer", None, "meat.*", "freezer", 180),
    ("deli-fridge", None, "deli.*", "fridge", 4),
    ("dairy-milk-fridge", None, "dairy.milk", "fridge", 7),
    ("dairy-plantmilk-fridge", None, "dairy.plantmilk", "fridge", 7),
    ("dairy-yogurt-fridge", None, "dairy.yogurt", "fridge", 14),
    ("cottage-cheese-fridge", "cottage cheese", None, "fridge", 7),
    ("ricotta-fridge", "ricotta", None, "fridge", 7),
    ("cream-cheese-fridge", "cream cheese", None, "fridge", 14),
    ("fresh-mozzarella-fridge", "mozzarella", None, "fridge", 7),
    ("dairy-cheese-fridge", None, "dairy.cheese", "fridge", 30),
    ("dairy-eggs-fridge", None, "dairy.eggs", "fridge", 28),
    ("bakery-counter", None, "bakery.*", "counter", 7),
    ("bakery-fridge", None, "bakery.*", "fridge", 14),
    ("bakery-freezer", None, "bakery.*", "freezer", 90),
    ("frozen-freezer", None, "frozen.*", "freezer", 180),
    ("pantry-pantry", None, "pantry.*", "pantry", 365),
    ("pantry-cupboard", None, "pantry.*", "cupboard", 365),
    ("snacks-pantry", None, "snacks.*", "pantry", 90),
    ("drinks-fridge", None, "drinks.*", "fridge", 30),
    ("drinks-pantry", None, "drinks.*", "pantry", 180),
    ("bar-any", None, "bar.*", "*", 365),
    ("household-any", None, "household.*", "*", 730),

    # A date would be actively misleading for these categories. Higher priority
    # makes these opt-outs beat the older catch-all built-ins on upgraded DBs.
    ("bar-no-estimate", None, "bar.*", "*", 0, 100, 1),
    ("household-no-estimate", None, "household.*", "*", 0, 100, 1),
    ("spices-no-estimate", None, "pantry.spices", "*", 0, 100, 1),

    # Total deterministic fallback: every new item receives an estimate.
    ("fallback-fridge", None, None, "fridge", 4),
    ("fallback-freezer", None, None, "freezer", 180),
    ("fallback-counter", None, None, "counter", 7),
    ("fallback-pantry", None, None, "pantry", 365),
    ("fallback-cupboard", None, None, "cupboard", 365),
    ("fallback-any", None, None, "*", 30),
)


def seed(con) -> None:
    """Install missing built-in rules without overwriting household edits."""
    dated = [rule for rule in DEFAULT_RULES if len(rule) == 5]
    undated = [rule for rule in DEFAULT_RULES if len(rule) == 7]
    con.executemany(
        """INSERT OR IGNORE INTO expiration_rules
           (id, generic, category, storage, days, priority, enabled, source, noEstimate)
           VALUES (?, ?, ?, ?, ?, 0, 1, 'built-in', 0)""",
        dated,
    )
    con.executemany(
        """INSERT OR IGNORE INTO expiration_rules
           (id, generic, category, storage, days, priority, enabled, source, noEstimate)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'built-in', 1)""",
        undated,
    )


def _category_matches(rule: str | None, category: str) -> bool:
    if not rule:
        return True
    if rule.endswith(".*"):
        return category.startswith(rule[:-1])
    return rule == category


def _base_date(value: str | None, today: dt.date) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return today


def estimate(con, obj: dict, *, today: dt.date | None = None) -> dict:
    """Return an expiration estimate and its rule for one item.

    Selection is deterministic: enabled matching rules sort by explicit
    priority, then generic/category/storage specificity, then stable rule id.
    """
    placed = classify(
        name=obj.get("name"),
        brand=obj.get("brand"),
        category=obj.get("category"),
        subCategory=obj.get("subCategory"),
        spiritType=obj.get("spiritType"),
        storage=obj.get("storage"),
    )
    generic = placed.get("generic")
    category = placed.get("cat") or "other.other"
    storage = str(obj.get("storage") or "").strip().lower()
    candidates = []
    for row in con.execute(
        """SELECT id, generic, category, storage, days, priority, noEstimate
           FROM expiration_rules WHERE enabled = 1"""
    ).fetchall():
        rule = dict(row)
        if rule["generic"] and rule["generic"] != generic:
            continue
        if not _category_matches(rule["category"], category):
            continue
        if rule["storage"] not in ("*", storage):
            continue
        score = (
            int(rule["priority"] or 0),
            1 if rule["generic"] else 0,
            2 if rule["category"] and not rule["category"].endswith(".*") else
            (1 if rule["category"] else 0),
            1 if rule["storage"] != "*" else 0,
        )
        candidates.append((score, str(rule["id"]), rule))
    if not candidates:  # defensive: the built-in wildcard normally makes this impossible
        return {}
    _, _, selected = max(candidates, key=lambda value: (value[0], value[1]))
    if selected["noEstimate"]:
        return {
            "expirationDate": None,
            "expirationSource": "not_applicable",
            "expirationRuleId": selected["id"],
            "category": category,
            "generic": generic,
        }
    base = _base_date(obj.get("purchaseDate") or obj.get("createdAt"), today or dt.date.today())
    return {
        "expirationDate": (base + dt.timedelta(days=int(selected["days"]))).isoformat(),
        "expirationSource": "estimated",
        "expirationRuleId": selected["id"],
        "category": category,
        "generic": generic,
    }


def refresh_plan(con) -> list[dict]:
    """Preview rule changes for active estimates without writing anything."""
    changes = []
    rows = con.execute(
        """SELECT * FROM items
           WHERE deletedAt IS NULL AND expirationSource = 'estimated'"""
    ).fetchall()
    for row in rows:
        result = estimate(con, dict(row))
        if not result:
            continue
        if (result.get("expirationDate"), result.get("expirationSource"), result.get("expirationRuleId")) == (
            row["expirationDate"], row["expirationSource"], row["expirationRuleId"]
        ):
            continue
        changes.append({
            "id": row["id"],
            "name": row["name"],
            "oldDate": row["expirationDate"],
            "newDate": result.get("expirationDate"),
            "oldSource": row["expirationSource"],
            "newSource": result.get("expirationSource"),
            "oldRuleId": row["expirationRuleId"],
            "newRuleId": result.get("expirationRuleId"),
        })
    return changes


def refresh_estimates(con) -> list[dict]:
    """Apply a previously previewable refresh to active generated estimates."""
    changes = refresh_plan(con)
    for change in changes:
        con.execute(
            """UPDATE items
               SET expirationDate = ?, expirationSource = ?, expirationRuleId = ?
               WHERE id = ?""",
            (change["newDate"], change["newSource"], change["newRuleId"], change["id"]),
        )
    return changes

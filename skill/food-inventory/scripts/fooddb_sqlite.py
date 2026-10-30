#!/usr/bin/env python3
"""fooddb_sqlite.py - local SQLite-backed food + bar inventory.

Why:
- safe concurrent writes (transactions)
- real updates/deletes
- indexed queries

DB path (first that applies):
- FOODDB_PATH
- GT_DATA/food.db
- the db an installer pinned beside this skill (grubtrack.json, written by tools/install_skill.py)
- ~/.local/share/grubtrack/food.db (XDG_DATA_HOME respected)

Usage:
  python3 fooddb_sqlite.py where                 # which food.db this CLI uses
  python3 fooddb_sqlite.py init
  python3 fooddb_sqlite.py add --json '{...}'
  python3 fooddb_sqlite.py add --name "..." --storage fridge --qty 1 --unit tub --category dairy
  python3 fooddb_sqlite.py list [--current] [--where "storage='fridge' AND deletedAt IS NULL"] [--limit 50]
  python3 fooddb_sqlite.py inventory [--where "location='bar'"] [--limit 50]
  python3 fooddb_sqlite.py expiring [--days 3 | --on 2026-08-16] [--limit 500]
  python3 fooddb_sqlite.py expired [--limit 500]
  python3 fooddb_sqlite.py find --q "disaronno"        # searches current inventory by default
  python3 fooddb_sqlite.py find --q "disaronno" --all  # searches full history
  python3 fooddb_sqlite.py update --id <itemId> --set '{"bottleState":"open"}'
  python3 fooddb_sqlite.py delete --id <itemId> [--notes eaten|tossed]

  python3 fooddb_sqlite.py shop                          # open list, JSON
  python3 fooddb_sqlite.py shop --all                    # including crossed off
  python3 fooddb_sqlite.py shop-add --name "oat milk" [--qty 2] [--unit carton]
                                    [--notes "..."] [--by kitchen]
  python3 fooddb_sqlite.py shop-done --id <id> | --name "oat milk"
  python3 fooddb_sqlite.py shop-undo --id <id>
  python3 fooddb_sqlite.py shop-clear                    # purge the crossed-off ones

  Receipts and prices (the purchase ledger, foodcore/):
  python3 fooddb_sqlite.py receipt-add --file /tmp/receipt.json [--replace] [--no-autolink]
  python3 fooddb_sqlite.py receipt-add --json - < /tmp/receipt.json      # same, from stdin
  python3 fooddb_sqlite.py receipts [--limit 20]
  python3 fooddb_sqlite.py receipt --id <receiptId>
  python3 fooddb_sqlite.py receipt-link --line <purchaseId> --item <itemId|none>
  python3 fooddb_sqlite.py prices --q "eggs"            # what it costs, where, and how that moved
  python3 fooddb_sqlite.py spend [--days 30]            # money out by store and department
  python3 fooddb_sqlite.py stores
  python3 fooddb_sqlite.py categories                   # the taxonomy: dept.cat keys
  python3 fooddb_sqlite.py set-cat --product <productId> --category dairy.yogurt
  python3 fooddb_sqlite.py sweep                        # re-resolve stores/products/categories

  Another machine's GrubTrack (foodcore/remote.py): with a URL in grubtrack.json or GRUBTRACK_URL,
  every command runs on that server, with the files it names uploaded alongside.
  python3 fooddb_sqlite.py snapshot [--scope core|full] [--max-age 60]   # a readable copy of the db
  python3 fooddb_sqlite.py journal-add --slug pad-thai --score 8 --review "..." [--type freeform] [--tags a,b]

  Recipe library (foodcore/recipes.py):
  python3 fooddb_sqlite.py recipes-import --file ~/recipes [--source NAME] [--dry-run]
      # Meal-Master, MasterCook, schema.org JSON / JSON-LD / HTML, Mealie, Paprika, GrubTrack JSON(L),
      # a folder or a zip of any of them; duplicates (same title and ingredients) are skipped
  python3 fooddb_sqlite.py recipes-relabel [--dry-run]   # re-derive protein/cuisine/dish with the current rules

Notes:
- Inventory rows are "current state": a restock merges into the existing row. Prices are NOT:
  every price written to a row is also recorded in the `purchases` ledger (database triggers),
  so a restock can never erase what something cost last time.
- FOODDB_PATH overrides the database path (tests, throwaway copies).
- `{baseDir}` in SKILL.md is this skill's folder (the installer writes the absolute path in).
"""

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import uuid

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_db_path() -> str:
    """Where food.db lives. GrubTrack's server, its tests and an installed agent skill all ask
    here, so the CLI an agent runs and the web app open the same file."""
    if os.environ.get("FOODDB_PATH"):
        return os.path.expanduser(os.environ["FOODDB_PATH"])
    if os.environ.get("GT_DATA"):
        return os.path.join(os.path.expanduser(os.environ["GT_DATA"]), "food.db")
    pinned = os.path.join(SKILL_DIR, "grubtrack.json")
    try:
        with open(pinned, encoding="utf-8") as f:
            db = json.load(f).get("db")
        if db:
            return os.path.expanduser(db)
    except (OSError, ValueError):
        pass
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "grubtrack", "food.db")


DB_PATH = default_db_path()
ROOT = os.path.dirname(DB_PATH)


def _remote():
    try:
        from foodcore import remote
    except Exception as e:  # pragma: no cover - a broken foodcore must not stop local logging
        print(f"warning: foodcore unavailable ({e}); using the local database", file=sys.stderr)
        return None
    return remote.config(SKILL_DIR)


def readable_db(scope: str = "core", max_age: float = 60) -> str:
    """A path code with its own SQL can open read-only: the local food.db, or a fresh copy of a
    GrubTrack server's (see foodcore/remote.py). Never write to it."""
    r = _remote()
    if not r:
        return DB_PATH
    from foodcore import remote
    return remote.snapshot(r, scope=scope, max_age=max_age)


def now_iso_local():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _core():
    """foodcore (receipts, prices, taxonomy) is loaded lazily and never allowed to break plain
    inventory logging: if it can't load, logging still works and the reason goes to stderr."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import foodcore.ledger as ledger  # noqa: F401
        import foodcore.intel as intel  # noqa: F401
        import foodcore.expiration as expiration  # noqa: F401
        import foodcore.schema as schema  # noqa: F401
        return sys.modules["foodcore"]
    except Exception as e:  # pragma: no cover - defensive
        print(f"warning: foodcore unavailable ({e}); prices/categories not updated", file=sys.stderr)
        return None


def _after_write(con):
    """Resolve categories/products/unit prices for what was just written (~40 ms). The write has
    already committed: if the database is busy the sweep is skipped (GrubTrack's own sweep
    catches up within 30 s) rather than holding the caller past its timeout."""
    core = _core()
    if core:
        try:
            con.execute("PRAGMA busy_timeout = 1500")
            core.ledger.sweep(con)
        except Exception as e:  # pragma: no cover - defensive
            print(f"warning: sweep skipped ({e})", file=sys.stderr)


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def init_db(con: sqlite3.Connection):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS items (
          id TEXT PRIMARY KEY,
          createdAt TEXT NOT NULL,
          updatedAt TEXT NOT NULL,
          deletedAt TEXT,
          matchKey TEXT,

          createdByChannel TEXT,
          createdByChatId TEXT,
          createdByName TEXT,

          name TEXT,
          brand TEXT,
          category TEXT,
          storage TEXT,
          location TEXT,

          quantity REAL,
          unit TEXT,
          size TEXT,
          expirationDate TEXT,
          purchaseDate TEXT,
          notes TEXT,

          subCategory TEXT,
          spiritType TEXT,
          abv REAL,
          volumeMl REAL,
          openedAt TEXT,
          bottleState TEXT,

          rawUserText TEXT,
          rawVision TEXT,
          confidenceJson TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(deletedAt);
        CREATE INDEX IF NOT EXISTS idx_items_storage ON items(storage);
        CREATE INDEX IF NOT EXISTS idx_items_location ON items(location);
        CREATE INDEX IF NOT EXISTS idx_items_spiritType ON items(spiritType);
        CREATE INDEX IF NOT EXISTS idx_items_expirationDate ON items(expirationDate);

        CREATE TABLE IF NOT EXISTS shopping (
          id TEXT PRIMARY KEY,
          createdAt TEXT NOT NULL,
          updatedAt TEXT NOT NULL,
          doneAt TEXT,
          name TEXT NOT NULL,
          quantity REAL,
          unit TEXT,
          notes TEXT,
          addedBy TEXT,
          itemId TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_shopping_done ON shopping(doneAt);
        CREATE INDEX IF NOT EXISTS idx_shopping_name ON shopping(name);

        CREATE TABLE IF NOT EXISTS images (
          id TEXT PRIMARY KEY,
          itemId TEXT NOT NULL,
          path TEXT NOT NULL,
          sourcePath TEXT,
          sha256 TEXT,
          createdAt TEXT NOT NULL,
          FOREIGN KEY(itemId) REFERENCES items(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_images_itemId ON images(itemId);
        """
    )
    # Backfill for older DBs that predate matchKey
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)").fetchall()}
    if "matchKey" not in cols:
        con.execute("ALTER TABLE items ADD COLUMN matchKey TEXT")

    # Backfill matchKey for older rows (best-effort)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM items WHERE matchKey IS NULL OR matchKey = ''").fetchall()
    for r in rows:
        obj = dict(r)
        mk = compute_match_key(obj)
        con.execute("UPDATE items SET matchKey=? WHERE id=?", (mk, obj.get('id')))

    # (re)create index after ensuring column exists
    con.execute("CREATE INDEX IF NOT EXISTS idx_items_matchKey ON items(matchKey)")
    con.commit()

    core = _core()
    if core:
        try:
            core.schema.migrate(con)
        except sqlite3.OperationalError as e:
            # a lock or a racing migration must not take `list` or `shop` down with it
            con.rollback()
            print(f"warning: schema migration deferred ({e})", file=sys.stderr)


def _normalize_date(s: str | None):
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # accept YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    # accept M/D[/YY]
    import re

    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", s)
    if m:
        mm = int(m.group(1))
        dd = int(m.group(2))
        yy = m.group(3)
        if yy is None:
            yy = str(dt.date.today().year)
        if len(yy) == 2:
            yy = "20" + yy
        return f"{int(yy):04d}-{mm:02d}-{dd:02d}"
    return s


def parse_price(v, strict: bool = False):
    """4.99, "4.99", "$4.99", "1,299.00" -> float; None/"" -> None. A value starting with "." is
    almost always "$4.99" with the "$4" eaten by the shell, so it is refused, not stored as 0.99.
    Unreadable: None (strict: SystemExit naming the value)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        v = None
    elif isinstance(v, (int, float)):
        return float(v)
    else:
        t = str(v).strip()
        if t.startswith("."):
            raise SystemExit(f"price {t!r} looks cut off: a $ inside double quotes is eaten by the shell "
                             "(\"$4.99\" arrives as \".99\"). Write it without the $ (4.99) or use single quotes.")
        try:
            return float(t.replace("$", "").replace(",", ""))
        except ValueError:
            pass
    if strict:
        raise SystemExit(f"price must be a number like 4.99, got {v!r}")
    print(f"warning: ignored unreadable price {v!r}", file=sys.stderr)
    return None


def _norm(s: str | None):
    if s is None:
        return ""
    return str(s).strip().lower()


def compute_match_key(obj: dict):
    # Heuristic identity for "same item".
    # Strong keys when available (bar): location + spiritType + brand + volumeMl
    # Otherwise: location + storage + brand + name
    location = _norm(obj.get("location"))
    storage = _norm(obj.get("storage"))
    spirit = _norm(obj.get("spiritType"))
    brand = _norm(obj.get("brand"))
    name = _norm(obj.get("name"))

    # Normalize common "update" suffixes from the old JSONL event-log style.
    import re
    name = re.sub(r"\s*\([^)]*update[^)]*\)\s*$", "", name).strip()

    vol = obj.get("volumeMl")
    vol_s = str(int(vol)) if isinstance(vol, (int, float)) and vol else ""

    if location and spirit and brand and vol_s:
        # Include name to avoid merging different expressions from same brand (e.g., Smokehead variants)
        return f"bar|{location}|{spirit}|{brand}|{name}|{vol_s}"
    if location and brand and name:
        return f"gen|{location}|{brand}|{name}"
    # fallback: include storage to avoid merging fridge vs cupboard
    return f"weak|{location}|{storage}|{brand}|{name}|{vol_s}"


def find_existing_by_matchkey(con: sqlite3.Connection, match_key: str):
    if not match_key:
        return None
    row = con.execute(
        "SELECT id FROM items WHERE deletedAt IS NULL AND matchKey = ? ORDER BY updatedAt DESC LIMIT 1",
        (match_key,),
    ).fetchone()
    return row[0] if row else None


def add_item(con: sqlite3.Connection, obj: dict, merge: bool = True):
    ts = now_iso_local()
    match_key = obj.get("matchKey") or compute_match_key(obj)

    existing_id = find_existing_by_matchkey(con, match_key) if merge else None
    item_id = existing_id or obj.get("id") or f"fi_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    created_by = obj.get("createdBy") or {}
    raw = obj.get("raw") or {}
    conf = obj.get("confidence")
    expiration_date = _normalize_date(obj.get("expirationDate"))
    expiration_source = "explicit" if expiration_date else None
    expiration_rule_id = None
    if not expiration_date:
        core = _core()
        if not core:
            raise RuntimeError("expiration rules are unavailable")
        estimate = core.expiration.estimate(con, obj)
        if not estimate.get("expirationDate"):
            raise RuntimeError("no expiration rule matched the item")
        expiration_date = estimate["expirationDate"]
        expiration_source = estimate["expirationSource"]
        expiration_rule_id = estimate["expirationRuleId"]

    row = {
        "id": item_id,
        "createdAt": obj.get("createdAt") or ts,
        "updatedAt": obj.get("updatedAt") or ts,
        "deletedAt": obj.get("deletedAt"),
        "matchKey": match_key,

        "createdByChannel": created_by.get("channel"),
        "createdByChatId": created_by.get("chatId"),
        "createdByName": created_by.get("name"),

        "name": obj.get("name"),
        "brand": obj.get("brand"),
        "category": obj.get("category"),
        "storage": obj.get("storage"),
        "location": obj.get("location"),

        "quantity": obj.get("quantity"),
        "unit": obj.get("unit"),
        "size": obj.get("size"),
        "expirationDate": expiration_date,
        "purchaseDate": _normalize_date(obj.get("purchaseDate")),
        "notes": obj.get("notes"),

        "subCategory": obj.get("subCategory"),
        "spiritType": obj.get("spiritType"),
        "abv": obj.get("abv"),
        "volumeMl": obj.get("volumeMl"),
        "openedAt": _normalize_date(obj.get("openedAt")),
        "bottleState": obj.get("bottleState"),

        "rawUserText": raw.get("userText"),
        "rawVision": raw.get("vision"),
        "confidenceJson": json.dumps(conf) if conf is not None else None,
    }
    # price columns exist once foodcore has migrated the schema
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)").fetchall()}
    if "expirationSource" in cols:
        row["expirationSource"] = expiration_source
        row["expirationRuleId"] = expiration_rule_id
    price = parse_price(obj.get("price"))
    receipt_id = obj.get("receiptId") or None
    priced = "price" in cols and (price is not None or receipt_id is not None)
    if "price" in cols:
        row["price"] = price
        row["receiptId"] = receipt_id

    with con:
        if existing_id:
            # Merge: update only non-null fields from incoming row.
            patch = {k: v for k, v in row.items() if v is not None}
            patch.pop('id', None)
            patch.pop('createdAt', None)
            patch['updatedAt'] = ts
            if priced:
                # A priced restock is a new purchase: its price, receipt and date are this trip's.
                # Keeping the old row's receiptId/purchaseDate would file the new price under the
                # old trip (or hide it behind the old receipt), and a receipt without a price must
                # not inherit the old one.
                patch["price"] = price
                patch["receiptId"] = receipt_id
                patch["purchaseDate"] = row.get("purchaseDate") or dt.date.today().isoformat()
            # Build UPDATE
            cols = list(patch.keys())
            sets = ",".join([f"{c}=?" for c in cols])
            con.execute(f"UPDATE items SET {sets} WHERE id=?", (*[patch[c] for c in cols], item_id))
        else:
            cols = ",".join(row.keys())
            qs = ",".join(["?"] * len(row))
            con.execute(f"INSERT INTO items ({cols}) VALUES ({qs})", list(row.values()))

        if priced and price is not None:
            core = _core()
            if core:
                core.ledger.capture_item_price(con, item_id)

        for img in obj.get("images") or []:
            con.execute(
                "INSERT INTO images (id,itemId,path,sourcePath,sha256,createdAt) VALUES (?,?,?,?,?,?)",
                (
                    f"img_{uuid.uuid4().hex[:10]}",
                    item_id,
                    img.get("path"),
                    img.get("sourcePath"),
                    img.get("sha256"),
                    ts,
                ),
            )

    return item_id


def list_items(con: sqlite3.Connection, where: str | None, limit: int, current: bool = False):
    where_clause = where.strip() if where else "deletedAt IS NULL"
    if not current:
        rows = con.execute(
            f"SELECT * FROM items WHERE {where_clause} ORDER BY createdAt DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    rows = con.execute(
        f"""
        SELECT i.* FROM items i
        JOIN (
          SELECT matchKey, MAX(updatedAt) AS mu
          FROM items
          WHERE {where_clause} AND matchKey IS NOT NULL
          GROUP BY matchKey
        ) m
        ON i.matchKey = m.matchKey AND i.updatedAt = m.mu
        WHERE {where_clause}
        ORDER BY i.updatedAt DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def find_items(con: sqlite3.Connection, q: str, limit: int, current: bool = True):
    ql = f"%{q.lower()}%"
    if not current:
        rows = con.execute(
            """
            SELECT * FROM items
            WHERE deletedAt IS NULL
              AND (
                lower(coalesce(name,'')) LIKE ? OR
                lower(coalesce(brand,'')) LIKE ? OR
                lower(coalesce(notes,'')) LIKE ? OR
                lower(coalesce(category,'')) LIKE ? OR
                lower(coalesce(storage,'')) LIKE ? OR
                lower(coalesce(location,'')) LIKE ? OR
                lower(coalesce(spiritType,'')) LIKE ?
              )
            ORDER BY createdAt DESC
            LIMIT ?
            """,
            (ql, ql, ql, ql, ql, ql, ql, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # Search current inventory (latest row per matchKey)
    rows = con.execute(
        """
        WITH latest AS (
          SELECT matchKey, MAX(updatedAt) AS mu
          FROM items
          WHERE deletedAt IS NULL AND matchKey IS NOT NULL
          GROUP BY matchKey
        )
        SELECT i.* FROM items i
        JOIN latest l ON i.matchKey = l.matchKey AND i.updatedAt = l.mu
        WHERE i.deletedAt IS NULL
          AND (
            lower(coalesce(i.name,'')) LIKE ? OR
            lower(coalesce(i.brand,'')) LIKE ? OR
            lower(coalesce(i.notes,'')) LIKE ? OR
            lower(coalesce(i.category,'')) LIKE ? OR
            lower(coalesce(i.storage,'')) LIKE ? OR
            lower(coalesce(i.location,'')) LIKE ? OR
            lower(coalesce(i.spiritType,'')) LIKE ?
          )
        ORDER BY i.updatedAt DESC
        LIMIT ?
        """,
        (ql, ql, ql, ql, ql, ql, ql, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def update_item(con: sqlite3.Connection, item_id: str, patch: dict):
    patch = dict(patch)
    patch.pop("id", None)
    patch.pop("createdAt", None)
    patch["updatedAt"] = now_iso_local()

    # normalize date-ish fields
    for k in ("expirationDate", "purchaseDate", "openedAt"):
        if k in patch:
            patch[k] = _normalize_date(patch[k])
    if "expirationDate" in patch:
        item_cols = {r[1] for r in con.execute("PRAGMA table_info(items)").fetchall()}
        if "expirationSource" in item_cols:
            patch["expirationSource"] = "explicit" if patch["expirationDate"] else None
            patch["expirationRuleId"] = None
    if "price" in patch:
        patch["price"] = parse_price(patch["price"], strict=True)

    cols = list(patch.keys())
    if not cols:
        return
    sets = ",".join([f"{c}=?" for c in cols])
    vals = [patch[c] for c in cols]

    with con:
        con.execute(f"UPDATE items SET {sets} WHERE id=?", (*vals, item_id))


def delete_item(con: sqlite3.Connection, item_id: str, note: str | None = None):
    """Soft delete. `note` records WHY, when the caller knows.

    Added for kiosk-style clients whose rows have an ATE IT and a
    TOSSED button: both are this same soft delete, and the only difference between
    them (the only thing this list can ever learn from being cleared) is which one
    was pressed. Appended to any existing note rather than replacing it, because a
    note somebody typed about an item is not ours to throw away on the way out.
    """
    ts = now_iso_local()
    with con:
        if note:
            row = con.execute("SELECT notes FROM items WHERE id=?", (item_id,)).fetchone()
            had = (row["notes"] if row and row["notes"] else "").strip()
            merged = (had + " · " + note) if had else note
            con.execute("UPDATE items SET deletedAt=?, updatedAt=?, notes=? WHERE id=?",
                        (ts, ts, merged, item_id))
        else:
            con.execute("UPDATE items SET deletedAt=?, updatedAt=? WHERE id=?",
                        (ts, ts, item_id))


# ---------------------------------------------------------------- shopping list
#
# Lives here, in the same database as the inventory, because that is the whole point:
# "we're out of oat milk" and "oat milk is on the list" are two halves of one fact, and
# the Alexa list they used to live on accepts writes and silently drops them (measured
# 2026-08-17: add_item and update_item both return success and change nothing).
#
# Crossed off, never deleted: `doneAt` is the history, and it is what makes "did we
# already buy that" answerable. `shop-clear` is the only thing that removes a row.


def _shop_norm(s):
    return " ".join(str(s or "").strip().lower().split())


def shop_rows(con, include_done=False, limit=500):
    sql = "SELECT * FROM shopping"
    if not include_done:
        sql += " WHERE doneAt IS NULL"
    sql += " ORDER BY (doneAt IS NOT NULL), createdAt ASC LIMIT ?"
    return [dict(r) for r in con.execute(sql, (limit,)).fetchall()]


def shop_add(con, name, quantity=None, unit=None, notes=None, by=None, item_id=None):
    """Add one item. Adding something already on the list is not an error; it is a
    thing worth SAYING, so the caller is told which it was."""
    clean = " ".join(str(name or "").strip().split())
    if not clean:
        raise SystemExit("shop-add requires --name")
    dup = con.execute(
        "SELECT id, name FROM shopping WHERE doneAt IS NULL AND lower(name) = ?",
        (_shop_norm(clean),)).fetchone()
    if dup:
        return {"id": dup["id"], "name": dup["name"], "added": False,
                "reason": "already on the list"}
    now = now_iso_local()
    sid = str(uuid.uuid4())
    con.execute(
        "INSERT INTO shopping (id, createdAt, updatedAt, doneAt, name, quantity, unit,"
        " notes, addedBy, itemId) VALUES (?,?,?,NULL,?,?,?,?,?,?)",
        (sid, now, now, clean, quantity, unit, notes, by, item_id))
    con.commit()
    return {"id": sid, "name": clean, "added": True}


def shop_resolve(con, name):
    """Which row a spoken name means, with the same rule the kiosk uses.

    An EXACT match wins outright even when it is a substring of others, because a list
    that holds both "Parsley" and "Parsley flakes" makes a plain substring match a coin
    flip, and crossing off the wrong thing is silent, unrecoverable loss.
    """
    want = _shop_norm(name)
    rows = shop_rows(con)
    exact = [r for r in rows if _shop_norm(r["name"]) == want]
    if exact:
        return exact[0], None
    starts = [r for r in rows if _shop_norm(r["name"]).startswith(want)]
    inside = [r for r in rows if want in _shop_norm(r["name"])]
    for pool in (starts, inside):
        if len(pool) == 1:
            return pool[0], None
        if len(pool) > 1:
            return None, [r["name"] for r in pool]
    return None, []


def shop_set_done(con, sid, done=True):
    now = now_iso_local()
    cur = con.execute("UPDATE shopping SET doneAt=?, updatedAt=? WHERE id=?",
                      (now if done else None, now, sid))
    con.commit()
    return cur.rowcount


# ------------------------------------------------------------------ receipts & prices

LEDGER_COMMANDS = {"receipt-add", "receipts", "receipt", "receipt-link", "prices", "spend", "stores",
                   "categories", "set-cat", "sweep", "recipes-import", "recipes-relabel",
                   "journal-add"}


def _load_json(args):
    """--json '{...}', --json - (stdin), or --file path. Prefer the file or stdin: a dollar
    amount inside a double-quoted shell string is eaten by the shell ("$6.00" arrives as ".00")."""
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return json.load(f)
    if args.json == "-":
        return json.load(sys.stdin)
    return json.loads(args.json)


def _price_brief(p):
    keep = ("id", "name", "brand", "generic", "cat", "catLabel", "size", "n", "verified", "basis", "stats",
            "change", "storeGap", "deal", "inStock")
    out = {k: p.get(k) for k in keep}
    last = p.get("last") or {}
    out["last"] = {k: last.get(k) for k in ("date", "price", "regular", "unit", "unitLabel", "store", "verified")}
    out["stores"] = [{k: s.get(k) for k in ("store", "last", "avg", "n", "lastDate")} for s in p.get("stores", [])]
    return out


def _ledger_cmd(core, con, args):
    ledger, intel = core.ledger, core.intel
    cmd = args.cmd
    if cmd == "receipt-add":
        if not (args.json or args.file):
            raise SystemExit("receipt-add needs --file path.json or --json - (stdin)")
        data = _load_json(args)
        try:
            rep = ledger.import_receipt(con, data, replace=args.replace, autolink=not args.no_autolink)
        except ValueError as e:
            raise SystemExit(f"receipt not recorded: {e}")
        rc = rep["reconciliation"]
        if not rc["ok"] and not rep["partial"]:
            print(f"WARNING: receipt does not reconcile: lines ${rc['lines']} + tax ${rc['tax']} vs total "
                  f"${rc['total']} (off by ${rc['diff']}). Re-read the photo: a line is missing or misread.",
                  file=sys.stderr)
        return rep
    if cmd == "receipts":
        lim = args.limit if args.limit != 50 else 20
        return intel.spend(con)["trips"][:lim]
    if cmd == "receipt":
        if not args.id:
            raise SystemExit("receipt needs --id")
        r = ledger.receipt_json(con, args.id)
        if not r:
            raise SystemExit(f"no receipt {args.id}")
        return r
    if cmd == "receipt-link":
        if not args.line or not args.item:
            raise SystemExit("receipt-link needs --line <purchaseId> --item <itemId|none>")
        ledger.link_line(con, args.line, None if args.item.lower() == "none" else args.item)
        return {"ok": True}
    if cmd == "prices":
        book = intel.price_book(con, q=args.q)
        return [_price_brief(p) for p in book[: (args.limit if args.limit != 50 else 25)]]
    if cmd == "spend":
        sp = intel.spend(con)
        days = args.days or 30
        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        trips = [t for t in sp["trips"] if t["date"] >= since]
        return {"days": days, "total": round(sum(t["total"] or 0 for t in trips), 2), "trips": trips,
                "months": sp["months"], "byStore": sp["byStore"], "byDept": sp["byDept"]}
    if cmd == "stores":
        return intel.stores(con)
    if cmd == "categories":
        return intel.taxonomy()
    if cmd == "set-cat":
        cat = args.category
        if not args.product or not cat:
            raise SystemExit("set-cat needs --product <productId> --category dept.cat (see `categories`)")
        if cat not in core.CATEGORIES:
            raise SystemExit(f"unknown category {cat!r} (see `categories`)")
        if not con.execute("SELECT 1 FROM products WHERE id = ?", (args.product,)).fetchone():
            raise SystemExit(f"no product {args.product!r} (the id is in `prices` output)")
        ledger.set_product_category(con, args.product, cat)
        return {"ok": True}
    if cmd == "sweep":
        return ledger.sweep(con)
    if cmd == "recipes-import":
        import foodcore.recipes as rc
        if not args.file:
            raise SystemExit("recipes-import needs --file: a file, a folder, or a zip")
        path = os.path.expanduser(args.file)
        if not os.path.exists(path):
            raise SystemExit(f"no such file or folder: {args.file}")
        files = {}

        def found():
            from pathlib import Path
            for f, r in rc.from_path(Path(path)):
                files[f] = files.get(f, 0) + 1
                yield r
        rep = rc.import_recipes(con, found(), source=args.source, dry_run=bool(args.dry_run))
        return {**rep, "files": len(files), "dryRun": bool(args.dry_run)}
    if cmd == "journal-add":
        import foodcore.recipes as rc
        if not args.slug:
            raise SystemExit("journal-add needs --slug")
        score = int(args.score) if args.score not in (None, "") else None
        tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
        return rc.journal_add(con, args.slug, args.type or "freeform", score, tags, args.review or "")
    if cmd == "recipes-relabel":
        import foodcore.recipes as rc
        return rc.relabel(con, dry_run=bool(args.dry_run))
    raise SystemExit(f"Unknown command: {cmd}")


# The flags this CLI had before the ledger (2026-10-24). argparse used to accept any unique
# prefix of these (`--cat` for --category, `--li` for --limit) and the agent may rely on it, so
# those prefixes are expanded against THIS list; flags added since must be written in full.
BASELINE_FLAGS = ["--json", "--id", "--set", "--where", "--limit", "--name", "--brand", "--category", "--storage",
                  "--location", "--qty", "--unit", "--size", "--exp", "--purchase", "--notes", "--subCategory",
                  "--spiritType", "--abv", "--volumeMl", "--openedAt", "--bottleState", "--q", "--days", "--on",
                  "--current", "--all", "--no-merge", "--by", "--help"]


def expand_abbrevs(argv):
    out = []
    for a in argv:
        if a.startswith("--") and len(a) > 2:
            flag, eq, val = a.partition("=")
            if flag not in BASELINE_FLAGS:
                hits = [f for f in BASELINE_FLAGS if f.startswith(flag)]
                if len(hits) == 1:
                    a = hits[0] + eq + val
        out.append(a)
    return out


def main():
    remote = _remote()
    if remote and len(sys.argv) > 1 and sys.argv[1] not in ("-h", "--help", "snapshot", "where"):
        from foodcore import remote as rm
        sys.exit(rm.run(remote, sys.argv[1:], SKILL_DIR))
    ap = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    ap.add_argument("cmd", nargs="?")
    ap.add_argument("--json")
    ap.add_argument("--id")
    ap.add_argument("--set")
    ap.add_argument("--where")
    ap.add_argument("--limit", type=int, default=50)

    # item fields
    ap.add_argument("--name")
    ap.add_argument("--brand")
    ap.add_argument("--category")
    ap.add_argument("--storage")
    ap.add_argument("--location")
    ap.add_argument("--qty", type=float)
    ap.add_argument("--unit")
    ap.add_argument("--size")
    ap.add_argument("--exp")
    ap.add_argument("--purchase")
    ap.add_argument("--notes")

    ap.add_argument("--subCategory")
    ap.add_argument("--spiritType")
    ap.add_argument("--abv", type=float)
    ap.add_argument("--volumeMl", type=float)
    ap.add_argument("--openedAt")
    ap.add_argument("--bottleState")

    ap.add_argument("--q")
    ap.add_argument("--days", type=int)
    ap.add_argument("--on")
    ap.add_argument("--current", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-merge", dest="no_merge", action="store_true")
    ap.add_argument("--by")            # which unit/room put it on the list
    ap.add_argument("--price")
    ap.add_argument("--receipt")
    ap.add_argument("--file")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--no-autolink", dest="no_autolink", action="store_true")
    ap.add_argument("--product")
    ap.add_argument("--line")
    ap.add_argument("--item")
    ap.add_argument("--source")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true")
    ap.add_argument("--scope", default="core")
    ap.add_argument("--max-age", dest="max_age", type=float, default=60)
    ap.add_argument("--slug")
    ap.add_argument("--type")
    ap.add_argument("--score")
    ap.add_argument("--tags")
    ap.add_argument("--review")
    ap.add_argument("-h", "--help", action="store_true")

    args = ap.parse_args(expand_abbrevs(sys.argv[1:]))

    if args.help or not args.cmd:
        print(__doc__.strip())
        return

    if args.cmd == "where":
        if remote:
            print(json.dumps({"server": remote["url"], "remote": True}, indent=2))
        else:
            print(json.dumps({"db": DB_PATH, "exists": os.path.exists(DB_PATH),
                              "images": os.path.join(os.path.dirname(DB_PATH), "images")}, indent=2))
        return

    if args.cmd == "snapshot":
        print(json.dumps({"path": readable_db(args.scope, args.max_age), "remote": bool(remote)}, indent=2))
        return

    con = connect()

    if args.cmd == "init":
        init_db(con)
        print("OK")
        return

    init_db(con)

    if args.cmd == "add":
        merge = not getattr(args, 'no_merge', False)
        if args.json or args.file:
            obj = _load_json(args)
        else:
            obj = {
                "name": args.name,
                "brand": args.brand,
                "category": args.category,
                "storage": args.storage,
                "location": args.location,
                "quantity": args.qty,
                "unit": args.unit,
                "size": args.size,
                "expirationDate": args.exp,
                "purchaseDate": args.purchase,
                "notes": args.notes,
                "subCategory": args.subCategory,
                "spiritType": args.spiritType,
                "abv": args.abv,
                "volumeMl": args.volumeMl,
                "openedAt": args.openedAt,
                "bottleState": args.bottleState,
                "price": parse_price(args.price, strict=True),
                "receiptId": args.receipt,
            }
        item_id = add_item(con, obj, merge=merge)
        _after_write(con)
        print(item_id)
        return

    if args.cmd == "list":
        rows = list_items(con, args.where, args.limit, current=args.current)
        print(json.dumps(rows, indent=2))
        return

    if args.cmd == "inventory":
        # "what do we have" must be the complete answer: same high-limit rule as
        # expiring: the default 50-row window silently hides a third of the pantry.
        rows = list_items(con, args.where, args.limit if args.limit != 50 else 500, current=True)
        print(json.dumps(rows, indent=2))
        return

    if args.cmd == "expiring":
        # Answers "what expires today / tomorrow / in N days" in one call.
        # Filtering happens in SQL and the limit is deliberately high: a plain
        # `list` returns the 50 newest rows, which silently hides older items
        # that are the very ones about to expire.
        if args.on:
            # exact single day: accepts today/tomorrow/yesterday or YYYY-MM-DD so
            # "what expires tomorrow" can't be answered with a range that also
            # sweeps in today's items
            key = args.on.strip().lower()
            rel = {"today": "now", "tomorrow": "+1 day", "yesterday": "-1 day"}
            if key in rel:
                clause = f"expirationDate = date('now', 'localtime', '{rel[key]}')" if key != "today" \
                         else "expirationDate = date('now', 'localtime')"
                params = []
            else:
                clause = "expirationDate = ?"
                params = [args.on]
        else:
            days = args.days if args.days is not None else 3
            clause = "expirationDate BETWEEN date('now', 'localtime') AND date('now', 'localtime', ? || ' days')"
            params = [f"+{int(days)}"]
        limit = args.limit if args.limit != 50 else 500
        rows = con.execute(
            "SELECT * FROM items WHERE deletedAt IS NULL AND expirationDate IS NOT NULL "
            f"AND {clause} ORDER BY expirationDate ASC, name ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        print(json.dumps([dict(r) for r in rows], indent=2))
        return

    if args.cmd == "expired":
        rows = con.execute(
            "SELECT * FROM items WHERE deletedAt IS NULL AND expirationDate IS NOT NULL "
            "AND expirationDate < date('now', 'localtime') ORDER BY expirationDate DESC LIMIT ?",
            (args.limit if args.limit != 50 else 500,),
        ).fetchall()
        print(json.dumps([dict(r) for r in rows], indent=2))
        return

    if args.cmd == "find":
        if not args.q:
            raise SystemExit("find requires --q")
        rows = find_items(con, args.q, args.limit, current=(not args.all))
        print(json.dumps(rows, indent=2))
        return

    if args.cmd == "update":
        if not args.id or not args.set:
            raise SystemExit("update requires --id and --set '{...}'")
        patch = json.loads(args.set)
        update_item(con, args.id, patch)
        _after_write(con)
        print("OK")
        return

    if args.cmd == "delete":
        if not args.id:
            raise SystemExit("delete requires --id")
        delete_item(con, args.id, note=args.notes)
        _after_write(con)
        print("OK")
        return

    if args.cmd in LEDGER_COMMANDS:
        core = _core()
        if not core:
            raise SystemExit("foodcore could not be loaded; receipt/price commands are unavailable")
        print(core.ledger.dumps(_ledger_cmd(core, con, args)))
        return

    if args.cmd == "shop":
        print(json.dumps(shop_rows(con, include_done=bool(args.all),
                                   limit=args.limit if args.limit != 50 else 500),
                         indent=2))
        return

    if args.cmd == "shop-add":
        res = shop_add(con, args.name, quantity=args.qty, unit=args.unit,
                       notes=args.notes, by=args.by, item_id=args.id)
        print(json.dumps(res, indent=2))
        return

    if args.cmd in ("shop-done", "shop-undo"):
        sid = args.id
        if not sid:
            if not args.name:
                raise SystemExit(f"{args.cmd} requires --id or --name")
            row, candidates = shop_resolve(con, args.name)
            if row is None:
                if candidates:
                    raise SystemExit("ambiguous: " + ", ".join(candidates))
                raise SystemExit(f"nothing like {args.name!r} on the list")
            sid = row["id"]
        n = shop_set_done(con, sid, done=(args.cmd == "shop-done"))
        if not n:
            raise SystemExit(f"no list item with id {sid}")
        print(json.dumps({"id": sid, "done": args.cmd == "shop-done"}, indent=2))
        return

    if args.cmd == "shop-clear":
        cur = con.execute("DELETE FROM shopping WHERE doneAt IS NOT NULL")
        con.commit()
        print(json.dumps({"removed": cur.rowcount}, indent=2))
        return

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()

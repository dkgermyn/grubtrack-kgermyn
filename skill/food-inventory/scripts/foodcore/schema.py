"""Schema for price intelligence, layered onto food.db without touching what exists.

Additive only. `items`, `shopping`, `receipts` keep every column they had: kiosks, digests
and reports may read them directly. New tables:

    stores           one row per physical store (chain + address); store_aliases maps every
                     spelling the agent has used ("Albertsons (Oak & Elm)") onto it
    products         what gets bought, independent of any one inventory row; carries the
                     taxonomy (dept, cat, generic) and the package size
    product_aliases  name keys merged into a product (a person said "same thing")
    purchases        THE LEDGER: one row per thing paid for. Append-only in spirit: a restock
                     never overwrites an earlier price, which is exactly what items.price did
    item_price_audit every correction made to items.price, with the old value

Two triggers keep the ledger honest no matter who writes: any INSERT/UPDATE that gives an
items row a price records it in `purchases` (source='item'), unless a receipt line already
covers that item on that receipt (receipt lines are the authority). A correction on the same
receipt or day updates that observation instead of adding a second one. An observation a
receipt line later replaces is marked `supersededBy` (kept, so unlinking can bring it back).

Version lives in PRAGMA user_version (food.db was 0 before this). Version 3 adds
the expiration-rule catalog and estimate provenance columns; version 4 refreshes
existing estimates after adding the storage-independent banana rule.
"""

from __future__ import annotations

import sqlite3

from . import expiration

VERSION = 4

# milliseconds: whether a logged price came before or after a receipt was recorded decides
# whether it was a guess at that receipt (ledger._GUESS); seconds tie too easily
_NOW = "strftime('%Y-%m-%dT%H:%M:%f','now','localtime')"
# date an item-sourced price belongs to: the receipt's date, else the purchase date (a priced
# restock through the CLI sets it), else the day the row was created. Never updatedAt: a price
# corrected the next day is the same purchase. date() drops anything that isn't a real date
# ("Oct 20", "yesterday"), so a stray value can't become a key or break the analytics.
_DAY = ("COALESCE(date((SELECT date FROM receipts WHERE id = NEW.receiptId)), date(NEW.purchaseDate), "
        "date(substr(NEW.createdAt, 1, 10)), date('now', 'localtime'))")
# only a real positive number is a price (a text "$13.49" written by raw SQL is not)
_PRICED = "NEW.price IS NOT NULL AND typeof(NEW.price) IN ('integer', 'real') AND NEW.price > 0"
_KEY = "'item|' || NEW.id || '|' || COALESCE(NEW.receiptId, " + _DAY + ")"
# a receipt line already prices this row on this receipt, or the receipt is fully itemized and
# reconciled (then its lines are the whole truth and an item-level price would double count)
_COVERED = ("(EXISTS (SELECT 1 FROM purchases p WHERE p.itemId = NEW.id AND p.source != 'item' "
            "AND COALESCE(p.receiptId, '') = COALESCE(NEW.receiptId, '')) "
            "OR EXISTS (SELECT 1 FROM receipts r WHERE r.id = NEW.receiptId AND r.reconciled = 1))")

_CAPTURE = f"""
  UPDATE purchases SET price = NEW.price, name = NEW.name, brand = NEW.brand, sizeLabel = NEW.size,
         storeId = COALESCE((SELECT storeId FROM receipts WHERE id = NEW.receiptId), storeId),
         productId = NULL, unitPrice = NULL, updatedAt = {_NOW}
   WHERE captureKey = {_KEY} AND NOT {_COVERED};
  INSERT OR IGNORE INTO purchases (id, source, receiptId, storeId, date, itemId, name, brand, qty,
         sizeLabel, price, captureKey, createdAt, updatedAt)
  SELECT 'pu_' || lower(hex(randomblob(6))), 'item', NEW.receiptId,
         (SELECT storeId FROM receipts WHERE id = NEW.receiptId), {_DAY}, NEW.id, NEW.name, NEW.brand,
         1, NEW.size, NEW.price, {_KEY}, {_NOW}, {_NOW}
   WHERE NOT {_COVERED};
"""

DDL = f"""
CREATE TABLE IF NOT EXISTS stores (
  id TEXT PRIMARY KEY,
  chain TEXT NOT NULL,
  name TEXT NOT NULL,
  branch TEXT,
  address TEXT, city TEXT, region TEXT, postal TEXT, phone TEXT,
  storeNumber TEXT,
  notes TEXT,
  createdAt TEXT NOT NULL,
  updatedAt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS store_aliases (
  alias TEXT PRIMARY KEY,
  storeId TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  brand TEXT,
  generic TEXT,
  dept TEXT,
  cat TEXT,
  catSource TEXT NOT NULL DEFAULT 'auto',
  confidence TEXT,
  sizeAmount REAL,
  sizeDim TEXT,
  sizeLabel TEXT,
  notes TEXT,
  createdAt TEXT NOT NULL,
  updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_cat ON products(cat);
CREATE INDEX IF NOT EXISTS idx_products_generic ON products(generic);
CREATE TABLE IF NOT EXISTS product_aliases (
  key TEXT PRIMARY KEY,
  productId TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expiration_rules (
  id TEXT PRIMARY KEY,
  generic TEXT,
  category TEXT,
  storage TEXT NOT NULL DEFAULT '*',
  days INTEGER NOT NULL CHECK(days >= 0 AND days <= 3650),
  priority INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
  source TEXT NOT NULL DEFAULT 'custom'
);
CREATE INDEX IF NOT EXISTS idx_expiration_rules_match
  ON expiration_rules(enabled, generic, category, storage, priority);
CREATE TABLE IF NOT EXISTS purchases (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  receiptId TEXT,
  line INTEGER,
  storeId TEXT,
  date TEXT NOT NULL,
  itemId TEXT,
  productId TEXT,
  raw TEXT,
  name TEXT,
  brand TEXT,
  code TEXT,
  section TEXT,
  qty REAL NOT NULL DEFAULT 1,
  sizeLabel TEXT,
  weightLb REAL,
  perLb REAL,
  price REAL NOT NULL,
  regular REAL,
  taxed INTEGER NOT NULL DEFAULT 0,
  amount REAL,
  dim TEXT,
  unitPrice REAL,
  captureKey TEXT UNIQUE,
  supersededBy TEXT,
  notes TEXT,
  createdAt TEXT NOT NULL,
  updatedAt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_purchases_product ON purchases(productId);
CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(date);
CREATE INDEX IF NOT EXISTS idx_purchases_receipt ON purchases(receiptId);
CREATE INDEX IF NOT EXISTS idx_purchases_item ON purchases(itemId);
CREATE INDEX IF NOT EXISTS idx_purchases_store ON purchases(storeId);
CREATE TABLE IF NOT EXISTS item_price_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  itemId TEXT NOT NULL,
  oldPrice REAL,
  newPrice REAL,
  oldReceiptId TEXT,
  newReceiptId TEXT,
  reason TEXT,
  at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS gt_items_price_ins AFTER INSERT ON items
WHEN {_PRICED}
BEGIN{_CAPTURE}END;

CREATE TRIGGER IF NOT EXISTS gt_items_price_upd AFTER UPDATE OF price, receiptId ON items
WHEN {_PRICED}
 AND (OLD.price IS NULL OR OLD.price != NEW.price OR COALESCE(OLD.receiptId, '') != COALESCE(NEW.receiptId, ''))
BEGIN{_CAPTURE}END;
"""

# columns added to existing tables: (table, column, type)
COLUMNS = [
    ("items", "price", "REAL"),
    ("items", "receiptId", "TEXT"),
    ("items", "productId", "TEXT"),
    ("items", "dept", "TEXT"),
    ("items", "cat", "TEXT"),
    ("items", "expirationSource", "TEXT"),
    ("items", "expirationRuleId", "TEXT"),
    ("receipts", "storeId", "TEXT"),
    ("receipts", "subtotal", "REAL"),
    ("receipts", "tax", "REAL"),
    ("receipts", "lineCount", "INTEGER"),
    ("receipts", "reconciled", "INTEGER"),
    ("receipts", "diff", "REAL"),
    ("receipts", "updatedAt", "TEXT"),
]

RECEIPTS = """
CREATE TABLE IF NOT EXISTS receipts (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  store TEXT,
  total REAL,
  savings REAL,
  currency TEXT DEFAULT 'USD',
  paymentNote TEXT,
  imagePath TEXT,
  notes TEXT,
  createdAt TEXT
)
"""


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(con: sqlite3.Connection) -> int:
    """Bring food.db up to VERSION. Cheap when already there (one PRAGMA read)."""
    have = con.execute("PRAGMA user_version").fetchone()[0]
    if have >= VERSION:
        return have
    if have >= 1:
        # trigger bodies changed: drop them so the DDL below recreates them
        con.execute("DROP TRIGGER IF EXISTS gt_items_price_ins")
        con.execute("DROP TRIGGER IF EXISTS gt_items_price_upd")
    con.execute(RECEIPTS)
    for table, col, typ in COLUMNS:
        if col not in _cols(con, table):
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e):  # another process got there first: fine
                    raise
    con.executescript(DDL)
    expiration.seed(con)
    expiration.backfill_missing(con)
    expiration.refresh_estimates(con)
    con.execute("CREATE INDEX IF NOT EXISTS idx_items_product ON items(productId)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_items_cat ON items(cat)")
    con.execute(f"PRAGMA user_version = {VERSION}")
    con.commit()
    return VERSION

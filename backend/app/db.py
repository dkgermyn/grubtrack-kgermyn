"""One connection per request, through the same module the agent uses (fooddb_sqlite), so
both writers share one set of rules."""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Iterator

from . import config  # noqa: F401  (sets FOODDB_PATH + sys.path before the imports below)

import fooddb_sqlite as fdb  # noqa: E402
from foodcore import cat_label  # noqa: E402
from foodcore import intel, ledger, recipes  # noqa: E402,F401


def connect() -> sqlite3.Connection:
    """Same settings as fdb.connect(), but usable across threads: FastAPI resolves sync
    dependencies in a worker thread and async endpoints run on the event loop."""
    con = sqlite3.connect(fdb.DB_PATH, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout = 15000")
    return con


def get_con() -> Iterator[sqlite3.Connection]:
    con = connect()
    try:
        yield con
    finally:
        con.close()


def today() -> dt.date:
    return dt.date.today()


def freshness(exp: str | None, now: dt.date | None = None) -> tuple[int | None, str]:
    """Days left and a state the UI can colour: expired / today / soon (3d) / week / ok / none."""
    if not exp:
        return None, "none"
    try:
        d = dt.date.fromisoformat(exp[:10])
    except ValueError:
        return None, "none"
    left = (d - (now or today())).days
    if left < 0:
        return left, "expired"
    if left == 0:
        return left, "today"
    if left <= 3:
        return left, "soon"
    if left <= 7:
        return left, "week"
    return left, "ok"


ITEM_FIELDS = ("id", "name", "brand", "storage", "location", "dept", "cat", "category", "subCategory", "spiritType",
               "quantity", "unit", "size", "expirationDate", "expirationSource", "expirationRuleId",
               "purchaseDate", "openedAt", "bottleState", "abv",
               "volumeMl", "price", "receiptId", "productId", "notes", "createdAt", "updatedAt", "deletedAt",
               "createdByName")


def item_out(r: sqlite3.Row | dict, image: str | None = None, now: dt.date | None = None) -> dict:
    d = dict(r)
    out = {k: d.get(k) for k in ITEM_FIELDS}
    out["catLabel"] = cat_label(d.get("cat"))
    out["daysLeft"], out["state"] = freshness(d.get("expirationDate"), now)
    out["image"] = image
    return out


def images_for(con: sqlite3.Connection, ids: list[str] | None = None) -> dict[str, str]:
    rows = con.execute("SELECT itemId, path FROM images ORDER BY createdAt").fetchall()
    out = {}
    for r in rows:
        if ids is None or r["itemId"] in ids:
            out.setdefault(r["itemId"], r["path"])
    return out

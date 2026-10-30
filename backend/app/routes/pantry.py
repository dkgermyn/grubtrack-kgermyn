"""The pantry: what's in the house, what to use first, and clearing out what's gone."""

from __future__ import annotations

import re
from collections import Counter

from fastapi import APIRouter, Body, Depends, HTTPException

from ..db import fdb, get_con, images_for, intel, item_out, ledger, today

router = APIRouter(prefix="/api")

FATES = {"eaten", "tossed"}


def _sweep(con):
    """After a write that has committed: resolve what can be, never fail the request over it."""
    try:
        ledger.sweep(con)
    except Exception:
        pass


def _live(con):
    rows = con.execute("SELECT * FROM items WHERE deletedAt IS NULL").fetchall()
    imgs = images_for(con)
    now = today()
    return [item_out(r, imgs.get(r["id"]), now) for r in rows]


@router.get("/pantry")
def pantry(con=Depends(get_con)):
    """Everything in stock in one payload (a few hundred rows): the page filters locally, so
    switching storage, department or search never waits on the network."""
    items = _live(con)
    depts = Counter(i["dept"] or "other" for i in items)
    cats = Counter(i["cat"] or "other.other" for i in items)
    storage = Counter((i["storage"] or "other") for i in items)
    states = Counter(i["state"] for i in items)
    # last price paid for each product that's in stock, for the shelf tag on its card
    last = {}
    for r in con.execute("SELECT p.productId, p.price, p.date, s.name AS store FROM purchases p"
                         " LEFT JOIN stores s ON s.id = p.storeId WHERE p.productId IS NOT NULL"
                         " ORDER BY p.date, p.line").fetchall():
        last[r["productId"]] = dict(r)
    for i in items:
        lp = last.get(i["productId"])
        i["lastPaid"] = {"price": lp["price"], "date": lp["date"], "store": lp["store"]} if lp else None
    return {
        "items": items,
        "facets": {"depts": dict(depts), "cats": dict(cats), "storage": dict(storage), "states": dict(states)},
        "overview": intel.overview(con),
        "taxonomy": intel.taxonomy(),
    }


@router.get("/items/{item_id}")
def item_detail(item_id: str, con=Depends(get_con)):
    r = con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Item not found")
    imgs = [dict(x) for x in con.execute("SELECT path, sha256, createdAt FROM images WHERE itemId = ?", (item_id,))]
    out = item_out(r, imgs[0]["path"] if imgs else None)
    out["images"] = imgs
    out["rawUserText"] = r["rawUserText"]
    out["product"] = intel.product_detail(con, r["productId"]) if r["productId"] else None
    out["purchases"] = [dict(p) for p in con.execute(
        "SELECT p.id, p.date, p.price, p.regular, p.qty, p.raw, p.source, p.receiptId, p.storeId, s.name AS store"
        " FROM purchases p LEFT JOIN stores s ON s.id = p.storeId WHERE p.itemId = ? ORDER BY p.date DESC",
        (item_id,)).fetchall()]
    out["audit"] = [dict(a) for a in con.execute(
        "SELECT oldPrice, newPrice, reason, at FROM item_price_audit WHERE itemId = ? ORDER BY at DESC",
        (item_id,)).fetchall()]
    return out


_EDITABLE = {"name", "brand", "storage", "location", "category", "subCategory", "spiritType", "quantity", "unit",
             "size", "expirationDate", "purchaseDate", "openedAt", "bottleState", "abv", "volumeMl", "notes", "price"}
_EXPIRATION_SOURCES = {"explicit", "estimated", "adjusted", "not_applicable", None}


@router.post("/items", status_code=201)
def add_item(data: dict = Body(...), con=Depends(get_con)):
    if not (data.get("name") or "").strip():
        raise HTTPException(400, "A name is required")
    obj = {k: v for k, v in data.items() if k in _EDITABLE and v not in ("", None)}
    obj["createdBy"] = {"channel": "grubtrack", "name": data.get("by") or "GrubTrack"}
    try:
        item_id = fdb.add_item(con, obj)
    except SystemExit as e:
        raise HTTPException(400, str(e))
    _sweep(con)
    return item_out(con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


@router.patch("/items/{item_id}")
def update_item(item_id: str, data: dict = Body(...), con=Depends(get_con)):
    if not con.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
        raise HTTPException(404, "Item not found")
    patch = {k: (None if v == "" else v) for k, v in data.items() if k in _EDITABLE}
    if not patch:
        raise HTTPException(400, "Nothing to change")
    if "price" in patch:
        try:
            patch["price"] = fdb.parse_price(patch["price"], strict=True)
        except SystemExit as e:  # the CLI's way of refusing; here it's a 400
            raise HTTPException(400, str(e))
    mode = data.get("expirationMode")
    if "expirationDate" in patch and mode == "adjusted":
        patch["_expirationSource"] = "adjusted"
        patch["_expirationRuleId"] = None
    elif "expirationDate" in patch and mode == "restore":
        source = data.get("expirationSource")
        if source not in _EXPIRATION_SOURCES:
            raise HTTPException(400, "Invalid expiration source")
        patch["_expirationSource"] = source
        patch["_expirationRuleId"] = data.get("expirationRuleId")
    fdb.update_item(con, item_id, patch)
    _sweep(con)
    return item_out(con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


def _consume(con, item_id: str, fate: str | None):
    if fate is not None and fate not in FATES:
        raise HTTPException(400, f"fate must be one of {sorted(FATES)}")
    if not con.execute("SELECT 1 FROM items WHERE id = ? AND deletedAt IS NULL", (item_id,)).fetchone():
        return False
    fdb.delete_item(con, item_id, note=fate)
    return True


@router.post("/items/{item_id}/consume")
def consume(item_id: str, data: dict = Body(default={}), con=Depends(get_con)):
    """Gone: eaten or tossed. The same soft delete (and the same words in notes) as the CLI's
    `delete --notes eaten|tossed`, so waste numbers agree everywhere."""
    if not _consume(con, item_id, data.get("fate")):
        raise HTTPException(404, "Item not found or already gone")
    _sweep(con)
    return {"ok": True}


@router.post("/items/batch")
def batch(data: dict = Body(...), con=Depends(get_con)):
    ids = [str(i) for i in (data.get("ids") or [])][:200]
    fate = data.get("fate")
    done = sum(1 for i in ids if _consume(con, i, fate))
    _sweep(con)
    return {"ok": True, "done": done}


@router.post("/items/{item_id}/restore")
def restore(item_id: str, con=Depends(get_con)):
    """Undo a consume: bring the row back and take off the fate word it was given."""
    r = con.execute("SELECT notes FROM items WHERE id = ? AND deletedAt IS NOT NULL", (item_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Nothing to restore")
    notes = re.sub(r"(?:\s·\s|^)(eaten|tossed)$", "", r["notes"] or "").strip() or None
    with con:
        con.execute("UPDATE items SET deletedAt = NULL, notes = ?, updatedAt = ? WHERE id = ?",
                    (notes, fdb.now_iso_local(), item_id))
    return {"ok": True}


@router.get("/history")
def history(limit: int = 120, con=Depends(get_con)):
    """Recently gone, newest first: what was eaten, what was tossed, what was a typo fixed."""
    rows = con.execute("SELECT * FROM items WHERE deletedAt IS NOT NULL ORDER BY deletedAt DESC LIMIT ?",
                       (min(limit, 500),)).fetchall()
    out = []
    for r in rows:
        o = item_out(r)
        o["fate"] = intel._fate(r["notes"])
        o["correction"] = intel._is_correction(r["createdAt"], r["deletedAt"])
        out.append(o)
    return {"items": out, "waste": intel.waste(con, 90)}

"""The HTTP API end to end, on a throwaway database with no AI set up and recipe saving switched off."""

import importlib
import json
import os
import sys

import pytest

from conftest import SCRIPTS


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gt")
    recipes = tmp / "recipes" / "Dinner"
    recipes.mkdir(parents=True)
    (recipes / "Egg Fried Rice.md").write_text("---\ncuisine: Chinese\n---\n# Egg Fried Rice\n\n## Ingredients\n\n"
                                             "- 2 cups jasmine rice\n- 3 eggs\n- 2 green onions, sliced\n- 1 tbsp soy sauce\n")
    static = tmp / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>GrubTrack</title>")
    os.environ.update({"FOODDB_PATH": str(tmp / "food.db"), "GT_SKILL_SCRIPTS": str(SCRIPTS), "GT_RECIPES_DIR": str(tmp / "recipes"),
                       "GT_RECIPES_WRITE": "0", "GT_AGENT": "", "GT_MODEL_PROVIDER": "", "GT_STATIC": str(static),
                       "GT_SWEEP_SECONDS": "3600"})
    for m in [m for m in sys.modules if m.startswith("app") or m == "fooddb_sqlite"]:
        del sys.modules[m]
    from fastapi.testclient import TestClient
    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        yield c


def test_shell_and_unknown_api(client):
    assert client.get("/").status_code == 200
    assert "GrubTrack" in client.get("/prices/anything").text  # SPA fallback
    r = client.get("/api/nope")
    assert r.status_code == 404 and "No such endpoint" in r.text
    assert client.get("/api/build").headers.get("X-GT-Build")


def test_pantry_add_consume_restore(client):
    r = client.post("/api/items", json={"name": "Raspberry kefir", "storage": "fridge", "category": "dairy",
                                        "expirationDate": "2099-01-01", "price": 4.59})
    assert r.status_code == 201
    item = r.json()
    assert item["cat"] == "dairy.yogurt" and item["catLabel"] == "Yogurt & Kefir" and item["state"] == "ok"
    p = client.get("/api/pantry").json()
    assert [i["id"] for i in p["items"]] == [item["id"]]
    assert p["facets"]["depts"] == {"dairy": 1} and p["items"][0]["lastPaid"]["price"] == 4.59
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["product"]["generic"] == "kefir" and detail["purchases"][0]["price"] == 4.59
    assert client.post(f"/api/items/{item['id']}/consume", json={"fate": "tossed"}).json()["ok"]
    assert client.get("/api/pantry").json()["items"] == []
    assert client.post(f"/api/items/{item['id']}/consume", json={"fate": "eaten"}).status_code == 404
    assert client.post(f"/api/items/{item['id']}/consume", json={"fate": "lost"}).status_code in (400, 404)
    assert client.post(f"/api/items/{item['id']}/restore").json()["ok"]
    back = client.get(f"/api/items/{item['id']}").json()
    assert back["deletedAt"] is None and (back["notes"] or "") == ""


def test_patch_item_extends_date(client):
    item = client.post("/api/items", json={"name": "Hummus", "storage": "fridge", "expirationDate": "2000-01-01"}).json()
    assert item["state"] == "expired"
    r = client.patch(f"/api/items/{item['id']}", json={"expirationDate": "2099-02-02"})
    assert r.json()["state"] == "ok"
    assert client.patch(f"/api/items/{item['id']}", json={"id": "x"}).status_code == 400


def test_still_good_marks_date_adjusted_and_restore_keeps_provenance(client):
    item = client.post("/api/items", json={"name": "Spinach", "storage": "fridge"}).json()
    original = (item["expirationDate"], item["expirationSource"], item["expirationRuleId"])
    adjusted = client.patch(
        f"/api/items/{item['id']}",
        json={"expirationDate": "2099-02-02", "expirationMode": "adjusted"},
    ).json()
    assert adjusted["expirationSource"] == "adjusted"
    assert adjusted["expirationRuleId"] is None

    restored = client.patch(
        f"/api/items/{item['id']}",
        json={
            "expirationDate": original[0], "expirationMode": "restore",
            "expirationSource": original[1], "expirationRuleId": original[2],
        },
    ).json()
    assert (restored["expirationDate"], restored["expirationSource"], restored["expirationRuleId"]) == original


def test_api_add_without_date_returns_visible_estimate(client):
    item = client.post("/api/items", json={"name": "Bananas", "storage": "counter"}).json()
    assert item["expirationDate"]
    assert item["expirationSource"] == "estimated"
    assert item["expirationRuleId"] == "banana-counter"


def test_receipt_flow_and_prices(client):
    from app.db import connect, ledger
    con = connect()
    eggs = client.post("/api/items", json={"name": "Eggs (dozen)", "storage": "fridge", "category": "dairy"}).json()
    rep = ledger.import_receipt(con, {
        "store": "Albertsons Store #12, 2200 W Oak Ave, Springfield, IL 62704", "date": __import__("datetime").date.today().isoformat(), "total": 13.48,
        "tax": 0, "lines": [{"raw": "PETE & GERRY EGGS", "name": "Pete & Gerry's eggs", "brand": "Pete & Gerry's",
                             "size": "dozen", "price": 6.99, "regular": 7.99},
                            {"raw": "ORIGIN X", "name": "Origin X", "section": "GROCERY", "price": 6.49}]},
        autolink=False)
    con.close()
    rid = rep["receiptId"]
    r = client.get(f"/api/receipts/{rid}").json()
    assert r["reconciled"] == 1 and r["unitemized"] == 0 and len(r["lines"]) == 2
    line = next(l for l in r["lines"] if l["raw"].startswith("PETE"))
    assert line["product"]["catLabel"] == "Eggs" and line["item"] is None
    cands = client.get(f"/api/receipts/{rid}/candidates").json()
    assert eggs["id"] in [c["id"] for c in cands]
    assert client.post(f"/api/receipts/{rid}/lines/{line['id']}/link", json={"itemId": eggs["id"]}).json()["ok"]
    assert client.get(f"/api/items/{eggs['id']}").json()["price"] == 6.99

    pr = client.get("/api/prices").json()
    names = {p["name"]: p for p in pr["book"]}
    assert names["Pete & Gerry's eggs"]["last"]["unitLabel"] == "egg"
    assert names["Pete & Gerry's eggs"]["deal"] == 13
    review = client.get("/api/products/review").json()["products"]
    origin = next(p for p in review if p["name"] == "Origin X")
    assert origin["section"] == "GROCERY"
    fixed = client.patch(f"/api/products/{origin['id']}", json={"cat": "drinks.coffee"}).json()
    assert fixed["cat"] == "drinks.coffee" and fixed["catSource"] == "user"
    assert all(p["name"] != "Origin X" for p in client.get("/api/products/review").json()["products"])
    assert client.patch(f"/api/products/{origin['id']}", json={"cat": "nope.nope"}).status_code == 400
    sized = client.patch(f"/api/products/{origin['id']}", json={"size": "12 oz"}).json()
    assert sized["size"] == "12 oz" and sized["last"]["unitLabel"] == "oz"
    assert client.patch(f"/api/products/{origin['id']}", json={"size": "a bag"}).status_code == 400

    sp = client.get("/api/spend").json()
    assert sp["spend"]["trips"][0]["total"] == 13.48
    listed = sp["stores"][0]
    store = client.get(f"/api/stores/{listed['id']}").json()
    # the store list counts trips; one store's page lists them (`trips`) and carries the count as `tripCount`,
    # which the store sheet shows (it used to render the list itself and crash)
    assert isinstance(listed["trips"], int) and isinstance(store["tripCount"], int)
    assert store["tripCount"] == listed["trips"] == len(store["trips"]) == 1
    assert store["trips"][0]["id"] == rid and store["trips"][0]["total"] == 13.48 and store["products"]


def test_shopping_uses_the_shared_table(client):
    r = client.post("/api/shopping", json={"name": "Pete & Gerry's eggs"})
    assert r.status_code == 201 and r.json()["added"]
    assert client.post("/api/shopping", json={"name": "pete & gerry's eggs"}).json()["added"] is False
    s = client.get("/api/shopping").json()
    row = s["open"][0]
    assert row["estimate"]["estimate"] == 6.99 and row["estimate"]["match"] == "exact"
    assert client.get("/api/shopping-list").json()["items"][0]["text"] == "Pete & Gerry's eggs"
    assert client.put("/api/shopping-list", json={"items": []}).status_code == 410
    assert client.post(f"/api/shopping/{row['id']}/done").json()["ok"]
    s = client.get("/api/shopping").json()
    assert s["open"] == [] and s["done"][0]["id"] == row["id"]
    assert client.post("/api/shopping/clear").json()["removed"] == 1


def test_recipes_know_whats_in_the_house(client):
    client.post("/api/items", json={"name": "Jasmine rice", "storage": "pantry"})
    client.post("/api/items", json={"name": "Green onions", "storage": "fridge"})
    r = client.get("/api/recipes").json()
    rice = r["personal"][0]
    assert rice["title"] == "Egg Fried Rice"
    assert rice["make"]["have"] >= 2 and "soy sauce" in rice["make"]["need"]
    assert client.post("/api/recipes", json={"title": "X"}).status_code == 403  # saving is off here
    assert client.put("/api/recipes/egg-fried-rice/journal", json={"score": 9, "tags": ["weeknight"]}).json()["ok"]
    assert client.get("/api/recipes/egg-fried-rice/journal").json()["entry"]["score"] == 9


def test_past_date_food_is_not_on_hand_for_cooking(client):
    """Recipe ranking and the meal-ideas prompt agree: food past its date counts for neither, food dated
    today counts for both."""
    import datetime as dt
    from app.db import connect
    from app.routes import cook

    def prompt():
        con = connect()
        try:
            return cook._meal_prompt(con, None, "")
        finally:
            con.close()

    def soy_line():
        rice = client.get("/api/recipes/egg-fried-rice").json()
        return next(l for l in rice["lines"] if "soy sauce" in l["text"]), rice["make"]

    soy = client.post("/api/items", json={"name": "Soy sauce", "storage": "pantry", "expirationDate": "2000-01-01"}).json()
    line, make = soy_line()
    assert line["have"] is False and "soy sauce" in make["need"]
    assert "Soy sauce" not in prompt()
    mine = next(r for r in client.get("/api/recipes").json()["personal"] if r["slug"] == "egg-fried-rice")
    assert "soy sauce" in mine["make"]["need"]

    client.patch(f"/api/items/{soy['id']}", json={"expirationDate": dt.date.today().isoformat()})
    line, make = soy_line()
    assert line["have"] is True and "soy sauce" not in make["need"]
    assert "Soy sauce" in prompt()


def test_overview_counts_whats_in_the_house(client):
    """overview.stock is real numbers on every page that sends it (the Pantry page's "come to $X" line)."""
    client.post("/api/items", json={"name": "Oat milk", "storage": "fridge", "price": 4.29, "expirationDate": "2099-01-01"})
    items = client.get("/api/pantry").json()["items"]
    priced = [i["price"] for i in items if isinstance(i["price"], (int, float))]
    assert priced and len(priced) < len(items)   # some rows have no price, and they must not count
    for page in ("pantry", "prices", "spend"):
        stock = client.get(f"/api/{page}").json()["overview"]["stock"]
        assert stock["items"] == len(items) and stock["priced"] == len(priced), page
        assert stock["value"] == pytest.approx(sum(priced), abs=0.01), page


def test_ai_jobs_without_any_ai(client):
    cfg = client.get("/api/config").json()["ai"]
    assert cfg == {"model": None, "agent": None, "chat": None, "extract": None, "vision": False, "send": None}
    assert client.post("/api/meals/suggest", json={}).status_code == 503
    assert client.post("/api/meals/suggest", json={"storage": "garage"}).status_code == 400
    assert client.post("/api/shopping/send").status_code == 503
    assert client.post("/api/recipes/parse", json={"text": "toast: bread, toaster"}).status_code == 503
    r = client.post("/api/receipts/read", files={"photo": ("r.jpg", bytes([0xFF, 0xD8, 0xFF]), "image/jpeg")})
    assert r.status_code == 503


def test_receipt_photo_to_saved_trip(client, monkeypatch):
    import httpx
    from app import config
    from app.ai import openai_compat
    answer = {"store": "Corner Grocer, 12 Elm St", "date": "2026-10-22", "tax": 0.31, "total": 9.29,
              "lines": [{"raw": "BANANAS", "name": "Bananas", "price": 1.32, "weightLb": 2.2, "perLb": 0.6},
                        {"raw": "SOURDOUGH LOAF", "name": "Sourdough loaf", "price": 7.66, "regular": 8.49}]}
    monkeypatch.setattr(config, "MODEL_PROVIDER", "openai")
    monkeypatch.setattr(config, "MODEL", "vision-test")
    monkeypatch.setattr(openai_compat, "transport", httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})))
    assert client.get("/api/config").json()["ai"]["vision"] is True
    r = client.post("/api/receipts/read", files={"photo": ("r.jpg", bytes([0xFF, 0xD8, 0xFF, 0xE0]), "image/jpeg")})
    assert r.status_code == 200, r.text
    out = r.json()
    draft = out["draft"]
    assert out["reconciliation"]["ok"] and draft["image"].startswith("images/receipts/") and len(draft["lines"]) == 2
    assert client.get(f"/api/images/{draft['image']}").content == bytes([0xFF, 0xD8, 0xFF, 0xE0])
    for sneaky in ("/api/images/..%2F..%2F..%2F..%2Fetc%2Fpasswd", "/api/images/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
                   "/api/images/%2Fetc%2Fpasswd"):
        r = client.get(sneaky)
        assert r.status_code == 404 and b"root:" not in r.content, sneaky
    assert client.post("/api/receipts/read", files={"photo": ("r.txt", b"hi", "text/plain")}).status_code == 400

    saved = client.post("/api/receipts", json=draft)
    assert saved.status_code == 201 and saved.json()["reconciliation"]["ok"]
    assert client.post("/api/receipts", json=draft).status_code == 400   # same store, date and total
    trip = next(t for t in client.get("/api/spend").json()["spend"]["trips"] if t["id"] == saved.json()["receiptId"])
    assert trip["reconciled"] and trip["total"] == 9.29
    assert client.get(f"/api/receipts/{trip['id']}").json()["imagePath"] == draft["image"]


def test_import_a_recipe_collection(client):
    import gzip
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, ings, cats in (("Lemon Chicken", "2 lb chicken thighs\n2 lemons", ["Dinner"]),
                                 ("Banana Bread", "3 bananas\n2 cups flour", ["Breads"])):
            z.writestr(f"{name}.paprikarecipe", gzip.compress(json.dumps(
                {"name": name, "ingredients": ings, "directions": "Cook it.", "categories": cats}).encode()))
    before = client.get("/api/recipes").json()["libraryTotal"]
    r = client.post("/api/recipes/import", files={"file": ("export.paprikarecipes", buf.getvalue(), "application/zip")})
    assert r.status_code == 200 and r.json()["added"] == 2
    assert client.get("/api/recipes").json()["libraryTotal"] == before + 2
    hits = client.get("/api/recipes/bulk/search", params={"protein": "chicken"}).json()["recipes"]
    assert [h["title"] for h in hits] == ["Lemon Chicken"]
    baked = client.get("/api/recipes/bulk/search", params={"dish": "baked", "q": "banana"}).json()["recipes"]
    assert baked[0]["title"] == "Banana Bread" and baked[0]["make"]["known"] >= 1
    again = client.post("/api/recipes/import", files={"file": ("export.paprikarecipes", buf.getvalue(), "application/zip")})
    assert again.json()["added"] == 0 and again.json()["duplicates"] == 2
    bad = client.post("/api/recipes/import", files={"file": ("notes.txt", b"just some notes", "text/plain")})
    assert bad.status_code == 400 and "Meal-Master" in bad.json()["detail"]

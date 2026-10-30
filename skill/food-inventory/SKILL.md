---
name: food-inventory
description: Log and query the household's food and bar inventory, receipts, prices and grocery spend (GrubTrack's food.db). Use for grocery, pantry, fridge or receipt photos; "what do we have", what's expiring, meal ideas; what X cost, where it's cheaper, whether it went up, and what we spent.
version: 2.1.0
license: MIT
homepage: https://github.com/chungus-actual/grubtrack
metadata:
  openclaw:
    requires:
      bins: [python3]
  hermes:
    tags: [food, groceries, pantry, receipts, prices, budgeting]
    category: household
---

# Food Inventory

Log food into a local SQLite database and answer questions from it: what's in stock, what
expires when, what things cost, where they're cheaper, and where the money went. GrubTrack (the
web app) reads and writes the same database.

**First:** if `{baseDir}/LOCAL.md` exists, read it. It holds this household's own rules (who is
who, where to confirm, house conventions) and wins where it disagrees with this file.

## Where things live

- The CLI: `python3 {baseDir}/scripts/fooddb_sqlite.py`. Always go through it; never open the
  database with your own SQL and never guess flags (`--help` lists them).
- The database: `python3 {baseDir}/scripts/fooddb_sqlite.py where` prints the `food.db` path and the
  `images/` folder beside it, or the GrubTrack server the commands go to. When GrubTrack runs on
  another machine, every command runs there with the same arguments and output, and the files a
  command names (`--file`, a photo's path inside the JSON) are uploaded with it. If it prints
  `Can't reach GrubTrack`, nothing was saved: say so, and don't claim it was logged.
- Schema: `{baseDir}/references/SCHEMA.md`. Session behaviour: `{baseDir}/SESSION_RULES.md`.

## Workflow: when someone sends food photos

### 0) Required fields and acknowledgment

- Required to say **"Logged"**: `storage` + some `name` (or `Unknown item #1/#2`).
- If `expirationDate` is absent, GrubTrack assigns a deterministic shelf-life estimate from its
  `expiration_rules` table. Report it as an **estimated use-by date**, never as a package date.
- Never claim that an estimated date was printed on the product.
- Never present an estimate as a food-safety guarantee. Package instructions, recalls, temperature
  history, and signs of spoilage take precedence.

### 1) Extract what you can

- From the caption or text: storage and quantity hints.
- From the image: name, brand, size and any **EXP / Best By / Use By / Sell By** date.
- `category`: infer it from the product and storage unless the person says otherwise. If unsure, use `other`.
- Bar items: infer `subCategory` and `spiritType` when you can.
  - Spirits: a whiskey => `subCategory=spirit`, `spiritType=whiskey`
  - Liqueurs: Disaronno, Mr Black, Midori => `subCategory=liqueur`, `spiritType=liqueur`
  - Wine: `subCategory=wine`, `spiritType=wine`

Expiration parsing:
- If the stamp is partial (`202_`) or ambiguous, **do not** fill `expirationDate`.
- Put the raw stamp in `notes`; GrubTrack will apply and label its deterministic estimate. Ask the
  person to type the date only when they want the printed date to replace that estimate.

### 2) Pending submissions when something important is missing

Pending state makes follow-ups deterministic. Helper: `node {baseDir}/scripts/pending.js`
(`pending.json` sits beside `food.db`).

If another required key field is missing:
1) Create a pending entry (one per photo) with the extracted items and the missing fields.
2) Ask for the missing info **in the same thread**, in one message with a copy-paste format.

Example follow-up (two items):
- "I logged these as fridge items, but I can't read the exp dates. Reply like: `cottage=2/10 bread=2/18` (or `no date`)."

### 3) Save the records

- One record per distinct product.
- Prefer a labeled deterministic estimate over an invented package date.
- Add `confidence` when a field is inferred.

### 4) Store the image

- Copy the photo into the `images/` folder beside `food.db` and reference it from the record.

## Quick capture: photo + one word

A photo with one word is enough: `fridge` | `freezer` | `cupboard` | `pantry` | `counter` | `bar`.

Bar defaults:
- `location=bar` (alcohol lives at the bar unless stated otherwise)
- `storage` is the temperature class: default `cupboard`, `fridge` when refrigerated
- A dedicated drink fridge: `storage=fridge` + `location=drink fridge`

Several items in one photo can be told apart with `left/right` or `1/2`. If an exp date can't be
read, ask once, immediately.

## Commands

### Set up

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py where   # which food.db, and whether it exists yet
python3 {baseDir}/scripts/fooddb_sqlite.py init    # create it (safe to re-run)
```

### Add an item

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py add \
  --name "Greek yogurt" --brand "Fage" --storage fridge --category dairy \
  --exp 2026-02-10 --qty 1 --unit container --size "5.3 oz" --notes "vanilla"
```

A restock of something already in the house merges into its row. Add `--price 4.99` when a price
is known (see the ledger below).

### What do we have

**"What do we have" / "show my inventory" is `inventory`, never `list`.**

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py inventory          # current stock, latest row per item, limit 500
python3 {baseDir}/scripts/fooddb_sqlite.py find --q yogurt    # search current items by name/brand
python3 {baseDir}/scripts/fooddb_sqlite.py list --limit 50    # RAW rows, newest first: audit/debug only
```

- Output is already JSON. There is **no `--json` output flag**: `--json '{...}'` is an input
  payload for `add`. Read the array directly.
- On a voice surface, never read the whole inventory aloud: summarize (counts by storage plus what
  expires soon).

### Expiration questions: `expiring`, never eyeball a `list`

`list` returns the 50 newest rows, so older items (exactly the ones about to expire) are invisible
and you will wrongly report that nothing is expiring.

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py expiring --on today        # expires ON that day only
python3 {baseDir}/scripts/fooddb_sqlite.py expiring --on tomorrow
python3 {baseDir}/scripts/fooddb_sqlite.py expiring --on 2026-08-20
python3 {baseDir}/scripts/fooddb_sqlite.py expiring --days 3          # RANGE: today through 3 days out
python3 {baseDir}/scripts/fooddb_sqlite.py expired                    # already past date, still on record
```

**A single day is `--on`, never `--days`.** `--days 1` includes today, so it's wrong for "what
expires tomorrow".

- Report **every** row returned: no sampling, no "and a few others".
- If the result is empty, say nothing is expiring **and name the date you checked**.
- Dates are `YYYY-MM-DD` text; `--on` is an exact match.
- For anything else, `list --where "..." --limit 500` works; always pass a high `--limit`.

### Used up or thrown out

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py delete --id <itemId> --notes eaten    # or tossed
```

A delete is soft and keeps the record; `eaten` and `tossed` feed the restock ideas and the waste
numbers. Don't delete past-date items unless someone says they're gone.

### The shopping list

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py shop                         # open list
python3 {baseDir}/scripts/fooddb_sqlite.py shop-add --name "oat milk" [--qty 2] [--by <who>]
python3 {baseDir}/scripts/fooddb_sqlite.py shop-done --name "oat milk"   # cross off
```

GrubTrack's List page is the same list.

## Receipts and prices (the purchase ledger)

Every price lives in the `purchases` ledger, not just on the inventory row. A restock merges into
the old row, but the ledger keeps every price ever paid, so "did eggs go up" and "where is Fairlife
cheaper" have real answers. GrubTrack's Prices and Spend pages show it.

### When a receipt photo arrives

1. **Transcribe every line**, not just the inventory items. For each line:
   - `raw`: the text exactly as printed (`"VITAL FARMS LG EGGS"`)
   - `name`: what it is in plain words (`"Vital Farms large eggs"`), `brand` when you know it
   - `code`: the item number printed at the left, if any (it ties the same product across trips)
   - `section`: the department header it sits under (`"PRODUCE"`, `"DAIRY"`)
   - `price`: the amount actually paid for that line ("You Pay"), after any sale
   - `regular`: the pre-sale price when a "Sale Savings" / "Regular Price" line follows
   - `qty`: for multi-buys (`2@ ...`, `3 @ $2.29 ea`) the count; default 1
   - `weightLb` + `perLb`: for weighed produce (`WT 2.80 lb @ $2.29 /lb`)
   - `taxed`: true when the line carries a tax flag (T)
   - `size`: only when printed or known for sure (`"32 oz"`, `"dozen"`)
   - `itemId`: the inventory row this line stocked, when you know it (`find --q` to look it up)
2. Header: `store` (as printed, with the address if shown), `date`, `tax`, `total`, `savings`,
   `payment`, `image` (where you saved the photo), optional `id`.
3. Write it to a file and import it. Never pass JSON with `$` inside double quotes on the shell
   (the shell eats `$4.99`):
   ```bash
   python3 {baseDir}/scripts/fooddb_sqlite.py receipt-add --file /tmp/receipt-2026-10-21.json
   ```
4. **Read the report before replying.** `reconciliation.ok` means lines + tax equal the printed
   total to the cent. If it prints `WARNING: receipt does not reconcile`, a line is missing or
   misread: look at the photo again, fix the JSON, and re-run with `--replace` (same `id`).
   Never make it add up by inventing or adjusting a line. If part of the receipt is unreadable,
   set `"partial": true` and say so.
5. Links: confident matches to inventory rows logged around that day are made automatically
   (`autoLinked`). For `unlinkedLines` that did stock an inventory item, add `itemId` and re-run
   with `--replace`, or `receipt-link --line <purchaseId> --item <itemId>`. Linked rows take the
   receipt's price (`corrected` lists any price it fixed).
6. Receipt-only extras are **not added to the inventory**. They are recorded as ledger lines,
   which is the point: the spend and price history are real either way.
7. Reply briefly: store, total, line count, whether it adds up, how many linked, any corrected.

Minimal file (two lines, no tax, so the lines alone come to the total):
```json
{"store": "Fieldstone Market #214, 1180 Harbor Rd, Maple Falls, OR 97031", "date": "2026-10-21",
 "tax": 0, "total": 13.40, "savings": 0.50, "payment": "Visa 4242",
 "image": "images/receipt-20261021-fieldstone.jpg",
 "lines": [
  {"raw": "VITAL FARMS LG EGGS", "name": "Vital Farms large eggs", "brand": "Vital Farms", "code": "64420",
   "section": "DAIRY", "price": 6.99, "regular": 7.49, "size": "dozen", "itemId": "fi_20261021_180000_a1b2c3"},
  {"raw": "APPLES HONEYCRISP", "name": "Honeycrisp apples", "section": "PRODUCE", "price": 6.41,
   "weightLb": 2.80, "perLb": 2.29}
 ]}
```

### A price said out loud (no receipt)

`add ... --price 9.99` (and `--receipt <id>` if it belongs to one). It lands in the ledger as a
voice-logged price.

### Questions about money

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py prices --q "fairlife"   # last price, unit price, per-store prices, shelf change, store gap
python3 {baseDir}/scripts/fooddb_sqlite.py spend --days 30         # trips, totals by month / store / department
python3 {baseDir}/scripts/fooddb_sqlite.py stores                  # each store: trips, spend, price level vs the others
python3 {baseDir}/scripts/fooddb_sqlite.py receipts                # recent trips; `receipt --id <id>` shows every line
```

- A price change is the **shelf** price at **one store** between two visits (`change`). A sale is
  not a price change (`deal` = % off that time) and a store difference is not one either
  (`storeGap`). Say which one you mean.
- Say how much evidence there is: "bought 3 times, all off receipts" beats a bare number.
- Unit prices (`last.unit` + `last.unitLabel`) compare sizes and brands: "58¢ an egg vs 22¢".

### A recipe collection

When someone sends a file of recipes (Meal-Master or MasterCook text, a Paprika or Mealie export, recipe
JSON, a saved recipe web page, or a zip of them), save it and import it into the library:

```bash
python3 {baseDir}/scripts/fooddb_sqlite.py recipes-import --file /tmp/recipes.zip --dry-run   # what's in it
python3 {baseDir}/scripts/fooddb_sqlite.py recipes-import --file /tmp/recipes.zip
```

Recipes with the same title and ingredients as one already there are skipped. Reply with how many were
added and how many were already in the library. GrubTrack's Cook page ranks them by what's in the house.

### Categories

Every row gets a department and category automatically (`dept`, `cat`, e.g. `dairy.yogurt`).
`categories` lists the keys. If one is wrong: `set-cat --product <productId> --category dairy.yogurt`
(the productId is in `prices` output). A category set by hand is never changed back.

## Guardrails

- **No hallucinated package dates.** If unreadable, leave the explicit field blank or keep the raw
  text; GrubTrack's rule-generated estimate remains visibly identified as an estimate.
- A receipt photo may show names or card digits; don't echo them back unless asked. Never put full
  card numbers, auth codes or reference numbers in a receipt's `payment`.
- Confirm in the chat the request came from.
- **Persistence before confirmation:** if you say an item was logged, added, updated or removed,
  the database write already happened in the same turn.
- **Don't stall after an explicit logging request:** log now unless critical fields are missing.

## Conventions

- `storage` is a fixed enum: `fridge` | `freezer` | `cupboard` | `pantry` | `counter` | `other`
- Bar inventory adds: `location`, `subCategory`, `spiritType`, `abv`, `volumeMl`, `openedAt`, `bottleState`
- `quantity` is a **count** (optionally with a `unit` like box/bag/can)

# Food Inventory Schema

Storage: SQLite `food.db`. `python3 {baseDir}/scripts/fooddb_sqlite.py where` prints its path.

## Item record

```json
{
  "id": "fi_20260204_173800_p2k3x9",
  "createdAt": "2026-02-04T17:38:00-08:00",
  "createdBy": {
    "channel": "telegram",
    "chatId": "123456789",
    "name": "Alex"
  },
  "name": "Greek yogurt",
  "brand": "Fage",
  "category": "ingredient",
  "storage": "fridge",
  "quantity": 1,
  "unit": "container",
  "size": "5.3 oz",
  "expirationDate": "2026-02-10",
  "expirationSource": "explicit",
  "expirationRuleId": null,
  "purchaseDate": "2026-02-04",
  "notes": "vanilla",
  "confidence": {
    "name": 0.8,
    "expirationDate": 0.4
  },
  "images": [
    {
      "path": "images/fi_20260204_173800_p2k3x9.jpg",
      "sourcePath": "media/inbound/file_...jpg",
      "sha256": "..."
    }
  ],
  "raw": {
    "userText": "fridge exp 2/10",
    "vision": "optional freeform" 
  }
}
```

### Enumerations
- `storage` (fixed enum): `fridge` | `freezer` | `cupboard` | `pantry` | `counter` | `other`
- `category`: `ingredient` | `ready_meal` | `snack` | `treat` | `beverage` | `condiment` | `produce` | `protein` | `dairy` | `bakery` | `other`

### Bar extensions
Use these optional fields for bar inventory:
- `location` (string): where it lives (defaults to `bar` for alcohol unless user says otherwise). Examples: `bar`, `bar cart`, `liquor cabinet`, `drink fridge`, `wine fridge`.
- `subCategory` (string): `spirit` | `wine` | `beer` | `liqueur` | `mixer` | `bitters` | `garnish` | `syrup` | `NA` | `other`
- `spiritType` (string): normalized spirit family when applicable, for queries like "what vodkas do I have?".
  - Recommended values: `vodka` | `gin` | `rum` | `tequila` | `mezcal` | `whiskey` | `bourbon` | `rye` | `scotch` | `irish` | `brandy` | `cognac` | `armagnac` | `vermouth` | `amaro` | `aperitif` | `liqueur` | `bitters` | `wine` | `beer` | `other`
- `abv` (number): alcohol % (e.g. `40`).
- `volumeMl` (number): bottle/carton size in mL.
- `openedAt` (YYYY-MM-DD): optional.
- `bottleState` (string): `sealed` | `open` | `low` | `empty`.

### Quantity convention
- `quantity` is a **count** (integer when possible).
- `unit` is optional (e.g., `box`, `bag`, `can`, `jar`). If unknown, omit it.

All fields are optional except: `id`, `createdAt`, and at least one of `name` or `images`.

## Pending submissions

Pending state file: `pending.json` beside `food.db`.

Used to store an "open" submission while the agent asks for missing required information. A missing
expiration date alone no longer needs pending state: GrubTrack records a labeled rule estimate.
See `scripts/pending.js`.


## Foodcore schema v4

`PRAGMA user_version` = 4 (v3 plus catalog-version estimate refresh). Additive: nothing above changed.
Code: `scripts/foodcore/`. Migration fills active undated legacy items from their purchase date or,
when that is absent, their original `createdAt` date. It also recalculates active rule-generated
dates when a catalog revision adds a more specific match; explicit dates are untouched.
Built-ins are conservative household estimates informed by USDA FoodKeeper and its cold-storage
chart, not package dates or food-safety guarantees.

| Table | One row per | Key columns |
|---|---|---|
| `purchases` | thing paid for (receipt line, or a voice-logged price) | `supersededBy` (a receipt replaced this logged guess), `source` receipt/item, `receiptId`, `line`, `storeId`, `date`, `itemId`, `productId`, `raw`, `name`, `code`, `section`, `qty`, `sizeLabel`, `weightLb`, `perLb`, `price` (paid), `regular` (pre-sale), `taxed`, `amount`+`dim` (g / ml / count / pkg), `unitPrice` (per g/ml/each) |
| `products` | thing bought, across rows and trips | `key` (order-free name tokens), `name`, `brand`, `generic` (kefir, eggs), `dept`, `cat`, `catSource` auto/receipt/user, `sizeAmount`+`sizeDim` |
| `product_aliases` | name merged into a product | `key` → `productId` |
| `stores` | physical store | `chain`, `name`, `branch`, `address`, `city`, `region`, `postal`, `storeNumber` |
| `store_aliases` | spelling of a store | `alias` → `storeId` |
| `item_price_audit` | correction to `items.price` | `oldPrice`, `newPrice`, `reason`, `at` |
| `expiration_rules` | shelf-life rule | optional canonical `generic` or taxonomy `category`, `storage`, `days`, `priority`, `enabled`, `source` |

| Added column | Meaning |
|---|---|
| `items.price`, `items.receiptId` | what this row cost, on which receipt (latest linked receipt wins) |
| `items.productId`, `items.dept`, `items.cat` | resolved product and taxonomy (filled by the sweep) |
| `items.expirationSource`, `items.expirationRuleId` | `explicit` or labeled `estimated` provenance and the matching rule |
| `receipts.storeId`, `subtotal`, `tax`, `lineCount` | resolved store, printed figures |
| `receipts.reconciled`, `receipts.diff` | 1 when lines + tax = total within $0.02; the gap otherwise |

| Rule | Where |
|---|---|
| Any write that gives an `items` row a price also records it in `purchases` | triggers `gt_items_price_ins/upd` |
| A correction on the same receipt (or same day, no receipt) updates that observation | trigger `captureKey` |
| A reconciled receipt's lines outrank item-level prices for that receipt | trigger + `import_receipt` |
| Same item code at the same chain = same product | `ledger.sweep` |
| A category set by a person (`catSource='user'`) is never re-classified | `ledger.sweep` |
| An explicit expiration date wins; otherwise the highest-priority most-specific enabled rule supplies an estimate | `expiration.estimate` |

Taxonomy: 12 departments, `dept.cat` keys (`python3 fooddb_sqlite.py categories`).

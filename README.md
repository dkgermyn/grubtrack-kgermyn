<div align="center">

# GrubTrack

**A self-hosted pantry, price book and grocery budget for one household.**

Log what you buy from a receipt photo, by hand, or by telling your AI agent. GrubTrack keeps every
price ever paid and turns it into answers: what's in the house and when it expires, what eggs cost
at each store, what went up, and where the money went.

![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![React 18](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![SQLite](https://img.shields.io/badge/SQLite-one%20file-003B57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)
![Agent skill](https://img.shields.io/badge/agent%20skill-OpenClaw%20%7C%20Hermes-6E56CF)

<img src="docs/screenshots/product.png" width="820" alt="The price history of a dozen eggs at three stores, with the shelf price before each sale marked" />

<sub>Every screenshot is the made-up household from <code>tools/seed_demo.py</code>: three stores in a
town called Maple Falls and six months of weekly trips.</sub>

</div>

---

## Contents

[Features](#features) · [Screens](#screens) · [How it fits together](#how-it-fits-together) ·
[Run it](#run-it) · [Receipts](#receipts) · [The pantry](#the-pantry) · [Recipes](#recipes) ·
[AI: a model, an agent, or both](#ai-a-model-an-agent-or-both) · [The agent skill](#the-agent-skill) ·
[The CLI](#the-cli) · [Settings](#settings) · [How the data works](#how-the-data-works) ·
[Development](#development) · [Troubleshooting](#troubleshooting) · [License](#license)

## Features

| | |
|---|---|
| **Receipts, read or typed** | A photo goes to your vision model and comes back as a draft beside the photo, every line editable; or type the receipt in. Either way the lines are checked against the printed total as you go |
| **Every price kept** | Each receipt line lands in a purchase ledger, so a restock never overwrites what something cost last time |
| **A pantry with dates** | Everything in the house by storage and department, what to use first, what's past its date. Nothing leaves until you mark it eaten or tossed |
| **A price book** | A history chart per product and store, unit prices (a 32 oz tub against a 5.3 oz cup), where each thing is cheaper, real shelf-price changes, your own inflation rate, buying rhythms |
| **Spend** | Money out by month, department and store; every trip as a receipt you can check line by line; what got thrown away and what it cost |
| **One shopping list** | Priced at what you paid last, the cheaper store per line, restock ideas from your buying rhythm. The web app, the CLI and your agent all write to the same list |
| **Cook from what's here** | Your recipes and an imported library, ranked by how much of each is already in the house; meal ideas that lead with what expires first |
| **Categories on their own** | Every product gets one of 12 departments and 90 categories from its name and the receipt section it sat under. Set one by hand and it sticks |
| **A skill for your agent** | An OpenClaw and Hermes skill that logs groceries and receipts from a chat and answers "where are eggs cheaper" from the same database |
| **Bring any model, or none** | Ollama, LM Studio, vLLM, OpenRouter, OpenAI or Claude read photos and recipes. Everything else works without AI |
| **Phone and desktop** | One responsive app: a tab bar on phones, light and dark themes, a web app manifest for the home screen |
| **Small and yours** | One SQLite file, a copy of it every day, no accounts, no analytics. The only outbound calls are to the model you set and the recipe links you paste |

## Screens

<img src="docs/screenshots/pantry.png" width="100%" alt="The Pantry page: two things to use first, then everything in the house by storage and department, each with its last price and date" />

| | |
|:---:|:---:|
| <img src="docs/screenshots/pantry-past.png" width="100%" alt="The Pantry page showing past-date items with Ate it, Tossed and Still good buttons" /><br><sub>Past their date: nothing leaves until someone says it was eaten or tossed</sub> | <img src="docs/screenshots/prices.png" width="100%" alt="The Prices page: the cheaper store per product and the buying rhythm panel" /><br><sub>Prices: the cheaper store per product, and what's due on its usual rhythm</sub> |
| <img src="docs/screenshots/spend.png" width="100%" alt="The Spend page: spend by month, by department and by store" /><br><sub>Spend: by month, by department, by store</sub> | <img src="docs/screenshots/receipt.png" width="100%" alt="A recorded receipt: each line with its category and the pantry row it stocked" /><br><sub>A recorded trip: every line, its category and the pantry row it stocked</sub> |
| <img src="docs/screenshots/item.png" width="100%" alt="A pantry item: storage, category, its price tag and price history" /><br><sub>A pantry item: what it cost, where, and every purchase of it</sub> | <img src="docs/screenshots/list.png" width="100%" alt="The List page: six things with price estimates, the cheapest store per line, and restock ideas" /><br><sub>The list, priced at what you paid last, with restock ideas below</sub> |
| <img src="docs/screenshots/cook.png" width="100%" alt="The Cook page: meal ideas from the agent and your recipes ranked by how much is in the house" /><br><sub>Cook: recipes ranked by how much of each is in the house</sub> | <img src="docs/screenshots/recipe.png" width="100%" alt="A recipe: each ingredient marked as in the house or missing, with a button to add the missing ones to the list" /><br><sub>A recipe, line by line: what's here, and what's missing a tap from the list</sub> |

| | | |
|:---:|:---:|:---:|
| <img src="docs/screenshots/phone-pantry-dark.png" width="260" alt="The Pantry on a phone in dark mode" /><br><sub>Pantry, dark</sub> | <img src="docs/screenshots/phone-list.png" width="260" alt="The shopping list on a phone" /><br><sub>The list in the store</sub> | <img src="docs/screenshots/phone-spend.png" width="260" alt="Spend on a phone" /><br><sub>Spend</sub> |

<sub>The demo runs with an agent named Juniper set up (<code>GT_AGENT_NAME</code>), which is where "Ask
Juniper for dinner" and "Send to family chat" come from.</sub>

## How it fits together

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-dark.svg">
  <img src="docs/diagrams/architecture-light.svg" alt="How GrubTrack fits together: the browser talks to the FastAPI server and your agent runs the skill CLI; both go through the shared foodcore rules into one food.db file; the server also calls the optional model slot, keeps a two-way recipe folder, and asks the agent for meal ideas and to send the list">
</picture>

The web app and the agent's command line are two front doors to one SQLite file. Both go through
`foodcore`, the same Python package, so a receipt recorded by the agent and one typed into the
browser follow the same rules: the same store matching, the same categories, the same check
against the printed total. A sweep every 30 seconds categorizes and prices rows that other tools
wrote with their own SQL.

## Run it

**Docker**

```bash
git clone https://github.com/chungus-actual/grubtrack && cd grubtrack
mkdir -p data && sudo chown 1000 data          # Linux: the container runs as uid 1000
docker compose up -d                            # http://localhost:8888, data in ./data
docker compose exec grubtrack python3 /app/tools/seed_demo.py   # optional: the demo household
```

| | |
|---|---|
| Settings | environment variables in `compose.yaml` (model examples are there, commented out); every one is listed under [Settings](#settings) |
| HTTPS | mount a certificate and key read-only and set `GT_TLS_CERT` and `GT_TLS_KEY` |
| The CLI | inside the image it is `grubtrack`: `docker compose exec grubtrack grubtrack inventory` |
| Health | `curl localhost:8888/api/health` shows the item count and whether the model and agent are set up |
| Backups | one copy of `food.db` a day in `data/backups`, the newest 14 kept |
| Phones | open it in the phone's browser and add it to the home screen |

**From source** (Python 3.12, Node 22)

```bash
cd frontend && npm ci && npm run build && cd ..
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
python3 tools/seed_demo.py                      # optional: the demo household
cd backend && ../.venv/bin/python serve.py      # http://localhost:8888, data in ~/.local/share/grubtrack
```

GrubTrack has no login. Keep it on your home network, or put it behind your reverse proxy's
authentication. `GT_API_TOKEN` protects only the two endpoints an agent on another machine uses.

## Receipts

<table>
<tr>
<td width="50%"><img src="docs/screenshots/receipt-photo.png" width="100%" alt="Adding a receipt from a photo: the photo above the draft's store, date, total and tax fields" /><br><sub>A photo comes back as a draft beside it, every field editable</sub></td>
<td width="50%"><img src="docs/screenshots/receipt-check.png" width="100%" alt="The foot of a recorded receipt: lines, tax, total, savings and a note that every line is here" /><br><sub>The foot of a saved receipt: lines plus tax against the printed total</sub></td>
</tr>
</table>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/receipt-flow-dark.svg">
  <img src="docs/diagrams/receipt-flow-light.svg" alt="A receipt: you send a photo, the model slot drafts store, date, tax, total and every line, you check it beside the photo, GrubTrack matches the store and products and refuses duplicates, food.db gets a ledger row per line linked to pantry rows, and you see whether it adds up; the agent skill joins at the match step with the same checks">
</picture>

A receipt is checked against its printed total: lines plus tax must come to the total within two
cents, or GrubTrack says how far off it is and in which direction. A read can add up and still be
wrong, so the draft also warns when no store or total was read, when the date is more than 60 days
from today, or when the model marked part of the receipt unreadable.

Saving does three more things. The same store, date and total sent twice is refused instead of
becoming two trips. Each line is linked to the pantry row it stocked when exactly one row logged
from the day before to three days after is a confident match; the rest can be linked by hand on the
receipt. And linked pantry rows take their price from the receipt, replacing any price guessed for
them earlier.

Receipt reading is only as good as the photo and the model, which is why the draft always comes back
for you to check. Measured on real receipts with glm-5.3-flash at `low` effort: a sharp 37-line
receipt read perfectly in 17 seconds, and a 51-line one came back with two misread prices (flagged,
because it was 21 cents off the total). With full reasoning on, the same model once "fixed" a misread
by changing the printed tax so the sum worked, which is why lower effort is the safer setting for
reading.

## The pantry

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/pantry-states-dark.svg">
  <img src="docs/diagrams/pantry-states-light.svg" alt="A pantry row: logged, in date (a restock merges into the row), use first at three days or fewer, past date when the date passes, still good adds seven more days, and ate it or tossed moves it to gone, kept on record, with undo">
</picture>

A pantry row is in date, then **Use first** (dated today through the next three days, at the top of
the Pantry page), then past its date. A restock of something already in the house merges into its
row; the ledger keeps the old price. **Still good** on a past-date row gives it seven more days.

When a new row has no explicit use-by date, GrubTrack assigns a deterministic estimate from the
SQLite `expiration_rules` catalog. Rules match the taxonomy's canonical product or category plus
its storage location; specific examples include bananas on the counter and lettuce in the fridge.
An explicit date always wins. The Pantry marks generated dates as estimates and each item retains
the rule id that produced it. Built-in rules are inserted only when absent, so a higher-priority
household rule can override them without an application-code change. Unknown products still get a
storage-based fallback rather than silently remaining undated. The schema-v3 migration also fills
active legacy rows that have no date, using their purchase date or original logged date as the base.
The built-in household defaults are conservative estimates informed by the USDA
[FoodKeeper](https://www.foodsafety.gov/keep-food-safe/foodkeeper-app) and
[cold-storage chart](https://www.foodsafety.gov/food-safety-charts/cold-food-storage-charts).
They are not package dates or a food-safety guarantee: package instructions, recalls, temperature
history, and signs of spoilage take precedence.

Past-date items stay on the Pantry page under **Past date** until someone marks them, one at a time
or a whole department at once. Marking is a soft delete that records the fate: **Ate it** feeds the
restock ideas on the List page, **Tossed** feeds the waste numbers on the Spend page, and both
come with an undo.

## Recipes

Two kinds, both ranked by how much of each recipe is already in the house:

| | Where they live | How they get there |
|---|---|---|
| **Your recipes** | markdown files in `GT_RECIPES_DIR` (an Obsidian folder works) | **Save a recipe** on the Cook page: a link (read from the recipe data the page publishes), pasted text (read by the model), or typed in |
| **The library** | the database, filtered by time, protein, cuisine and dish | **Import recipes** on the Cook page, or `recipes-import` on the CLI |

| Library import reads | |
|---|---|
| Meal-Master | text files, many recipes per file, one or two ingredient columns |
| MasterCook | text exports (`.mxp`) |
| Paprika | `.paprikarecipes` and `.paprikarecipe` |
| Mealie | recipe JSON exports |
| schema.org | recipe JSON or JSON-LD, or a saved recipe web page |
| GrubTrack | JSON Lines: `{"title", "ingredients": [...], "instructions"}` |
| Any of them | in a zip or a folder |

Each recipe gets its protein, cuisine, dish type and time from its ingredients and categories. A
recipe already in the library (same title, same ingredients) is skipped, so importing the same file
twice is safe. **What I can make first** ranks recipes with at least three recognizable ingredients
by how many are in the house. Food past its date counts as missing, in the ranking and in meal ideas
alike. A recipe's page marks each ingredient as here or missing, adds the missing ones to the list in
one tap, and keeps a journal: a score out of 10, tags, and how it went.
GrubTrack ships no recipe collection of its own.

## AI: a model, an agent, or both

GrubTrack works without any AI: receipts can be typed in, and recipe links from most sites import
straight from the recipe data the page publishes. AI adds four jobs, through two optional slots.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/ai-routing-dark.svg">
  <img src="docs/diagrams/ai-routing-light.svg" alt="Which slot does which AI job: reading a receipt photo uses the model only; reading pasted recipe text uses the model, else the agent; suggesting meals uses the agent, else the model; sending the list uses the agent only; links, typed receipts and Share need no AI">
</picture>

| Job | First choice | Otherwise |
|---|---|---|
| Read a receipt photo into lines you check before saving | the model (it has to read images) | nobody: type the receipt in |
| Read pasted recipe text, estimate a library recipe's times | the model | the agent |
| Suggest meals from what's in the house | the agent | the model |
| Send the shopping list to a chat | the agent, with `GT_LIST_SEND_TO` set | nobody: **Share** still works |

The app names whoever answers: with an agent called Juniper, the Cook page says "Ask Juniper for
dinner".

**The model** is a direct LLM endpoint: any OpenAI-compatible server (Ollama, LM Studio, vLLM,
OpenRouter, llama.cpp, OpenAI) or Claude.

| Example | Settings |
|---|---|
| Ollama on this machine | `GT_MODEL_PROVIDER=openai` `GT_MODEL_URL=http://localhost:11434/v1` `GT_MODEL=gemma4:31b` |
| Ollama on the Docker host | as above with `GT_MODEL_URL=http://host.docker.internal:11434/v1` (`compose.yaml` maps the name) |
| Ollama cloud | `GT_MODEL_PROVIDER=openai` `GT_MODEL_URL=https://ollama.com/v1` `GT_MODEL=glm-5.3-flash` `GT_MODEL_KEY=...` `GT_MODEL_EFFORT=low` |
| OpenAI | `GT_MODEL_PROVIDER=openai` `GT_MODEL=gpt-5.5` `GT_MODEL_KEY=sk-...` |
| Claude | `GT_MODEL_PROVIDER=anthropic` `GT_MODEL_KEY=sk-ant-...` (model defaults to `claude-opus-5-5`) |

**The agent** is an [OpenClaw](https://github.com/openclaw/openclaw) or
[Hermes](https://github.com/NousResearch/hermes-agent) install with GrubTrack's skill (below). It
answers in its own voice with its own memory, and it can act, like sending the list to your family
chat.

| Setting | OpenClaw | Hermes |
|---|---|---|
| `GT_AGENT` | `openclaw` | `hermes` |
| How it's called | `openclaw agent --agent main -m <prompt>` | `hermes -z <prompt>` |
| `GT_AGENT_NAME` | what the app calls it ("Ask *Juniper* for dinner") | same |
| `GT_LIST_SEND_TO` | where the List page's Send button sends to, in words the agent understands: `Telegram chat 123456789` | same |

The agent slot runs the harness's CLI, so GrubTrack has to run where that CLI does (from source on
the same machine, or an image you extend). With or without one, the List page's **Share** button
hands the list to the phone's share sheet, or copies it on a desktop.

## The agent skill

`skill/food-inventory/` is a skill for OpenClaw and Hermes (the [AgentSkills](https://agentskills.io)
format both read). With it, your agent logs groceries from photos and messages, records receipts line
by line (and won't call one done until it adds up), and answers "what's expiring tomorrow", "where are
eggs cheaper" and "what did we spend this month" from the same database GrubTrack shows. Its CLI
needs only `python3` and the standard library.

```bash
python3 tools/install_skill.py openclaw --db ~/grubtrack/data/food.db
python3 tools/install_skill.py hermes   --db ~/grubtrack/data/food.db --local our-house.md
```

| Option | Does |
|---|---|
| `openclaw` or `hermes` | installs to `~/.openclaw/workspace/skills/food-inventory` or `~/.hermes/skills/household/food-inventory` |
| `--db PATH` | pins this `food.db` in the skill's `grubtrack.json`, so the agent and the web app open the same file |
| `--url URL` `--token T` `--ca FILE` | sends every command to a GrubTrack server instead (below) |
| `--local FILE` | installs household notes as `LOCAL.md`, which the skill reads first: who's who, which chat to confirm in, house rules |
| `--dest DIR` | another skill folder |
| `--backup-dir DIR` | where the previous copy is archived (default `~/.local/share/grubtrack/skill-backups`) |

The installer writes the folder's absolute path into the skill in place of `{baseDir}`, runs `init`
against the pinned database, and prints which database or server it will use. Re-running it updates
the skill and keeps the pin and the notes. The agent picks it up in its next session.

### When GrubTrack runs somewhere else

GrubTrack in a container on a NAS and the agent on your desktop is the usual setup, and SQLite can't
be shared over a network. So the skill's CLI can send every command to GrubTrack instead: same
commands, same output.

```bash
python3 tools/install_skill.py openclaw --url https://nas.lan:8888 --token "$GT_API_TOKEN" --ca house-ca.pem
```

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/server-mode-dark.svg">
  <img src="docs/diagrams/server-mode-light.svg" alt="GrubTrack on a server: the agent runs the same skill, the CLI forwards each command with its files and token to POST /api/cli, the server runs it against its own food.db and returns the output and exit code">
</picture>

The files a command names travel with it: a receipt JSON or recipe collection given with `--file`
(a folder is zipped on the way), and any photo a JSON payload points at, which the server keeps in
its `images/`. Scripts that read the database with their own SQL can use `fooddb_sqlite.py
snapshot`, which prints the path of a fresh copy (cached for 60 seconds; `--scope full` includes the
recipe library). Set `GT_API_TOKEN` on the server so only the agent can do either. If the server
can't be reached, the CLI says `Can't reach GrubTrack` and nothing is saved.

## The CLI

The skill's script is a complete command line for the same data (`grubtrack` inside the Docker
image). Output is JSON.

```bash
S=skill/food-inventory/scripts/fooddb_sqlite.py
python3 $S where                                  # which food.db (or server) it uses
python3 $S add --name "Greek yogurt" --storage fridge --exp 2026-11-02 --price 6.49
python3 $S inventory                              # what's in the house
python3 $S expiring --days 3                      # or --on tomorrow
python3 $S receipt-add --file receipt.json        # checked against the printed total
python3 $S prices --q eggs                        # last price, per store, shelf change, store gap
python3 $S spend --days 30
python3 $S shop-add --name "oat milk"
python3 $S recipes-import --file ~/Downloads/recipes.zip   # add --dry-run to see what's in it first
python3 $S journal-add --slug pad-thai --score 8 --review "Better with more lime"
python3 $S snapshot                               # a copy for your own SQL
```

`python3 $S --help` lists everything. The receipt JSON format is in the skill's `SKILL.md`.

| The CLI finds its data | |
|---|---|
| 1. `FOODDB_PATH` | that file, always local |
| 2. `GRUBTRACK_URL`, or a URL in `grubtrack.json` | a GrubTrack server (`GRUBTRACK_TOKEN`, `GRUBTRACK_CA` go with it) |
| 3. `GT_DATA` | `$GT_DATA/food.db` |
| 4. A path in `grubtrack.json` | the database the installer pinned |
| 5. Otherwise | `~/.local/share/grubtrack/food.db` (`XDG_DATA_HOME` respected) |

## Settings

Everything is an environment variable. Photos (`images/`), recipes and backups live beside `food.db`.

**Data**

| Variable | Default | What it does |
|---|---|---|
| `GT_DATA` | `~/.local/share/grubtrack` (`/data` in Docker) | the folder `food.db` lives in |
| `FOODDB_PATH` | `$GT_DATA/food.db` | the database itself, if it lives elsewhere |
| `GT_RECIPES_DIR` | `recipes/` beside `food.db` | your recipes: markdown files with an `## Ingredients` list (an Obsidian folder works) |
| `GT_RECIPES_WRITE` | `1` | `0` stops the app saving new recipes there |
| `GT_MEDIA_ROOT` | the data folder | folder relative photo paths resolve against (an agent's workspace, if it records paths from there) |
| `GT_BACKUPS` | `14` | daily copies of `food.db` kept in `backups/` (`0` turns them off) |
| `GT_SWEEP_SECONDS` | `30` | how often rows written by other tools get categorized and priced |

**The model**

| Variable | Default | What it does |
|---|---|---|
| `GT_MODEL_PROVIDER` | none | `openai` (any compatible server) or `anthropic` |
| `GT_MODEL` | none (`claude-opus-5-5` for anthropic) | model id |
| `GT_MODEL_URL` | `https://api.openai.com/v1` | base URL, the part before `/chat/completions` |
| `GT_MODEL_KEY` | none | API key (Claude also reads `ANTHROPIC_API_KEY`) |
| `GT_MODEL_EFFORT` | none | `low`, `medium` or `high`, for models that take it |
| `GT_MODEL_VISION` | `1` | `0` if the model can't read images |
| `GT_MODEL_MAX_TOKENS` | server's default (16000 for Claude) | output cap |
| `GT_MODEL_TIMEOUT` | `180` | seconds |

**The agent**

| Variable | Default | What it does |
|---|---|---|
| `GT_AGENT` | none | `openclaw` or `hermes` |
| `GT_AGENT_NAME` | `OpenClaw` / `Hermes` | the name shown in the app |
| `GT_AGENT_CMD` | `openclaw` / `hermes` | the command, if it isn't on `PATH` (e.g. `/usr/bin/node /opt/openclaw/openclaw.mjs`) |
| `GT_OPENCLAW_AGENT` | `main` | which OpenClaw agent answers |
| `GT_AGENT_PATH` | the server's `PATH` | `PATH` for the agent process |
| `GT_AGENT_TIMEOUT` | `300` | seconds |
| `GT_LIST_SEND_TO` | none | where Send delivers the list, in words the agent understands |
| `GT_LIST_SEND_LABEL` | `chat` | the button's label: "Send to *chat*" |
| `GT_AI_STYLE` | plain markdown, no em dashes | style line added to every prompt |
| `GT_MEAL_NOTES` | none | household preferences added to meal-idea prompts |

**The server**

| Variable | Default | What it does |
|---|---|---|
| `GT_PORT` | `8888` | port |
| `GT_HOST` | `0.0.0.0` | address to listen on |
| `GT_TLS_CERT`, `GT_TLS_KEY` | none | serve HTTPS with this certificate and key |
| `GT_API_TOKEN` | none | bearer token required by `/api/cli` and `/api/export/db` (the agent's CLI sends it) |
| `TZ` | the server's | "today" for expiry dates is the server's date |

`GT_PORT`, `GT_HOST` and the TLS pair apply when GrubTrack starts with `serve.py`, as the Docker
image and the from-source steps above do.

## How the data works

| Rule | Why |
|---|---|
| Every price lands in a `purchases` ledger, never only on the pantry row | a restock merges into the existing row, which would overwrite the old price |
| A receipt is complete when lines plus tax equal the printed total (±$0.02) | the total is the one number you can check a transcription against |
| Receipt lines that didn't stock the pantry (bags, cleaning, extras) are ledger lines, not pantry rows | the spend and price history are real either way |
| A receipt line replaces the price guessed earlier for the pantry row it stocked | the receipt is what was actually paid |
| The same store, date and total twice is one receipt | a receipt sent again (or re-sent to fix a line) must not become two trips |
| A price change is the shelf price at one store between two visits | a sale is a deal, and a different store is a store gap; neither is inflation |
| Sold-by-weight packages are compared only when the weight is known | two packs of deli turkey say nothing per pound |
| A buying rhythm predicts a due date only after three purchases | two purchases are a gap, not a rhythm |
| A category set by hand is never changed back | a correction should only have to be made once |
| Explicit use-by dates win; otherwise `expiration_rules` supplies a labeled estimate | reminders stay deterministic without pretending an estimate was printed on the package |
| Deleting a pantry item is soft and records eaten or tossed | that's what the restock ideas and the waste numbers learn from |

## Development

| Path | What |
|---|---|
| `skill/food-inventory/` | the agent skill: `SKILL.md`, the CLI (`scripts/fooddb_sqlite.py`) and `scripts/foodcore/` (schema, taxonomy, unit prices, receipt ledger, price analytics, recipe import, server mode) |
| `backend/app/` | FastAPI; `ai/` holds the model and agent providers, `routes/` the API (one file per page, plus `remote.py` for server mode) |
| `frontend/src/` | React 18 + Vite: `pages/` and `sheets/` (detail panels addressed by URL, `?open=product:<id>`) |
| `tools/` | `install_skill.py`, `seed_demo.py` |
| `tests/` | pytest: the core, the CLI, the API, server mode, the AI layer (mock transports and fake agent CLIs, no network) |

```bash
pip install -r backend/requirements-dev.txt && python -m pytest -q tests
cd frontend && npm run dev        # proxies /api to :8888
```

`seed_demo.py --today YYYY-MM-DD` pretends it's another day, and it refuses to touch a database that
already has items in it (`--force` overrides). CI runs the tests, builds the frontend, and starts the
Docker image on the demo data.

## Troubleshooting

| Symptom | Cause, fix |
|---|---|
| The container keeps restarting; the log says `unable to open database file` | Docker created `./data` as root and GrubTrack runs as uid 1000: `sudo chown 1000 data` |
| "Add a receipt" offers only **Type it in** | no vision model: set `GT_MODEL_PROVIDER` and `GT_MODEL`, and leave `GT_MODEL_VISION` at `1` |
| `<model> answered 401` or `404` when reading | the key, the model id or `GT_MODEL_URL` is wrong; the URL is the part before `/chat/completions` |
| A recipe link says the site "doesn't let apps read its pages" | that site refuses server requests; paste the recipe text instead (needs a model) |
| A saved receipt is "off by" some cents | a line is missing or misread: check the lines against the photo. Don't change the tax to make it fit |
| `... is already recorded` on a receipt | the same store, date and total exist; to rewrite it, `receipt-add --replace` with its `id` |
| `<name> isn't installed here` | the agent's command isn't on GrubTrack's `PATH`: set `GT_AGENT_CMD` or `GT_AGENT_PATH`; the stock Docker image has no agent in it |
| `Can't reach GrubTrack at <url>` from the agent | the server is down or the URL or CA is wrong; nothing was saved |
| `answered 401: This needs GrubTrack's API token` | re-run `install_skill.py` with `--token` matching the server's `GT_API_TOKEN` |
| The agent and the web app disagree | they opened different files: compare `fooddb_sqlite.py where` with the app's `GT_DATA`, then re-install with `--db` |
| Things expire a day early or late | the server's time zone: set `TZ` |

## License

MIT, see [LICENSE](LICENSE).

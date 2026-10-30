"""GrubTrack: the household's pantry, price book and spend, on top of food.db."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, config
from .db import connect, fdb, ledger
from .routes import cook, pantry, prices, remote, shopping, spend

log = logging.getLogger("grubtrack")


def _build_id() -> str:
    """Changes whenever a new frontend is deployed; open tabs compare it and reload when idle."""
    idx = config.STATIC_DIR / "index.html"
    try:
        return hashlib.sha1(idx.read_bytes()).hexdigest()[:10]
    except OSError:
        return "dev"


async def _sweeper():
    """Writes that bypass the CLI (another tool's raw SQL) still get resolved within a beat, and
    once a day food.db is copied into backups/."""
    while True:
        await asyncio.sleep(config.SWEEP_SECONDS)
        try:
            await asyncio.to_thread(_sweep_once)
            await asyncio.to_thread(backup_once)
        except Exception as e:  # pragma: no cover
            log.warning("sweep failed: %s", e)


def backup_once(today: str | None = None) -> Path | None:
    """Today's copy of food.db (the SQLite online backup, safe while it's being written), keeping
    the newest GT_BACKUPS. Nothing when today's exists or backups are off."""
    if config.BACKUPS <= 0 or not config.DB_PATH.exists():
        return None
    import datetime as dt
    import sqlite3
    folder = config.DATA_DIR / "backups"
    dest = folder / f"food-{today or dt.date.today().isoformat()}.db"
    if dest.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    src, out = sqlite3.connect(str(config.DB_PATH), timeout=15), sqlite3.connect(str(tmp))
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    tmp.replace(dest)
    for old in sorted(folder.glob("food-*.db"))[:-config.BACKUPS]:
        old.unlink()
    return dest


def _sweep_once():
    con = connect()
    try:
        ledger.sweep(con)
    finally:
        con.close()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)   # a first run from source has no data folder yet
    con = connect()
    try:
        fdb.init_db(con)          # inventory schema + foodcore migration
        cook.migrate_recipes(con)
        try:
            backup_once()
        except Exception as e:
            log.warning("backup failed: %s", e)
        try:
            ledger.sweep(con)
        except Exception as e:    # a bad row must never keep the site from starting
            log.warning("startup sweep failed: %s", e)
    finally:
        con.close()
    app.state.build = _build_id()
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()


VERSION = "2.3.2"
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".pdf"}
app = FastAPI(title="GrubTrack", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def stamp(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["X-GT-Build"] = getattr(app.state, "build", "dev")
        resp.headers["Cache-Control"] = "no-store"
    return resp


for r in (pantry.router, prices.router, spend.router, shopping.router, cook.router, remote.router):
    app.include_router(r)


@app.get("/api/build")
def build():
    return {"build": getattr(app.state, "build", "dev")}


@app.get("/api/config")
def client_config():
    """What this instance can do, for the browser: which AI answers which job, and recipe saving."""
    return {"version": VERSION, "ai": ai.describe(), "recipes": {"write": config.RECIPES_WRITE}}


@app.get("/api/health")
async def health():
    con = connect()
    try:
        items = con.execute("SELECT COUNT(*) FROM items WHERE deletedAt IS NULL").fetchone()[0]
    finally:
        con.close()
    return {"ok": True, "version": VERSION, "items": items, "ai": await ai.health()}


@app.get("/api/images/{img_path:path}")
def image(img_path: str):
    """Item and receipt photos. Paths are relative to the data folder (or GT_MEDIA_ROOT, where an agent
    records them relative to its workspace); a path from another machine's layout falls back to its
    file name in images/. Only image files, and nothing outside those folders, is served."""
    clean = img_path.lstrip("/")
    if Path(clean).suffix.lower() not in IMAGE_TYPES:
        raise HTTPException(404, "Image not found")
    roots = [config.DATA_DIR.resolve(), config.MEDIA_ROOT.resolve()]
    for p in (config.IMAGES_DIR / clean, config.DATA_DIR / clean, config.MEDIA_ROOT / clean,
              config.IMAGES_DIR / Path(clean).name):
        try:
            rp = p.resolve()
            if not any(rp.is_relative_to(r) for r in roots):
                continue
            if rp.is_file():
                return FileResponse(str(rp), headers={"Cache-Control": "max-age=86400"})
        except OSError:
            continue
    raise HTTPException(404, "Image not found")


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_404(rest: str):
    raise HTTPException(404, f"No such endpoint: /api/{rest}")


if (config.STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(config.STATIC_DIR / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """The app shell for every non-API path (the uptime check hits `/` every ~50 s)."""
    static = config.STATIC_DIR
    f = (static / full_path).resolve() if full_path else None
    if f and f.is_file() and f.is_relative_to(static.resolve()):
        return FileResponse(str(f))
    idx = static / "index.html"
    if idx.exists():
        return FileResponse(str(idx), headers={"Cache-Control": "no-cache"})
    return JSONResponse({"grubtrack": "API running; frontend not built"})

"""Runs once per scheduled job (GitHub Actions): fetch rate, save history, rebuild the JSON files the website reads."""
import asyncio, json, os, pathlib
os.environ.setdefault("DB_PATH", "data/gold.db")
import main

async def run():
    out = pathlib.Path("static/data"); out.mkdir(parents=True, exist_ok=True)
    main.init()
    got = await main.fetch_rate()
    print("live rate:", got or "none (no key or feed failed; using last saved rate)")
    (out / "rates.json").write_text(json.dumps(main.rates()))
    (out / "history.json").write_text(json.dumps(main.history()))
    (out / "advice.json").write_text(json.dumps(await main.advice()))

asyncio.run(run())

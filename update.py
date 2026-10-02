import asyncio, json, os, pathlib
os.environ.setdefault("DB_PATH", "data/gold.db")
pathlib.Path("data").mkdir(exist_ok=True)
pathlib.Path("static/data").mkdir(parents=True, exist_ok=True)
import main

async def run():
    out = pathlib.Path("static/data")
    main.init()
    got = await main.fetch_rate()
    print("live rate:", got or "none (no key; using last saved rate)")
    (out / "rates.json").write_text(json.dumps(main.rates()))
    (out / "history.json").write_text(json.dumps(main.history()))
    (out / "advice.json").write_text(json.dumps(await main.advice()))

asyncio.run(run())

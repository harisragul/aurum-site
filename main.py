import os, json, html, sqlite3, datetime as dt, statistics as st
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo
import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

IST = ZoneInfo("Asia/Kolkata")
DB = os.getenv("DB_PATH", "gold.db")
GKEY, AKEY = os.getenv("GOLDAPI_KEY"), os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
PREMIUM, ADMIN = float(os.getenv("PREMIUM") or 1.0), os.getenv("ADMIN_TOKEN")
today = lambda: dt.datetime.now(IST).date()

# Seed history (24K INR/gram, Paytm/IBJA-aligned): monthly lows Oct25-Aug26 + daily 30 Aug-29 Sep 2026
SEED = {"2025-10-15":12309.0,"2025-11-15":13226.9,"2025-12-15":14304.9,"2026-01-15":17195.2,"2026-02-15":17551.9,
"2026-03-15":15041.5,"2026-04-15":15543.1,"2026-05-15":16498.0,"2026-06-15":14830.3,"2026-07-15":14690.1,"2026-08-15":16011.8,
"2026-08-30":16245.9,"2026-09-19":15992.9,"2026-09-20":15992.9,"2026-09-21":15852.8,"2026-09-22":15839.5,"2026-09-23":15636.8,
"2026-09-24":15613.6,"2026-09-25":15649.7,"2026-09-26":15670.0,"2026-09-27":15670.0,"2026-09-28":15181.9,"2026-09-29":15274.8}

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init():
    with db() as c:
        c.execute("create table if not exists rates(d text primary key, k24 real, src text)")
        c.execute("create table if not exists advice(d text primary key, j text)")
        for d, v in SEED.items():
            c.execute("insert or ignore into rates values(?,?,?)", (d, v, "seed"))

def save(k24, src):
    with db() as c:
        c.execute("insert or replace into rates values(?,?,?)", (str(today()), round(k24, 2), src))
        c.execute("delete from advice where d=?", (str(today()),))

async def fetch_rate():
    if not GKEY: return None
    try:
        async with httpx.AsyncClient(timeout=20) as h:
            r = await h.get("https://www.goldapi.io/api/XAU/INR", headers={"x-access-token": GKEY})
            r.raise_for_status()
            v = float(r.json()["price_gram_24k"]) * PREMIUM
        save(v, "goldapi"); return v
    except Exception as e:
        print("rate fetch failed:", e); return None

@asynccontextmanager
async def life(app):
    init()
    sch = AsyncIOScheduler(timezone=IST)
    sch.add_job(fetch_rate, "cron", hour="10,16", minute=30)  # twice a day, IST
    sch.start()
    with db() as c:
        have = c.execute("select 1 from rates where d=?", (str(today()),)).fetchone()
    if not have: await fetch_rate()
    yield
    sch.shutdown()

app = FastAPI(lifespan=life)

def rows():
    with db() as c: return [(dt.date.fromisoformat(r["d"]), r["k24"], r["src"]) for r in c.execute("select * from rates order by d")]

@app.get("/api/rates")
def rates():
    r = rows(); d, k, src = r[-1]; p = r[-2][1]
    chg = (k - p) / p * 100
    return {"asof": f"{d.day} {d:%b %Y}", "stale": (today() - d).days > 1, "source": src, "r24": k, "r22": k*22/24, "r18": k*.75, "chg24": chg, "chg22": chg}

@app.get("/api/history")
def history():
    r = rows(); t = today()
    wk = r[-7:]
    mo = [x for x in r if (t - x[0]).days <= 31]
    ym = {}
    for d, k, _ in r:
        if (t - d).days <= 366: ym[(d.year, d.month)] = min(ym.get((d.year, d.month), 1e9), k)
    return {"W": {"l": [f"{d.day} {d:%b}" for d, *_ in wk], "v": [round(k, 1) for _, k, _ in wk], "s": "Last 7 published days"},
            "M": {"l": [f"{d.day} {d:%b}" for d, *_ in mo], "v": [round(k, 1) for _, k, _ in mo], "s": "Last month (days with a recorded rate)"},
            "Y": {"l": [f"{dt.date(y, m, 1):%b %y}" for (y, m), _ in sorted(ym.items())], "v": [round(v, 1) for _, v in sorted(ym.items())], "s": "Lowest price in each month"}}

def features():
    v = [k for _, k, _ in rows()][-60:]
    last, prev = v[-1], v[-2]
    h30 = max(v[-30:]); w = v[-8:]
    gains = [max(b - a, 0) for a, b in zip(w, w[1:])]; loss = [max(a - b, 0) for a, b in zip(w, w[1:])]
    rsi = 100 - 100 / (1 + (sum(gains) / (sum(loss) or 1e-9)))
    return {"price_per_gram_24k": round(last), "day_change_pct": round((last - prev) / prev * 100, 2),
            "pct_below_30d_high": round((h30 - last) / h30 * 100, 2), "avg_7": round(st.mean(v[-7:])), "avg_30": round(st.mean(v[-30:])),
            "rsi_7": round(rsi), "volatility_pct": round(st.pstdev(v[-30:]) / st.mean(v[-30:]) * 100, 2), "days_of_data": len(v)}

def rule_advice(f):
    s = 35 + min(f["pct_below_30d_high"], 8) * 6 + (6 if f["day_change_pct"] < 0 else -6) + (8 if f["rsi_7"] < 35 else -8 if f["rsi_7"] > 65 else 0) + (5 if f["price_per_gram_24k"] < f["avg_30"] else -5)
    s = int(max(5, min(95, round(s))))
    tone = "buy" if s >= 65 else "split" if s >= 45 else "wait"
    return {"score": s, "tone": tone, "verdict": {"buy": "Good time to start buying", "split": "Buy in small parts", "wait": "Wait for a dip"}[tone],
            "reasons": [f"24K is {f['pct_below_30d_high']}% below its 30-day high and {'below' if f['price_per_gram_24k'] < f['avg_30'] else 'above'} its 30-day average.",
                        f"Today's move is {f['day_change_pct']}%; 7-day RSI is {f['rsi_7']} ({'oversold' if f['rsi_7'] < 35 else 'overbought' if f['rsi_7'] > 65 else 'neutral'}).",
                        "Gold is volatile; spreading purchases over a few weeks lowers the risk of buying at a peak.",
                        "Jewellery adds making charges and 3% GST; coins and bars cost less to buy."], "engine": "rule-based model"}

SYS = ("You are a cautious gold-buying analyst for retail buyers in Chennai, India. Use ONLY the numbers given. "
       'Reply with JSON only: {"score":0-100 buy-readiness,"tone":"buy"|"split"|"wait","verdict":"<=6 words","reasons":[3 or 4 short sentences]}. '
       "Never promise returns or predict exact prices. Mention if days_of_data is small. Plain text, no markup.")

async def claude(f, base):
    async with httpx.AsyncClient(timeout=40) as h:
        r = await h.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": AKEY, "anthropic-version": "2023-06-01"},
            json={"model": MODEL, "max_tokens": 600, "system": SYS, "messages": [{"role": "user", "content": json.dumps({"features": f, "baseline_score": base["score"]})}]})
        r.raise_for_status()
        t = r.json()["content"][0]["text"].strip().strip("`").removeprefix("json").strip()
    j = json.loads(t)
    sc = int(max(base["score"] - 15, min(base["score"] + 15, j["score"])))  # keep model near the statistical baseline
    tone = j["tone"] if j["tone"] in ("buy", "split", "wait") else base["tone"]
    return {"score": sc, "tone": tone, "verdict": html.escape(str(j["verdict"]))[:60], "reasons": [html.escape(str(x))[:260] for x in j["reasons"][:4]], "engine": "Claude AI + statistics"}

@app.get("/api/advice")
async def advice():
    k = str(today())
    with db() as c:
        row = c.execute("select j from advice where d=?", (k,)).fetchone()
    if row: return json.loads(row["j"])
    f = features(); out = rule_advice(f)
    if AKEY:
        try: out = await claude(f, out)
        except Exception as e: print("claude failed:", e)
    out["asof"] = f"{today().day} {today():%b %Y}"
    with db() as c: c.execute("insert or replace into advice values(?,?)", (k, json.dumps(out)))
    return out

@app.post("/api/admin/rate")
def manual(body: dict, x_admin_token: str = Header(None)):
    if not ADMIN or x_admin_token != ADMIN: raise HTTPException(401)
    save(float(body["k24"]), "manual"); return {"ok": True}

app.mount("/", StaticFiles(directory="static", html=True), name="static")

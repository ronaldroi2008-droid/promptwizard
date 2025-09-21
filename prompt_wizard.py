"""
Prompt Wizard — FREE/PAID with daily reset + cache-busted static + robust buttons
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from dotenv import load_dotenv
import httpx

# Timezone (tzdata fallback)
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------------- Env ----------------
load_dotenv(override=True)

APP_NAME = os.getenv("APP_NAME", "Prompt Wizard")
ENABLE_GPT = os.getenv("ENABLE_GPT", "0") == "1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_ORG = os.getenv("OPENAI_ORG")

ROLLOVER_MODE = os.getenv("ROLLOVER_MODE", "0") == "1"          # 0=FREE, 1=PAID
DAILY_FREE_LIMIT = int(os.getenv("DAILY_FREE_LIMIT", "10"))      # FREE only

INITIAL_CREDITS = int(os.getenv("INITIAL_CREDITS", "0"))
DAILY_GRANT = int(os.getenv("DAILY_GRANT", "0"))
MAX_BALANCE = int(os.getenv("MAX_BALANCE", "100"))

SHOW_USAGE = os.getenv("SHOW_USAGE", "1") == "1"
SHOW_TIMER = os.getenv("SHOW_TIMER", "1") == "1"
APP_TZ_STR = os.getenv("APP_TZ", "Asia/Manila")

DB_FILE = os.getenv("DB_FILE", "prompts.db")

ROOT = os.getcwd()
DB_PATH = os.path.join(ROOT, DB_FILE)
TEMPLATE_DIR = os.path.join(ROOT, "templates")
STATIC_DIR = os.path.join(ROOT, "static")
os.makedirs(TEMPLATE_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# ---------------- Timezone helpers ----------------
try:
    TZ = ZoneInfo(APP_TZ_STR)
except (ZoneInfoNotFoundError, Exception):
    print(f"WARN: tzdata not found for {APP_TZ_STR}; falling back to UTC+8.")
    TZ = timezone(timedelta(hours=8))  # Manila: UTC+8, no DST

def now_tz() -> datetime:
    return datetime.now(TZ)

def today_str() -> str:
    return now_tz().strftime("%Y-%m-%d")

def next_midnight_tz_iso() -> str:
    n = now_tz()
    tmr = (n + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tmr.isoformat()

# ---------------- HTML/CSS (unchanged style) ----------------
styles_css = """*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#fbfbfd;color:#111;margin:0}
.wrap{max-width:980px;margin:28px auto;padding:0 16px}
.title{margin:0}
.subtitle{color:#666;margin:6px 0 18px}
.panel{background:#fff;border:1px solid #eee;border-radius:14px;box-shadow:0 4px 12px rgba(0,0,0,.04);padding:16px 20px;margin:14px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
label{display:flex;flex-direction:column;gap:6px;font-size:14px}
input,select,textarea{padding:10px 12px;border:1px solid #ddd;border-radius:10px;font-size:14px}
.actions{display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap}
button{padding:10px 14px;border:none;border-radius:10px;background:#111;color:#fff;cursor:pointer}
button.alt{background:#2e6ee6}
button.ghost{background:#f0f0f3;color:#111}
.msg{color:#2e6ee6;font-size:12px}
textarea#output,textarea#outputConcise{width:100%;font-family:ui-monospace,Consolas,monospace}
#history{display:grid;gap:8px}
#history .item{border:1px solid #eee;border-radius:10px;padding:10px}
.small{color:#666;font-size:12px}
footer{margin:16px 0;color:#777;font-size:12px}
.usagebar{display:flex;gap:12px;align-items:center;margin-top:8px}
.badge{display:inline-block;padding:6px 10px;border-radius:999px;background:#eef3ff;color:#1f3db6;font-weight:600;font-size:12px}
.badge.warn{background:#ffeceb;color:#b11d1d}
.pill{display:inline-block;margin-left:8px;padding:2px 8px;border-radius:999px;background:#eef3ff;color:#1f3db6;font-size:12px;font-weight:600}
"""

base_html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ app_name }}</title>
  <link rel="stylesheet" href="/static/styles.css?v={{ build_id }}" />
</head>
<body>
  <div class="wrap">
    <h1 class="title">{{ app_name }} <span class="pill">{{ "PAID" if rollover_mode else "FREE" }}</span></h1>
    <p class="subtitle">Form-based AI prompt builder. Offline builder + optional GPT enhancement.</p>
    {% block content %}{% endblock %}
    <footer><p class="muted">© {{ year }} Prompt Wizard</p></footer>
  </div>
  <script src="/static/app.js?v={{ build_id }}"></script>
</body>
</html>
"""

index_html = """{% extends "base.html" %}
{% block content %}
<section class="panel">
  <form id="genForm" onsubmit="return false;">
    <div class="grid">
      <label>Quick Preset
        <select id="presetSelect" onchange="applyPreset(this.value)">
          <option value="">-- choose preset --</option>
          <option value="ecom_ig">E-commerce IG Caption</option>
          <option value="tiktok_hook">TikTok Hook</option>
          <option value="email_subject">Email Subject Line</option>
          <optgroup id="myPresets" label="My Presets"></optgroup>
        </select>
      </label>

      <label>Preset Name (to save)
        <input id="presetName" placeholder="e.g., My Chamomile IG Set" />
      </label>

      <label>Target Audience
        <input name="audience" placeholder="e.g., Filipino freelancers" required />
      </label>

      <label>Tone
        <select name="tone">
          <option>Friendly</option>
          <option>Professional</option>
          <option>Persuasive</option>
          <option>Casual</option>
          <option>Authoritative</option>
          <option>Inspirational</option>
        </select>
      </label>

      <label>Goal
        <select name="goal">
          <option>Instagram caption</option>
          <option>Facebook post</option>
          <option>TikTok script</option>
          <option>Product description</option>
          <option>Email subject lines</option>
          <option>Blog outline</option>
        </select>
      </label>

      <label>Platform / Context
        <input name="platform" placeholder="e.g., Instagram Reels" />
      </label>

      <label>Language
        <select name="language">
          <option>English</option>
          <option>Tagalog</option>
          <option>Taglish</option>
        </select>
      </label>

      <label>Constraints
        <input name="constraints" placeholder="e.g., 120 chars, include CTA" />
      </label>

      <label>Brand Voice
        <input name="brand" placeholder="e.g., witty, premium" />
      </label>

      <label>Key Details
        <textarea name="details" rows="3" placeholder="e.g., organic soap, ₱199 launch"></textarea>
      </label>
    </div>

    <div class="actions">
      <button id="buildBtn" type="button">Build Prompt</button>
      {% if enable_gpt %}
      <button id="enhanceBtn" class="alt" type="button">Enhance Detailed</button>
      <button id="enhanceConciseBtn" class="alt" type="button">Enhance Concise</button>
      {% endif %}
      <button id="copyBtn" class="ghost" type="button">Copy</button>
      <button id="copyConciseBtn" class="ghost" type="button">Copy Concise</button>
      <button id="saveBtn" class="ghost" type="button">Save</button>
      <span id="msg" class="msg"></span>
    </div>

    {% if show_usage %}
      <div id="usageBar" class="usagebar" style="display:none">
        <span id="usageBadge" class="badge">Usage: –</span>
        {% if show_timer %}<span id="resetTimerUsage" class="small">Resets in: –</span>{% endif %}
      </div>

      <div id="creditsBar" class="usagebar" style="display:none">
        <span id="creditsBadge" class="badge">Credits: –</span>
        {% if show_timer %}<span id="resetTimerCredits" class="small">Resets in: –</span>{% endif %}
      </div>
    {% endif %}
  </form>
</section>

<section class="panel">
  <h3>Output Prompt (Detailed)</h3>
  <textarea id="output" rows="10"></textarea>
</section>

<section class="panel">
  <h3>Concise Prompt (Copy-ready)</h3>
  <textarea id="outputConcise" rows="10"></textarea>
</section>

<section class="panel">
  <h3>My Presets (local to this browser)</h3>
  <div id="presetList"></div>
</section>

<section class="panel">
  <h3>History</h3>
  <div id="history"></div>
</section>
{% endblock %}
"""

# Write assets
with open(os.path.join(TEMPLATE_DIR, "base.html"), "w", encoding="utf-8") as f:
    f.write(base_html)
with open(os.path.join(TEMPLATE_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(index_html)
with open(os.path.join(STATIC_DIR, "styles.css"), "w", encoding="utf-8") as f:
    f.write(styles_css)

# static/app.js provided separately (already saved by you)
# ---------------- DB ----------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prompt TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS usage_counts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip TEXT,
  day TEXT,
  count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS credit_wallets (
  ip TEXT PRIMARY KEY,
  balance INTEGER DEFAULT 0,
  last_grant_day TEXT,
  timezone TEXT
);
"""
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    try:
        conn.execute("UPDATE credit_wallets SET timezone=? WHERE timezone IS NULL OR timezone=''", (APP_TZ_STR,))
        conn.commit()
    except Exception:
        pass
    conn.close()
init_db()

# ---------------- Helpers ----------------
app = FastAPI(title=APP_NAME)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

def _get_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else req.client.host)

# FREE limits
def can_use_and_inc(ip: str) -> bool:
    day = today_str()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute("SELECT count FROM usage_counts WHERE ip=? AND day=?", (ip, day)).fetchone()
    count = (row[0] if row else 0)
    if count >= DAILY_FREE_LIMIT:
        conn.close()
        return False
    if row:
        cur.execute("UPDATE usage_counts SET count=count+1 WHERE ip=? AND day=?", (ip, day))
    else:
        cur.execute("INSERT INTO usage_counts (ip, day, count) VALUES (?, ?, 1)", (ip, day))
    conn.commit()
    conn.close()
    return True

def get_usage_status(ip: str):
    day = today_str()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT count FROM usage_counts WHERE ip=? AND day=?", (ip, day)).fetchone()
    conn.close()
    count = (row[0] if row else 0)
    limit = DAILY_FREE_LIMIT
    remaining = max(limit - count, 0)
    reset_at = next_midnight_tz_iso()
    return {"count": count, "limit": limit, "remaining": remaining, "reset_at": reset_at}

# PAID wallet
def wallet_get(ip: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT ip,balance,last_grant_day,timezone FROM credit_wallets WHERE ip=?", (ip,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO credit_wallets (ip,balance,last_grant_day,timezone) VALUES (?,?,?,?)",
            (ip, max(INITIAL_CREDITS, 0), today_str(), APP_TZ_STR)
        )
        conn.commit()
        row = conn.execute("SELECT ip,balance,last_grant_day,timezone FROM credit_wallets WHERE ip=?", (ip,)).fetchone()
    conn.close()
    return dict(row)

def wallet_grant_if_needed(ip: str):
    if DAILY_GRANT <= 0:
        return
    w = wallet_get(ip)
    last = w.get("last_grant_day") or today_str()
    today = today_str()
    if today > last:
        d1 = datetime.strptime(last, "%Y-%m-%d")
        d2 = datetime.strptime(today, "%Y-%m-%d")
        days = (d2 - d1).days
        add = max(days, 0) * DAILY_GRANT
        new_bal = min(w["balance"] + add, MAX_BALANCE)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE credit_wallets SET balance=?, last_grant_day=? WHERE ip=?",
                     (new_bal, today, ip))
        conn.commit()
        conn.close()

def wallet_status(ip: str):
    wallet_grant_if_needed(ip)
    w = wallet_get(ip)
    reset_at = next_midnight_tz_iso()
    return {"balance": w["balance"], "grant_per_day": DAILY_GRANT,
            "max_balance": MAX_BALANCE, "reset_at": reset_at}

def wallet_spend(ip: str, n: int = 1) -> bool:
    wallet_grant_if_needed(ip)
    w = wallet_get(ip)
    if w["balance"] < n:
        return False
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE credit_wallets SET balance=balance-? WHERE ip=?", (n, ip))
    conn.commit()
    conn.close()
    return True

# ---------------- Models ----------------
class BuildPayload(BaseModel):
    audience: str
    tone: str
    goal: str
    platform: Optional[str] = None
    language: Optional[str] = "English"
    constraints: Optional[str] = None
    brand: Optional[str] = None
    details: Optional[str] = None

class EnhancePayload(BaseModel):
    prompt: str

# ---------------- Routes ----------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": APP_NAME,
            "enable_gpt": ENABLE_GPT,
            "year": now_tz().year,
            "rollover_mode": ROLLOVER_MODE,
            "show_usage": SHOW_USAGE,
            "show_timer": SHOW_TIMER,
            "build_id": int(datetime.now().timestamp()),  # cache-bust static
        },
    )

@app.post("/build")
async def build(payload: BuildPayload):
    # simple debug to see payload
    print("DEBUG /build payload:", payload.model_dump())

    lines = [
        f"You are an expert. Create a {payload.goal}.",
        f"Target audience: {payload.audience}.",
        f"Tone: {payload.tone}.",
        f"Language: {payload.language}.",
    ]
    if payload.platform:    lines.append(f"Platform: {payload.platform}.")
    if payload.brand:       lines.append(f"Brand voice: {payload.brand}.")
    if payload.details:     lines.append(f"Details: {payload.details}.")
    if payload.constraints: lines.append(f"Constraints: {payload.constraints}.")
    lines.append("Provide 3 variants when possible.")
    detailed = "\n".join(lines)

    goal = (payload.goal or "content").strip()
    audience = payload.audience.strip()
    tone = payload.tone.strip()
    language = payload.language or "English"
    platform = (payload.platform or "").strip()
    brand = (payload.brand or "").strip()
    details = (payload.details or "").strip()
    constraints = (payload.constraints or "").strip()

    g = goal.lower()
    if "instagram" in g and "caption" in g:
        output_fmt = ("OUTPUT FORMAT (STRICT):\n"
                      "1) Caption 1: <text> #<tag1> #<tag2>\n"
                      "2) Caption 2: <text> #<tag1> #<tag2>\n"
                      "3) Caption 3: <text> #<tag1> #<tag2>")
    elif "email subject" in g or "email" in g:
        output_fmt = ("OUTPUT FORMAT (STRICT):\n"
                      "1) <subject line> (chars: ###)\n"
                      "2) <subject line> (chars: ###)\n"
                      "3) <subject line> (chars: ###)")
    elif "tiktok" in g and "script" in g:
        output_fmt = ("OUTPUT FORMAT (STRICT):\n"
                      "1) Hook (≤8 words)\n"
                      "2) Beat 1 (5–7s)\n"
                      "3) Beat 2 (5–7s)\n"
                      "4) Beat 3 (3–5s)\n"
                      "5) CTA (1 line)\n"
                      "6) 2 hashtags")
    elif "blog" in g and "outline" in g:
        output_fmt = ("OUTPUT FORMAT (STRICT):\n"
                      "H1 Title\n"
                      "H2 Sections (4–6)\n"
                      "Bullet points per section (3–5)")
    else:
        output_fmt = ("OUTPUT FORMAT (STRICT):\n"
                      "Return a numbered list of 3 variants:\n"
                      "1) ...\n"
                      "2) ...\n"
                      "3) ...")

    concise_lines = [
        f"TASK: Create 3 variants of {goal}.",
        f"AUDIENCE: {audience}",
        f"TONE/VOICE: {tone}" + (f" | Brand: {brand}" if brand else ""),
        f"LANGUAGE: {language}",
    ]
    if platform: concise_lines.append(f"PLATFORM: {platform}")
    if details:  concise_lines.append(f"PRODUCT/DETAILS: {details}")
    concise_lines.append("CONSTRAINTS:")
    if constraints:
        concise_lines.append(f"- {constraints}")
    else:
        concise_lines.append("- Keep it concise and scroll-stopping.")
        if "instagram" in g and "caption" in g:
            concise_lines.append("- End each caption with exactly 2 relevant hashtags.")

    concise_lines += ["", output_fmt, "", "QUALITY CHECK:", "- If any variant violates constraints, rewrite it before returning."]
    concise = "\n".join(concise_lines)

    return {"ok": True, "prompt": detailed, "concise": concise}

@app.post("/enhance")
async def enhance(payload: EnhancePayload, request: Request):
    if not ENABLE_GPT or not OPENAI_API_KEY:
        return JSONResponse({"ok": False, "error": "GPT disabled."}, status_code=400)

    ip = _get_ip(request)
    if ROLLOVER_MODE:
        if not wallet_spend(ip, 1):
            return JSONResponse({"ok": False, "error": "Not enough credits.", "credits": wallet_status(ip)}, status_code=402)
    else:
        if not can_use_and_inc(ip):
            return JSONResponse({"ok": False, "error": "Daily GPT limit reached.", "usage": get_usage_status(ip)}, status_code=429)

    system = ("You refine prompt instructions for generative AI models. "
              "Improve clarity, add structure, keep it concise but complete, "
              "and include explicit output formatting when helpful. "
              "Do NOT generate the final content—return only the improved prompt.")

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    if OPENAI_ORG: headers["OpenAI-Organization"] = OPENAI_ORG

    try:
        async with httpx.AsyncClient(timeout=30, base_url=OPENAI_BASE_URL, headers=headers) as client:
            r = await client.post("/chat/completions", json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": payload.prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 600,
            })
            r.raise_for_status()
            data = r.json()
            out = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return {"ok": True, "prompt": out, **({"credits": wallet_status(ip)} if ROLLOVER_MODE else {"usage": get_usage_status(ip)})}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/save")
async def save(item: Dict[str, Any]):
    text = (item or {}).get("prompt", "").strip()
    if not text: return {"ok": False, "error": "Empty prompt."}
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO history (prompt, created_at) VALUES (?, ?)", (text, now_tz().strftime("%Y-%m-%d %H:%M")))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/history")
async def history():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT prompt, created_at FROM history ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}

@app.get("/health")
async def health():
    info: Dict[str, Any] = {"ok": True, "enable_gpt": ENABLE_GPT, "mode": ("paid_credits" if ROLLOVER_MODE else "free_daily_cap")}
    if ROLLOVER_MODE:
        info.update({"initial_credits": INITIAL_CREDITS, "max_balance": MAX_BALANCE})
    else:
        info.update({"limit": DAILY_FREE_LIMIT})
    return info

@app.get("/usage_today")
async def usage_today(request: Request):
    ip = _get_ip(request)
    return get_usage_status(ip)

@app.get("/credits_status")
async def credits_status(request: Request):
    ip = _get_ip(request)
    return wallet_status(ip)

if __name__ == "__main__":
    import uvicorn
    print("DEBUG:",
          "MODE=", "PAID" if ROLLOVER_MODE else "FREE",
          "| DAILY_FREE_LIMIT=", DAILY_FREE_LIMIT,
          "| INITIAL_CREDITS=", INITIAL_CREDITS,
          "| DAILY_GRANT=", DAILY_GRANT,
          "| MAX_BALANCE=", MAX_BALANCE,
          "| DB=", DB_PATH)
    uvicorn.run("prompt_wizard:app", host="127.0.0.1", port=8000, reload=True)









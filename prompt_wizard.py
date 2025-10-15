# Prompt Wizard — Free + Paid
# - robust /build
# - dark mode flags passed to template
# - signup/upgrade + 300 Free Prompts download
# - EmailOctopus ESP integration (optional)
# - usage (free) and credits (paid) meters
# - absolute URL handling for local /static PDF

import os
import io
import re
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from urllib.parse import urljoin

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, PlainTextResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

# Email (optional for /api/signup)
import smtplib
from email.mime.text import MIMEText

# Timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# -------- ENV LOADING --------
dotenv_path = os.getenv("DOTENV_FILE") or ".env"
load_dotenv(dotenv_path=dotenv_path, override=True)

# -------- CONFIG --------
APP_NAME = os.getenv("APP_NAME", "Prompt Wizard")
ENABLE_GPT = os.getenv("ENABLE_GPT", "0") == "1"
ROLLOVER_MODE = os.getenv("ROLLOVER_MODE", "0") == "1"   # 0=FREE, 1=PAID

# FREE usage
DAILY_FREE_LIMIT = int(os.getenv("DAILY_FREE_LIMIT", "10"))

# PAID credits
INITIAL_CREDITS = int(os.getenv("INITIAL_CREDITS", "0"))
DAILY_GRANT = int(os.getenv("DAILY_GRANT", "0"))
MAX_BALANCE = int(os.getenv("MAX_BALANCE", "100"))
DAILY_RESET_BALANCE = int(os.getenv("DAILY_RESET_BALANCE", "100"))

# UI flags
SHOW_USAGE = os.getenv("SHOW_USAGE", "1") == "1"
SHOW_TIMER = os.getenv("SHOW_TIMER", "1") == "1"
APP_TZ_STR = os.getenv("APP_TZ", "Asia/Manila")

# Lead/checkout (optional display)
CAPTURE_REQUIRED = os.getenv("CAPTURE_REQUIRED", "0") == "1"
GUMROAD_CHECKOUT_URL = os.getenv("GUMROAD_CHECKOUT_URL", "")
AFFILIATE_NOTE = os.getenv("AFFILIATE_NOTE", "")
FREEBIE_NOTE = os.getenv("FREEBIE_NOTE", "Unlock 300 bonus prompts via email.")
LTD_PRICE_TEXT = os.getenv("LTD_PRICE_TEXT", "$29 Lifetime (free updates)")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_ORG = os.getenv("OPENAI_ORG", "")

# Email delivery (optional)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FREE_PROMPTS_URL = os.getenv("FREE_PROMPTS_URL", "").strip()

# ESP (EmailOctopus) optional
ESP_PROVIDER = os.getenv("ESP_PROVIDER", "").lower()          # set to 'emailoctopus'
EO_API_KEY   = os.getenv("EMAILOCTOPUS_API_KEY", "").strip()
EO_LIST_ID   = os.getenv("EMAILOCTOPUS_LIST_ID", "").strip()
EO_STATUS    = os.getenv("EMAILOCTOPUS_STATUS", "SUBSCRIBED").strip()  # SUBSCRIBED|PENDING
EO_TAGS      = [t.strip() for t in os.getenv("EMAILOCTOPUS_TAGS", "").split(",") if t.strip()]

# GTM/FB Pixel (optional)
GTM_ID = os.getenv("GTM_ID", "")
FB_PIXEL_ID = os.getenv("FB_PIXEL_ID", "")

# DB
DB_FILE = os.getenv("DB_FILE", "prompts.db")

# -------- PATHS --------
ROOT = os.getcwd()
DB_PATH = os.path.join(ROOT, DB_FILE)
STATIC_DIR = os.path.join(ROOT, "static")
TEMPLATE_DIR = os.path.join(ROOT, "templates")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)

# If no FREE_PROMPTS_URL but the local PDF exists, default to it
LOCAL_FREE_PDF = "/static/PromptWizard_300_Free_Prompts.pdf"
if not FREE_PROMPTS_URL and Path(STATIC_DIR, "PromptWizard_300_Free_Prompts.pdf").exists():
    FREE_PROMPTS_URL = LOCAL_FREE_PDF

print(f"[PromptWizard] STATIC_DIR={STATIC_DIR}")
print(f"[PromptWizard] FREE_PROMPTS_URL={FREE_PROMPTS_URL or '(none)'}")

# -------- TIME HELPERS --------
def _tz():
    if ZoneInfo:
        try:
            return ZoneInfo(APP_TZ_STR)
        except Exception:
            pass
    return timezone(timedelta(hours=8))  # Manila fallback

TZ = _tz()

def now_tz() -> datetime:
    return datetime.now(TZ)

def today_str() -> str:
    return now_tz().strftime("%Y-%m-%d")

def next_midnight_tz_iso() -> str:
    n = now_tz()
    tmr = (n + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tmr.isoformat()

# -------- ABSOLUTE URL HELPER --------
def absolute_url(request: Request, maybe_path: str) -> str:
    """If starts with '/', make it absolute with this server's base URL."""
    if not maybe_path:
        return ""
    if maybe_path.startswith("/"):
        return urljoin(str(request.base_url), maybe_path.lstrip("/"))
    return maybe_path

# -------- DB INIT --------
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
CREATE TABLE IF NOT EXISTS leads (
  email TEXT PRIMARY KEY,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
init_db()

# -------- HELPERS --------
def _get_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else req.client.host)

# FREE meter
def can_use_and_inc(ip: str) -> bool:
    day = today_str()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute("SELECT count FROM usage_counts WHERE ip=? AND day=?", (ip, day)).fetchone()
    count = row[0] if row else 0
    if count >= DAILY_FREE_LIMIT:
        conn.close()
        return False
    if row:
        cur.execute("UPDATE usage_counts SET count=count+1 WHERE ip=? AND day=?", (ip, day))
    else:
        cur.execute("INSERT INTO usage_counts (ip, day, count) VALUES (?, ?, 1)", (ip, day))
    conn.commit(); conn.close()
    return True

def get_usage_status(ip: str):
    day = today_str()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT count FROM usage_counts WHERE ip=? AND day=?", (ip, day)).fetchone()
    conn.close()
    count = row[0] if row else 0
    return {"count": count, "limit": DAILY_FREE_LIMIT, "remaining": max(DAILY_FREE_LIMIT-count, 0), "reset_at": next_midnight_tz_iso()}

# PAID wallet
def wallet_get(ip: str):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM credit_wallets WHERE ip=?", (ip,)).fetchone()
    if not row:
        init_bal = DAILY_RESET_BALANCE if DAILY_RESET_BALANCE > 0 else max(INITIAL_CREDITS, 0)
        conn.execute("INSERT INTO credit_wallets (ip,balance,last_grant_day,timezone) VALUES (?,?,?,?)",
                     (ip, init_bal, today_str(), APP_TZ_STR))
        conn.commit()
        row = conn.execute("SELECT * FROM credit_wallets WHERE ip=?", (ip,)).fetchone()
    conn.close()
    return dict(row)

def wallet_grant_if_needed(ip: str):
    w = wallet_get(ip)
    last = w.get("last_grant_day") or today_str()
    today = today_str()
    if today <= last:
        return
    if DAILY_RESET_BALANCE > 0:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE credit_wallets SET balance=?, last_grant_day=? WHERE ip=?",
                     (DAILY_RESET_BALANCE, today, ip))
        conn.commit(); conn.close()
        return
    if DAILY_GRANT > 0:
        new_bal = min(w["balance"] + DAILY_GRANT, MAX_BALANCE)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE credit_wallets SET balance=?, last_grant_day=? WHERE ip=?",
                     (new_bal, today, ip))
        conn.commit(); conn.close()

def wallet_spend(ip: str, n: int = 1) -> bool:
    wallet_grant_if_needed(ip)
    w = wallet_get(ip)
    if w["balance"] < n:
        return False
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE credit_wallets SET balance=balance-? WHERE ip=?", (n, ip))
    conn.commit(); conn.close()
    return True

def wallet_status(ip: str):
    wallet_grant_if_needed(ip)
    w = wallet_get(ip)
    return {"balance": w["balance"], "max_balance": MAX_BALANCE, "reset_at": next_midnight_tz_iso(),
            "reset_to": DAILY_RESET_BALANCE if DAILY_RESET_BALANCE > 0 else None}

# -------- ESP (EmailOctopus) helper --------
async def add_to_emailoctopus(email: str, first_name: str = "", last_name: str = "") -> Tuple[bool, Optional[str]]:
    """
    Create/update a contact in EmailOctopus list.
    Returns (ok, error_message_or_None)
    """
    if ESP_PROVIDER != "emailoctopus":
        return True, None  # ESP disabled; treat as OK
    if not (EO_API_KEY and EO_LIST_ID):
        return False, "Missing EMAILOCTOPUS_API_KEY or EMAILOCTOPUS_LIST_ID"

    url = f"https://emailoctopus.com/api/1.6/lists/{EO_LIST_ID}/contacts"
    data = {
        "api_key": EO_API_KEY,
        "email_address": email,
        "status": EO_STATUS,  # SUBSCRIBED or PENDING
    }
    if first_name:
        data["fields[FirstName]"] = first_name
    if last_name:
        data["fields[LastName]"] = last_name
    for i, tag in enumerate(EO_TAGS):
        data[f"tags[{i}]"] = tag

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, data=data)
        if r.status_code in (200, 201):
            return True, None

        # Parse error; treat "already exists" as success.
        msg = ""
        try:
            js = r.json()
            msg = js.get("error", {}).get("message") or r.text
        except Exception:
            msg = r.text

        if re.search(r"already exists", (msg or ""), re.I):
            return True, None

        print("EmailOctopus error:", r.status_code, msg)
        return False, msg
    except Exception as e:
        return False, str(e)

# -------- FASTAPI --------
app = FastAPI(title=APP_NAME)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

# -------- MODELS --------
class BuildPayload(BaseModel):
    audience: str = ""
    tone: str = "Friendly"
    goal: str = "content"
    platform: Optional[str] = None
    language: Optional[str] = "English"
    constraints: Optional[str] = None
    brand: Optional[str] = None
    details: Optional[str] = None

class EnhancePayload(BaseModel):
    prompt: str
    mode: Optional[str] = "medium"  # short|medium|detailed

# -------- ROUTES --------
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
            "capture_required": CAPTURE_REQUIRED,
            "affiliate_note": AFFILIATE_NOTE,
            "freebie_note": FREEBIE_NOTE,
            "ltd_price_text": LTD_PRICE_TEXT,
            "gtm_id": GTM_ID,
            "fb_pixel_id": FB_PIXEL_ID,
            "gumroad_checkout_url": GUMROAD_CHECKOUT_URL,
            "free_prompts_url": FREE_PROMPTS_URL,
            "build_id": int(datetime.now().timestamp()),
        },
    )

@app.get("/free", response_class=HTMLResponse)
async def free_redirect(request: Request):
    if FREE_PROMPTS_URL:
        return RedirectResponse(absolute_url(request, FREE_PROMPTS_URL), status_code=302)
    html = f"""
    <!doctype html><html><head>
      <meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>{APP_NAME} — Free Prompts</title>
      <link rel="stylesheet" href="/static/styles.css" />
    </head><body style="padding:20px">
      <div class="panel" style="max-width:720px;margin:0 auto">
        <h2>🎁 300 Free Prompts</h2>
        <p>Wala pang <code>FREE_PROMPTS_URL</code> sa iyong <code>.env</code>.</p>
        <p>Maglagay ng direct link (Google Drive/Dropbox/Gumroad free file, etc.):</p>
        <pre class="fav-pre">FREE_PROMPTS_URL=https://example.com/your/free/prompts.zip</pre>
        <p>Pag na-set mo na, i-refresh ang page at gagana ang CTA.</p>
        <a href="/" class="btn ghost">← Back to app</a>
      </div>
    </body></html>
    """
    return HTMLResponse(html)

@app.get("/upgrade", response_class=HTMLResponse)
async def upgrade():
    if GUMROAD_CHECKOUT_URL:
        return RedirectResponse(GUMROAD_CHECKOUT_URL, status_code=302)
    html = f"""
    <!doctype html><html><head>
      <meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>{APP_NAME} — Upgrade</title>
      <link rel="stylesheet" href="/static/styles.css" />
    </head><body style="padding:20px">
      <div class="panel" style="max-width:720px;margin:0 auto">
        <h2>⬆️ Upgrade</h2>
        <p>Wala pang <code>GUMROAD_CHECKOUT_URL</code> sa iyong <code>.env</code>.</p>
        <p>Maglagay ng checkout link (Gumroad/Stripe/PayPal page):</p>
        <pre class="fav-pre">GUMROAD_CHECKOUT_URL=https://gum.co/your-product</pre>
        <a href="/" class="btn ghost">← Back to app</a>
      </div>
    </body></html>
    """
    return HTMLResponse(html)

# expose templates.json even if requested at root
@app.get("/templates.json")
async def get_templates_json():
    path = os.path.join(STATIC_DIR, "templates.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return JSONResponse(json.load(f))
        except Exception:
            pass
    return JSONResponse([
        {"title":"Sample Template","category":"General","preview":"You are an expert copywriter. Create a Facebook post about {{product}} for {{audience}}.",
         "fill":{"audience":"Filipino freelancers","tone":"Friendly","goal":"Facebook post","platform":"Facebook","language":"English","constraints":"Short, catchy, CTA","brand":"friendly"},
         "details":"Product: organic soap."}
    ])

# ---------- /build ----------
def _s(x): return "" if x is None else (x if isinstance(x, str) else str(x))

@app.post("/build")
async def build(request: Request):
    try:
        payload = None
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            payload = await request.json()
        elif "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
            form = await request.form()
            payload = dict(form)
        else:
            try:
                payload = await request.json()
            except Exception:
                try:
                    form = await request.form()
                    payload = dict(form)
                except Exception:
                    payload = {}

        audience    = _s((payload or {}).get("audience")).strip()
        tone        = _s((payload or {}).get("tone")).strip() or "Friendly"
        goal        = _s((payload or {}).get("goal")).strip() or "content"
        platform    = _s((payload or {}).get("platform")).strip()
        language    = _s((payload or {}).get("language")).strip() or "English"
        constraints = _s((payload or {}).get("constraints")).strip()
        brand       = _s((payload or {}).get("brand")).strip()
        details     = _s((payload or {}).get("details")).strip()

        lines = [
            f"You are an expert content creator. Create a {goal}.",
            f"Target audience: {audience}.",
            f"Tone: {tone}.",
            f"Language: {language}.",
        ]
        if platform:    lines.append(f"Platform: {platform}.")
        if brand:       lines.append(f"Brand voice: {brand}.")
        if details:     lines.append(f"Details: {details}.")
        if constraints: lines.append(f"Constraints: {constraints}.")
        lines.append("Provide 3 variants when possible.")
        detailed = "\n".join(lines)

        concise_lines = [
            f"TASK: Create 3 {goal} variants for {audience}.",
            f"TONE: {tone}. LANG: {language}.",
        ]
        if constraints: concise_lines.append(f"CONSTRAINTS: {constraints}")
        concise = "\n".join(concise_lines)

        return {"ok": True, "prompt": detailed, "concise": concise}

    except Exception as e:
        print("ERROR /build:", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# ---------- /enhance ----------
@app.post("/enhance")
async def enhance(payload: EnhancePayload, request: Request):
    ip = _get_ip(request)

    # Spend/limit first (consistent UX)
    if ROLLOVER_MODE:
        if not wallet_spend(ip, 1):
            return JSONResponse({"ok": False, "error": "No credits left.", "credits": wallet_status(ip)}, status_code=402)
    else:
        if not can_use_and_inc(ip):
            return JSONResponse({"ok": False, "error": "Free limit reached.", "usage": get_usage_status(ip)}, status_code=429)

    # Offline fallback if GPT not available
    if not ENABLE_GPT or not OPENAI_API_KEY:
        prefix = {
            "short": "Tighten & polish (short):",
            "detailed": "Restructure with numbered steps and clarity:",
        }.get((payload.mode or "medium").lower(), "Polish:")
        improved = f"{prefix}\n\n{payload.prompt}".strip()
        meter = wallet_status(ip) if ROLLOVER_MODE else get_usage_status(ip)
        return {"ok": True, "prompt": improved, **({"credits": meter} if ROLLOVER_MODE else {"usage": meter})}

    mode_text = {
        "short":   "You refine prompt instructions briefly. Be concise, keep structure tight. Output only the improved prompt.",
        "medium":  "You refine prompt instructions. Improve clarity and structure. Output only the improved prompt.",
        "detailed":"You refine prompt instructions thoroughly. Add sections and explicit output formats if helpful. Output only the improved prompt.",
    }.get(payload.mode, "You refine prompt instructions. Output only the improved prompt.")

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    if OPENAI_ORG: headers["OpenAI-Organization"] = OPENAI_ORG

    try:
        async with httpx.AsyncClient(timeout=30, base_url=OPENAI_BASE_URL, headers=headers) as client:
            r = await client.post("/chat/completions", json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": mode_text},
                    {"role": "user", "content": payload.prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 700,
            })
            r.raise_for_status()
            data = r.json()
            out = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return {"ok": True, "prompt": out, **({"credits": wallet_status(ip)} if ROLLOVER_MODE else {"usage": get_usage_status(ip)})}
    except Exception as e:
        # Graceful fallback (still counts)
        improved = f"[fallback] {payload.prompt}".strip()
        meter = wallet_status(ip) if ROLLOVER_MODE else get_usage_status(ip)
        return {"ok": True, "prompt": improved, **({"credits": meter} if ROLLOVER_MODE else {"usage": meter})}

# ---------- save/history ----------
@app.post("/save")
async def save(item: Dict[str, Any]):
    text = (item or {}).get("prompt", "").strip()
    if not text:
        return {"ok": False, "error": "Empty prompt."}
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO history (prompt, created_at) VALUES (?, ?)", (text, now_tz().strftime("%Y-%m-%d %H:%M")))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/history")
async def history():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT prompt, created_at FROM history ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}

# ---------- meters/health ----------
@app.get("/usage_today")
async def usage_today(request: Request):
    return get_usage_status(_get_ip(request))

@app.get("/credits_status")
async def credits_status(request: Request):
    return wallet_status(_get_ip(request))

@app.get("/health")
async def health():
    return {
        "ok": True,
        "mode": "paid" if ROLLOVER_MODE else "free",
        "app_name": APP_NAME,
        "gpt_enabled": ENABLE_GPT,
        "api_key_present": bool(OPENAI_API_KEY),
        "model": OPENAI_MODEL
    }

# ---------- Export PDF ----------
@app.post("/export_pdf")
async def export_pdf(request: Request):
    try:
        data = await request.json()
        items = data.get("items", [])
        if not isinstance(items, list) or not items:
            return JSONResponse({"ok": False, "error": "No items to export."}, status_code=400)

        text = "\n\n---\n\n".join((str(x) or "") for x in items).strip() or "(empty)"
        # Try ReportLab; fallback to TXT if not available
        try:
            from reportlab.pdfgen import canvas as rcanvas
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm

            buf = io.BytesIO()
            c = rcanvas.Canvas(buf, pagesize=A4)
            width, height = A4
            left = 20 * mm
            top = height - 20 * mm
            line_h = 6 * mm

            def wrap_lines(block):
                from textwrap import wrap
                out = []
                for para in (block or "").splitlines():
                    out += (wrap(para.replace("\t", "    "), 95) or [""])
                return out

            c.setTitle("Prompt Wizard — Export")
            c.setFont("Helvetica-Bold", 14)
            c.drawString(left, top, "Prompt Wizard — Export")
            y = top - 10 * mm
            c.setFont("Helvetica", 10)
            c.drawString(left, y, f"Exported: {now_tz().strftime('%Y-%m-%d %H:%M')}")
            y -= 8 * mm

            idx = 1
            for block in text.split("\n\n---\n\n"):
                b = (block or "").strip()
                if not b:
                    continue
                c.setFont("Helvetica-Bold", 11)
                c.drawString(left, y, f"{idx}.")
                y -= line_h
                c.setFont("Helvetica", 10)
                for line in wrap_lines(b):
                    if y <= 20 * mm:
                        c.showPage()
                        y = height - 20 * mm
                        c.setFont("Helvetica", 10)
                    c.drawString(left, y, line); y -= line_h
                y -= 6 * mm
                idx += 1

            c.showPage(); c.save()
            buf.seek(0)
            return StreamingResponse(buf, media_type="application/pdf",
                                     headers={"Content-Disposition": 'attachment; filename="promptwizard_export.pdf"'})
        except Exception:
            return PlainTextResponse(text, media_type="text/plain")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# ---------- Email Signup (optional) ----------
@app.post("/api/signup")
async def api_signup(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    email = (data.get("email") or "").strip().lower()
    first_name = (data.get("first_name") or "").strip()
    last_name  = (data.get("last_name") or "").strip()
    source = (data.get("source") or "free").strip()

    if not email:
        return JSONResponse({"ok": False, "error": "Email required"}, status_code=400)

    # Save to local leads table
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO leads(email, source) VALUES(?,?)", (email, source))
    conn.commit()
    conn.close()

    # Push to EmailOctopus (if configured)
    ok, err = await add_to_emailoctopus(email, first_name, last_name)
    if not ok:
        # Don’t block UX; just log the error.
        print("EmailOctopus push failed:", err)

    # Optional: SMTP send of link (if configured)
    if SMTP_HOST and SMTP_EMAIL and SMTP_PASS and FREE_PROMPTS_URL:
        try:
            msg = MIMEText(
                f"Hi!\n\nThanks for signing up to PromptWizard Free.\n\n"
                f"Download your 300 Free Prompts here:\n{absolute_url(request, FREE_PROMPTS_URL)}\n\n"
                f"Enjoy! — PromptWizard"
            )
            msg["Subject"] = "🎁 Your 300 Free Prompts"
            msg["From"] = SMTP_EMAIL
            msg["To"] = email
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_EMAIL, SMTP_PASS)
                s.send_message(msg)
        except Exception as e:
            print("SMTP error:", e)

    # Always return an absolute link for instant UX
    return {"ok": True, "download_url": absolute_url(request, FREE_PROMPTS_URL)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("prompt_wizard:app", host="127.0.0.1", port=8888, reload=True)



































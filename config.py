"""
DON v3.0 — configuration.

Reads settings from environment variables / a local .env file.
The only REQUIRED setting is GEMINI_API_KEY (get one free at
https://aistudio.google.com/apikey). Everything else has sane defaults.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
for _d in (DATA_DIR, SCREENSHOTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SQLITE_PATH = DATA_DIR / "don3.db"

# ---------------- Gemini (the brain) ----------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Fast + free model. "gemini-flash-lite-latest" has the highest availability and lowest latency.
# Override in .env with DON_GEMINI_MODEL if you prefer a different one.
GEMINI_MODEL = os.getenv("DON_GEMINI_MODEL", "gemini-flash-lite-latest")

# Speed/quality knobs.
# Lower max tokens = faster, snappier replies. Raise for longer answers.
GEMINI_MAX_TOKENS = int(os.getenv("DON_MAX_TOKENS", "800"))
GEMINI_TEMPERATURE = float(os.getenv("DON_TEMPERATURE", "0.7"))

SYSTEM_PROMPT = (
    "You are DON, a highly capable personal AI assistant, like JARVIS from Iron Man. "
    "Personality: sharp, witty, confident, loyal, with a polite slightly British tone. "
    "Address the user as 'sir'. Be helpful and proactive.\n\n"
    "RESPONSE STYLE: Be CONCISE by default — answer in 1-3 sentences unless the "
    "user asks for detail or the topic genuinely needs it. Get to the point fast. "
    "Don't pad with filler. If you can answer directly, do so immediately.\n\n"
    "TOOLS: You can search the live web, fetch articles, get weather, open apps/websites, "
    "take screenshots, analyze the user's active screen with AI vision, control system volume/media, "
    "read/write clipboard, and set reminders. Use a tool ONLY when needed (e.g. for current "
    "events, real-time data, or an action). For general knowledge you already have, "
    "answer directly without tools — it's faster. When you use search results, "
    "ground your answer in them. Never invent facts; if unsure, say so."
)

# ---------------- Web server ----------------
SERVER_HOST = os.getenv("DON_SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("DON_SERVER_PORT", "8000"))
AUTO_OPEN_BROWSER = os.getenv("DON_AUTO_OPEN_BROWSER", "true").lower() == "true"

# ---------------- Skills ----------------
WEATHER_LAT = float(os.getenv("DON_WEATHER_LAT", "12.9716"))
WEATHER_LON = float(os.getenv("DON_WEATHER_LON", "77.5946"))

THEME = {
    "bg": "#02070A",              # Midnight Black
    "blue": "#0297DE",            # Electric Blue
    "orange": "#FC734D",          # Cantaloupe Orange
    "text": "#e0e0e0",
}

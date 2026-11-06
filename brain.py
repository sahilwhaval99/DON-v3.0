"""
DON v3.0 brain — Google Gemini via the NEW `google-genai` SDK.

Google deprecated the old `google-generativeai` package; this uses the current
`google-genai` client, which has clean automatic function-calling: you pass
plain Python functions as `tools` and the SDK handles the call/response loop
for you (automatic function calling), so DON can search the web, open apps, etc.

Defensive: if the key or library is missing, chat() returns a clear setup
message instead of crashing.
"""
from __future__ import annotations

import config


class Brain:
    def __init__(self, tools: dict | None = None, memory=None) -> None:
        # tools: {name: callable}; the callables' signatures + docstrings are
        # what the SDK shows to Gemini, so they must be well-typed/documented.
        self.tools = tools or {}
        self.memory = memory
        self._client = None
        self._types = None
        self._session = None  # persistent chat session (reused for speed)
        self.model = config.GEMINI_MODEL  # may be replaced by _resolve_model()
        self._init()

    def _init(self) -> None:
        if not config.GEMINI_API_KEY:
            print("[brain] GEMINI_API_KEY not set. Add it to your .env file. "
                  "Get a free key at https://aistudio.google.com/apikey")
            return
        try:
            from google import genai
            from google.genai import types

            self._client = genai.Client(api_key=config.GEMINI_API_KEY)
            self._types = types
            # Resolve a model that actually works with this key/SDK version.
            self.model = self._resolve_model(config.GEMINI_MODEL)
            print(f"[brain] Using model: {self.model}")
        except Exception as exc:
            print(f"[brain] Gemini unavailable ({exc}). "
                  f"Install: pip install google-genai")
            self._client = None

    def _resolve_model(self, preferred: str) -> str:
        """Return a usable model name that actually works for this API key."""
        try:
            usable = []
            for m in self._client.models.list():
                name = getattr(m, "name", "") or ""
                actions = (getattr(m, "supported_actions", None)
                           or getattr(m, "supported_generation_methods", None) or [])
                if actions and "generateContent" not in actions:
                    continue
                usable.append(name.split("/")[-1])  # store short name e.g. 'gemini-flash-lite-latest'

            # 1. Exact match with preferred
            pref_short = preferred.split("/")[-1]
            if pref_short in usable:
                return pref_short

            # 2. Modern working models priority list
            priority_models = [
                "gemini-flash-lite-latest",
                "gemini-3.5-flash-lite",
                "gemini-3.8-flash",
                "gemini-flash-latest",
                "gemini-pro-latest"
            ]
            for pm in priority_models:
                if pm in usable:
                    return pm

            # 3. Any non-image, non-tts flash model
            for u in usable:
                if "flash" in u and not any(x in u for x in ("tts", "image", "audio", "vision", "preview")):
                    return u

            if usable:
                return usable[0]
        except Exception as exc:
            print(f"[brain] Could not list models ({exc}); using preferred as-is.")
        return preferred

    @property
    def available(self) -> bool:
        return self._client is not None

    def _contents(self, user_text: str) -> str:
        """Build the prompt, prepending a little recent history for context."""
        if self.memory is None:
            return user_text
        try:
            turns = self.memory.recent_turns(limit=6)
            if not turns:
                return user_text
            history_lines = []
            for t in turns:
                if t.get("user"):
                    history_lines.append(f"User: {t['user']}")
                if t.get("assistant"):
                    history_lines.append(f"DON: {t['assistant']}")
            history = "\n".join(history_lines)
            return f"(Recent conversation:\n{history}\n)\nUser: {user_text}"
        except Exception:
            return user_text

    def _ensure_session(self):
        """Create ONE persistent chat session and reuse it (big speed win).

        Reusing the session means Gemini keeps the conversation context itself,
        so we don't resend the whole history on every message.
        """
        if self._session is not None:
            return self._session
        types = self._types
        config_obj = types.GenerateContentConfig(
            system_instruction=config.SYSTEM_PROMPT,
            temperature=config.GEMINI_TEMPERATURE,
            max_output_tokens=config.GEMINI_MAX_TOKENS,
            tools=[types.Tool(function_declarations=self._declarations())]
            if self.tools else None,
        )
        self._session = self._client.chats.create(model=self.model, config=config_obj)
        return self._session

    def chat_stream(self, user_text: str):
        """Yield DON's reply in chunks as it's generated (feels much faster).

        Tools are NOT used in streaming mode for simple speed; if the model
        wants a tool it will still work via the non-streaming chat() path. We
        keep streaming for plain conversation, which is the common, latency-
        sensitive case.
        """
        if not self._client:
            yield ("My brain isn't connected yet. Add your GEMINI_API_KEY to .env "
                   "and restart me.")
            return
        try:
            chat = self._ensure_session()
            stream = chat.send_message_stream(user_text)
            got_any = False
            for chunk in stream:
                piece = getattr(chunk, "text", None)
                if piece:
                    got_any = True
                    yield piece
            if not got_any:
                yield "Done, sir."
        except Exception as exc:
            self._session = None
            yield self._friendly_error(exc)

    def chat(self, user_text: str) -> str:
        """Return DON's reply, using tools automatically. Never raises."""
        if not self._client:
            return ("My brain isn't connected yet. Please add your free Gemini API "
                    "key to the .env file (GEMINI_API_KEY=...), then restart me. "
                    "Get one at https://aistudio.google.com/apikey.")
        types = self._types
        try:
            chat = self._ensure_session()
            # Persistent session already holds history, so just send the message.
            resp = self._send_with_retry(chat, user_text)

            # Handle up to a few rounds of tool calls.
            for _ in range(5):
                calls = self._function_calls(resp)
                if not calls:
                    break
                responses = []
                for name, args in calls:
                    fn = self.tools.get(name)
                    try:
                        result = fn(**args) if fn else f"(no tool '{name}')"
                    except Exception as tool_exc:
                        result = f"(tool '{name}' error: {tool_exc})"
                    responses.append(types.Part.from_function_response(
                        name=name, response={"result": str(result)}))
                resp = self._send_with_retry(chat, responses)

            text = (getattr(resp, "text", None) or "").strip()
            return text or "Done, sir."
        except Exception as exc:
            # If the session broke, drop it so the next call rebuilds cleanly.
            self._session = None
            return self._friendly_error(exc)

    # -- function-calling helpers -------------------------------------- #
    def _declarations(self) -> list:
        """Describe each tool to Gemini (name, description, params).

        Uses plain dicts for the schema, which the SDK accepts and which avoids
        depending on exact helper-class names across SDK versions.
        """
        types = self._types
        specs = {
            "web_search": ("Search the live internet for current info, news, "
                           "prices, or facts.", {"query": "The search query"}),
            "fetch_webpage": ("Fetch the actual text content of a URL or article.",
                              {"url": "The full website or article URL"}),
            "get_weather": ("Get current weather for a location.",
                            {"location": "City name (optional)"}),
            "open_app": ("Open an app or website on the user's PC.",
                         {"name": "e.g. notepad, calculator, youtube"}),
            "take_screenshot": ("Capture a screenshot of the user's screen.", {}),
            "analyze_screen": ("Take a screenshot of the screen and analyze it with AI vision.",
                              {"prompt": "What to look for or question about the screen"}),
            "clipboard_action": ("Read from or write to the system clipboard.",
                                {"action": "'read' or 'write'", "text": "text to write if action is write"}),
            "system_control": ("Control volume, media playback, or windows.",
                              {"action": "mute, volume_up, volume_down, play_pause, next_track, prev_track, or minimize_all"}),
            "add_reminder": ("Save a reminder for the user.",
                             {"text": "reminder text", "when": "e.g. 5pm, in 10 min"}),
        }
        decls = []
        for name, (desc, params) in specs.items():
            if name not in self.tools:
                continue
            props = {k: types.Schema(type="STRING", description=v)
                     for k, v in params.items()}
            decls.append(types.FunctionDeclaration(
                name=name, description=desc,
                parameters=types.Schema(type="OBJECT", properties=props) if props else None,
            ))
        return decls

    @staticmethod
    def _function_calls(resp) -> list:
        """Extract (name, args) tool calls from a response, if any."""
        calls = []
        try:
            for cand in resp.candidates:
                for part in cand.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and fc.name:
                        calls.append((fc.name, dict(fc.args or {})))
        except Exception:
            pass
        return calls

    def _send_with_retry(self, chat, message):
        """Send a message, retrying transient 503/429 with smart backoff.

        For 429 (rate limit), Google usually tells us how long to wait via a
        'retry_delay'/'retryDelay' field — we honour it. We retry more times and
        wait longer than before so the user almost never sees a rate-limit note.
        """
        import time
        import re as _re

        last = None
        max_attempts = 6
        for attempt in range(max_attempts):
            try:
                return chat.send_message(message)
            except Exception as exc:
                last = exc
                m = str(exc)
                is_429 = "429" in m or "RESOURCE_EXHAUSTED" in m
                is_503 = "503" in m or "UNAVAILABLE" in m or "overloaded" in m.lower()
                if not (is_429 or is_503) or attempt == max_attempts - 1:
                    raise

                # Honour Google's suggested retry delay if present.
                delay = None
                match = _re.search(r"retry.?delay['\"]?\s*[:=]\s*['\"]?(\d+)", m, _re.I)
                if match:
                    delay = float(match.group(1))
                if delay is None:
                    match = _re.search(r"(\d+(?:\.\d+)?)\s*s(?:econds)?", m)
                    if match and is_429:
                        delay = float(match.group(1))
                if delay is None:
                    # Exponential backoff: 2, 4, 8, 16, 30 (capped) seconds.
                    delay = min(2 ** (attempt + 1), 30)
                delay = min(max(delay, 1.0), 45.0)
                time.sleep(delay)
        raise last

    def _friendly_error(self, exc) -> str:
        msg = str(exc)
        if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
            return ("Google's servers are momentarily busy. Please try that again "
                    "in a few seconds, sir.")
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            return "I've hit a brief rate limit. Give me a few seconds, sir."
        if "NOT_FOUND" in msg or "not found" in msg or "404" in msg:
            return (f"The model '{self.model}' isn't available on your key. "
                    f"{self._suggest_models()}")
        return (f"I hit a problem thinking about that: {exc}. "
                f"(If this mentions the API key, double-check it in your .env.)")

    def _suggest_models(self) -> str:
        """List models the key can actually use — so we never guess blindly."""
        try:
            names = []
            for m in self._client.models.list():
                actions = getattr(m, "supported_actions", None) or \
                          getattr(m, "supported_generation_methods", []) or []
                name = getattr(m, "name", "")
                if "generateContent" in actions or not actions:
                    short = name.split("/")[-1]
                    if "flash" in short or "pro" in short:
                        names.append(short)
            names = sorted(set(names))[:6]
            if names:
                return ("Try setting DON_GEMINI_MODEL in your .env to one of: "
                        + ", ".join(names))
        except Exception:
            pass
        return ("Set DON_GEMINI_MODEL in your .env to a current model, e.g. "
                "gemini-2.0-flash or gemini-2.5-flash.")


if __name__ == "__main__":
    b = Brain()
    print("Gemini available:", b.available)
    if b.available:
        print(b.chat("In one sentence, who are you?"))

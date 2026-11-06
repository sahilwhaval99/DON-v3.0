"""
DON v3.0 assistant — wires the Gemini brain to the tools and memory.

Single entry point: Assistant.handle(text) -> str. Used by both the CLI test
(test_brain.py) and the web server, so behaviour is identical everywhere.
"""
from __future__ import annotations

import traceback

import config
from brain import Brain
from memory import Memory
import tools as T


class Assistant:
    def __init__(self) -> None:
        self.memory = Memory()

        # Register the tools DON can use. add_reminder is bound to memory.
        self.tools = {
            "web_search": T.web_search,
            "fetch_webpage": T.fetch_webpage,
            "get_weather": T.get_weather,
            "open_app": T.open_app,
            "take_screenshot": T.take_screenshot,
            "analyze_screen": T.analyze_screen,
            "clipboard_action": T.clipboard_action,
            "system_control": T.system_control,
            "add_reminder": T.make_reminder_tool(self.memory),
        }
        self.brain = Brain(tools=self.tools, memory=self.memory)

    @property
    def brain_ready(self) -> bool:
        return self.brain.available

    # Keywords that suggest a tool/action is needed (use non-stream tool path).
    _TOOL_HINTS = (
        "search", "google", "look up", "news", "latest", "weather", "temperature",
        "open ", "launch", "screenshot", "remind", "reminder", "price", "stock",
        "who won", "today", "current", "right now",
        "clipboard", "mute", "volume", "play", "pause", "screen", "fetch",
    )

    def _needs_tool(self, text: str) -> bool:
        t = text.lower()
        return any(h in t for h in self._TOOL_HINTS)

    def _fast_path(self, text: str):
        """Handle common commands DIRECTLY without calling Gemini.

        This makes them instant AND avoids using any API quota (no rate limit).
        Returns a reply string if handled, else None.
        """
        import re
        import datetime as _dt

        t = text.strip().lower()

        # open <something>
        m = re.match(r"^(?:hey )?(?:don[,\s]*)?(?:please )?open (?:up )?(.+)$", t)
        if m:
            target = m.group(1).strip().rstrip("?.!")
            return T.open_app(target)

        # time / date
        if re.search(r"\b(what.?s |what is )?the time\b", t) or t in ("time", "what time is it"):
            return "It's " + _dt.datetime.now().strftime("%I:%M %p").lstrip("0") + ", sir."
        if re.search(r"\b(what.?s |what is )?(the |today.?s )?date\b", t) or t == "date":
            return "Today is " + _dt.datetime.now().strftime("%A, %d %B %Y") + ", sir."

        # screenshot
        if "screenshot" in t or "screen shot" in t:
            return T.take_screenshot()

        return None

    def handle(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "I'm listening."
        try:
            fast = self._fast_path(text)
            if fast is not None:
                self.memory.log_turn(text, fast)
                return fast
            reply = self.brain.chat(text)
            self.memory.log_turn(text, reply)
            return reply
        except Exception as exc:
            traceback.print_exc()
            return f"Apologies sir, I hit a problem: {exc}"

    def handle_stream(self, text: str):
        """Yield the reply in chunks for fast, live output.

        For tool-needing requests we fall back to the full (non-stream) path so
        web search / actions still work, then yield the whole answer at once.
        For plain conversation we stream token-by-token (feels instant).
        """
        text = (text or "").strip()
        if not text:
            yield "I'm listening."
            return
        try:
            # Instant, no-API commands first (open apps, time, date, screenshot).
            fast = self._fast_path(text)
            if fast is not None:
                self.memory.log_turn(text, fast)
                yield fast
                return
            if self._needs_tool(text):
                reply = self.brain.chat(text)
                self.memory.log_turn(text, reply)
                yield reply
                return
            collected = []
            for piece in self.brain.chat_stream(text):
                collected.append(piece)
                yield piece
            self.memory.log_turn(text, "".join(collected))
        except Exception as exc:
            traceback.print_exc()
            yield f"Apologies sir, I hit a problem: {exc}"


if __name__ == "__main__":
    a = Assistant()
    print("Brain ready:", a.brain_ready)

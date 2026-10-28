"""Client for the ViviPet body (adapter on :18765): speech, poses and facial expressions."""
from __future__ import annotations

import logging
import re
import threading
import time

import requests

log = logging.getLogger("pet")

# Emotion vocabulary the LLM can use -> (body action, facial expression).
# Actions are ViviPet adapter actions; expressions map to the character's face presets.
EMOTIONS: dict[str, tuple[str | None, str | None]] = {
    "happy": ("happy", "happy"),
    "excited": ("success", "happy"),
    "proud": ("success", "smile"),
    "love": ("doubleClicked", "shy"),
    "shy": (None, "shy"),
    "thinking": ("thinking", None),
    "curious": ("searching", "focused"),
    "surprised": ("surprised", "surprised"),
    "confused": ("confused", "confused"),
    "angry": ("angry", "angry"),
    "sad": (None, "sad"),
    "worried": ("error", "worried"),
    "sleepy": ("sleep", None),
    "calm": (None, "smile"),
    "speaking": (None, None),
    "neutral": (None, None),
    # accepted aliases
    "success": ("success", "happy"),
    "error": ("error", "worried"),
}

# Pose shown while a tool runs, by tool name.
TOOL_ACTIONS = {
    "web_search": "searching", "youtube": "searching", "open_url": "searching",
    "look_at_screen": "reading", "openclaw_task": "terminal", "open_app": "coding",
    "media": "coding", "iot_control": "coding", "remember": "thinking",
    "learn_shortcut": "thinking", "forget": "thinking", "set_behavior": "thinking",
}

_TAG = re.compile(r"\[(\w+)\]")
CHARS_PER_SEC = 14.0  # approximate Kokoro speaking rate at speed 1.0


def parse_segments(text: str) -> list[tuple[str | None, str]]:
    """'[happy] Yay! [worried] But it's late.' -> [('happy','Yay!'), ('worried',"But it's late.")]
    Unknown tags are dropped from the spoken text."""
    segments: list[tuple[str | None, str]] = []
    emotion: str | None = None
    pos = 0
    for m in _TAG.finditer(text or ""):
        chunk = text[pos:m.start()].strip()
        if chunk:
            segments.append((emotion, chunk))
        tag = m.group(1).lower()
        if tag in EMOTIONS:
            emotion = tag
        pos = m.end()
    tail = (text or "")[pos:].strip()
    if tail:
        segments.append((emotion, tail))
    return segments


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", text or "")).strip()


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"https?://\S+", "a link", text)
    return re.sub(r"\s+", " ", text).strip()


class Pet:
    def __init__(self, cfg: dict):
        self.url = cfg["adapter_url"].rstrip("/")
        self.tts = cfg.get("tts", True)
        self.voice = cfg.get("voice")
        self._performance = 0  # bumps on every new utterance so stale timers stop

    def _post(self, path: str, payload: dict) -> bool:
        try:
            requests.post(f"{self.url}{path}", json=payload, timeout=3)
            return True
        except requests.RequestException as e:
            log.debug("pet unreachable: %s", e)
            return False

    def alive(self) -> bool:
        try:
            return requests.get(f"{self.url}/health", timeout=2).ok
        except requests.RequestException:
            return False

    def state(self, phase: str, kind: str | None = None) -> None:
        self._post("/adapter", {"agent": "companion", "phase": phase, **({"kind": kind} if kind else {})})

    def release(self) -> None:
        """End this agent's adapter sessions (they otherwise hold a pose by priority)."""
        # phase "idle" maps to action "idle", which the session manager treats as a release
        # ("session:end" would also release, but plays a happy hop).
        self._post("/adapter", {"agent": "companion", "phase": "idle"})

    def act(self, action: str) -> None:
        """Play a body pose directly (thinking, searching, sleep, wake...)."""
        self._post("/adapter/action", {"action": action})

    def express(self, expression: str | None) -> None:
        self._post("/adapter/action", {"expression": expression or "reset"})

    def tool(self, tool_name: str) -> None:
        self.act(TOOL_ACTIONS.get(tool_name, "thinking"))

    def say(self, text: str, default_emotion: str | None = None) -> None:
        """Speak text that may contain several [emotion] tags; poses/expressions change in time with speech."""
        segments = parse_segments(text)
        if not segments:
            return
        if segments[0][0] is None and default_emotion:
            segments[0] = (default_emotion, segments[0][1])
        spoken = clean_for_speech(" ".join(s for _, s in segments))
        if not spoken:
            return

        self._performance += 1
        perf = self._performance
        first_action, first_expr = EMOTIONS.get(segments[0][0] or "speaking", (None, None))
        # Release any held adapter session (e.g. "speaking") so it can't outrank the reaction pose.
        self.release()
        self.express(first_expr)
        tts = {"enabled": True, "model": "preset", **({"voice": self.voice} if self.voice else {})} if self.tts else False
        payload = {"agent": "companion", "phase": "message", "text": spoken, "tts": tts}
        if first_action:
            payload["action"] = first_action
        self._post("/adapter", payload)

        def choreograph():
            time.sleep(0.6)  # TTS start-up latency
            for i, (emotion, chunk) in enumerate(segments):
                if i > 0:
                    if self._performance != perf:
                        return
                    action, expr = EMOTIONS.get(emotion or "speaking", (None, None))
                    self.express(expr)
                    if action:
                        self.act(action)
                time.sleep(max(0.8, len(chunk) / CHARS_PER_SEC))
            time.sleep(1.5)
            if self._performance == perf:
                self.express(None)  # relax the face when done talking
                self.release()

        threading.Thread(target=choreograph, daemon=True).start()

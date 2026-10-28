"""Things the companion can do on the PC. Each public tool is exposed to the LLM via TOOLS."""
from __future__ import annotations

import ctypes
import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Callable

import requests

from .memory import Memory

log = logging.getLogger("actions")

BUILTIN_APPS = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe", "paint": "mspaint.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "files": "explorer.exe",
    "command prompt": "cmd.exe", "cmd": "cmd.exe", "powershell": "powershell.exe", "terminal": "wt.exe",
    "task manager": "taskmgr.exe", "settings": "ms-settings:", "control panel": "control.exe",
    "snipping tool": "ms-screenclip:", "vscode": "code", "vs code": "code", "visual studio code": "code",
}

MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF}

START_MENU_DIRS = [
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
    Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
    Path.home() / "Desktop",
    Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
]


def _fn(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required or list(props)}}}


S = {"type": "string"}

TOOLS = [
    _fn("open_url", "Open a website in the default browser.", {"url": S}),
    _fn("web_search", "Search the web in the browser.", {"query": S}),
    _fn("youtube", "Open YouTube. With play=true plays the top video for the query, else shows search results. "
                   "Empty query opens the YouTube homepage.",
        {"query": S, "play": {"type": "boolean"}}, ["query"]),
    _fn("open_app", "Launch an installed application by name (e.g. 'spotify', 'discord', 'steam', 'notepad').",
        {"name": S}),
    _fn("media", "Control media playback / volume.",
        {"action": {"type": "string", "enum": list(MEDIA_KEYS)}, "times": {"type": "integer"}}, ["action"]),
    _fn("look_at_screen", "Take a fresh look at the user's screen to answer a question about what is on it.",
        {"question": S}),
    _fn("openclaw_task", "Delegate a complex, multi-step computer task to the OpenClaw agent (file operations, "
                         "browsing and filling pages, running commands, research). Runs in the background and "
                         "reports back when done. Do NOT use for simple app/website opening.",
        {"task": S}),
    _fn("iot_control", "Control a smart-home device by name.",
        {"device": S, "action": {"type": "string", "enum": ["on", "off", "toggle", "set"]},
         "value": {"type": "string", "description": "optional, e.g. brightness 0-100"}}, ["device", "action"]),
    _fn("remember", "Save a durable fact about the user (name, likes, dislikes, job, routines, goals, people, "
                    "pets...). Use whenever the user tells you something worth remembering.",
        {"category": {"type": "string", "enum": ["identity", "preference", "dislike", "work", "routine", "goal",
                                                  "people", "health", "other"]},
         "key": {"type": "string", "description": "short snake_case label, e.g. favorite_game"}, "value": S}),
    _fn("forget", "Delete remembered facts matching some text, when the user asks you to forget something.",
        {"text": S}),
    _fn("learn_shortcut", "Teach yourself a named shortcut the user defines, e.g. 'my music' -> a URL, "
                          "'my editor' -> app 'code'.",
        {"name": S, "kind": {"type": "string", "enum": ["url", "app", "youtube"]}, "target": S}),
    _fn("set_behavior", "Adjust your own behaviour when the user asks (e.g. talk less, stop watching the screen).",
        {"setting": {"type": "string", "enum": ["chattiness", "screen_watch"]},
         "value": {"type": "string", "description": "chattiness: 0.0-1.0; screen_watch: true/false"}}),
]


class Actions:
    def __init__(self, cfg: dict, memory: Memory, notify: Callable[[str, str | None], None],
                 look: Callable[[str], str]):
        self.cfg = cfg
        self.memory = memory
        self.notify = notify          # notify(text, emotion) -> speak through the pet
        self.look = look
        self._start_menu: dict[str, Path] | None = None

    def dispatch(self, name: str, args: dict) -> str:
        fn = getattr(self, f"tool_{name}", None)
        if not fn:
            return f"Unknown tool {name}"
        try:
            return str(fn(**args))
        except TypeError as e:
            return f"Bad arguments for {name}: {e}"
        except Exception as e:  # report failures back to the model instead of crashing
            log.exception("tool %s failed", name)
            return f"{name} failed: {e}"

    # ---------- web ----------
    def tool_open_url(self, url: str) -> str:
        alias = self.memory.get_alias(url)
        if alias and alias["kind"] == "url":
            url = alias["target"]
        if not re.match(r"^[a-z]+://", url):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened {url}"

    def tool_web_search(self, query: str) -> str:
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
        return f"Searched the web for '{query}'"

    def tool_youtube(self, query: str = "", play: bool = False) -> str:
        alias = self.memory.get_alias(query) if query else None
        if alias and alias["kind"] in ("youtube", "url"):
            webbrowser.open(alias["target"])
            return f"Opened {alias['target']}"
        if not query:
            webbrowser.open("https://www.youtube.com")
            return "Opened YouTube"
        search = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
        if play:
            try:
                html = requests.get(search, timeout=8, headers={"User-Agent": "Mozilla/5.0",
                                                                "Accept-Language": "en-US,en"}).text
                m = re.search(r'"videoId":"([\w-]{11})"', html)
                if m:
                    webbrowser.open(f"https://www.youtube.com/watch?v={m.group(1)}")
                    return f"Playing top YouTube result for '{query}'"
            except requests.RequestException:
                pass
        webbrowser.open(search)
        return f"Opened YouTube search for '{query}'"

    # ---------- apps ----------
    def _scan_start_menu(self) -> dict[str, Path]:
        if self._start_menu is None:
            found: dict[str, Path] = {}
            for root in START_MENU_DIRS:
                if root.exists():
                    for p in root.rglob("*"):
                        if p.suffix.lower() in (".lnk", ".url", ".appref-ms") and "uninstall" not in p.stem.lower():
                            found.setdefault(p.stem.lower(), p)
            self._start_menu = found
        return self._start_menu

    def tool_open_app(self, name: str) -> str:
        key = name.strip().lower()
        alias = self.memory.get_alias(key)
        if alias:
            if alias["kind"] == "url":
                return self.tool_open_url(alias["target"])
            key = alias["target"].lower()
        if key in BUILTIN_APPS:
            target = BUILTIN_APPS[key]
            if target == "code" and shutil.which("code"):
                subprocess.Popen("code", shell=True)
            else:
                os.startfile(target)
            return f"Launched {name}"

        apps = self._scan_start_menu()
        match = apps.get(key)
        if not match:
            contains = [k for k in apps if key in k]
            close = contains or difflib.get_close_matches(key, apps.keys(), n=1, cutoff=0.6)
            match = apps[sorted(close, key=len)[0]] if close else None
        if match:
            os.startfile(str(match))
            self.memory.set_alias(name, "app", str(match))  # learn it for next time
            return f"Launched {match.stem}"
        exe = shutil.which(key) or shutil.which(key + ".exe")
        if exe:
            subprocess.Popen([exe])
            return f"Launched {exe}"
        if os.path.exists(name):
            os.startfile(name)
            return f"Opened {name}"
        return f"Could not find an app called '{name}'. Ask the user for the exact name or path, then use learn_shortcut."

    def tool_media(self, action: str, times: int = 1) -> str:
        vk = MEDIA_KEYS[action]
        for _ in range(max(1, min(int(times), 25))):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return f"Pressed {action}"

    def tool_look_at_screen(self, question: str) -> str:
        return self.look(question)

    # ---------- OpenClaw ----------
    def tool_openclaw_task(self, task: str) -> str:
        oc = self.cfg.get("openclaw", {})
        if not oc.get("enabled", True):
            return "OpenClaw is disabled in config."
        exe = shutil.which("openclaw.cmd") or shutil.which("openclaw")
        if not exe:
            return "OpenClaw is not installed."
        cmd = [exe, "agent", "--agent", oc.get("agent", "main"), "--session-key",
               oc.get("session_key", "agent:main:companion"), "--message", task, "--json",
               "--timeout", str(oc.get("timeout_sec", 300))]

        def run():
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=oc.get("timeout_sec", 300) + 30)
                result = _openclaw_reply(proc.stdout) or proc.stderr.strip()[-300:] or "no output"
                ok = proc.returncode == 0
            except subprocess.TimeoutExpired:
                result, ok = "it took too long and timed out", False
            log.info("openclaw done ok=%s: %.300s", ok, result)
            self.memory.add_message("assistant", f"(OpenClaw finished '{task}': {result[:500]})")
            self.notify(("Done! " if ok else "Hmm, that task had trouble: ") + result[:300],
                        "success" if ok else "error")

        threading.Thread(target=run, daemon=True).start()
        return "Task handed to OpenClaw; it is running in the background and you'll announce the result later."

    # ---------- IoT ----------
    def tool_iot_control(self, device: str, action: str, value: str = "") -> str:
        iot = self.cfg.get("iot", {})
        devices = iot.get("devices") or []
        if not devices:
            return "No smart-home devices are configured yet (add them under iot.devices in config.yaml)."
        names = {d["name"].lower(): d for d in devices}
        hit = names.get(device.lower()) or next(
            (names[n] for n in difflib.get_close_matches(device.lower(), names, n=1, cutoff=0.5)), None)
        if not hit:
            return f"Unknown device '{device}'. Known: {', '.join(names)}"

        if hit.get("driver") == "homeassistant":
            ha = iot.get("homeassistant", {})
            entity = hit["entity_id"]
            domain = entity.split(".")[0]
            service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle", "set": "turn_on"}[action]
            data: dict = {"entity_id": entity}
            if action == "set" and value:
                data["brightness_pct" if domain == "light" else "value"] = int(re.sub(r"\D", "", value) or 0)
            r = requests.post(f"{ha['url'].rstrip('/')}/api/services/{domain}/{service}", json=data, timeout=8,
                              headers={"Authorization": f"Bearer {ha['token']}"})
            r.raise_for_status()
            return f"{hit['name']}: {service} ok"

        spec = (hit.get("actions") or {}).get(action)
        if not spec:
            return f"{hit['name']} has no '{action}' action configured."
        url = spec["url"].replace("{value}", urllib.parse.quote(value))
        r = requests.request(spec.get("method", "GET"), url, json=spec.get("json"), timeout=8)
        r.raise_for_status()
        return f"{hit['name']}: {action} ok"

    # ---------- memory / learning ----------
    def tool_remember(self, category: str, key: str, value: str) -> str:
        self.memory.upsert_fact(category, key, value, confidence=0.8, source="told")
        return f"Remembered {key} = {value}"

    def tool_forget(self, text: str) -> str:
        return f"Forgot {self.memory.forget(text)} fact(s) about '{text}'"

    def tool_learn_shortcut(self, name: str, kind: str, target: str) -> str:
        self.memory.set_alias(name, kind, target)
        return f"Learned shortcut '{name}' -> {target}"

    def tool_set_behavior(self, setting: str, value: str) -> str:
        if setting == "chattiness":
            v = max(0.0, min(1.0, float(value)))
            self.memory.set_pref("chattiness", v)
            return f"chattiness set to {v}"
        on = str(value).lower() in ("true", "1", "on", "yes")
        self.memory.set_pref("screen_watch", on)
        return f"screen watching {'on' if on else 'off'}"


def _openclaw_reply(stdout: str) -> str:
    """Pull the agent's final text out of `openclaw agent --json` output (tolerant of shape changes)."""
    text = stdout.strip()
    if not text:
        return ""
    try:
        data = json.loads(text[text.find("{"):])
    except json.JSONDecodeError:
        return text[-500:]
    return (_find_str(data, ("finalAssistantVisibleText",))
            or _find_str(data, ("reply", "text", "content", "message", "output", "result"))
            or text[-500:])


def _find_str(o, keys: tuple[str, ...]) -> str:
    if isinstance(o, dict):
        for k in keys:
            if isinstance(o.get(k), str) and o[k].strip():
                return o[k]
        values = list(o.values())
    elif isinstance(o, list):
        values = list(reversed(o))
    else:
        return ""
    for v in values:
        if (r := _find_str(v, keys)):
            return r
    return ""

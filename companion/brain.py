"""The companion's mind: conversation, tool use, screen reactions, learning and adaptation."""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections import deque

from . import screen
from .actions import TOOLS, Actions
from .llm import Ollama
from .memory import Memory
from .pet import Pet, strip_tags

log = logging.getLogger("brain")

EMOTION_RULE = """Your body animates from emotion tags. Start every reply with an emotion tag, and switch tags
mid-reply whenever your feeling changes. Available: [happy] [excited] [proud] [love] [shy] [thinking] [curious]
[surprised] [confused] [angry] [sad] [worried] [sleepy] [calm].
Pick them from the conversation context, not at random:
- user shares good news / a task worked -> [excited] or [proud]; a compliment or affection -> [shy] or [love]
- user is sad, stressed or tired -> [sad] or [worried] first, then [calm] to comfort them
- teasing or rudeness -> playful [angry]; something unexpected -> [surprised]; puzzling request -> [confused]
- explaining or considering -> [thinking]; asking a question back -> [curious]
Example: "[surprised] Three in the morning?! [worried] You really should rest. [calm] I'll keep your music going."
"""

TOOL_RULES = """Tool rules:
- When the user asks you to open/play/launch/search/control something, CALL THE TOOL; don't just say you will.
- Use `remember` whenever the user reveals a durable fact about themselves (name, likes, job, schedule, people).
- Use `look_at_screen` when the user refers to what is on their screen ("this", "look at this", "what do you think").
- Use `openclaw_task` only for complex multi-step work; simple opening uses the direct tools.
- After tools run, reply with one short natural sentence about what you did."""

LEARN_PROMPT = """You maintain a memory profile of a user. From the exchange below, extract NEW durable facts
about the USER (not the assistant): name, preferences, dislikes, job, projects, routines, goals, important people,
pets, communication style. Ignore small talk and anything temporary. Return JSON:
{"facts": [{"category": "identity|preference|dislike|work|routine|goal|people|health|style|other",
            "key": "short_snake_case", "value": "concise value", "confidence": 0.0-1.0}]}
Return {"facts": []} if nothing worth keeping."""

SUMMARY_PROMPT = ("Summarise this conversation between the user and their desktop companion in 1-3 sentences, "
                  "focusing on what the user did, wanted, or felt. Plain text.")

SCREEN_PROMPT = """You are {name}, a desktop companion glancing at the user's screen (active window: {app} - "{title}").
{profile}
Your current chattiness is {chat:.2f} (0 = only speak if truly worthwhile, 1 = happy to chime in).
Return JSON:
{{"observation": "one sentence describing what the user is doing",
  "remark": "a short, natural, friendly remark (max 20 words) OR empty string if you should stay quiet",
  "emotion": "happy|excited|curious|surprised|confused|worried|thinking|calm",
  "interest": "a topic the user seems interested in, or empty"}}
Good remarks are specific, helpful or playful (spot an error, cheer progress, react to a video/game).
Never read out private information. Stay quiet if nothing is interesting or you'd be repeating yourself.
Your recent remarks: {recent}"""


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg["companion"]["name"]
        self.llm = Ollama(cfg["ollama"])
        self.memory = Memory(cfg["memory"]["db_path"])
        self.pet = Pet(cfg["pet"])
        self.actions = Actions(cfg, self.memory, notify=self.say, look=self.look_at_screen)
        self.think_lock = threading.Lock()       # one GPU: serialise LLM calls
        self.screen_notes: deque = deque(maxlen=6)
        self.recent_remarks: deque = deque(maxlen=5)
        self.last_remark_ts = 0.0
        self.pending_remark: dict | None = None  # proactive remark awaiting user reaction
        self.current_app = ("", "")
        self._stop = threading.Event()

    # ================= speaking =================
    def say(self, text: str, emotion: str | None = None) -> None:
        log.info("%s [%s]: %s", self.name, emotion or "-", text)
        print(f"\n{self.name}: {text}\n> ", end="", flush=True)
        self.pet.say(text, emotion)

    # ================= conversation =================
    def system_prompt(self, user_text: str) -> str:
        parts = [self.cfg["companion"]["persona"].strip(),
                 f"Current time: {time.strftime('%A %Y-%m-%d %H:%M')}."]
        user_name = self.memory.get_pref("user_name")
        if user_name:
            parts.append(f"The user's name is {user_name}.")
        profile = self.memory.profile_block()
        if profile:
            parts.append(profile)
        recalled = self.memory.recall(user_text)
        if recalled:
            parts.append("Possibly relevant memories:\n" + "\n".join(recalled))
        app, title = self.current_app
        if app:
            parts.append(f"The user's active window right now: {app} - \"{title}\".")
        if self.screen_notes:
            parts.append("What you've recently seen on their screen:\n" +
                         "\n".join(f"- {time.strftime('%H:%M', time.localtime(t))} {o}" for t, o in self.screen_notes))
        parts += [TOOL_RULES, EMOTION_RULE]
        return "\n\n".join(parts)

    def chat(self, user_text: str) -> str:
        user_text = user_text.strip()
        if not user_text:
            return ""
        self._register_engagement()
        self._maybe_close_session()
        self.pet.act("thinking")
        with self.think_lock:
            history = self.memory.recent_messages(self.cfg["memory"]["history_turns"])
            messages = [{"role": "system", "content": self.system_prompt(user_text)}]
            messages += [m for m in history if m["role"] in ("user", "assistant")]
            messages.append({"role": "user", "content": user_text})
            self.memory.add_message("user", user_text)

            reply = ""
            for _ in range(5):  # tool-use rounds
                try:
                    msg = self.llm.chat(messages, tools=TOOLS)
                except Exception as e:
                    log.exception("LLM error")
                    reply = f"[confused] My brain hiccuped ({e.__class__.__name__}). Is Ollama running?"
                    break
                calls = msg.get("tool_calls") or []
                if not calls:
                    reply = msg.get("content", "")
                    break
                messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
                for call in calls:
                    fn = call.get("function", {})
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args or "{}")
                    log.info("tool %s %s", fn.get("name"), args)
                    self.pet.tool(fn.get("name", ""))
                    result = self.actions.dispatch(fn.get("name", ""), args)
                    log.info(" -> %s", result)
                    messages.append({"role": "tool", "content": result, "tool_name": fn.get("name")})

        reply = reply or "[confused] Hmm, I lost my train of thought."
        text = strip_tags(reply)
        self.memory.add_message("assistant", text)
        self.say(reply, "calm")
        threading.Thread(target=self._learn_from, args=(user_text, text), daemon=True).start()
        return text

    # ================= learning =================
    def _learn_from(self, user_text: str, reply: str) -> None:
        if len(user_text) < 12:
            return
        with self.think_lock:
            data = self.llm.chat_json([
                {"role": "system", "content": LEARN_PROMPT},
                {"role": "user", "content": f"USER: {user_text}\nASSISTANT: {reply}"}])
        for f in (data or {}).get("facts", []) if isinstance(data, dict) else []:
            try:
                conf = float(f.get("confidence", 0.6))
                if conf >= 0.5:
                    self.memory.upsert_fact(f["category"], f["key"], str(f["value"]), conf, source="inferred")
                    log.info("learned %s/%s = %s (%.2f)", f["category"], f["key"], f["value"], conf)
            except (KeyError, TypeError, ValueError):
                continue

    def _maybe_close_session(self, force: bool = False) -> None:
        last = self.memory.last_message_ts()
        idle_limit = self.cfg["memory"]["session_idle_min"] * 60
        if not last or (not force and time.time() - last < idle_limit):
            return
        msgs = self.memory.session_messages()
        if len(msgs) < 2:
            self.memory.session += 1
            return
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in msgs[-40:])
        try:
            with self.think_lock:
                summary = self.llm.chat([{"role": "system", "content": SUMMARY_PROMPT},
                                         {"role": "user", "content": transcript}], temperature=0.3)["content"]
        except Exception:
            log.exception("summary failed")
            summary = ""
        self.memory.close_session(summary)
        log.info("session archived: %s", summary)

    # ================= adaptation =================
    def _register_engagement(self) -> None:
        """User replied soon after a proactive remark -> they like the chatter."""
        if self.pending_remark and time.time() - self.pending_remark["ts"] < 120:
            v = self.memory.nudge_pref("chattiness", +0.03)
            self.memory.add_feedback("engaged", self.pending_remark["text"])
            log.info("user engaged with remark -> chattiness %.2f", v)
        self.pending_remark = None

    def feedback(self, kind: str) -> float:
        """Explicit feedback from the UI: 'like' | 'dislike' | 'quiet'."""
        delta = {"like": +0.05, "dislike": -0.08, "quiet": -0.2}.get(kind, 0)
        self.memory.add_feedback(kind, self.recent_remarks[-1] if self.recent_remarks else "")
        self.pending_remark = None
        return self.memory.nudge_pref("chattiness", delta)

    def _expire_remark(self) -> None:
        if self.pending_remark and time.time() - self.pending_remark["ts"] > 600:
            v = self.memory.nudge_pref("chattiness", -0.02, lo=0.1)  # ignored -> slightly quieter
            self.memory.add_feedback("ignored", self.pending_remark["text"])
            log.info("remark ignored -> chattiness %.2f", v)
            self.pending_remark = None

    # ================= touch =================
    TOUCH_LINES = {
        "head": [("Hehe, headpats!", "love"), ("Mmm, that's nice~", "shy"), ("[surprised] Ah! [shy] You'll mess up my hair...", None)],
        "face": [("Hey! That's my face!", "surprised"), ("Boop?", "confused"), ("Hehe, that tickles.", "happy")],
        "hand": [("High five!", "excited"), ("Need something? Double-click me to chat!", "curious")],
        "clothing": [("Hey, hands off!", "angry"), ("Can I help you?", "confused"), ("Hmm?", "curious")],
    }

    def touched(self, region: str) -> bool:
        now = time.time()
        if now - getattr(self, "_last_touch", 0) < 6:
            return False
        self._last_touch = now
        self.memory.add_feedback(f"touch:{region}")
        if region == "head":
            self.memory.nudge_pref("affection", +0.01)
        text, emotion = random.choice(self.TOUCH_LINES.get(region, self.TOUCH_LINES["clothing"]))
        self.say(text, emotion)
        return True

    # ================= eyes =================
    def look_at_screen(self, question: str) -> str:
        """Tool: describe the screen for the chat model (already holding think_lock, so no lock here)."""
        app, title = screen.foreground_window()
        if screen.is_private(app, title, self.cfg["screen"]["privacy_blocklist"]):
            return "The screen shows something private (password manager/banking); not looking."
        img = screen.screenshot_b64(self.cfg["screen"]["max_image_width"])
        msg = self.llm.chat([{"role": "user", "content": f"Active window: {app} - {title}.\n"
                              f"Describe what is on this screen relevant to: {question}. Be concise and specific.",
                              "images": [img]}], model=self.llm.vision_model, temperature=0.3)
        desc = msg.get("content", "")
        self.screen_notes.append((time.time(), f"[{app}] {desc[:200]}"))
        return desc

    def _proactive_look(self, app: str, title: str) -> None:
        chat = float(self.memory.get_pref("chattiness"))
        profile = self.memory.profile_block()[:1500]
        prompt = SCREEN_PROMPT.format(name=self.name, app=app, title=title[:120], profile=profile, chat=chat,
                                      recent="; ".join(self.recent_remarks) or "none")
        img = screen.screenshot_b64(self.cfg["screen"]["max_image_width"])
        if not self.think_lock.acquire(timeout=1):
            return  # busy talking to the user; skip this glance
        try:
            data = self.llm.chat_json([{"role": "user", "content": prompt, "images": [img]}],
                                      model=self.llm.vision_model)
        finally:
            self.think_lock.release()
        if not isinstance(data, dict):
            return
        if data.get("observation"):
            self.screen_notes.append((time.time(), f"[{app}] {data['observation'][:200]}"))
        if data.get("interest"):
            key = "interest_" + "_".join(str(data["interest"]).lower().split())[:40]
            self.memory.upsert_fact("preference", key, str(data["interest"]), 0.4, source="screen")
        remark = (data.get("remark") or "").strip()
        if remark and random.random() < 0.35 + chat * 0.65:
            self.last_remark_ts = time.time()
            self.recent_remarks.append(remark)
            self.pending_remark = {"ts": time.time(), "text": remark}
            self.memory.add_message("assistant", f"(glancing at {app}) {remark}")
            self.say(remark, data.get("emotion"))

    def screen_loop(self) -> None:
        sc = self.cfg["screen"]
        last_key, last_tick, was_idle, asleep = None, time.time(), False, False
        while not self._stop.wait(sc["check_interval_sec"]):
            try:
                now = time.time()
                app, title = screen.foreground_window()
                idle = screen.idle_seconds()
                if app and idle < 300:
                    self.memory.log_app_time(app, title, now - last_tick)
                last_tick = now
                self.current_app = (app, title)
                self._expire_remark()
                self._maybe_close_session()

                # nap when the user has been away a while, wake up when they return
                if idle > 600 and not asleep:
                    asleep = True
                    self.pet.act("sleep")
                if idle > 1800:
                    was_idle = True
                if idle > 600:
                    continue
                if asleep and idle < 10:
                    asleep = False
                    self.pet.act("wake")
                if was_idle and idle < 10:
                    was_idle = False
                    if random.random() < float(self.memory.get_pref("chattiness")) + 0.3:
                        name = self.memory.get_pref("user_name")
                        self.say(f"[sleepy] Hm? Oh! [excited] Welcome back{', ' + name if name else ''}!")
                        continue

                if not (sc.get("enabled", True) and self.memory.get_pref("screen_watch")) or not app:
                    continue
                if screen.is_private(app, title, sc["privacy_blocklist"]) or idle > 300:
                    continue
                key = (app, title[:60])
                changed = key != last_key
                last_key = key
                gap = sc["min_comment_gap_sec"] * (1.6 - float(self.memory.get_pref("chattiness")))
                if now - self.last_remark_ts < gap:
                    continue
                if sc.get("look_on_window_change", True) and not changed and random.random() > 0.15:
                    continue
                self._proactive_look(app, title)
            except Exception:
                log.exception("screen loop error")

    # ================= lifecycle =================
    def greet(self) -> None:
        name = self.memory.get_pref("user_name")
        facts = len(self.memory.all_facts())
        hour = time.localtime().tm_hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        if not facts:
            self.say(f"Hi! I'm {self.name}, your new desktop buddy. What should I call you?", "happy")
        else:
            self.say(f"Good {part}{', ' + name if name else ''}! I'm here if you need me.", "happy")

    def start(self) -> None:
        threading.Thread(target=self.screen_loop, daemon=True, name="screen").start()

    def stop(self) -> None:
        self._stop.set()
        self._maybe_close_session(force=True)

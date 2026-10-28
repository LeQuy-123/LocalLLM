"""Thin Ollama /api/chat client with tool-calling, vision and JSON mode."""
from __future__ import annotations

import json
import logging
import re

import requests

log = logging.getLogger("llm")


class Ollama:
    def __init__(self, cfg: dict):
        self.url = cfg["url"].rstrip("/")
        self.chat_model = cfg["chat_model"]
        self.vision_model = cfg.get("vision_model", self.chat_model)
        self.options = {"num_ctx": cfg.get("num_ctx", 8192), "temperature": cfg.get("temperature", 0.7)}
        self.keep_alive = cfg.get("keep_alive", "30m")

    def available_models(self) -> list[str]:
        r = requests.get(f"{self.url}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    def chat(self, messages: list[dict], tools: list[dict] | None = None, model: str | None = None,
             json_mode: bool = False, temperature: float | None = None, timeout: int = 180) -> dict:
        """Returns the assistant message dict: {role, content, tool_calls?}."""
        body = {
            "model": model or self.chat_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {**self.options, **({"temperature": temperature} if temperature is not None else {})},
        }
        if tools:
            body["tools"] = tools
        if json_mode:
            body["format"] = "json"
        r = requests.post(f"{self.url}/api/chat", json=body, timeout=timeout)
        if r.status_code == 400 and "think" in r.text:
            body.pop("think")  # model without a thinking toggle
            r = requests.post(f"{self.url}/api/chat", json=body, timeout=timeout)
        r.raise_for_status()
        msg = r.json().get("message", {})
        msg["content"] = strip_think(msg.get("content", ""))
        return msg

    def chat_json(self, messages: list[dict], model: str | None = None, timeout: int = 120):
        msg = self.chat(messages, model=model, json_mode=True, temperature=0.2, timeout=timeout)
        return parse_json(msg.get("content", ""))


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    log.warning("could not parse JSON from model: %.200s", text)
    return None

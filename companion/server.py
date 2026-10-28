"""Local HTTP API so ViviPet's chat box (or anything else) can talk to the brain."""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .brain import Brain

log = logging.getLogger("server")


def make_handler(brain: Brain):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console clean
            pass

        def _send(self, status: int, body) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_OPTIONS(self):
            self._send(204, {})

        def do_GET(self):
            m = brain.memory
            if self.path == "/health":
                self._send(200, {"ok": True, "name": brain.name})
            elif self.path == "/memory":
                self._send(200, {"prefs": {k: m.get_pref(k) for k in ("user_name", "chattiness", "screen_watch")},
                                 "facts": m.all_facts(), "aliases": m.list_aliases(),
                                 "episodes": m.recent_episodes(10), "habits": m.habits_summary(10)})
            else:
                self._send(404, {"ok": False})

        def do_POST(self):
            try:
                body = self._body()
                if self.path == "/chat":
                    reply = brain.chat(str(body.get("text", "")))
                    self._send(200, {"ok": True, "reply": reply})
                elif self.path == "/react":  # pet was touched (ViviPet hit-test: head/face/hand/clothing)
                    spoke = brain.touched(str(body.get("region", "clothing")))
                    self._send(200, {"ok": True, "triggered": False, "reason": "spoken" if spoke else "cooldown"})
                elif self.path == "/feedback":
                    self._send(200, {"ok": True, "chattiness": brain.feedback(str(body.get("kind", "")))})
                else:
                    self._send(404, {"ok": False})
            except Exception as e:
                log.exception("request failed")
                self._send(500, {"ok": False, "error": str(e)})

    return Handler


def serve(brain: Brain, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(brain))
    threading.Thread(target=httpd.serve_forever, daemon=True, name="http").start()
    log.info("companion API on http://%s:%d", host, port)
    return httpd

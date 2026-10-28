"""Local AI desktop companion - entry point.

    python main.py            run the companion (also gives a text prompt in this console)
    python main.py --no-screen  run without screen watching
    python main.py --headless   no console prompt (chat through the pet only)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
os.chdir(ROOT)

from companion.brain import Brain  # noqa: E402
from companion.server import serve  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-screen", action="store_true")
    ap.add_argument("--headless", action="store_true", help="no console prompt (for autostart)")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    if args.no_screen:
        cfg["screen"]["enabled"] = False

    (ROOT / "data").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.FileHandler(ROOT / "data" / "companion.log", encoding="utf-8")])
    sys.stdout.reconfigure(encoding="utf-8")

    brain = Brain(cfg)
    try:
        models = brain.llm.available_models()
        if brain.llm.chat_model not in models:
            print(f"!! Ollama model '{brain.llm.chat_model}' not found. Installed: {models}")
    except Exception as e:
        print(f"!! Cannot reach Ollama at {cfg['ollama']['url']}: {e}")
    if not brain.pet.alive():
        print("!! ViviPet is not running - replies will only appear in this console.")

    serve(brain, cfg["server"]["host"], cfg["server"]["port"])
    brain.start()
    brain.greet()
    print("Type to chat (Ctrl+C to quit). Double-click the pet or press Ctrl+Shift+Space to chat there.")
    try:
        if args.headless:
            threading.Event().wait()
        while True:
            text = input("> ")
            if text.strip():
                brain.chat(text)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        print("\nSaving memory...")
        brain.stop()


if __name__ == "__main__":
    main()

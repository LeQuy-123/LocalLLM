"""Drive the running pet through its poses and save a preview sheet into assets/previews/<model>/.

    python tools/preview/capture_poses.py                 # current model, default poses
    python tools/preview/capture_poses.py --model capri   # switch model first
    python tools/preview/capture_poses.py --poses idle happy sleep --expressions sad shy

Needs ViviPet running (adapter on :18765). Restores size 1 and a neutral face afterwards.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests

from pose_sheet import build

ADAPTER = "http://127.0.0.1:18765"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POSES = ["idle", "happy", "success", "surprised", "thinking", "confused", "angry", "error", "sleep", "wake",
                 "dragging", "searching", "coding"]
DEFAULT_EXPRESSIONS = ["sad", "shy", "worried"]


def action(payload: dict) -> None:
    requests.post(f"{ADAPTER}/adapter/action", json=payload, timeout=5).raise_for_status()


def capture(path: Path) -> None:
    r = requests.get(f"{ADAPTER}/adapter/capture", timeout=10)
    r.raise_for_status()
    path.write_bytes(r.content)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="model id to switch to first (e.g. capri, vivi-chibi)")
    ap.add_argument("--poses", nargs="*", default=DEFAULT_POSES)
    ap.add_argument("--expressions", nargs="*", default=DEFAULT_EXPRESSIONS)
    ap.add_argument("--scale", type=float, default=1.6, help="pet size while capturing")
    ap.add_argument("--wait", type=float, default=1.0, help="seconds to let each pose settle")
    args = ap.parse_args()

    if args.model:
        action({"model": args.model})
        time.sleep(3)  # load + entrance animation
    diag = requests.get(f"{ADAPTER}/adapter/diagnostics", timeout=10).json()
    model = args.model or diag["renderer"]["activeModelId"]
    frames = ROOT / "assets" / "previews" / model / "frames"
    frames.mkdir(parents=True, exist_ok=True)

    action({"action": f"resizePet:{args.scale}"})
    action({"action": "wake"})  # start from an awake idle, even if she was napping
    time.sleep(1.5)
    names = []
    try:
        for pose in args.poses:
            action({"action": pose})
            time.sleep(args.wait)
            capture(frames / f"{pose}.png")
            names.append(pose)
        action({"action": "wake"})  # "idle" alone doesn't wake her if a sleep pose was captured
        time.sleep(1.2)
        action({"action": "idle"})
        for expr in args.expressions:
            action({"expression": expr})
            time.sleep(args.wait)
            capture(frames / f"expr-{expr}.png")
            names.append(f"expr-{expr}")
    finally:
        action({"expression": "reset"})
        action({"action": "wake"})
        action({"action": "resizePet:1"})

    stamp = time.strftime("%Y%m%d-%H%M")
    build(frames, ROOT / "assets" / "previews" / model / f"poses-{stamp}.png", names)


if __name__ == "__main__":
    main()

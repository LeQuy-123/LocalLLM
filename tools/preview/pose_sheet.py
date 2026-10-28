"""Combine captured pose frames into one labelled sheet.

    python pose_sheet.py <frames_dir> <out.png> idle happy thinking ...

Each name reads <frames_dir>/<name>.png (a full-window capture); the character is cropped out by its alpha.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

TILE_W, TILE_H, PER_ROW = 300, 420, 5


def build(frames_dir: Path, out: Path, names: list[str]) -> None:
    rows = (len(names) + PER_ROW - 1) // PER_ROW
    sheet = Image.new("RGBA", (TILE_W * min(PER_ROW, len(names)), TILE_H * rows), (255, 255, 255, 255))
    for i, name in enumerate(names):
        im = Image.open(frames_dir / f"{name}.png").convert("RGBA")
        bb = im.getbbox()
        tile = Image.new("RGBA", (TILE_W, TILE_H), (235, 240, 248, 255))
        if bb:
            crop = im.crop((max(0, bb[0] - 10), max(0, bb[1] - 10), bb[2] + 10, bb[3] + 5))
            crop.thumbnail((TILE_W, TILE_H - 20))
            tile.alpha_composite(crop, ((TILE_W - crop.width) // 2, 0))
        ImageDraw.Draw(tile).text((10, TILE_H - 15), name, fill=(40, 40, 60, 255))
        sheet.paste(tile, ((i % PER_ROW) * TILE_W, (i // PER_ROW) * TILE_H))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print("saved", out)


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])

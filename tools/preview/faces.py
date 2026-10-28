"""Crop the face region from several captured frames side by side (to check lip sync).

    python faces.py <out.png> frame1.png frame2.png ...
"""
import sys

from PIL import Image


def build(out: str, frames: list[str]) -> None:
    tiles = []
    for path in frames:
        im = Image.open(path).convert("RGBA")
        bb = im.getbbox()
        if not bb:
            continue
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        face = im.crop((bb[0] + int(w * 0.30), bb[1] + int(h * 0.22), bb[0] + int(w * 0.85), bb[1] + int(h * 0.48)))
        bg = Image.new("RGBA", face.size, (235, 240, 248, 255))
        bg.alpha_composite(face)
        tiles.append(bg)
    width = sum(t.width for t in tiles) + 10 * (len(tiles) - 1)
    sheet = Image.new("RGBA", (width, max(t.height for t in tiles)), (255, 255, 255, 255))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width + 10
    sheet.save(out)
    print("saved", out)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2:])

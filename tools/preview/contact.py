"""Contact sheet of sprite strips: python -I contact.py <sprites_dir> <out.png> name:count[:frames_to_show] ..."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

src, out, specs = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
rows = []
for spec in specs:
    name, count, *show = spec.split(":")
    count = int(count)
    strip = Image.open(src / f"{name}.png").convert("RGBA")
    w = strip.width // count
    idx = [int(i) for i in show[0].split(",")] if show else list(range(0, count, max(1, count // 6)))[:6]
    cells = [strip.crop((i * w, 0, (i + 1) * w, strip.height)) for i in idx]
    rows.append((name, cells, idx))

cell_h = 200
sheet = Image.new("RGBA", (1400, len(rows) * (cell_h + 18)), (236, 240, 248, 255))
d = ImageDraw.Draw(sheet)
for r, (name, cells, idx) in enumerate(rows):
    y = r * (cell_h + 18)
    d.text((6, y + 2), name, fill=(30, 30, 50, 255))
    x = 90
    for c, i in zip(cells, idx):
        c = c.copy()
        c.thumbnail((400, cell_h))
        sheet.alpha_composite(c, (x, y + 16))
        d.text((x, y + 2), str(i), fill=(120, 120, 140, 255))
        x += c.width + 8
sheet.save(out)
print("saved", out)

"""Print size/mode of each PNG passed on the command line (reads images only)."""
import sys
from pathlib import Path

from PIL import Image

for arg in sys.argv[1:]:
    for f in sorted(Path(arg).glob("*.png")) if Path(arg).is_dir() else [Path(arg)]:
        with Image.open(f) as im:
            bbox = im.convert("RGBA").getbbox()
            print(f"{f.name:24s} {im.size} {im.mode} opaque_bbox={bbox}")

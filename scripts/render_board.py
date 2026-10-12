"""Render the Ville's map to a PNG once, for the live viewer to draw agents on.

    python scripts/render_board.py out.png [tile_px]

The maze CSVs are a single flat row of width*height values, not a grid -- they
are reshaped row-major by maze_width, the same way maze.py reads them.
"""
import colorsys
import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
B = ROOT / "environment/frontend_server/static_dirs/assets/the_ville/matrix"
W, H = 140, 100


def flat(p):
  return [c.strip() for c in Path(p).read_text().strip().split(",")]


def render(out_path, S=9):
  coll, sect, aren = (flat(B / f"maze/{n}_maze.csv")
                      for n in ("collision", "sector", "arena"))
  names = {r[0].strip(): r[2].strip()
           for r in csv.reader(open(B / "special_blocks/sector_blocks.csv")) if r}

  def at(layer, x, y):
    i = y * W + x
    return layer[i] if i < len(layer) else "0"

  ids = sorted({c for c in sect if c and c != "0"})
  pal = {}
  for i, s in enumerate(ids):
    r, g, b = colorsys.hsv_to_rgb((i * 0.618033) % 1.0, 0.30, 0.93)
    pal[s] = (int(r * 255), int(g * 255), int(b * 255))

  img = Image.new("RGB", (W * S, H * S), (243, 241, 236))
  d = ImageDraw.Draw(img)
  for y in range(H):
    for x in range(W):
      s = at(sect, x, y)
      if s and s != "0":
        d.rectangle([x * S, y * S, x * S + S - 1, y * S + S - 1], fill=pal[s])
  for y in range(H):                      # room outlines
    for x in range(W):
      a = at(aren, x, y)
      if not a or a == "0":
        continue
      if x + 1 < W and at(aren, x + 1, y) != a:
        d.line([(x * S + S - 1, y * S), (x * S + S - 1, y * S + S - 1)], fill=(255, 255, 255))
      if y + 1 < H and at(aren, x, y + 1) != a:
        d.line([(x * S, y * S + S - 1), (x * S + S - 1, y * S + S - 1)], fill=(255, 255, 255))
  for y in range(H):                      # walls
    for x in range(W):
      if at(coll, x, y) == "32125":
        d.rectangle([x * S, y * S, x * S + S - 1, y * S + S - 1], fill=(70, 66, 60))

  try:
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 12)
  except OSError:
    font = ImageFont.load_default()
  cent = {}
  for y in range(H):
    for x in range(W):
      s = at(sect, x, y)
      if s and s != "0":
        cent.setdefault(s, []).append((x, y))
  placed = []
  for s, pts in sorted(cent.items(), key=lambda kv: -len(kv[1])):
    nm = names.get(s, "")
    if not nm or len(pts) < 40:
      continue
    nm = nm.replace("'s apartment", "").replace(" family's house", " house")[:26]
    cx = sum(p[0] for p in pts) / len(pts) * S
    cy = sum(p[1] for p in pts) / len(pts) * S
    bb = d.textbbox((0, 0), nm, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    box = (cx - w / 2 - 4, cy - h / 2 - 3, cx + w / 2 + 4, cy + h / 2 + 4)
    if any(not (box[2] < o[0] or box[0] > o[2] or box[3] < o[1] or box[1] > o[3])
           for o in placed):
      continue
    placed.append(box)
    d.rectangle(box, fill=(255, 255, 255))
    d.text((cx - w / 2, cy - h / 2), nm, fill=(40, 44, 42), font=font)
  img.save(out_path)
  return img.size


if __name__ == "__main__":
  out = sys.argv[1] if len(sys.argv) > 1 else "board.png"
  size = render(out, int(sys.argv[2]) if len(sys.argv) > 2 else 9)
  print(f"wrote {out} {size[0]}x{size[1]}")

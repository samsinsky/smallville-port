"""Composite the Ville's real Tiled map into a single PNG.

    python scripts/render_map.py out.png [scale]

The frontend builds this at runtime in Phaser from the_ville_jan7.json plus its
tilesets. Rendering it once lets the live viewer show the same artwork the paper
does, instead of a schematic drawn from the collision CSVs.

Visual layers only: Collisions and Object Interaction Blocks are logic, not art.
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
VIS = ROOT / "environment/frontend_server/static_dirs/assets/the_ville/visuals"
MAP = VIS / "the_ville_jan7.json"
SKIP = {"Collisions", "Object Interaction Blocks"}
FLIP_H, FLIP_V, FLIP_D = 0x80000000, 0x40000000, 0x20000000


def render(out_path, scale=1.0):
  m = json.loads(MAP.read_text())
  tw, th = m["tilewidth"], m["tileheight"]
  W, H = m["width"] * tw, m["height"] * th

  sheets = []
  for ts in sorted(m["tilesets"], key=lambda t: t["firstgid"]):
    if "image" not in ts:
      continue
    img = Image.open(VIS / ts["image"]).convert("RGBA")
    sheets.append({"first": ts["firstgid"], "cols": ts["columns"],
                   "count": ts.get("tilecount", 0), "img": img,
                   "tw": ts.get("tilewidth", tw), "th": ts.get("tileheight", th)})

  def lookup(gid):
    for s in reversed(sheets):
      if gid >= s["first"]:
        local = gid - s["first"]
        if s["count"] and local >= s["count"]:
          return None
        x = (local % s["cols"]) * s["tw"]
        y = (local // s["cols"]) * s["th"]
        return s["img"].crop((x, y, x + s["tw"], y + s["th"]))
    return None

  canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
  drawn = 0
  for layer in m["layers"]:
    if layer["type"] != "tilelayer" or layer["name"].strip() in SKIP or not layer.get("visible", True):
      continue
    for i, raw in enumerate(layer["data"]):
      if not raw:
        continue
      gid = raw & ~(FLIP_H | FLIP_V | FLIP_D)
      tile = lookup(gid)
      if tile is None:
        continue
      if raw & FLIP_H:
        tile = tile.transpose(Image.FLIP_LEFT_RIGHT)
      if raw & FLIP_V:
        tile = tile.transpose(Image.FLIP_TOP_BOTTOM)
      x, y = (i % layer["width"]) * tw, (i // layer["width"]) * th
      canvas.alpha_composite(tile, (x, y))
      drawn += 1

  if scale != 1.0:
    canvas = canvas.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
  canvas.convert("RGB").save(out_path, optimize=True)
  return canvas.size, drawn


if __name__ == "__main__":
  out = sys.argv[1] if len(sys.argv) > 1 else "map.png"
  size, n = render(out, float(sys.argv[2]) if len(sys.argv) > 2 else 1.0)
  print(f"wrote {out} {size[0]}x{size[1]} from {n:,} tiles")

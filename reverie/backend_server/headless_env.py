"""
Headless environment stepper -- replaces the browser frontend for experiments.

The reverie backend and the Phaser frontend talk in lockstep through files:
the backend reads environment/<step>.json, writes movement/<step>.json (tile
coords its own pathfinder already computed), increments, then blocks until
something writes environment/<step+1>.json. So the echo is offset by one:
environment/N is produced from movement/N-1.

The browser does not decide anything -- verified against a shipped run, where
movement/1.json's [73,14] reappears verbatim as environment/1.json's x/y. It
renders the sprites and echoes the coordinates back. So for a headless
experiment run we can do the echo directly and drop Django, Phaser and
selenium from the loop entirely.

Keep using the real frontend when you want to *watch* a sim. Use this when you
want to run seed conditions unattended.

    python headless_env.py <sim_code>
"""
import json
import os
import sys
import time

from utils import fs_storage


def transpose(movement_doc, prev_env):
  """movement {persona:{Name:{movement:[x,y],...}}} -> environment {Name:{maze,x,y}}."""
  out = {}
  for name, rec in movement_doc.get("persona", {}).items():
    xy = rec.get("movement")
    if not xy:                      # no instruction: hold last known position
      out[name] = prev_env.get(name, {"maze": "the_ville", "x": 0, "y": 0})
      continue
    maze = prev_env.get(name, {}).get("maze", "the_ville")
    out[name] = {"maze": maze, "x": int(xy[0]), "y": int(xy[1])}
  return out


def run(sim_code, poll=0.05, idle_timeout=None):
  sim = os.path.join(fs_storage, sim_code)
  env_dir, mov_dir = os.path.join(sim, "environment"), os.path.join(sim, "movement")

  # The backend forks a sim with shutil.copytree, which refuses an existing
  # destination -- so wait for the fork rather than creating the folder here.
  if not os.path.isdir(sim):
    print(f"[headless] waiting for {sim_code} to be forked...")
    while not os.path.isdir(sim):
      time.sleep(0.2)
  # The base sims ship with environment/ and personas/ but no movement/, and
  # the backend writes movement/<step>.json without creating the parent. The
  # Django frontend makes it; headless, that is this process's job.
  os.makedirs(env_dir, exist_ok=True)
  os.makedirs(mov_dir, exist_ok=True)

  step = 0
  while os.path.exists(os.path.join(env_dir, f"{step}.json")):
    step += 1                        # resume where a previous run left off

  print(f"[headless] {sim_code}: waiting from step {step}  (ctrl-c to stop)")
  last_seen = time.time()

  while True:
    # environment/N is the echo of movement/N-1 -- verified against a shipped
    # run, where environment/0 is [72,14] while movement/0 already says [73,14].
    mov_path = os.path.join(mov_dir, f"{step - 1}.json")
    if os.path.exists(mov_path):
      try:
        with open(mov_path) as f:
          movement = json.load(f)
      except (json.JSONDecodeError, OSError):
        time.sleep(poll)             # backend mid-write; try again
        continue

      prev_path = os.path.join(env_dir, f"{step - 1}.json")
      prev_env = {}
      if os.path.exists(prev_path):
        with open(prev_path) as f:
          prev_env = json.load(f)

      # Atomic write: the backend polls for this file and reads it as soon as
      # it appears, so a partially-written file would be a torn read.
      dst = os.path.join(env_dir, f"{step}.json")
      tmp = dst + ".tmp"
      with open(tmp, "w") as f:
        json.dump(transpose(movement, prev_env), f, indent=2)
      os.replace(tmp, dst)

      if step % 100 == 0:
        print(f"[headless] step {step}")
      step += 1
      last_seen = time.time()
    else:
      if idle_timeout and time.time() - last_seen > idle_timeout:
        print(f"[headless] idle {idle_timeout}s at step {step}; stopping")
        return
      time.sleep(poll)


if __name__ == "__main__":
  if len(sys.argv) < 2:
    sys.exit("usage: python headless_env.py <sim_code> [idle_timeout_s]")
  run(sys.argv[1], idle_timeout=float(sys.argv[2]) if len(sys.argv) > 2 else None)

"""
Summarise one simulation run's logs.

    python run_report.py ../../runs/<sim_code>

Reads cost_log.jsonl (one line per API call) and outcome_log.jsonl (one line
per logical request). The integrity section is the one to report: how often a
task's answer was replaced by its fail-safe default. A run can finish cleanly
with the architecture partly switched off -- every memory scored 4, everyone
walking to the kitchen -- and that section is how you would know.
"""
import collections
import json
import sys
from pathlib import Path


def load(path):
  if not path.exists():
    return []
  return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def main(log_dir):
  d = Path(log_dir)
  calls = load(d / "cost_log.jsonl")
  outcomes = load(d / "outcome_log.jsonl")
  chat = [c for c in calls if c["template"] != "embedding"]

  print(f"=== {d.name} ===")
  print(f"API calls {len(calls)} ({len(calls) - len(chat)} embeddings)   "
        f"cost ${sum(c['cost_usd'] for c in calls):.4f}   "
        f"tokens in {sum(c['in'] for c in calls):,} / out {sum(c['out'] for c in calls):,}   "
        f"cached {sum(c['cached_in'] for c in calls):,}")
  errs = [c for c in calls if "error" in c]
  print(f"transport errors {len(errs)}   wasted round trips {sum(c['retries'] for c in chat)}")

  # --- integrity -----------------------------------------------------------
  # Every logical request ends in exactly one terminal record: "ok", "exhausted"
  # (gpt-3.5 path; followed by a 0-attempt "fail_safe" or a fallback prompt), or
  # a "fail_safe" that itself consumed attempts (davinci path). A 0-attempt
  # fail_safe is the follow-up to an "exhausted", not a new request.
  by = collections.defaultdict(collections.Counter)
  att = collections.defaultdict(list)
  req = collections.Counter()
  for o in outcomes:
    by[o["template"]][o["outcome"]] += 1
    if o["outcome"] in ("ok", "exhausted") or (o["outcome"] == "fail_safe" and o["attempts"]):
      req[o["template"]] += 1
      att[o["template"]].append(o["attempts"])
  requests = sum(req.values())
  used_fs = sum(c["fail_safe"] for c in by.values())
  print(f"\n--- integrity: fail-safe used for {used_fs} of {requests} requests "
        f"({(100 * used_fs / requests) if requests else 0:.1f}%) ---")
  print(f"{'template':42s} {'reqs':>5s} {'ok':>5s} {'exhaust':>7s} {'failsafe':>8s} {'avg tries':>9s}")
  for tmpl, c in sorted(by.items(), key=lambda kv: (-kv[1]["fail_safe"], -kv[1]["ok"])):
    tries = att[tmpl]
    flag = "  <--" if c["fail_safe"] or c["exhausted"] else ""
    print(f"{tmpl:42s} {req[tmpl]:5d} {c['ok']:5d} {c['exhausted']:7d} {c['fail_safe']:8d} "
          f"{(sum(tries) / len(tries)) if tries else 0:9.2f}{flag}")

  # --- provenance: what actually ran ---------------------------------------
  print("\n--- provenance: model / temperature / effort actually used ---")
  seen = collections.defaultdict(collections.Counter)
  cost = collections.Counter()
  for c in chat:
    seen[c["template"]][(c["model"], c.get("temp"), c.get("effort"))] += 1
    cost[c["template"]] += c["cost_usd"]
  for tmpl in sorted(seen, key=lambda t: -cost[t]):
    combos = ", ".join(f"{m} @{t} {e or ''}".strip() + f" x{n}" for (m, t, e), n in seen[tmpl].items())
    warn = "  <-- MIXED" if len(seen[tmpl]) > 1 else ""
    print(f"{tmpl:42s} ${cost[tmpl]:.4f}  {combos}{warn}")


if __name__ == "__main__":
  if len(sys.argv) != 2:
    sys.exit(__doc__)
  main(sys.argv[1])

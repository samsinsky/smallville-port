"""
Config for the reverie backend.

Ported from the original (2023) template: the API key is no longer a literal
here, it is read from the gitignored .env at the repo root so that rotating it
touches exactly one line in one file.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------- credentials
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path=_REPO_ROOT / ".env"):
  """Minimal .env reader — avoids a python-dotenv dependency."""
  if not path.exists():
    return
  for line in path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

openai_api_key = os.environ.get("OPENAI_API_KEY_SMALLVILLE", "")
if not openai_api_key:
  raise RuntimeError(
      "No API key. Set OPENAI_API_KEY_SMALLVILLE in generative_agents/.env")

key_owner = "smallville"

# ------------------------------------------------------------- model routing
# One row per task. `temp` is the ORIGINAL temperature from Park et al.'s code
# (davinci gpt_param values; gpt-3.5 calls sent none, so the API default of 1).
# Decision 2026-09-16: keep every task at its original temperature, since
# humans are not deterministic. Models are chosen so each temp can actually be
# honoured -- gpt-5 / gpt-5-mini / gpt-5-nano only accept temperature 1.
#
# Keys are <prompt dir>/<template name>, as recorded by generate_prompt(). The
# directory matters: v2/ and v3_ChatGPT/ reuse names for different call paths
# with different original temperatures (e.g. memo_on_convo_v1: 1 vs 0).
T = dict  # readability

ROUTES = {
    # 1  importance scoring -- poignancy bake-off: 4.1-mini @1 rho 0.98, sd 0.12, 24/24 parsed
    "v3_ChatGPT/poignancy_event_v1":            T(model="gpt-4.1-mini", temp=1.0),
    "v3_ChatGPT/poignancy_chat_v1":             T(model="gpt-4.1-mini", temp=1.0),
    "v3_ChatGPT/poignancy_thought_v1":          T(model="gpt-4.1-mini", temp=1.0),
    # 2  wake-up hour
    "v2/wake_up_hour_v1":                       T(model="gpt-4.1-nano", temp=0.8),
    # 3  daily plan (first day) + revise_identity (every later day, rewrites `currently`)
    "v2/daily_planning_v6":                     T(model="gpt-5.1", effort="none", temp=1.0),
    "revise_identity":                          T(model="gpt-5.1", effort="none", temp=1.0),
    # 4  hourly schedule
    "v2/generate_hourly_schedule_v2":           T(model="gpt-4.1-mini", temp=0.5),
    # 5  action decomposition
    "v2/task_decomp_v3":                        T(model="gpt-4.1-mini", temp=0.0),
    "v2/new_decomp_schedule_v1":                T(model="gpt-4.1-mini", temp=0.0),
    # 6  location choice
    "v1/action_location_sector_v1":             T(model="gpt-4.1-mini", temp=0.0),
    "v1/action_location_object_vMar11":         T(model="gpt-4.1-mini", temp=0.0),   # arena
    "v1/action_object_v2":                      T(model="gpt-4.1-nano", temp=0.0),   # game object
    # 7  action labeling
    "v2/generate_event_triple_v1":              T(model="gpt-4.1-nano", temp=0.0),
    "v3_ChatGPT/generate_pronunciatio_v1":      T(model="gpt-5-nano", effort="minimal", temp=1.0),
    # object-state bake-off @1, 12 samples: gpt-5-nano median 8 words (max 51), 5/12 downstream
    # triple fail-safes; gpt-4.1-mini median 4 (template example: "being fixed"), 0/12
    "v3_ChatGPT/generate_obj_event_v1":         T(model="gpt-4.1-mini", temp=1.0),
    # 8  social gate (only called when SOCIAL_GATE=working)
    "v2/decide_to_talk_v2":                     T(model="gpt-4.1-mini", temp=0.0),
    "v2/decide_to_react_v1":                    T(model="gpt-4.1-mini", temp=0.0),
    # 9  dialogue -- temp 1 is the original, so gpt-5's forced temperature costs nothing
    "v3_ChatGPT/iterative_convo_v1":            T(model="gpt-5-mini", effort="low", temp=1.0),
    "v3_ChatGPT/summarize_conversation_v1":     T(model="gpt-5-nano", effort="minimal", temp=1.0),
    # 10 memory writing
    "v3_ChatGPT/summarize_chat_relationship_v2": T(model="gpt-4.1-mini", temp=1.0),  # before EVERY utterance
    "v3_ChatGPT/memo_on_convo_v1":              T(model="gpt-4.1-mini", temp=1.0),   # runs first
    "v2/memo_on_convo_v1":                      T(model="gpt-4.1-mini", temp=0.0),   # only if the above fails
    "v2/planning_thought_on_convo_v1":          T(model="gpt-4.1-mini", temp=0.0),
    # 11 reflection
    "v3_ChatGPT/generate_focal_pt_v1":          T(model="gpt-5.1", effort="none", temp=1.0),  # runs first
    "v2/generate_focal_pt_v1":                  T(model="gpt-5.1", effort="none", temp=0.0),  # only if the above fails
    "v2/insight_and_evidence_v1":               T(model="gpt-5.1", effort="none", temp=0.5),
    # interview feature only (you questioning agents), not the simulation loop
    "v3_ChatGPT/summarize_ideas_v1":            T(model="gpt-4.1-mini", temp=1.0),
    "v2/generate_next_convo_line_v1":           T(model="gpt-4.1-mini", temp=1.0),
    "v2/whisper_inner_thought_v1":              T(model="gpt-4.1-mini", temp=0.0),
    "safety/anthromorphosization_v1":           T(model="gpt-4.1-mini", temp=1.0),
    # dead code in the shipped repo -- routed anyway so nothing can ever run at
    # an unintended temperature if it is revived
    "v3_ChatGPT/agent_chat_v1":                 T(model="gpt-4.1-mini", temp=1.0),
    "v3_ChatGPT/summarize_chat_ideas_v1":       T(model="gpt-4.1-mini", temp=1.0),
    "v2/convo_to_thoughts_v1":                  T(model="gpt-4.1-mini", temp=0.7),
    "v2/create_conversation_v2":                T(model="gpt-4.1-mini", temp=0.7),
    "v2/get_keywords_v1":                       T(model="gpt-4.1-mini", temp=0.0),
    "v2/keyword_to_thoughts_v1":                T(model="gpt-4.1-mini", temp=0.7),
}

# ------------------------------------------------------------ social gate
# decide_to_talk / decide_to_react. In the shipped code neither ever reached the
# model's judgment: a 20-token cap truncated the step-by-step reasoning before
# the answer, and decide_to_talk's parser split on `Answer in yes or no:` while
# its own template writes `Answer in "yes" or "no":`. Both fell through to their
# fail-safes: talk -> "yes", react -> "3" (no reaction).
#   shipped : reproduce that behaviour without calling the model (baseline;
#             comparable to the paper's results)
#   working : the model actually decides (the architecture the paper describes)
# Choose per run:  SMALLVILLE_SOCIAL_GATE=working python reverie.py
SOCIAL_GATE = os.environ.get("SMALLVILLE_SOCIAL_GATE", "shipped").strip().lower()
if SOCIAL_GATE not in ("shipped", "working"):
  raise RuntimeError(f"SMALLVILLE_SOCIAL_GATE must be 'shipped' or 'working', got {SOCIAL_GATE!r}")
print(f"[config] SOCIAL_GATE={SOCIAL_GATE}")

# Anything unrouted: a temperature-capable model, logged under its template name
# so it shows up in cost_log.jsonl and can be given its own row.
DEFAULT_ROUTE = T(model="gpt-4.1-mini", temp=None)

EMBEDDING_MODEL = "text-embedding-3-small"

# USD per 1M tokens. VERIFY against current pricing before trusting the
# cost column in cost_log.jsonl — these move.
PRICING = {
    "gpt-5-nano":  {"in": 0.05, "cached_in": 0.005, "out": 0.40},
    "gpt-5-mini":  {"in": 0.25, "cached_in": 0.025, "out": 2.00},
    "gpt-5.1":     {"in": 1.25, "cached_in": 0.125, "out": 10.00},
    "gpt-4.1-mini": {"in": 0.40, "cached_in": 0.10, "out": 1.60},
    "gpt-4.1-nano": {"in": 0.10, "cached_in": 0.025, "out": 0.40},
    "text-embedding-3-small": {"in": 0.02, "cached_in": 0.02, "out": 0.0},
}

# Per-run logs. The driver points this at runs/<sim_code>/ so every simulation
# keeps its own record; kept outside storage/ because forking a sim copies its
# whole folder, which would drag the parent's logs into the child.
LOG_DIR = Path(os.environ.get("SMALLVILLE_LOG_DIR", str(_REPO_ROOT)))
LOG_DIR.mkdir(parents=True, exist_ok=True)
COST_LOG = str(LOG_DIR / "cost_log.jsonl")        # one line per API call
OUTCOME_LOG = str(LOG_DIR / "outcome_log.jsonl")  # one line per logical request

# A hard local stop so a runaway loop cannot chew through the $20 cap.
# Raise deliberately; it is a seatbelt, not a budget.
MAX_SPEND_USD = float(os.environ.get("SMALLVILLE_MAX_SPEND_USD", "5.0"))

# ------------------------------------------------------------------- paths
maze_assets_loc = "../../environment/frontend_server/static_dirs/assets"
env_matrix = f"{maze_assets_loc}/the_ville/matrix"
env_visuals = f"{maze_assets_loc}/the_ville/visuals"

fs_storage = "../../environment/frontend_server/storage"
fs_temp_storage = "../../environment/frontend_server/temp_storage"

collision_block_id = "32125"

debug = True

# ----------------------------------------------------------- token budget
# Floor on max_completion_tokens for every call. Reasoning models need it or they
# starve to an empty string (measured: out=256, content ""). It is also applied
# to non-reasoning models on purpose: the davinci-era caps (often 5-50 tokens)
# silently truncated answers -- e.g. decide_to_talk's 20-token cap cuts its own
# step-by-step reasoning before the yes/no. Stop sequences and parsers, not
# truncation, now bound the output. Record as a deviation from the original code.
MAX_COMPLETION_FLOOR = 2000

# ------------------------------------------------------ model capabilities
# What each model family accepts, declared up front so no call ever pays a
# 400 round trip to discover it. Measured against the live API, 2026-09-16:
#   gpt-5-nano/mini : temperature only at default (1); no stop; reasoning_effort ok
#   gpt-5.1         : temperature ok when reasoning_effort="none"; no stop
#   gpt-4.1-*       : temperature (incl. 0), stop, seed all ok; no reasoning_effort
# Matched by longest prefix.
MODEL_CAPS = {
    "gpt-5.1":  {"temperature": "if_no_reasoning", "stop": False, "seed": False, "reasoning": True},
    "gpt-5":    {"temperature": False,             "stop": False, "seed": False, "reasoning": True},
    "gpt-4.1":  {"temperature": True,              "stop": True,  "seed": True,  "reasoning": False},
}

# Fixed seed for models that accept one. Best-effort on OpenAI's side, not a
# guarantee of bit-identical output, but it narrows run-to-run variance.
SIM_SEED = 7


def _validate_routes():
  """Fail fast if any task is routed to a model that cannot run at its original
  temperature -- the alternative is silently sampling at the wrong one."""
  def caps(model):
    best = max((p for p in MODEL_CAPS if model.startswith(p)), key=len, default="")
    return MODEL_CAPS.get(best)
  bad = []
  for tmpl, r in ROUTES.items():
    c = caps(r["model"])
    if c is None or r["model"] not in PRICING:
      bad.append(f"{tmpl}: no capability/pricing entry for {r['model']}")
      continue
    t = r.get("temp")
    if t is None or t == 1.0:
      continue                                   # default temperature always holds
    effort = r.get("effort")
    ok = c["temperature"] is True or (
        c["temperature"] == "if_no_reasoning" and effort in (None, "none"))
    if not ok:
      bad.append(f"{tmpl}: {r['model']} cannot run at temperature {t}")
  if bad:
    raise RuntimeError("Invalid ROUTES:\n  " + "\n  ".join(bad))


_validate_routes()

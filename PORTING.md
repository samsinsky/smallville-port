# Smallville, ported to 2026 models

A fork of [joonspk-research/generative_agents](https://github.com/joonspk-research/generative_agents),
the code accompanying *[Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)*
(Park et al., 2023), updated to run on current OpenAI models and Python 3.12.

The original targeted `text-davinci-003` and `gpt-3.5-turbo` through the pre-1.0
OpenAI SDK. Both models are retired and that SDK had a breaking release, so the
simulation no longer runs as shipped. This fork changes **how the simulation
talks to a model**, and as little else as possible.

## What works

A 4,500-step run (3 agents, midnight to 12:30 game time) completes with 0 errors
and **3 fail-safes in 1,116 requests (0.3%)**, in 25 minutes for **$0.29**.
Every call runs at its task's original temperature.

That run exercises the whole loop: waking, planning the day from the seed,
movement, perception, importance scoring, two 16-turn conversations, the memory
writing that follows them, and five reflections producing fifteen insights.

Observed behaviour, as a sanity check rather than a result: Isabella invited
Maria to the Valentine's party at 10:12 and Maria negotiated around her own
seeded streaming schedule. Klaus and Maria then talked for 16 turns at 12:10 and
the party never came up — Klaus ends the morning with none of it in memory. The
same non-transmission appears in the demo data shipped with the original repo.

Conversation length varies: of four observed, three ran the full 8 rounds
(16 turns) and one ended at 7. The long ones tend to restate an arrangement
already made in their closing turns.

## Setup

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements-2026.txt
printf 'OPENAI_API_KEY_SMALLVILLE=sk-...\n' > .env && chmod 600 .env
```

`.env` is gitignored. `reverie/backend_server/utils.py` is tracked here (it holds
configuration, not credentials) — unlike upstream, where it held the API key.

**Run headless** (no browser; the fastest way to run experiments):

```bash
scripts/drive_run.sh my_sim 3000 shipped      # <sim_code> <steps> <shipped|working>
scripts/watch_run.sh my_sim 3000              # progress, in another shell
./.venv/bin/python reverie/backend_server/run_report.py runs/my_sim
```

**Watch it in the browser** (the original Phaser frontend, on Django 4.2):

```bash
cd environment/frontend_server && python manage.py migrate && python manage.py runserver
```
Then `/replay/<sim_code>/1/` for a finished run, or `/` to drive a live one.

## Configuration

`ROUTES` in `reverie/backend_server/utils.py` has one row per prompt template:
which model runs it, what reasoning effort, and the temperature. **Every task
keeps the temperature from the original code.** That is not uniform — the
original ran importance scoring, dialogue and planning at 1, reflection insights
at 0.5, and location choice and task decomposition at 0 — so models are chosen
per task to honour it (the gpt-5 family only accepts temperature 1). Routes are
validated at import: a task that cannot run at its temperature fails loudly.

`SMALLVILLE_SOCIAL_GATE` selects how `decide_to_talk` / `decide_to_react` behave;
see "The social gates" below. Other environment variables: `SMALLVILLE_LOG_DIR`,
`SMALLVILLE_MAX_SPEND_USD` (a local spend seatbelt, default $5).

Every run writes `cost_log.jsonl` (one line per API call, with the model and
temperature actually used) and `outcome_log.jsonl` (one line per logical request:
`ok`, `exhausted`, or `fail_safe`). `run_report.py` summarises both. The
integrity section matters most: a run can finish while quietly falling back to
defaults — every memory scored 4, every agent walking to the kitchen — and that
section is how you would know.

## The social gates

In the shipped code, `decide_to_talk` and `decide_to_react` never reached the
model's judgment. A 20-token cap truncated their step-by-step reasoning before
the answer, and `decide_to_talk`'s parser split on `Answer in yes or no:` while
its own template writes `Answer in "yes" or "no":`. Both fell through to their
fail-safes on every call: talk → `yes`, react → no reaction. So conversation
initiation was effectively decided by the surrounding code filters (both awake,
not 11pm, neither already chatting, cooldown expired).

- `shipped` (default) reproduces that, without spending the calls.
- `working` fixes the parsers so the model actually decides.

If you are comparing against the paper's published results, `shipped` is the
like-for-like baseline.

## Changes from the original

**Model layer** (`persona/prompt_template/gpt_structure.py`)
- openai v1+ SDK; per-model capability table, so no call pays a 400 to discover
  an unsupported parameter; `stop` applied client-side where unsupported.
- The prompts are completion-style — they end mid-sentence, expecting davinci to
  continue. On chat models that needs: a system prompt requiring worked-example
  formatting be copied exactly; not echoing the delimiter a prompt ends on
  (`Answer: {`, an opening quote); and coercing JSON values to strings, since
  every shipped clean-up calls string methods on them.
- `max_completion_tokens` floored at 2000. The davinci-era caps (often 5–50)
  truncated answers; reasoning models also spend that budget thinking and can
  return empty. Output is now bounded by stop sequences and parsers instead.
- Error taxonomy with backoff, spend seatbelt, cost and outcome logging.

**Robustness** — all of these are latent defects in the original, reached more
often by modern models:
- 10 functions returned `None` after exhausted retries, crashing the caller
  several frames away. They now return their declared fail-safe, and log it.
- A failed reflection stored the thought `"this is blank"` in the agent's
  memory, with real evidence links, where it was retrieved later. It now stores
  nothing. Evidence citations pointing past the end of the statement list are
  dropped rather than discarding every insight.
- `task_decomp`'s fail-safe returned a shape its caller cannot unpack; a
  hardcoded index is guarded.
- Parsers made tolerant of format variation without changing their contract:
  decomposition durations, arena braces, wake-up hour (`6:00 AM`), event triples
  (repeated subject, commas inside the object), reflection insights (blank lines
  between items, multi-sentence insights), focal points (real JSON arrays).
  Note that retrying does not fix these at temperature 0, where every attempt
  returns the same answer.
- `revise_identity`'s untemplated calls get their own route, instead of
  inheriting whichever model the previous call happened to use.

**Headless running** (`reverie/backend_server/headless_env.py`)
The backend and the browser talk in lockstep through files, but the browser only
echoes back coordinates the backend's own pathfinder computed — verified against
7,873 steps of a shipped run. This script does that echo, so simulations run
unattended, in parallel, with no Django and no browser. The real frontend is
still there when you want to watch.

**Frontend** — Django 2.2 → 4.2: `url()` → `re_path`, the `staticfiles`
template tag and import moves.

## Limitations

- Not a bit-for-bit reproduction. Different models, and the original was never
  deterministic anyway: most of its tasks ran at temperature 0.5–1.
- Conversations and post-conversation memory writing are not yet exercised by a
  full-day run.
- Costs and behaviour depend on the models in `ROUTES`; change them and re-measure.

## Attribution

Original work and all research credit: Joon Sung Park, Joseph C. O'Brien,
Carrie J. Cai, Meredith Ringel Morris, Percy Liang, Michael S. Bernstein.
Licensed under Apache 2.0; see `LICENSE`. Game assets are by the three artists
credited in `README.md` — please support them, especially if you use the assets.

"""
Wrapper functions for calling OpenAI APIs.

Originally by Joon Sung Park (joonspk@stanford.edu).
Ported 2026: openai-python v1 SDK, chat models, per-call-type model routing,
real error taxonomy, and cost logging.

Public function names and signatures are unchanged, so the ~83 existing call
sites in run_gpt_prompt.py and friends need no edits.
"""
import json
import os
import random
import threading
import time

from openai import (OpenAI, APIConnectionError, APITimeoutError,
                    AuthenticationError, BadRequestError, RateLimitError,
                    InternalServerError, PermissionDeniedError)

from utils import *

_client = OpenAI(api_key=openai_api_key)

# The original prompts were written for text-davinci-003, a completion model:
# they end mid-thought and expect raw continuation. A chat model will happily
# answer conversationally instead ("The wake up hour is 7am."), which fails the
# hand-written __func_validate parsers and burns a retry. This system message
# is what makes 83 legacy prompts work unmodified.
_COMPLETION_SYSTEM = (
    "You are a text completion engine. The user gives you a passage that ends "
    "mid-thought. Output ONLY the text that directly continues it. Never "
    "restate the prompt, never explain, never add labels, quotation marks, or "
    "any preamble. Output nothing but the continuation itself.\n"
    "If the passage contains worked examples, reproduce their formatting "
    "EXACTLY -- the same field labels, punctuation, parentheses and ordering, "
    "character for character -- and change only the content. Downstream "
    "parsers match those labels literally, so a paraphrased format is a "
    "failure even when the meaning is right."
)

# ---------------------------------------------------------------------------
# Routing + accounting
# ---------------------------------------------------------------------------
# generate_prompt() is the only place that knows which template is in play, and
# it is called immediately before the request. The reverie loop is strictly
# single-threaded, so stashing it here is sound; the lock and the logged
# template name make any misattribution visible rather than silent.
# Params a given model rejects, learned on first refusal. Without this every
# call pays a wasted round trip: send temperature -> 400 -> strip -> resend.
# Measured at 158 such retries across 130 calls before this cache existed.
_unsupported = {}

_lock = threading.Lock()
_current_template = "unknown"
_spend_usd = 0.0
_calls = 0


def _route(template):
  """The ROUTES row for a template: model, reasoning effort, original temp."""
  return ROUTES.get(template, DEFAULT_ROUTE)


_warned_temp = set()


def _price(model, usage):
  p = PRICING.get(model)
  if not p or usage is None:
    return 0.0
  cached = getattr(getattr(usage, "prompt_tokens_details", None),
                   "cached_tokens", 0) or 0
  fresh = max((usage.prompt_tokens or 0) - cached, 0)
  out = getattr(usage, "completion_tokens", 0) or 0
  return (fresh * p["in"] + cached * p["cached_in"] + out * p["out"]) / 1e6


def _log(template, model, usage, latency, retries, error=None, temp=None,
         effort=None):
  global _spend_usd, _calls
  cost = _price(model, usage)
  with _lock:
    _spend_usd += cost
    _calls += 1
    total, n = _spend_usd, _calls
  cached = getattr(getattr(usage, "prompt_tokens_details", None),
                   "cached_tokens", 0) or 0 if usage else 0
  rec = {
      "ts": time.time(), "template": template, "model": model,
      "in": getattr(usage, "prompt_tokens", 0) if usage else 0,
      "cached_in": cached,
      "out": getattr(usage, "completion_tokens", 0) if usage else 0,
      "latency_s": round(latency, 3), "retries": retries,
      "cost_usd": round(cost, 8), "cum_usd": round(total, 6), "call_n": n,
      "temp": temp, "effort": effort,
  }
  if error:
    rec["error"] = error
  try:
    with open(COST_LOG, "a") as f:
      f.write(json.dumps(rec) + "\n")
  except OSError:
    pass
  return total


def _template_key(path_or_key):
  if "/" not in path_or_key or not path_or_key.endswith(".txt"):
    return path_or_key
  parts = os.path.normpath(path_or_key).split(os.sep)
  return "/".join([parts[-2], os.path.splitext(parts[-1])[0]])


def _outcome(template, outcome, attempts, reason=None):
  """One line per logical request -- a request may take several API calls.

  outcome: "ok"        a parseable answer was used
           "exhausted" every retry failed validation or errored; the caller
                       then either uses its fail-safe or a fallback prompt
           "fail_safe" the declared fail-safe value was used in place of an answer
  A run's integrity is how rarely the last two happen, per template."""
  rec = {"ts": time.time(), "template": template, "outcome": outcome,
         "attempts": attempts}
  if reason:
    rec["reason"] = reason
  try:
    with open(OUTCOME_LOG, "a") as f:
      f.write(json.dumps(rec) + "\n")
  except OSError:
    pass
  if outcome != "ok":
    print(f"[{outcome}] {template} after {attempts} attempt(s)"
          + (f": {reason}" if reason else ""))


def record_fail_safe(prompt_template, reason="primary path exhausted"):
  """Called by run_gpt_prompt functions when they substitute their fail-safe."""
  _outcome(_template_key(prompt_template), "fail_safe", 0, reason)


class SpendLimitExceeded(RuntimeError):
  pass


def spend_summary():
  return {"calls": _calls, "spend_usd": round(_spend_usd, 4)}


# ---------------------------------------------------------------------------
# Core request
# ---------------------------------------------------------------------------
# 25 of the shipped templates end on a dangling open delimiter -- "Answer: {"
# or a bare opening quote -- because davinci continued straight from it. A chat
# model re-emits that delimiter as part of its answer, so cleanups like
# gpt_response.split("}")[0] return "{kitchen" instead of "kitchen". Stripping a
# leading delimiter that merely echoes the prompt's trailing one fixes the whole
# class, including the conversation templates, in one place.
_OPENERS = {"{": "}", "[": "]", "(": ")", '"': '"', "'": "'", "<": ">"}


def _caps(model):
  best = ""
  for prefix in MODEL_CAPS:
    if model.startswith(prefix) and len(prefix) > len(best):
      best = prefix
  return MODEL_CAPS.get(best, {"temperature": True, "stop": True,
                               "seed": False, "reasoning": False})


def _apply_stop(text, stop):
  """Client-side stop: cut at the earliest stop sequence. Used when the model
  cannot take `stop` server-side -- otherwise the 13 call sites that rely on
  it (12 on newline, 1 on a quote) silently get multi-line answers."""
  if not stop:
    return text
  seqs = [stop] if isinstance(stop, str) else list(stop)
  cut = min((text.find(q) for q in seqs if q and q in text), default=-1)
  return text[:cut] if cut >= 0 else text


def _undouble_delimiter(prompt, text):
  tail = prompt.rstrip()
  if not tail or not text:
    return text
  opener = tail[-1]
  if opener in _OPENERS and text.lstrip().startswith(opener):
    return text.lstrip()[1:].lstrip()
  return text


def _chat(prompt, model=None, max_tokens=512, temperature=None, stop=None,
          system=_COMPLETION_SYSTEM, template=None, max_retries=4):
  """One chat request, with a real error taxonomy.

  The 2023 code wrapped every call in a bare `except:` that returned the
  *string* "TOKEN LIMIT EXCEEDED". That string then failed validation, which
  triggered up to 5 more identical calls -- so an auth error or a rate limit
  silently burned 5 full requests and returned a fail-safe. Here: transient
  errors back off and retry, fatal errors raise immediately.
  """
  template = template or _current_template
  route = _route(template)
  model = model or route["model"]
  # Callers on the gpt-3.5 path never pass a temperature (the original relied on
  # the API default); davinci-path callers pass their original gpt_param value.
  # Either way the ROUTES row holds the original, so fill it in when absent.
  if temperature is None:
    temperature = route.get("temp")

  if _spend_usd >= MAX_SPEND_USD:
    raise SpendLimitExceeded(
        f"Local seatbelt hit: ${_spend_usd:.4f} >= ${MAX_SPEND_USD:.2f} over "
        f"{_calls} calls. Raise SMALLVILLE_MAX_SPEND_USD to continue.")

  # Reasoning-family models spend tokens thinking before emitting. The original
  # max_tokens values were tuned for davinci (often 5-50) and would starve the
  # response to empty -- measured: a 256-token budget produced out=256 and an
  # empty string. Floor generously AND cap the thinking via reasoning_effort.
  budget = max(int(max_tokens or 0), MAX_COMPLETION_FLOOR)

  caps = _caps(model)
  if caps["reasoning"]:
    effort = route.get("effort") or ("none" if model.startswith("gpt-5.1")
                                     else "minimal")
  else:
    effort = None
  kwargs = {
      "model": model,
      "messages": [{"role": "system", "content": system},
                   {"role": "user", "content": prompt}],
      "max_completion_tokens": budget,
  }
  if effort:
    kwargs["reasoning_effort"] = effort
  if stop and caps["stop"]:
    kwargs["stop"] = stop
  temp_ok = (caps["temperature"] is True or
             (caps["temperature"] == "if_no_reasoning" and effort in (None, "none")))
  if temperature is not None and temp_ok:
    kwargs["temperature"] = temperature
  # The decision is original temperatures everywhere, so never sample at a
  # different one silently. ROUTES is validated at import; this catches an
  # explicit model= override that bypasses it.
  temp_effective = kwargs.get("temperature", 1.0)
  if temperature is not None and abs(temp_effective - temperature) > 1e-9:
    if template not in _warned_temp:
      print(f"[temperature] {template}: requested {temperature}, but {model} "
            f"runs at {temp_effective}")
      _warned_temp.add(template)
  if caps["seed"]:
    kwargs["seed"] = SIM_SEED
  # Backstop only: anything the table got wrong is learned once, not per call.
  for bad in _unsupported.get(model, ()):
    kwargs.pop(bad, None)

  delay, last_err = 1.0, None
  for attempt in range(max_retries + 1):
    t0 = time.time()
    try:
      resp = _client.chat.completions.create(**kwargs)
      text = (resp.choices[0].message.content or "").strip()
      text = _undouble_delimiter(prompt, text)
      if stop and "stop" not in kwargs:
        text = _apply_stop(text, stop).strip()
      total = _log(template, model, resp.usage, time.time() - t0, attempt,
                   temp=kwargs.get("temperature", 1.0), effort=effort)
      if total >= MAX_SPEND_USD:
        print(f"[spend] ${total:.4f} of ${MAX_SPEND_USD:.2f} seatbelt used")
      return text

    except BadRequestError as e:
      # Most often an unsupported sampling param for this model family.
      # Strip the optional knobs once and retry before giving up.
      msg = str(e)
      dropped = False
      for k in ("temperature", "stop", "top_p", "frequency_penalty",
                "presence_penalty", "reasoning_effort"):
        if k in msg and k in kwargs:
          kwargs.pop(k)
          _unsupported.setdefault(model, set()).add(k)
          dropped = True
      if dropped:
        continue
      if "max_completion_tokens" in msg and "max_tokens" not in kwargs:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        continue
      _log(template, model, None, time.time() - t0, attempt, error=msg[:200])
      raise

    except (AuthenticationError, PermissionDeniedError) as e:
      # Fatal. Never retry -- this is the case the old code burned 5 calls on.
      _log(template, model, None, time.time() - t0, attempt,
           error=str(e)[:200])
      raise

    except (RateLimitError, APIConnectionError, APITimeoutError,
            InternalServerError) as e:
      last_err = e
      _log(template, model, None, time.time() - t0, attempt,
           error=type(e).__name__)
      if attempt == max_retries:
        break
      time.sleep(delay + random.uniform(0, 0.4))
      delay = min(delay * 2, 30)

  raise last_err


# ---------------------------------------------------------------------------
# Public API -- signatures preserved
# ---------------------------------------------------------------------------
def temp_sleep(seconds=0.1):
  time.sleep(seconds)


def ChatGPT_single_request(prompt):
  # Only caller is plan.revise_identity (4 calls per agent per new day). It has
  # no template, so without an explicit label it would inherit whatever
  # template the previous call used -- wrong model, wrong temperature, wrong log.
  return _chat(prompt, template="revise_identity",
               system="You are a helpful assistant.")


def GPT4_request(prompt):
  return _chat(prompt)


def ChatGPT_request(prompt):
  return _chat(prompt)


def GPT_request(prompt, gpt_parameter):
  """Legacy completion entry point. `engine` is ignored -- text-davinci-00{2,3}
  are long dead, and the model is chosen by routing on the prompt template."""
  try:
    return _chat(
        prompt,
        max_tokens=gpt_parameter.get("max_tokens", 512),
        temperature=gpt_parameter.get("temperature"),
        stop=gpt_parameter.get("stop"))
  except SpendLimitExceeded:
    raise
  except Exception as e:
    print(f"[gpt_structure] {type(e).__name__}: {str(e)[:160]}")
    return "GENERATION ERROR"


def generate_prompt(curr_input, prompt_lib_file):
  """Unchanged behaviour, plus: records the template so _chat can route on it."""
  global _current_template
  if type(curr_input) == type("string"):
    curr_input = [curr_input]
  curr_input = [str(i) for i in curr_input]

  # "<dir>/<name>", e.g. "v3_ChatGPT/memo_on_convo_v1" -- names collide across dirs
  _parts = os.path.normpath(prompt_lib_file).split(os.sep)
  _current_template = "/".join([_parts[-2], os.path.splitext(_parts[-1])[0]])

  with open(prompt_lib_file, "r") as f:
    prompt = f.read()
  for count, i in enumerate(curr_input):
    prompt = prompt.replace(f"!<INPUT {count}>!", i)
  if "<commentblockmarker>###</commentblockmarker>" in prompt:
    prompt = prompt.split("<commentblockmarker>###</commentblockmarker>")[1]
  return prompt.strip()


def _safe_loop(prompt, repeat, fail_safe_response, func_validate,
               func_clean_up, verbose, requester):
  template = _current_template
  reason = "validation failed on every attempt"
  for i in range(repeat):
    try:
      curr = requester(prompt).strip()
    except SpendLimitExceeded:
      raise
    except Exception as e:
      _outcome(template, "fail_safe", i + 1, f"{type(e).__name__}: {str(e)[:100]}")
      return fail_safe_response
    try:
      if func_validate(curr, prompt=prompt):
        out = func_clean_up(curr, prompt=prompt)
        _outcome(template, "ok", i + 1)
        return out
    except Exception as e:
      # The 2023 code swallowed this silently, so a parser that could never
      # match burned all 5 retries and returned a fail-safe with no clue why.
      reason = f"clean_up {type(e).__name__}: {str(e)[:80]}"
      print(f"[{template}] {reason}")
    if verbose:
      print(f"---- [{template}] repeat {i}: {curr[:160]}")
  _outcome(template, "fail_safe", repeat, reason)
  return fail_safe_response


def safe_generate_response(prompt, gpt_parameter, repeat=5,
                           fail_safe_response="error", func_validate=None,
                           func_clean_up=None, verbose=False):
  if verbose:
    print(prompt)
  return _safe_loop(prompt, repeat, fail_safe_response, func_validate,
                    func_clean_up, verbose,
                    lambda p: GPT_request(p, gpt_parameter))


def _json_wrapped(prompt, example_output, special_instruction, repeat,
                  fail_safe_response, func_validate, func_clean_up, verbose,
                  model):
  prompt = '"""\n' + prompt + '\n"""\n'
  prompt += f"Output the response to the prompt above in json. {special_instruction}\n"
  prompt += "Example output json:\n"
  prompt += '{"output": "' + str(example_output) + '"}'
  template = _current_template

  for i in range(repeat):
    try:
      raw = _chat(prompt, model=model, system="Respond with a single JSON "
                  "object and nothing else.").strip()
      end = raw.rfind("}") + 1
      curr = json.loads(raw[:end])["output"]
      # The 2023 callers all assume a STRING here (their clean-ups call
      # .strip()). Modern models honour instructions like "ONLY ONE integer"
      # literally and emit {"output": 1}, so .strip() throws, validation fails,
      # every retry burns and the caller falls through to an implicit None.
      # Coerce everything back to text -- every shipped clean-up expects a string.
      # Lists too: focal_pt asks for "a list of str", gets a real JSON array,
      # and its clean-up is ast.literal_eval(<string>) -- which rejects a list.
      if not isinstance(curr, str):
        curr = str(curr)
      if func_validate(curr, prompt=prompt):
        out = func_clean_up(curr, prompt=prompt)
        _outcome(template, "ok", i + 1)
        return out
      if verbose:
        print(f"---- [{template}] repeat {i}: {curr}")
    except SpendLimitExceeded:
      raise
    except Exception as e:
      last = f"{type(e).__name__}: {str(e)[:80]}"
      if verbose:
        print(f"---- [{template}] repeat {i} failed: {type(e).__name__}")
  _outcome(template, "exhausted", repeat,
           locals().get("last", "validation failed on every attempt"))
  return False


def ChatGPT_safe_generate_response(prompt, example_output, special_instruction,
                                   repeat=3, fail_safe_response="error",
                                   func_validate=None, func_clean_up=None,
                                   verbose=False):
  return _json_wrapped(prompt, example_output, special_instruction, repeat,
                       fail_safe_response, func_validate, func_clean_up,
                       verbose, None)


def GPT4_safe_generate_response(prompt, example_output, special_instruction,
                                repeat=3, fail_safe_response="error",
                                func_validate=None, func_clean_up=None,
                                verbose=False):
  return _json_wrapped(prompt, example_output, special_instruction, repeat,
                       fail_safe_response, func_validate, func_clean_up,
                       verbose, None)


def ChatGPT_safe_generate_response_OLD(prompt, repeat=3,
                                       fail_safe_response="error",
                                       func_validate=None, func_clean_up=None,
                                       verbose=False):
  out = _safe_loop(prompt, repeat, fail_safe_response, func_validate,
                   func_clean_up, verbose, ChatGPT_request)
  if out == fail_safe_response:
    print("FAIL SAFE TRIGGERED")
  return out


def get_embedding(text, model=None):
  model = model or EMBEDDING_MODEL
  text = text.replace("\n", " ")
  if not text:
    text = "this is blank"
  t0 = time.time()
  resp = _client.embeddings.create(input=[text], model=model)
  _log("embedding", model, resp.usage, time.time() - t0, 0)
  return resp.data[0].embedding

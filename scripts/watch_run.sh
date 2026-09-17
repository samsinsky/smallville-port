#!/bin/bash
# usage: watch_run.sh <sim_code> <total_steps>
SIM=$1; TOTAL=$2
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; LOG=$ROOT/runs/$SIM; S=$ROOT/environment/frontend_server/storage/$SIM
last_bucket=-1; seen_err=""; convo_seen=0; t0=$(date +%s)
while true; do
  n=$(find "$S/movement" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  err=$(grep -aoE "Traceback \(most recent call last\)|SpendLimitExceeded|KeyError: [^\"]{0,40}|TypeError: [^\"]{0,40}" "$LOG/backend.log" 2>/dev/null | sort -u | tr '\n' ' ')
  if [ -n "$err" ] && [ "$err" != "$seen_err" ]; then echo "ERROR near step $n: $err"; seen_err="$err"; fi
  if [ "$convo_seen" = 0 ] && [ "$n" -gt 0 ] && grep -q '"chat": \[' "$S/movement/$((n-1)).json" 2>/dev/null; then
    echo "FIRST CONVERSATION at step $((n-1))"; convo_seen=1; fi
  bucket=$((n/500))
  if [ "$bucket" -ne "$last_bucket" ] && [ "$n" -gt 0 ]; then
    calls=$(wc -l < "$LOG/cost_log.jsonl" 2>/dev/null | tr -d ' ')
    cost=$(python3 -c "import json;print('%.3f'%sum(json.loads(l)['cost_usd'] for l in open('$LOG/cost_log.jsonl')))" 2>/dev/null)
    fs=$(grep -c '"outcome": "fail_safe"' "$LOG/outcome_log.jsonl" 2>/dev/null)
    echo "step $n/$TOTAL | $(( ($(date +%s)-t0)/60 ))m | calls ${calls:-0} | \$${cost:-0} | fail-safes ${fs:-0}"
    last_bucket=$bucket
  fi
  if ! pgrep -f "drive_run.sh $SIM" >/dev/null; then
    echo "RUN ENDED at step $n | calls $(wc -l < "$LOG/cost_log.jsonl" 2>/dev/null | tr -d ' ')"; break
  fi
  sleep 20
done

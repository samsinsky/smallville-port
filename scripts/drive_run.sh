#!/bin/bash
# Run a simulation headless (no browser) and keep its logs in runs/<sim_code>/.
#
# usage: scripts/drive_run.sh <sim_code> <steps> <shipped|working> [base_sim]
#   shipped|working  SMALLVILLE_SOCIAL_GATE; see ROUTES/SOCIAL_GATE in utils.py
#
# Long runs outlive a terminal session; launch detached:
#   nohup scripts/drive_run.sh my_sim 3000 shipped > /dev/null 2>&1 &
# and follow progress with:
#   scripts/watch_run.sh my_sim 3000
# Replay afterwards in the Phaser frontend: /replay/<sim_code>/1/
set -u
SIM=$1; STEPS=$2; GATE=$3; BASE=${4:-base_the_ville_isabella_maria_klaus}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd $ROOT/reverie/backend_server
VP=$ROOT/.venv/bin/python
export SMALLVILLE_SOCIAL_GATE=$GATE
export SMALLVILLE_LOG_DIR=$ROOT/runs/$SIM
rm -rf $ROOT/environment/frontend_server/storage/$SIM "$SMALLVILLE_LOG_DIR"
mkdir -p "$SMALLVILLE_LOG_DIR"
printf '{"sim": "%s", "base": "%s", "steps": %s, "social_gate": "%s", "started": "%s"}\n' \
  "$SIM" "$BASE" "$STEPS" "$GATE" "$(date -u +%FT%TZ)" > "$SMALLVILLE_LOG_DIR/run_config.json"
$VP headless_env.py $SIM > "$SMALLVILLE_LOG_DIR/stepper.log" 2>&1 &
ST=$!
printf '%s\n%s\nrun %s\nfin\n' "$BASE" "$SIM" "$STEPS" | $VP reverie.py > "$SMALLVILLE_LOG_DIR/backend.log" 2>&1
kill $ST 2>/dev/null
echo "=== backend exited ==="

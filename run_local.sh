#!/usr/bin/env bash
# File: run_local.sh
set -e

# Clear previous logs and local DBs
rm -f gov.log orch.log governance.db orchestrator.db

echo "============================================="
echo "⚙️  1. Setting up Python Virtual Environment"
echo "============================================="
python3 -m venv venv
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -q \
  -r apps/governance-engine/requirements.txt \
  -r apps/agent-orchestrator/requirements.txt \
  httpx

echo "============================================="
echo "🔐 2. Loading .env Configuration"
echo "============================================="
set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a

echo "============================================="
echo "🚀 3. Launching Backend Services"
echo "============================================="
echo "Starting Governance Engine on http://localhost:8000..."
PYTHONPATH=. venv/bin/uvicorn apps.governance-engine.main:app --port 8000 > gov.log 2>&1 &
GOV_PID=$!

echo "Starting Agent Orchestrator on http://localhost:8001..."
PYTHONPATH=. venv/bin/uvicorn apps.agent-orchestrator.main:app --port 8001 > orch.log 2>&1 &
ORCH_PID=$!

# Trapping exit signals to stop background servers automatically
cleanup() {
    echo "============================================="
    echo "🛑 4. Shutting Down Services"
    echo "============================================="
    echo "Killing processes: GOV_PID=$GOV_PID, ORCH_PID=$ORCH_PID"
    kill $GOV_PID $ORCH_PID 2>/dev/null || true
    wait $GOV_PID $ORCH_PID 2>/dev/null || true
    echo "Cleanup complete."
}
trap cleanup EXIT

echo "============================================="
echo "🧪 5. Running Integration Tests"
echo "============================================="
# Run the python test flow
venv/bin/python test_flow.py

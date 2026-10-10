#!/bin/bash
# Runs inside the agent image. Starts the diagnostics agent, runs the evaluation harness against it,
# prints the results table, then stops the agent. Usable locally (docker compose run) or as a
# Nebius Serverless Job command. Sources ROS itself in case the container entrypoint is overridden.
#
# Environment: NEBIUS / Tavily keys (as named in .env.example), plus optional RUNS, SEVERITIES, TIMEOUT, GAP.

source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash

ros2 run atide_diagnostics_agent diagnostics_agent_node &
AGENT_PID=$!

python3 /ws/src/A.T.I.D.E./docker/eval_harness.py
STATUS=$?

kill "$AGENT_PID" 2>/dev/null
wait "$AGENT_PID" 2>/dev/null
exit "$STATUS"

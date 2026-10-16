#!/bin/bash
# Scenario evaluation inside the agent image: does the decision depend on the operating context?
# Starts the agent with use_context:=true, runs eval_scenarios.py, stops the agent.
# Environment: keys as in .env.example; optional RUNS (default 10), ONLY (comma list of scenario names), TIMEOUT, GAP.
source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash

ros2 run atide_diagnostics_agent diagnostics_agent_node --ros-args -p use_context:=true &
AGENT_PID=$!

python3 /ws/src/A.T.I.D.E./docker/eval_scenarios.py
STATUS=$?

kill "$AGENT_PID" 2>/dev/null
wait "$AGENT_PID" 2>/dev/null
exit "$STATUS"

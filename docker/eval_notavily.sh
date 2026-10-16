#!/bin/bash
# Tavily ablation: the same evaluation as eval.sh, but the agent skips the Tavily search
# (use_tavily:=false), so the prompt carries "(no context retrieved)" in the guidance slot.
# Compare the table with the one from eval.sh (same RUNS, same model, same temperature).
source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash

ros2 run atide_diagnostics_agent diagnostics_agent_node --ros-args -p use_tavily:=false &
AGENT_PID=$!

python3 /ws/src/A.T.I.D.E./docker/eval_harness.py
STATUS=$?

kill "$AGENT_PID" 2>/dev/null
wait "$AGENT_PID" 2>/dev/null
exit "$STATUS"

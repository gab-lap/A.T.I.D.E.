#!/bin/bash
# Runs inside the container. Starts the diagnostics agent and the hardcoded baseline,
# then injects an intermittent and a complete fault, so both decisions print side by side.
# Keys come from the environment (docker compose env_file), not from a .env file.

WAIT_FOR_AGENT=${WAIT_FOR_AGENT:-30}   # seconds to let Tavily + Nemotron finish

ros2 run atide_diagnostics_agent baseline_agent_node &
BASELINE_PID=$!

ros2 run atide_diagnostics_agent diagnostics_agent_node &
AGENT_PID=$!

sleep 6   # let both nodes start and discover each other

inject() {
  ros2 topic pub --once --wait-matching-subscriptions 1 \
    /fault_severity std_msgs/msg/String "{data: '$1'}" > /dev/null
}

for severity in intermittent complete; do
  echo
  echo "================ injecting fault: $severity ================"
  inject "$severity"
  sleep "$WAIT_FOR_AGENT"
  inject none
  sleep 2
done

echo
echo "================ demo finished ================"
kill "$BASELINE_PID" "$AGENT_PID" 2>/dev/null
wait "$BASELINE_PID" "$AGENT_PID" 2>/dev/null
exit 0
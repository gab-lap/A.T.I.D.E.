#!/usr/bin/env python3
"""
A.T.I.D.E. evaluation harness.

Injects faults on /fault_severity, waits for the diagnostics agent's answer on
/recovery_decision, and tabulates the decision distribution and latency per severity.
It only depends on those two topics, not on the agent's internals.

Configuration through environment variables:
  SEVERITIES  comma-separated list            (default: intermittent,complete)
  RUNS        repetitions per severity        (default: 10)
  TIMEOUT     seconds to wait for a decision  (default: 90)
  GAP         seconds to pause between runs   (default: 3)
"""

import json
import os
import statistics
import sys
import time
from collections import Counter

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

SEVERITIES = os.environ.get('SEVERITIES', 'intermittent,complete').split(',')
RUNS = int(os.environ.get('RUNS', '10'))
TIMEOUT = float(os.environ.get('TIMEOUT', '90'))
GAP = float(os.environ.get('GAP', '3'))


class EvalHarness(Node):
    def __init__(self):
        super().__init__('atide_eval_harness')
        self.pub = self.create_publisher(String, '/fault_severity', 10)
        self.sub = self.create_subscription(
            String, '/recovery_decision', self.on_decision, 10)
        self.last_decision = None

    def on_decision(self, msg: String):
        self.last_decision = msg.data

    def spin_for(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.1)

    def wait_for_agent(self, timeout: float = 90.0) -> bool:
        """Wait until the agent is subscribed to our faults and publishing decisions."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.2)
            if (self.pub.get_subscription_count() > 0
                    and self.sub.get_publisher_count() > 0):
                self.spin_for(2.0)  # let discovery settle
                return True
        return False

    def publish(self, value: str):
        msg = String()
        msg.data = value
        self.pub.publish(msg)

    def run_one(self, severity: str):
        """Returns (decision or 'TIMEOUT', seconds until the decision)."""
        self.last_decision = None
        start = time.monotonic()
        self.publish(severity)
        while time.monotonic() - start < TIMEOUT:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.last_decision is not None:
                return self.last_decision, time.monotonic() - start
        return 'TIMEOUT', TIMEOUT


def main():
    rclpy.init()
    node = EvalHarness()

    if not node.wait_for_agent():
        print('ERROR: diagnostics agent not found (no subscriber on /fault_severity '
              'or no publisher on /recovery_decision).', file=sys.stderr)
        node.destroy_node()
        rclpy.shutdown()
        return 1

    results = {}
    for severity in SEVERITIES:
        decisions, latencies = [], []
        for i in range(1, RUNS + 1):
            decision, latency = node.run_one(severity)
            decisions.append(decision)
            latencies.append(latency)
            print(f'[{severity}] run {i}/{RUNS}: {decision} ({latency:.1f}s)', flush=True)
            node.publish('none')        # reset the fault between runs
            node.spin_for(GAP)
        results[severity] = {
            'runs': RUNS,
            'decisions': dict(Counter(decisions)),
            'median_latency_s': round(statistics.median(latencies), 1),
        }

    actions = sorted({a for r in results.values() for a in r['decisions']})
    print('\n| severity | runs | ' + ' | '.join(actions) + ' | median latency (s) |')
    print('|---|---|' + '---|' * len(actions) + '---|')
    for severity, r in results.items():
        cells = ' | '.join(str(r['decisions'].get(a, 0)) for a in actions)
        print(f"| {severity} | {r['runs']} | {cells} | {r['median_latency_s']} |")
    print('\n' + json.dumps(results, indent=2))

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())

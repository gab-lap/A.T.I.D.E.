#!/usr/bin/env python3
"""A.T.I.D.E. scenario evaluation: does the agent's decision depend on the operating context? DRAFT, untested.

For each scenario in scenarios.json, N times: publish the context on /fault_context (JSON, skipped when the
scenario has none), then the severity on /fault_severity, wait for /recovery_decision, reset with 'none'.
Prints a table per scenario next to the hypothesis written BEFORE the run (commit scenarios.json first).
Needs the agent running with context enabled (use_context:=true); it works without Gazebo.

Environment: SCENARIOS_FILE (default ./scenarios.json), RUNS (10), TIMEOUT (90), GAP (3), ONLY (comma list of names)
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

SCENARIOS_FILE = os.environ.get('SCENARIOS_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scenarios.json'))
RUNS = int(os.environ.get('RUNS', '10'))
TIMEOUT = float(os.environ.get('TIMEOUT', '90'))
GAP = float(os.environ.get('GAP', '3'))
ONLY = [s for s in os.environ.get('ONLY', '').split(',') if s]


class Harness(Node):
    def __init__(self):
        super().__init__('atide_scenario_harness')
        self.fault_pub = self.create_publisher(String, '/fault_severity', 10)
        self.ctx_pub = self.create_publisher(String, '/fault_context', 10)
        self.sub = self.create_subscription(String, '/recovery_decision', self.on_decision, 10)
        self.last = None

    def on_decision(self, msg):
        self.last = msg.data

    def spin_for(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)

    def wait_for_agent(self, timeout=90.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.2)
            if self.fault_pub.get_subscription_count() > 0 and self.sub.get_publisher_count() > 0:
                self.spin_for(2.0)
                return True
        return False

    def run_one(self, severity, context):
        self.last = None
        if context is not None:
            m = String(); m.data = json.dumps(context)
            self.ctx_pub.publish(m)
            self.spin_for(0.5)       # let the agent store the context before the fault arrives
        start = time.monotonic()
        m = String(); m.data = severity
        self.fault_pub.publish(m)
        while time.monotonic() - start < TIMEOUT:
            rclpy.spin_once(self, timeout_sec=0.05)
            if self.last is not None:
                return self.last, time.monotonic() - start
        return 'TIMEOUT', TIMEOUT


def main():
    scenarios = json.load(open(SCENARIOS_FILE))
    if ONLY:
        scenarios = [s for s in scenarios if s['name'] in ONLY]
    rclpy.init()
    h = Harness()
    if not h.wait_for_agent():
        print('ERROR: diagnostics agent not found', file=sys.stderr)
        return 1
    results = {}
    for sc in scenarios:
        decisions, lat = [], []
        for i in range(1, RUNS + 1):
            d, t = h.run_one(sc['severity'], sc.get('context'))
            decisions.append(d); lat.append(t)
            print(f"[{sc['name']}] run {i}/{RUNS}: {d} ({t:.1f}s)", flush=True)
            m = String(); m.data = 'none'; h.fault_pub.publish(m)
            h.spin_for(GAP)
        results[sc['name']] = {'severity': sc['severity'], 'runs': RUNS, 'decisions': dict(Counter(decisions)),
                               'median_latency_s': round(statistics.median(lat), 1),
                               'hypothesis': sc.get('hypothesis', '')}
    actions = ['HALT', 'RETRY_NAVIGATION', 'REVERSE_AND_REPLAN']
    extra = sorted({a for r in results.values() for a in r['decisions']} - set(actions))
    cols = actions + extra
    print('\n| scenario | severity | runs | ' + ' | '.join(cols) + ' | median latency (s) |')
    print('|---|---|---|' + '---|' * len(cols) + '---|')
    for name, r in results.items():
        print(f"| {name} | {r['severity']} | {r['runs']} | " + ' | '.join(str(r['decisions'].get(a, 0)) for a in cols)
              + f" | {r['median_latency_s']} |")
    print('\nHypotheses (written before the run):')
    for name, r in results.items():
        print(f"- {name}: {r['hypothesis']}")
    print('\n' + json.dumps(results, indent=2))
    h.destroy_node(); rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())

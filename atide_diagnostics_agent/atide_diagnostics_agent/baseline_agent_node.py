"""
Hardcoded baseline -- the control group for the demo comparison.

Implements the naive rule a conventional system would use: any sensor fault
means stop. It has no retrieval, no reasoning, and no way to tell a
recoverable intermittent glitch from a genuine total failure. That inability
is the point: it is what the LLM pipeline is measured against.

Publishes to /baseline_decision, NOT /recovery_decision, so it can run
side by side with the real agent without competing for the robot. The
recovery executor never listens to this topic.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class BaselineAgentNode(Node):
    def __init__(self):
        super().__init__('baseline_agent_node')

        self.declare_parameter('fault_topic', '/fault_severity')
        self.declare_parameter('decision_topic', '/baseline_decision')

        fault_topic = self.get_parameter('fault_topic').value
        decision_topic = self.get_parameter('decision_topic').value

        self.sub = self.create_subscription(
            String, fault_topic, self.on_severity, 10)
        self.pub = self.create_publisher(String, decision_topic, 10)

        # /fault_severity is republished at ~5 Hz, so react only to changes.
        self.last_severity = 'none'

        self.get_logger().info(
            f'baseline_agent_node up (rule: any fault -> HALT, '
            f'{fault_topic} -> {decision_topic})')

    def on_severity(self, msg: String):
        severity = msg.data
        if severity == self.last_severity:
            return
        self.last_severity = severity

        if severity == 'none':
            self.get_logger().info('[BASELINE] fault cleared')
            return

        out = String()
        out.data = 'HALT'
        self.pub.publish(out)
        self.get_logger().info(f'[BASELINE] severity={severity} -> HALT')


def main(args=None):
    rclpy.init(args=args)
    node = BaselineAgentNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

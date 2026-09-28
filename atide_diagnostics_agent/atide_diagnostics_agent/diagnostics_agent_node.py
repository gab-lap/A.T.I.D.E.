"""
Diagnostics Agent -- the reasoning layer of A.T.I.D.E.

Deliberately robot-agnostic: the topic name is a
parameter, not hardcoded, so the same node can watch a different robot's
fault topic just by overriding one launch argument.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class DiagnosticsAgentNode(Node):
    def __init__(self):
        super().__init__('diagnostics_agent_node')

        # Parameter, not a hardcoded string
        self.severity_topic = self.declare_parameter('severity_topic', '/fault_severity').value

        # Edge-triggered state: we only want to react to a CHANGE in
        # severity, not to every single message (the fault trigger
        # publishes at 5Hz regardless of whether anything changed).
        self.last_severity = 'none'

        self.severity_sub = self.create_subscription(
            String, self.severity_topic, self.on_severity, 10)

        self.get_logger().info(
            f'diagnostics_agent_node up. watching {self.severity_topic}')

    def on_severity(self, msg: String):
        severity = msg.data
        if severity == self.last_severity:
            return
        self.last_severity = severity
        self.get_logger().info(f'>>> fault_severity changed to: {severity}')


def main(args=None):
    rclpy.init(args=args)
    node = DiagnosticsAgentNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()

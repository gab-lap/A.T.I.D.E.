#!/usr/bin/env python3
"""Publishes the operating context for the diagnostics agent on /fault_context (std_msgs/String, JSON).
DRAFT, untested with ROS.

It watches the LiDAR (/scan_filtered) only while there is no fault, so "nearest obstacle" is the last reliable
reading and its age grows once a fault starts. It also reports speed (/odom), distance to the goal (parameters
goal_x / goal_y, odom frame == map frame in this project) and how long the fault has lasted (/fault_severity).

Run with the simulation (same use_sim_time as the other nodes):
  ros2 run atide_diagnostics_agent fault_context_node --ros-args -p use_sim_time:=true \
      -p goal_x:=18.0 -p goal_y:=0.0
"""
import json

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

try:
    from atide_diagnostics_agent.fault_context import ContextTracker
except ImportError:  # running the file directly from the context/ folder
    from fault_context import ContextTracker


class FaultContextNode(Node):
    def __init__(self):
        super().__init__("fault_context_node")
        self.declare_parameter("scan_topic", "/scan_filtered")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("severity_topic", "/fault_severity")
        self.declare_parameter("context_topic", "/fault_context")
        self.declare_parameter("goal_x", 18.0)   # CONFIRM: the goal the executor sends (log showed 18.0, 0.0)
        self.declare_parameter("goal_y", 0.0)
        self.declare_parameter("publish_hz", 2.0)
        self.declare_parameter("front_half_width_deg", 15.0)

        p = self.get_parameter
        self.tracker = ContextTracker(goal=(p("goal_x").value, p("goal_y").value),
                                      half_width_deg=p("front_half_width_deg").value)
        self.pub = self.create_publisher(String, p("context_topic").value, 10)
        self.create_subscription(LaserScan, p("scan_topic").value, self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, p("odom_topic").value, self.on_odom, qos_profile_sensor_data)
        self.create_subscription(String, p("severity_topic").value, self.on_severity, 10)
        self.create_timer(1.0 / p("publish_hz").value, self.on_timer)
        self.get_logger().info("fault_context_node up: publishing /fault_context")

    def _now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def on_scan(self, msg: LaserScan):
        self.tracker.on_scan(self._now(), msg.ranges, msg.angle_min, msg.angle_increment,
                             msg.range_min, msg.range_max)

    def on_odom(self, msg: Odometry):
        pos = msg.pose.pose.position
        tw = msg.twist.twist.linear
        self.tracker.on_odom(pos.x, pos.y, tw.x, tw.y)

    def on_severity(self, msg: String):
        before = self.tracker.severity
        self.tracker.on_severity(self._now(), msg.data)
        if self.tracker.severity != before:
            self.get_logger().info(f"severity {before} -> {self.tracker.severity}")

    def on_timer(self):
        out = String()
        out.data = json.dumps(self.tracker.snapshot(self._now()))
        self.pub.publish(out)


def main():
    rclpy.init()
    node = FaultContextNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
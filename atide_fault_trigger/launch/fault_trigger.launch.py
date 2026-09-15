from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    fault_mode_arg = DeclareLaunchArgument(
        "fault_mode", default_value="none",
        description="Startup fault mode: none | intermittent | complete"
    )
    intermittent_rate_arg = DeclareLaunchArgument(
        "intermittent_rate", default_value="3",
        description="Forward 1 out of every N scans in intermittent mode"
    )
    auto_trigger_arg = DeclareLaunchArgument(
        "auto_trigger", default_value="false",
        description="If true, automatically toggle the fault on a timer (soak-testing only)"
    )
    fault_period_arg = DeclareLaunchArgument(
        "fault_period_sec", default_value="15.0",
        description="Seconds between automatic toggles, if auto_trigger is true"
    )

    fault_trigger_node = Node(
        package="atide_fault_trigger",
        executable="fault_trigger_node",
        name="fault_trigger_node",
        output="screen",
        parameters=[{
            "fault_mode": LaunchConfiguration("fault_mode"),
            "intermittent_rate": LaunchConfiguration("intermittent_rate"),
            "auto_trigger": LaunchConfiguration("auto_trigger"),
            "fault_period_sec": LaunchConfiguration("fault_period_sec"),
        }],
    )

    return LaunchDescription([
        fault_mode_arg,
        intermittent_rate_arg,
        auto_trigger_arg,
        fault_period_arg,
        fault_trigger_node,
    ])

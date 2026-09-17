import os
import xacro
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    pkg_atide_bringup = get_package_share_directory('atide_bringup')
    pkg_ros_gz_sim = get_package_share_directory('ros_gz_sim')
    pkg_turtlebot3_desc = get_package_share_directory('turtlebot3_description')
    pkg_nav2_bringup = get_package_share_directory('nav2_bringup')

    # FIX: tunnel.sdf now lives inside atide_bringup's own share dir, not a
    # nonexistent "A.T.I.D.E." package. Copy worlds/tunnel.sdf into
    # atide_bringup/worlds/ before building.
    world_path = os.path.join(pkg_atide_bringup, 'worlds', 'tunnel.sdf')
    bridge_config_path = os.path.join(pkg_atide_bringup, 'config', 'bridge_config.yaml')
    nav2_params_path = os.path.join(pkg_atide_bringup, 'config', 'nav2_params.yaml')

    # FIX: turtlebot3_description ships .urdf.xacro, not a pre-expanded .urdf.
    # Process it here instead of assuming a plain file exists.

    # xacro_path = os.path.join(pkg_turtlebot3_desc, 'urdf', 'turtlebot3_waffle.urdf.xacro')
    # robot_desc = xacro.process_file(xacro_path).toxml()
    urdf_path = os.path.join(pkg_turtlebot3_desc, 'urdf', 'turtlebot3_waffle.urdf')
    with open(urdf_path, 'r') as infp:
        robot_desc = infp.read()

    # 1. Start Gazebo Harmonic with tunnel.sdf
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_ros_gz_sim, 'launch', 'gz_sim.launch.py')
        ),
        launch_arguments={'gz_args': f'-r {world_path}'}.items(),
    )

    # 2. Publish Robot Description (TF tree)
    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'use_sim_time': True, 'robot_description': robot_desc}],
    )

    # 3. Spawn TurtleBot3 Waffle inside Gazebo at start marker (x=1.0, y=0.0)
    spawn_rover = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=[
            '-string', robot_desc,
            '-name', 'waffle',
            '-x', '1.0',
            '-y', '0.0',
            '-z', '0.1',
        ],
        output='screen',
    )

    # 4. Start Gazebo-ROS Bridge
    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        parameters=[{'config_file': bridge_config_path}],
        output='screen',
    )

    # 5. Start ATIDE Fault Trigger Node
    fault_trigger = Node(
        package='atide_fault_trigger',
        executable='fault_trigger_node',
        name='fault_trigger_node',
        output='screen',
        parameters=[{'fault_mode': 'none'}],
    )

    # 6. FIX (new): a fake "map" frame, since we're not running real
    # localization for a single-corridor demo. Nav2's costmaps still expect
    # a map frame to exist in TF even without AMCL — an identity transform
    # is a legitimate stand-in when you already know the start pose.
    map_to_odom = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='map_to_odom_static_tf',
        arguments=['0', '0', '0', '0', '0', '0', 'map', 'odom'],
    )

    # 7. FIX (new): Nav2 was configured (nav2_params.yaml) but never actually
    # launched. navigation_launch.py (not bringup_launch.py) is used
    # deliberately — it starts the planner/controller/behavior servers and
    # the lifecycle manager, WITHOUT AMCL/map_server, matching the fake-map
    # approach above instead of real localization.
    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_nav2_bringup, 'launch', 'navigation_launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'true',
            'params_file': nav2_params_path,
            'autostart': 'true',
        }.items(),
    )

    return LaunchDescription([
        gazebo,
        robot_state_publisher,
        spawn_rover,
        bridge,
        fault_trigger,
        map_to_odom,
        nav2,
    ])

// recovery_executor_node.cpp
//
// Consumes /recovery_decision and turns it into robot motion by driving
// Nav2 -- not by fighting it:
//   HALT               -> cancel the nav goal and any back-up, publish zero velocity
//   RETRY_NAVIGATION   -> re-send the navigation goal
//   REVERSE_AND_REPLAN -> cancel the nav goal, wait for Nav2 to confirm the
//                         cancel, run Nav2's BackUp behavior, then re-send the goal
//
// Deliberately contains no intelligence: all reasoning lives in the
// diagnostics agent. This node only translates a decision into actuation,
// so "what decided this?" always has a one-place answer.
//
// Why BackUp instead of publishing /cmd_vel: the behavior goes through
// behavior_server -> velocity_smoother -> collision_monitor, so the reverse
// maneuver keeps Nav2's acceleration limits and its last-resort collision
// check. The only direct /cmd_vel publish left is the zero-velocity stop in
// HALT, which is a deliberate bypass: an emergency stop should not wait on
// the pipeline.
//
// Threading: default single-threaded executor, so the plain bool flags below
// are only ever touched from one thread. Revisit if that changes.

#include <chrono>
#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"
#include "std_msgs/msg/string.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "nav2_msgs/action/navigate_to_pose.hpp"
#include "nav2_msgs/action/back_up.hpp"

using NavigateToPose = nav2_msgs::action::NavigateToPose;
using BackUp = nav2_msgs::action::BackUp;
using NavGoalHandle = rclcpp_action::ClientGoalHandle<NavigateToPose>;
using BackUpGoalHandle = rclcpp_action::ClientGoalHandle<BackUp>;

class RecoveryExecutorNode : public rclcpp::Node
{
public:
  RecoveryExecutorNode() : Node("recovery_executor_node")
  {
    // Goal is in the MAP frame. map is anchored to the rover's spawn pose, so
    // map x = Gazebo world x - 1.0. The green goal marker at world x=19 is
    // therefore map x=18.
    goal_x_ = this->declare_parameter<double>("goal_x", 18.0);
    goal_y_ = this->declare_parameter<double>("goal_y", 0.0);
    reverse_distance_ = this->declare_parameter<double>("reverse_distance", 0.3);
    reverse_speed_ = this->declare_parameter<double>("reverse_speed", 0.1);
    reverse_timeout_sec_ = this->declare_parameter<double>("reverse_timeout_sec", 10.0);
    // The action server is named after the behavior's plugin ID in
    // nav2_params.yaml ("backup"), not after the action type. Verify with
    // `ros2 action list`.
    backup_action_name_ = this->declare_parameter<std::string>("backup_action_name", "backup");
    send_initial_goal_ = this->declare_parameter<bool>("send_initial_goal", true);

    nav_client_ = rclcpp_action::create_client<NavigateToPose>(this, "navigate_to_pose");
    backup_client_ = rclcpp_action::create_client<BackUp>(this, backup_action_name_);
    cmd_vel_pub_ = this->create_publisher<geometry_msgs::msg::Twist>("/cmd_vel", 10);

    decision_sub_ = this->create_subscription<std_msgs::msg::String>(
      "/recovery_decision", 10,
      [this](const std_msgs::msg::String::SharedPtr msg) { this->on_decision(msg); });

    // Nav2 takes a while to come up (lifecycle manager). Instead of blocking
    // in the constructor, poll once a second until the action server is ready
    // AND accepts the goal -- a goal sent between configure and activate is
    // rejected, and this loop simply retries on the next tick.
    if (send_initial_goal_) {
      startup_timer_ = this->create_wall_timer(
        std::chrono::seconds(1), [this]() { this->try_initial_goal(); });
    }

    RCLCPP_INFO(this->get_logger(),
      "recovery_executor_node up. goal=(%.1f, %.1f) backup_action='%s'",
      goal_x_, goal_y_, backup_action_name_.c_str());
  }

private:
  // ---------------------------------------------------------------- startup
  void try_initial_goal()
  {
    if (awaiting_goal_response_) {
      return;
    }
    if (!nav_client_->action_server_is_ready()) {
      RCLCPP_INFO_THROTTLE(this->get_logger(), *this->get_clock(), 5000,
        "Waiting for Nav2's navigate_to_pose action server...");
      return;
    }
    send_goal();
  }

  // --------------------------------------------------------------- dispatch
  void on_decision(const std_msgs::msg::String::SharedPtr msg)
  {
    const std::string decision = msg->data;
    RCLCPP_INFO(this->get_logger(), ">>> EXECUTING: %s", decision.c_str());

    if (decision == "HALT") {
      halt();
    } else if (decision == "RETRY_NAVIGATION") {
      retry_navigation();
    } else if (decision == "REVERSE_AND_REPLAN") {
      reverse_and_replan();
    } else {
      RCLCPP_WARN(this->get_logger(),
        "Unknown decision '%s' -- halting as a safe default", decision.c_str());
      halt();
    }
  }

  // ------------------------------------------------------------------- HALT
  void halt()
  {
    reversing_ = false;
    nav_client_->async_cancel_all_goals();
    backup_client_->async_cancel_all_goals();
    publish_zero_velocity();
  }

  // ------------------------------------------------------- RETRY_NAVIGATION
  void retry_navigation()
  {
    if (reversing_) {
      RCLCPP_WARN(this->get_logger(), "Reverse in progress -- ignoring RETRY_NAVIGATION");
      return;
    }
    send_goal();
  }

  // ----------------------------------------------------- REVERSE_AND_REPLAN
  void reverse_and_replan()
  {
    if (reversing_) {
      RCLCPP_WARN(this->get_logger(), "Already reversing -- ignoring REVERSE_AND_REPLAN");
      return;
    }
    if (!backup_client_->action_server_is_ready()) {
      RCLCPP_ERROR(this->get_logger(),
        "'%s' action server unavailable -- halting as a safe default",
        backup_action_name_.c_str());
      halt();
      return;
    }

    reversing_ = true;

    if (!nav_client_->action_server_is_ready()) {
      start_backup();
      return;
    }
    // controller_server and behavior_server both publish on cmd_vel_nav, so
    // the back-up must not start until Nav2 confirms the nav goal is gone.
    // If that confirmation never arrives, HALT is always available.
    nav_client_->async_cancel_all_goals(
      [this](const auto &) { this->start_backup(); });
  }

  void start_backup()
  {
    auto goal = BackUp::Goal();
    goal.target.x = -reverse_distance_;  // BackUp normalizes the sign anyway
    goal.target.y = 0.0;
    goal.target.z = 0.0;
    goal.speed = static_cast<float>(reverse_speed_);
    goal.time_allowance = rclcpp::Duration::from_seconds(reverse_timeout_sec_);

    auto options = rclcpp_action::Client<BackUp>::SendGoalOptions();
    options.goal_response_callback =
      [this](BackUpGoalHandle::SharedPtr handle) {
        if (!handle) {
          RCLCPP_WARN(this->get_logger(), "BackUp goal rejected -- halting as a safe default");
          reversing_ = false;
          publish_zero_velocity();
        }
      };
    options.feedback_callback =
      [this](BackUpGoalHandle::SharedPtr,
             const std::shared_ptr<const BackUp::Feedback> feedback) {
        RCLCPP_INFO_THROTTLE(this->get_logger(), *this->get_clock(), 500,
          "Reversing: %.2f m", feedback->distance_traveled);
      };
    options.result_callback =
      [this](const BackUpGoalHandle::WrappedResult & result) {
        reversing_ = false;
        if (result.code == rclcpp_action::ResultCode::SUCCEEDED) {
          RCLCPP_INFO(this->get_logger(), "Back-up complete -- replanning");
          send_goal();
        } else {
          RCLCPP_WARN(this->get_logger(),
            "Back-up aborted or cancelled -- not resuming navigation");
          publish_zero_velocity();
        }
      };

    backup_client_->async_send_goal(goal, options);
  }

  // ------------------------------------------------------------- Nav2 goal
  void send_goal()
  {
    auto goal = NavigateToPose::Goal();
    goal.pose.header.frame_id = "map";
    // header.stamp is deliberately left at 0 ("use the latest transform").
    // A wall-clock stamp against sim-time TF is a classic extrapolation error.
    goal.pose.pose.position.x = goal_x_;
    goal.pose.pose.position.y = goal_y_;
    goal.pose.pose.orientation.w = 1.0;

    auto options = rclcpp_action::Client<NavigateToPose>::SendGoalOptions();
    options.goal_response_callback =
      [this](NavGoalHandle::SharedPtr handle) {
        awaiting_goal_response_ = false;
        if (!handle) {
          RCLCPP_WARN(this->get_logger(),
            "Nav2 rejected the goal (not active yet?) -- startup loop will retry");
          return;
        }
        RCLCPP_INFO(this->get_logger(), "Goal accepted: (%.1f, %.1f)", goal_x_, goal_y_);
        if (startup_timer_) {
          startup_timer_->cancel();
        }
      };
    options.result_callback =
      [this](const NavGoalHandle::WrappedResult & result) {
        switch (result.code) {
          case rclcpp_action::ResultCode::SUCCEEDED:
            RCLCPP_INFO(this->get_logger(), "Navigation goal reached");
            break;
          case rclcpp_action::ResultCode::ABORTED:
            RCLCPP_WARN(this->get_logger(), "Navigation goal aborted (or replaced by a new goal)");
            break;
          case rclcpp_action::ResultCode::CANCELED:
            RCLCPP_INFO(this->get_logger(), "Navigation goal cancelled");
            break;
          default:
            RCLCPP_WARN(this->get_logger(), "Navigation goal ended with an unknown result");
            break;
        }
      };

    awaiting_goal_response_ = true;
    nav_client_->async_send_goal(goal, options);
  }

  void publish_zero_velocity()
  {
    geometry_msgs::msg::Twist stop;  // all fields default to 0
    cmd_vel_pub_->publish(stop);
  }

  // ------------------------------------------------------------------ state
  double goal_x_, goal_y_;
  double reverse_distance_, reverse_speed_, reverse_timeout_sec_;
  std::string backup_action_name_;
  bool send_initial_goal_;
  bool reversing_{false};
  bool awaiting_goal_response_{false};

  rclcpp_action::Client<NavigateToPose>::SharedPtr nav_client_;
  rclcpp_action::Client<BackUp>::SharedPtr backup_client_;
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_pub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr decision_sub_;
  rclcpp::TimerBase::SharedPtr startup_timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<RecoveryExecutorNode>());
  rclcpp::shutdown();
  return 0;
}
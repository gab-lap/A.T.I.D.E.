// fault_trigger_node.cpp
//
// Sits between Gazebo's LiDAR publisher and Nav2.
// Subscribes to /scan, republishes to /scan_filtered, and can degrade
// that republished stream on command (manually, via `ros2 param set`,
// or automatically, via an internal timer) to simulate LiDAR dropout.
//
// Publishes /fault_status (Bool) and /fault_severity (String: "none" |
// "intermittent" | "complete") so downstream nodes, and the demo video,
// always know the current fault state.

#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "std_msgs/msg/bool.hpp"
#include "std_msgs/msg/string.hpp"
#include "rcl_interfaces/msg/set_parameters_result.hpp"


class FaultTriggerNode : public rclcpp::Node
{
public:
  FaultTriggerNode() : Node("fault_trigger_node"), scan_counter_(0)
  {
    // --- Parameters ---
    // fault_mode is the one you'll change live during the demo with:
    //   ros2 param set /fault_trigger_node fault_mode intermittent
    // That IS the "manual service trigger", parameter changes go through
    // a ROS 2 service under the hood, so no custom .srv file is needed.
    auto mode_desc = rcl_interfaces::msg::ParameterDescriptor{};
    mode_desc.description = "Current fault mode: none | intermittent | complete";
    fault_mode_ = this->declare_parameter<std::string>("fault_mode", "none", mode_desc);

    intermittent_rate_ = this->declare_parameter<int>("intermittent_rate", 3);
    auto_trigger_ = this->declare_parameter<bool>("auto_trigger", false);
    fault_period_sec_ = this->declare_parameter<double>("fault_period_sec", 15.0);

    validate_and_store_mode(fault_mode_);

    // Reject bad values at the source instead of failing silently downstream.
    param_callback_handle_ = this->add_on_set_parameters_callback(
      [this](const std::vector<rclcpp::Parameter> & params) {
        return this->on_parameter_change(params);
      });

    // --- Pub/Sub ---
    scan_sub_ = this->create_subscription<sensor_msgs::msg::LaserScan>(
      "/scan", rclcpp::SensorDataQoS(),
      [this](const sensor_msgs::msg::LaserScan::SharedPtr msg) {
        this->scan_callback(msg);
      });

    scan_pub_ = this->create_publisher<sensor_msgs::msg::LaserScan>(
      "/scan_filtered", rclcpp::SensorDataQoS());

    status_pub_ = this->create_publisher<std_msgs::msg::Bool>("/fault_status", 10);
    severity_pub_ = this->create_publisher<std_msgs::msg::String>("/fault_severity", 10);

    // Publish fault state on its own clock (not tied to scan arrival) so
    // downstream nodes always have a current value, even mid-dropout when
    // no scans are arriving at all.
    status_timer_ = this->create_wall_timer(
      std::chrono::milliseconds(200),
      [this]() { this->publish_status(); });

    // Optional automatic toggling, for unattended soak-testing only.
    if (auto_trigger_) {
      auto_timer_ = this->create_wall_timer(
        std::chrono::duration<double>(fault_period_sec_),
        [this]() { this->auto_toggle(); });
    }

    RCLCPP_INFO(this->get_logger(),
      "fault_trigger_node up. mode=%s intermittent_rate=%d auto_trigger=%s",
      fault_mode_.c_str(), intermittent_rate_, auto_trigger_ ? "true" : "false");
  }

private:
  void validate_and_store_mode(const std::string & mode)
  {
    if (mode == "none" || mode == "intermittent" || mode == "complete") {
      fault_mode_ = mode;
    } else {
      RCLCPP_WARN(this->get_logger(),
        "Invalid fault_mode '%s' — falling back to 'none'", mode.c_str());
      fault_mode_ = "none";
    }
  }

  rcl_interfaces::msg::SetParametersResult on_parameter_change(
    const std::vector<rclcpp::Parameter> & params)
  {
    auto result = rcl_interfaces::msg::SetParametersResult();
    result.successful = true;

    for (const auto & p : params) {
      if (p.get_name() == "fault_mode") {
        const std::string value = p.as_string();
        if (value != "none" && value != "intermittent" && value != "complete") {
          result.successful = false;
          result.reason = "fault_mode must be one of: none, intermittent, complete";
          continue;
        }
        fault_mode_ = value;
        RCLCPP_INFO(this->get_logger(), ">>> fault_mode changed to '%s'", fault_mode_.c_str());
      } else if (p.get_name() == "intermittent_rate") {
        intermittent_rate_ = p.as_int();
      }
    }
    return result;
  }

  void scan_callback(const sensor_msgs::msg::LaserScan::SharedPtr msg)
  {
    scan_counter_++;

    if (fault_mode_ == "complete") {
      // Drop the message entirely, nothing goes out on /scan_filtered.
      return;
    }

    if (fault_mode_ == "intermittent") {
      // Forward only 1 out of every intermittent_rate_ messages.
      if (intermittent_rate_ <= 0 || scan_counter_ % intermittent_rate_ != 0) {
        return;
      }
    }

    // "none" mode, or an intermittent message that made it through: forward unchanged.
    scan_pub_->publish(*msg);
  }

  void publish_status()
  {
    std_msgs::msg::Bool status_msg;
    status_msg.data = (fault_mode_ != "none");
    status_pub_->publish(status_msg);

    std_msgs::msg::String severity_msg;
    severity_msg.data = fault_mode_;
    severity_pub_->publish(severity_msg);
  }

  void auto_toggle()
  {
    // Only meaningful if a non-"none" mode was configured at startup;
    // otherwise there's nothing to toggle back to.
    static bool currently_faulted = false;
    currently_faulted = !currently_faulted;
    fault_mode_ = currently_faulted ? saved_auto_mode_ : "none";
    RCLCPP_INFO(this->get_logger(), ">>> auto_trigger toggled mode to '%s'", fault_mode_.c_str());
  }

  // Parameters / state
  std::string fault_mode_;
  std::string saved_auto_mode_{"intermittent"};
  int intermittent_rate_;
  bool auto_trigger_;
  double fault_period_sec_;
  uint64_t scan_counter_;

  rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr scan_sub_;
  rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr scan_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr status_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr severity_pub_;
  rclcpp::TimerBase::SharedPtr status_timer_;
  rclcpp::TimerBase::SharedPtr auto_timer_;
  OnSetParametersCallbackHandle::SharedPtr param_callback_handle_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<FaultTriggerNode>());
  rclcpp::shutdown();
  return 0;
}
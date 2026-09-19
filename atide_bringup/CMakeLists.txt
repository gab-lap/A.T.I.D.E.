cmake_minimum_required(VERSION 3.8)
project(atide_bringup)

# Find dependencies
find_package(ament_cmake REQUIRED)

# Install launch files, config files, and worlds in share/<project_name>
install(DIRECTORY 
  launch
  config
  worlds
  DESTINATION share/${PROJECT_NAME}/
)

ament_package()

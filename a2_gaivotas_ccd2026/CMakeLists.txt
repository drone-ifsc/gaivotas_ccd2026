cmake_minimum_required(VERSION 3.0.2)
project(a2_gaivotas_ccd2026)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  message_generation
)

generate_messages(
  DEPENDENCIES
  std_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs message_runtime
)
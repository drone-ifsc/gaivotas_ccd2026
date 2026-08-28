cmake_minimum_required(VERSION 3.0.2)
project(gaivotas_common)

find_package(catkin REQUIRED)

catkin_package()

# Instala os nós compartilhados como executáveis rosrun-áveis:
#   rosrun gaivotas_common base_reader.py
catkin_install_python(PROGRAMS
  scripts/base_reader.py
  scripts/camera_host_server.py
  scripts/landing_target_sender.py
  scripts/rostopic_2_cv.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

cmake_minimum_required(VERSION 3.0.2)
project(gaivotas_common)

find_package(catkin REQUIRED)

catkin_package()

# Instala os nós compartilhados como executáveis rosrun-áveis:
#   rosrun gaivotas_common base_reader.py
catkin_install_python(PROGRAMS
  scripts/base_reader.py
  scripts/camera_driver.py
  scripts/detection_overlay.py
  scripts/landing_target_sender.py
  scripts/rqt_bag_autopublish.py
  scripts/stream_keeper.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

# Launch comum (apm.launch) e configuração do MAVROS
install(DIRECTORY launch DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})

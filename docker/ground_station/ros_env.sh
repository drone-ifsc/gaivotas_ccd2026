# ROS environment of the laptop's container, sourced at the end of ~/.bashrc (interactive shells
# only).

# Master: the drone by default. For the simulation open the shell with a local master:
#   docker exec -it -e ROS_MASTER_URI=http://127.0.0.1:11311 ros-container bash
# (read before setup.bash, which sets localhost when the variable is empty)
_master="${ROS_MASTER_URI:-http://192.168.0.105:11311}"

source /opt/ros/noetic/setup.bash
source /usr/share/gazebo/setup.sh
# the workspace comes from the host (volume) and only has devel/ after the first catkin build
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash

# Gazebo models from outside this repository: the droneIFSC drone includes model://iris_base,
# which lives in the droneifsc package of the workspace; plus ardupilot_gazebo's own models
export GAZEBO_MODEL_PATH="$GAZEBO_MODEL_PATH:/root/ardupilot_gazebo/models:/root/catkin_ws/src/droneifsc/models"
export DISABLE_ROS1_EOL_WARNINGS=1

# ROS_IP = the laptop's Wi-Fi address: the drone's nodes connect back to it
MY_ROS_IFACE="${MY_ROS_IFACE:-wlp1s0}"
_get_ip_by_iface() {
  ip -4 addr show "$1" 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1
}
ROS_IP="$(_get_ip_by_iface "$MY_ROS_IFACE")"
[ -z "$ROS_IP" ] && ROS_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -z "$ROS_IP" ] && ROS_IP="127.0.0.1"
export ROS_IP
export ROS_MASTER_URI="$_master"
unset _master

# kills the Gazebo / MAVROS leftovers of a simulation run (SITL runs on the host: stop it there)
alias killsim='pkill -9 gzserver; pkill -9 gzclient; pkill -9 mavros_node; pkill -9 arducopter; pkill -9 mavproxy.py; pkill -9 -f sim_vehicle'

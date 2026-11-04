# ROS environment of the drone's container, sourced at the end of ~/.bashrc (interactive shells
# only: that is why start_ros.sh uses "bash -ic").
source /opt/ros/noetic/setup.bash
# the workspace comes from the host (volume) and only has devel/ after the first catkin build
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash

# ROS_IP = the Wi-Fi address: the laptop reaches the drone's master through it. Never the FCU link
# (192.168.144.x) nor docker0 (172.17.x). At boot wlan0 may come up late: wait up to 10 s.
MY_ROS_IFACE="${MY_ROS_IFACE:-wlan0}"
_get_ip_by_iface() {
  ip -4 addr show "$1" 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1
}
for _ in $(seq 1 10); do
  command -v ip >/dev/null || break      # without iproute2 there is no way to read the wlan0 address
  ROS_IP="$(_get_ip_by_iface "$MY_ROS_IFACE")"
  [ -n "$ROS_IP" ] && break
  sleep 1
done
[ -z "$ROS_IP" ] && ROS_IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^(192\.168\.144\.|172\.17\.)' | head -n1)"
[ -z "$ROS_IP" ] && ROS_IP="127.0.0.1"
export ROS_IP
export ROS_HOSTNAME="$ROS_IP"
export ROS_MASTER_URI="http://$ROS_IP:11311"
export PATH="$PATH:$HOME/.local/bin"

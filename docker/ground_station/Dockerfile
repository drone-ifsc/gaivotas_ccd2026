# Image of the laptop's ROS container (x86_64, native — no emulation): ROS Noetic desktop-full
# (Ubuntu 20.04) with Gazebo 11 and the ArduPilot plugin for the simulation, MAVROS, the vision
# nodes and the model tools (ultralytics, ncnn/pnnx, tensorflow/tflite) — what the current laptop
# container (droneifsc/ros-noetic:x86) has for this repository.
#
# The code is NOT baked into the image: the host's ~/catkin_ws is mounted at /root/catkin_ws
# (docker-compose.yml) and catkin build runs inside the container. ArduPilot SITL stays on the
# host (main README, "Simulation").
#
# Build — the context is the repository root:
#   cd ~/catkin_ws/src/gaivotas_ccd2026
#   docker build -f docker/ground_station/Dockerfile -t gaivotas/ros-noetic-laptop .
#   (or, in docker/ground_station: docker compose build)
FROM ros:noetic-ros-core

ARG DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ROS desktop-full (rqt, rviz, Gazebo 11 + gazebo_ros), MAVROS (libgeographic-dev: to build MAVROS
# from source in the workspace too), vision, QR codes; build, graphics (Mesa, for the AMD GPU),
# audio and everyday tools. With recommends, as a desktop install (fonts, GUI bits).
RUN apt-get update && apt-get install -y \
        ros-noetic-desktop-full \
        ros-noetic-mavros ros-noetic-mavros-extras libgeographic-dev \
        ros-noetic-aruco-detect ros-noetic-zbar-ros libzbar0 \
        libgazebo11-dev \
        python3-catkin-tools python3-rosdep python3-pip python3-dev \
        build-essential cmake git wget curl \
        mesa-utils libgl1-mesa-dri \
        pulseaudio-utils alsa-utils \
        tmux htop nano less iproute2 iputils-ping net-tools usbutils \
    && rm -rf /var/lib/apt/lists/*

# rosdep, for the dependencies of the other packages in the workspace:
#   apt-get update && rosdep install --from-paths ~/catkin_ws/src --ignore-src -r -y
RUN rosdep init && rosdep update --include-eol-distros

# GeographicLib models: MAVROS does not start without the egm96-5 geoid
RUN /opt/ros/noetic/lib/mavros/install_geographiclib_datasets.sh \
    && test -f /usr/share/GeographicLib/geoids/egm96-5.pgm

# ArduPilot Gazebo plugin (libArduPilotPlugin.so — exchanges sensors and motors with SITL over UDP
# 9002/9003), same repository and commit as on the laptop. make install puts the plugin into
# Gazebo's plugin directory and its models into /usr/share/gazebo-11/models.
RUN git clone -q https://github.com/khancyr/ardupilot_gazebo /root/ardupilot_gazebo \
    && cd /root/ardupilot_gazebo && git checkout -q a28cab4 \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && make -C build -j"$(nproc)" install

# Detection and model-export Python packages, in the versions of the current container — see
# requirements.txt
COPY docker/ground_station/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# ROS environment of every shell (ROS_IP, master, Gazebo paths) and git without "dubious
# ownership" in the repository mounted from the host (owned by the host user, not root)
COPY docker/ground_station/ros_env.sh /root/ros_env.sh
RUN echo 'source /root/ros_env.sh' >> /root/.bashrc \
    && git config --global --add safe.directory '*'

WORKDIR /root/catkin_ws/src

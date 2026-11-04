# Image of the drone's ROS container (Raspberry Pi 5, arm64): ROS Noetic (Ubuntu 20.04) with what
# gaivotas_ccd2026 uses in flight — MAVROS, aruco_detect, YOLO (ultralytics + ncnn),
# tflite-runtime and libcamera/rpicam-apps for the CSI camera.
#
# The code is NOT baked into the image: the host's ~/catkin_ws is mounted at /root/catkin_ws
# (docker-compose.yml) and catkin build runs inside the container.
#
# Build — the context is the repository root (because of build_libcamera.sh); needs internet:
#   on the drone:   cd ~/catkin_ws/src/gaivotas_ccd2026
#                   docker build -f docker/drone/Dockerfile -t gaivotas/ros-noetic-drone .
#   on the laptop (x86, emulating arm64; binfmt has to be registered once per boot):
#                   docker run --privileged --rm tonistiigi/binfmt --install arm64
#                   docker build --platform linux/arm64 -f docker/drone/Dockerfile -t gaivotas/ros-noetic-drone .
#                   docker save gaivotas/ros-noetic-drone | gzip | ssh falcon@192.168.0.105 'gunzip | docker load'
FROM ros:noetic-ros-core

ARG DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ROS: MAVROS, vision, tf, compressed image transport; build and everyday tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-noetic-mavros ros-noetic-mavros-extras \
        ros-noetic-aruco-detect \
        ros-noetic-cv-bridge ros-noetic-image-transport ros-noetic-compressed-image-transport \
        ros-noetic-tf ros-noetic-tf2-ros ros-noetic-tf2-geometry-msgs \
        python3-catkin-tools python3-pip python3-dev python3-numpy python3-opencv python3-yaml \
        python3-pyzbar \
        build-essential cmake git \
        tmux htop nano less iproute2 iputils-ping net-tools \
    && rm -rf /var/lib/apt/lists/*

# GeographicLib models: MAVROS does not start without the egm96-5 geoid
RUN /opt/ros/noetic/lib/mavros/install_geographiclib_datasets.sh \
    && test -f /usr/share/GeographicLib/geoids/egm96-5.pgm

# Detection Python packages (ultralytics/torch + ncnn = YOLO, tflite-runtime = mobilenetv2), in the
# versions of the container that flew — see requirements.txt
COPY docker/drone/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# libcamera (Raspberry Pi fork) + rpicam-apps: focal has no package and the host's one does not run
# here. Same script as in the repository; the sources are deleted after the install. Runs after
# pip, as on the drone where it was tested (libcamera's code generator uses the jinja2 from there).
COPY gaivotas_common/scripts/utils/build_libcamera.sh /tmp/build_libcamera.sh
RUN mkdir -p /root/src && bash /tmp/build_libcamera.sh \
    && rm -rf /root/src /tmp/build_libcamera.sh /var/lib/apt/lists/*

# ROS environment of every shell (ROS_IP from Wi-Fi etc.) and git without "dubious ownership" in
# the repository mounted from the host (owned by falcon, not root)
COPY docker/drone/ros_env.sh /root/ros_env.sh
RUN echo 'source /root/ros_env.sh' >> /root/.bashrc \
    && git config --global --add safe.directory '*'

WORKDIR /root/catkin_ws

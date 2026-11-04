#!/bin/bash
# Compila libpisp + libcamera (fork da Raspberry Pi) + rpicam-apps dentro do container ROS
# (Ubuntu 20.04), nas mesmas versoes do host, para o camera_driver.py acessar a camera CSI
# direto do container. Pipelines rpi/vc4 (RPi 4) e rpi/pisp (RPi 5).
# Uso, como root no container:  bash build_libcamera.sh   (fontes em /root/src)
set -e -o pipefail
ninja_install() { ninja -C build install > build/ninja.log 2>&1 || { grep -E "FAILED|error" -A6 build/ninja.log | head -40; exit 1; }; tail -1 build/ninja.log; ldconfig; }
step() { echo; echo "##### $* ($(date +%T))"; }
export DEBIAN_FRONTEND=noninteractive
step apt
apt-get update -qq
apt-get install -y -qq --no-install-recommends git ca-certificates python3-pip python3-yaml python3-ply python3-jinja2 \
  libyaml-dev libgnutls28-dev libssl-dev pkg-config ninja-build g++ cmake \
  libboost-program-options-dev libexif-dev libjpeg-dev libtiff-dev libpng-dev >/dev/null
step meson; pip3 install -q 'meson>=1.3,<1.7'; meson --version
cd /root/src
# nlohmann_json do focal (3.7.3) nao tem ordered_json (3.9+), que a libpisp usa: instala o 3.11.3
apt-get remove -y -qq nlohmann-json3-dev >/dev/null 2>&1 || true
step "nlohmann_json v3.11.3"
[ -d json ] || git clone -q --depth 1 --branch v3.11.3 https://github.com/nlohmann/json.git
cmake -S json -B json/build -DJSON_BuildTests=OFF -DCMAKE_INSTALL_PREFIX=/usr/local >/dev/null && cmake --install json/build | tail -1
step "libpisp v1.2.1"
[ -d libpisp ] || git clone -q --depth 1 --branch v1.2.1 https://github.com/raspberrypi/libpisp.git
cd libpisp && rm -rf build
meson setup build --buildtype=release -Dlogging=disabled | tail -12
ninja_install
cd ..
step "libcamera v0.5.2+rpt20250903"
[ -d libcamera ] || git clone -q --depth 1 --branch v0.5.2+rpt20250903 https://github.com/raspberrypi/libcamera.git
cd libcamera && rm -rf build
meson setup build --buildtype=release -Dwerror=false -Dpipelines=rpi/vc4,rpi/pisp -Dipas=rpi/vc4,rpi/pisp -Dv4l2=false \
  -Dgstreamer=disabled -Dtest=false -Dlc-compliance=disabled -Dcam=disabled -Dqcam=disabled \
  -Ddocumentation=disabled -Dpycamera=disabled | tail -30
ninja_install
# headers do kernel do focal (5.4) nao tem dma-heap.h; usa a copia da libcamera
mkdir -p /usr/local/include/linux && cp include/linux/dma-heap.h /usr/local/include/linux/
cd ..
step "rpicam-apps v1.8.1"
[ -d rpicam-apps ] || git clone -q --depth 1 --branch v1.8.1 https://github.com/raspberrypi/rpicam-apps.git
cd rpicam-apps && rm -rf build
meson setup build --buildtype=release -Denable_libav=disabled -Denable_drm=disabled -Denable_egl=disabled \
  -Denable_qt=disabled -Denable_opencv=disabled -Denable_tflite=disabled -Denable_hailo=disabled | tail -12
ninja_install
sync
step FIM; rpicam-vid --version

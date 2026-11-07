# Installation — Docker and ROS on the drone and on the laptop

How to get from a clean machine to a built workspace, for the **drone** (Raspberry Pi 5) and
for the **ground station** (laptop). No previous Docker or ROS experience is assumed. After
this, flying is described in the [quick start](QUICKSTART.md) and the simulation in the
[main README](README.md#simulation-gazebo-classic--ardupilot-sitl).

- [How it fits together (read this first)](#how-it-fits-together-read-this-first)
- [Drone (Raspberry Pi 5)](#drone-raspberry-pi-5)
- [Ground station (laptop)](#ground-station-laptop)
- [Updating later](#updating-later)
- [Docker cheat sheet](#docker-cheat-sheet)
- [Installation problems](#installation-problems)

## How it fits together (read this first)

ROS Noetic needs Ubuntu 20.04, while the drone runs Raspberry Pi OS (Debian 12) and the laptop
a newer Ubuntu. So ROS is **never installed on the machine itself**: it lives in a Docker
container, an isolated Ubuntu 20.04 that shares the machine's kernel, network and devices.

| Word | What it is here |
|---|---|
| **host** | the real machine: the Raspberry Pi, or your laptop |
| **image** | a template of the system: Ubuntu 20.04 + ROS + MAVROS + Python packages. Built once from a `Dockerfile` |
| **container** | a running copy of the image, called `ros-container`. All ROS commands run in it |
| **docker compose** | reads `docker-compose.yml` (the container's settings: network, devices, folders) so you do not have to type a long `docker run …` |

You do not install ROS by hand: the `Dockerfile` already says what goes into the image, and
building the image is the ROS installation. Each machine has its own folder:

| Machine | Folder | Image | Container |
|---|---|---|---|
| drone (arm64) | [docker/drone](docker/drone/) | `gaivotas/ros-noetic-drone` | `ros-container` |
| laptop (x86_64) | [docker/ground_station](docker/ground_station/) | `gaivotas/ros-noetic-laptop` | `ros-container` |

**The code is not inside the image.** The host folder `~/catkin_ws` is mounted into the
container as `/root/catkin_ws`: it is one and the same folder seen from two sides.

```
host                                          container (ros-container)
~/catkin_ws/                       <====>     /root/catkin_ws/
  src/gaivotas_ccd2026/                         src/gaivotas_ccd2026/
  build/ devel/ logs/  (after catkin build)     build/ devel/ logs/
```

What follows from that:

- You clone and edit the repository **on the host** (git, VS Code, your GitHub login are there);
  you build and run it **in the container** (`catkin build`, `roslaunch`, `rosrun`).
- The workspace survives when the container is deleted and created again. Anything you
  installed by hand inside the container (`apt install`, `pip install`) does **not**: what
  has to stay belongs in the `Dockerfile` / `requirements.txt`.
- How to tell where you are: on the host the prompt is `<your user>@<hostname>:~$`, in the
  container it is `root@<hostname>:~/catkin_ws#` — **the same hostname** (the container uses the
  host network), so look at `root` and `#`. In this document every command block says which
  side it is for.
- Never run `docker compose` with `sudo`: with sudo `~` becomes `/root`, and the container
  would get an empty `/root/catkin_ws` instead of yours.

## Drone (Raspberry Pi 5)

Everything here runs **on the Raspberry Pi**, over SSH from the laptop
(`ssh <your user here>@<ip address of the Pi>`), with the Pi connected to the internet over
Wi-Fi. The flight-controller network (`eth0`) is set up separately — see
[Our setup](README.md#our-setup-pixhawk-6x-mini-over-ethernet) in the main README.

### 1. Check the system

The image is built for 64-bit ARM, so the Pi needs **Raspberry Pi OS 64-bit** (Bookworm):

```bash
# host (Pi)
dpkg --print-architecture     # must print arm64; armhf = 32-bit system, reinstall with the 64-bit one
df -h ~                       # free space: the image takes several GB, keep at least ~15 GB free
```

### 2. Install Docker and git

```bash
# host (Pi)
sudo apt update && sudo apt install -y git tmux curl
curl -fsSL https://get.docker.com | sh       # official Docker install script (engine + compose)
sudo usermod -aG docker $USER                # lets your user run docker without sudo
```

Log out and in again (`exit`, then `ssh` again) — the group only applies to new logins. Check:

```bash
# host (Pi)
docker run --rm hello-world     # prints "Hello from Docker!"
docker compose version          # Docker Compose version v2.x
```

(Older guides and comments use `docker-compose` with a dash: that is the old version of the
same tool; `docker compose` with a space does the same.)

### 3. Get the repository

The repository and its submodules (`ai_models`, `camera_correction`) are public and are
cloned over HTTPS: no GitHub account or SSH key is needed to get them. Clone **on the host**,
into the folder the container will see. The `--recurse-submodules` matters: without it the
models and the camera calibrations are missing.

```bash
# host (Pi)
mkdir -p ~/catkin_ws/src
cd ~/catkin_ws/src
git clone --recurse-submodules https://github.com/drone-ifsc/gaivotas_ccd2026.git
ls gaivotas_ccd2026/gaivotas_common/scripts/ai_models    # must not be empty
```

Why on the host and not in the container: the container is created from the image, and the
image is built from this repository (the `Dockerfile` is in it) — so the first clone happens
before there is any container.

Only pushing needs your GitHub login: over HTTPS git asks for your user name and a personal
access token instead of the password (GitHub → *Settings* → *Developer settings* →
*Personal access tokens*). An older clone made over SSH is switched to HTTPS as described in
the [FAQ](FAQ.md#an-old-clone-asks-for-an-ssh-key-permission-denied-publickey).

### 4. Build the image

This is the actual ROS installation. It downloads Ubuntu 20.04 + ROS, MAVROS, PyTorch and
compiles libcamera for the CSI camera, so it takes a long time. Run it inside `tmux`, so a
dropped SSH connection does not kill it:

```bash
# host (Pi)
cd ~/catkin_ws/src/gaivotas_ccd2026/docker/drone
tmux new -s build
docker compose build
```

`Ctrl+b` then `d` leaves it running in the background, `tmux attach -t build` comes back.
When it ends, `docker images` lists `gaivotas/ros-noetic-drone   latest`.

The image can also be built on the laptop and copied to the Pi (useful when the Pi has no
internet) — the commands are in the header of [docker/drone/Dockerfile](docker/drone/Dockerfile);
emulating ARM on the laptop is slow, though.

### 5. Create the container

```bash
# host (Pi), still in ~/catkin_ws/src/gaivotas_ccd2026/docker/drone
[ -e ~/.Xauthority ] || touch ~/.Xauthority   # see the note below
docker ps -a                                  # is there already a container called ros-container?
docker rename ros-container ros-container-old # only if there is (an old hand-made one)
docker compose up -d
docker ps                                     # ros-container ... Up
```

`docker-compose.yml` mounts `~/.Xauthority` into the container. On a Pi without a desktop
that file usually does not exist, and then Docker creates a root-owned **folder** with that
name — that is why it is created first.

`up -d` creates the container and starts it in the background. It does not start by itself
after a reboot: `start_ros.sh` from the [quick start](QUICKSTART.md) runs
`docker start ros-container`, or start it by hand.

### 6. Build the workspace (inside the container)

```bash
# host (Pi)
docker exec -it ros-container bash    # opens a shell in the container
```

```bash
# container
cd ~/catkin_ws
catkin init         # once; marks ~/catkin_ws as a catkin workspace
catkin build        # builds every package in src/ -> build/, devel/
exit
```

Open the shell again (`docker exec -it ros-container bash`): every new shell loads
`devel/setup.bash` by itself (see [docker/drone/ros_env.sh](docker/drone/ros_env.sh)), but
only once it exists. `build/`, `devel/` and `logs/` belong to root, because the container runs
as root: to delete them from the host use `sudo`, or delete them from the container.

### 7. Check

```bash
# container
rospack find gaivotas_common                        # a path: the workspace is built and loaded
echo $ROS_IP                                        # the Pi's Wi-Fi address (wlan0), not 127.0.0.1
rpicam-hello --list-cameras                         # the IMX219 is listed (camera connected)
python3 -c "import ultralytics, ncnn; print('ok')"  # detection packages
```

libcamera is already in this image, so the "build libcamera in the container and
`docker commit`" step from older instructions is not needed.

The drone is ready: go on with the [quick start](QUICKSTART.md). When the new container
works, the old one can go: `docker rm ros-container-old` (this deletes it for good).

## Ground station (laptop)

The laptop container is for everything ROS on the ground: watching the drone's topics over
Wi-Fi (`rostopic`, `rqt_image_view`), rosbags, and the Gazebo simulation. Requirements:

- Ubuntu 22.04 or 24.04, x86_64 (ours: 24.04). Other Linux distributions with Docker work too,
  the commands below are for Ubuntu.
- Free disk space: the image is big (desktop ROS, Gazebo, TensorFlow, PyTorch) — check with
  `df -h ~` and keep a few tens of GB free.
- For flights: the laptop on the same Wi-Fi network as the drone.
- Graphics: the image uses Mesa, which works with Intel and AMD GPUs. With an NVIDIA GPU and
  its proprietary driver Gazebo falls back to slow software rendering (making the NVIDIA GPU
  work in Docker needs the NVIDIA Container Toolkit, not covered here).

### 1. Docker, git, repository

The same as on the drone, on the laptop:

1. Install Docker and git — [drone step 2](#2-install-docker-and-git) (log out of the desktop
   session and back in, or reboot, after `usermod`).
2. Clone into `~/catkin_ws/src` — [drone step 3](#3-get-the-repository).

If `~/catkin_ws/src` already has other packages, they will be built too by `catkin build`; for
a first install a workspace with only this repository is the least trouble.

### 2. Let the container open windows

Gazebo, rviz and rqt run in the container but draw on your screen through the X server. The
X server only accepts programs it knows, and the container's root is not one of them. Allow
local programs (on a personal laptop that is fine) — every new terminal will do it:

```bash
# host (laptop)
echo 'xhost +local: >/dev/null 2>&1' >> ~/.bashrc
source ~/.bashrc
```

Also create the files `docker-compose.yml` mounts, if they are missing (otherwise Docker
creates root-owned folders with those names):

```bash
# host (laptop)
[ -e ~/.Xauthority ] || touch ~/.Xauthority
mkdir -p ~/.config/pulse && [ -e ~/.config/pulse/cookie ] || touch ~/.config/pulse/cookie   # sound, optional
```

`echo $XDG_SESSION_TYPE` shows the desktop session: `x11` is the safe one. On `wayland` the
windows usually still open (through Xwayland); if Gazebo misbehaves, log out and pick
*Ubuntu on Xorg* with the gear icon on the login screen.

### 3. The drone's address and your Wi-Fi interface

Two settings of the container are personal, so they are not kept in git but in a `.env` file
next to `docker-compose.yml` (git ignores it, docker compose reads it by itself):

- `DRONE_IP` — the container connects to the drone's ROS master when it knows the drone's IP;
- `MY_ROS_IFACE` — the network interface whose address becomes the laptop's `ROS_IP`, the
  address the drone's nodes connect back to. The default is `wlp1s0`, our laptop's Wi-Fi; yours
  may be called differently (`wlo1`, `wlp2s0`, …).

```bash
# host (laptop)
cd ~/catkin_ws/src/gaivotas_ccd2026/docker/ground_station
echo "DRONE_IP=<ip address of the Pi>" > .env
ip -br addr                                          # your Wi-Fi: the wl… line with your address
echo "MY_ROS_IFACE=<your Wi-Fi interface>" >> .env   # only if it is not wlp1s0
```

Without `DRONE_IP` everything still works, only with a local master (enough for the
simulation). Changing `.env` later: edit it, then `docker compose up -d` (recreates the
container with the new values).

`ROS_IP` follows the interface, not the network: if one day the laptop is connected another
way (Ethernet cable, USB tethering from a phone, a USB Wi-Fi adapter), `MY_ROS_IFACE` has to
name that interface, or ROS stops getting data from the drone (see
[Installation problems](#rostopic-list-shows-the-drones-topics-but-rostopic-echo-prints-nothing)).
The same goes for the drone, whose default is `wlan0`: if the laptop reaches the Pi through
something other than its Wi-Fi, put `MY_ROS_IFACE=<interface>` into `docker/drone/.env` on the
Pi and run `docker compose up -d` there.

### 4. Build the image and create the container

```bash
# host (laptop), in ~/catkin_ws/src/gaivotas_ccd2026/docker/ground_station
docker ps -a                                  # is there already a container called ros-container?
docker rename ros-container ros-container-old # only if there is
docker compose up -d --build                  # builds the image (long, the first time) and starts the container
docker ps                                     # ros-container ... Up
```

### 5. Open a shell in the container

There are two ways, depending on which ROS master you want:

```bash
# host (laptop)
docker exec -it ros-container bash                                            # master = the drone (DRONE_IP)
docker exec -it -e ROS_MASTER_URI=http://127.0.0.1:11311 ros-container bash   # local master: simulation, rosbags
```

`echo $ROS_MASTER_URI` in the container tells which one you got.

### 6. Build the workspace (inside the container)

```bash
# container
cd ~/catkin_ws
catkin init
catkin build
exit
```

Then open the shell again, as on the drone. If other packages in the workspace need system
libraries, rosdep can install them (they are lost when the container is recreated):

```bash
# container
apt-get update && rosdep install --from-paths ~/catkin_ws/src --ignore-src -r -y
```

### 7. Check

```bash
# container (local master)
rospack find gaivotas_common          # a path: the workspace is built and loaded
glxinfo -B | grep -i renderer         # your GPU (AMD/Intel); "llvmpipe" = software rendering, slow
roscore &                             # then:
rqt                                   # a window must open on your screen
```

Talking to the drone (drone powered, its container running `roscore` — see the
[quick start](QUICKSTART.md)), in a shell with the drone as master:

```bash
# container (master = drone)
echo $ROS_IP          # the laptop's Wi-Fi address, the drone connects back to it
rostopic list         # the drone's topics
```

If `ROS_IP` is not your Wi-Fi address, `MY_ROS_IFACE` in `.env` is missing or wrong — see
[step 3](#3-the-drones-address-and-your-wi-fi-interface).

### 8. ArduPilot SITL (only for the simulation)

The simulated flight controller (ArduPilot SITL) runs on the laptop host, **not** in the
container; Gazebo and MAVROS run in the container. It is installed with ArduPilot's own script
(details: [ArduPilot docs — setting up the build environment](https://ardupilot.org/dev/docs/building-setup-linux.html)):

```bash
# host (laptop)
cd ~
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cd ardupilot
Tools/environment_install/install-prereqs-ubuntu.sh -y   # also puts Tools/autotest into PATH
. ~/.profile                                             # or log out and in
```

The first `sim_vehicle.py` run compiles ArduCopter. How to start it together with Gazebo is
in [Simulation](README.md#simulation-gazebo-classic--ardupilot-sitl) in the main README.

## Updating later

- **Code changed** (`git pull` on the host): build again in the container — `catkin build`.
  New packages or launch files need a new shell afterwards.
- **Something in `docker/` changed** (`Dockerfile`, `requirements.txt`, `ros_env.sh`,
  `docker-compose.yml`): rebuild the image and recreate the container, in that machine's
  `docker/…` folder on the host:

  ```bash
  # host
  docker compose up -d --build
  ```

  The workspace stays (it is on the host); things installed by hand in the old container are
  gone. Old image layers can be removed with `docker image prune`.

`git pull` prints the changed files; `git diff --stat HEAD@{1} -- docker/` shows whether
`docker/` was among them.

## Docker cheat sheet

All on the host:

| Command | What it does |
|---|---|
| `docker ps -a` | lists containers, running and stopped |
| `docker start ros-container` / `docker stop ros-container` | starts / stops the container |
| `docker exec -it ros-container bash` | opens one more shell in a running container |
| `docker compose up -d` | (in `docker/…`) creates the container from the compose file, or recreates it if the file changed |
| `docker compose up -d --build` | the same, rebuilding the image first |
| `docker compose down` | deletes the container (not the image, not the workspace) |
| `docker images` | lists images and their size |
| `docker system df` | how much disk Docker uses |

`exit` in a container shell only closes that shell; the container keeps running.

## Installation problems

More, about running things, in the [FAQ](FAQ.md).

### `permission denied while trying to connect to the Docker daemon socket`

**Why:** your user is not in the `docker` group yet, or the session started before
`usermod`.
**Fix:** `sudo usermod -aG docker $USER`, then log out and in (on the laptop: reboot is the
surest). `groups` must list `docker`.

### `Conflict. The container name "/ros-container" is already in use`

**Why:** an older container with that name exists (for example the hand-made one).
**Fix:** `docker rename ros-container ros-container-old`, then `docker compose up -d` again.

### `catkin: command not found`, `roslaunch: command not found`

**Why:** the command was typed on the host — ROS only exists in the container.
**Fix:** `docker exec -it ros-container bash` first.

### `rospack` / `roslaunch` cannot find the packages of this repository

**Why:** the workspace was not built yet, or the shell was opened before the first
`catkin build` (it loads `devel/setup.bash` only if it existed at that moment).
**Fix:** `catkin build` in `~/catkin_ws`, then open a new shell (or
`source ~/catkin_ws/devel/setup.bash`).

### The container is running but `~/catkin_ws/src` inside it is empty

**Why:** `docker compose` was run with `sudo` (so `~` meant `/root` on the host), or the
repository was cloned somewhere other than `~/catkin_ws/src`.
**Fix:** without sudo, in the right folder: `docker compose down && docker compose up -d`.

### `~/.Xauthority` (or `~/.config/pulse/cookie`) is a folder owned by root

**Why:** the file did not exist when the container was created, so Docker created a folder
in its place.
**Fix:** `docker stop ros-container`, `sudo rmdir ~/.Xauthority && touch ~/.Xauthority`, then
`docker compose up -d --force-recreate`.

### Windows do not open: `cannot open display`, `Authorization required`, `could not connect to display`

**Why:** the X server does not let the container's root in, or `DISPLAY` is wrong.
**Fix:** on the host, in a terminal of the desktop session: `xhost +local:` (and the line in
`~/.bashrc` from [laptop step 2](#2-let-the-container-open-windows)). `echo $DISPLAY` on the
host and in the container must match (usually `:0`). If the host's is different, recreate the
container from a desktop terminal: `docker compose up -d --force-recreate`.

### `rostopic list` shows the drone's topics, but `rostopic echo` prints nothing

**Why:** `ROS_IP` on one of the machines is not an address the other one can reach. The master
only hands out addresses; the data goes straight from node to node, to the `ROS_IP` each node
announced. It happens when the machine is connected through another interface than
`MY_ROS_IFACE` (Ethernet cable, USB tethering, another Wi-Fi adapter): `ros_env.sh` then uses
the wrong interface's address or falls back to a guess (docker0's `172.17.0.1`, `127.0.0.1`).
**Fix:** `echo $ROS_IP` in the container on both machines, and `ip -br addr` on the host to see
which interface has the address of the shared network. Put `MY_ROS_IFACE=<that interface>` into
the `.env` next to that machine's `docker-compose.yml` and run `docker compose up -d` there.

### `exec format error` when the drone container starts

**Why:** the image was built for another architecture — on the laptop without
`--platform linux/arm64`, or the Pi runs the 32-bit system.
**Fix:** `dpkg --print-architecture` on the Pi must print `arm64`; build the image on the Pi
itself, or with the commands from the header of [docker/drone/Dockerfile](docker/drone/Dockerfile).

### The image build stops with network errors (`Temporary failure resolving`, timeouts)

**Why:** no internet on the machine, or it dropped during the build.
**Fix:** check `ping -c3 github.com` and run `docker compose build` again: the steps that
already finished are cached and are not repeated.

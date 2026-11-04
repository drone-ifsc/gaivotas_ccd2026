# gaivotas_ccd2026

Monorepo for the **gaivotas** team's drone missions in the [Catarinense Drones Competition 2026](https://www.ifsc.edu.br/web/campus-florianopolis/veiculos-nao-tripulados/competicao-de-drones) competition.
Each mission is a catkin package; the nodes shared across missions live in
`gaivotas_common`.

**Platform.** ROS Noetic is never installed on the system itself: it lives inside a **Docker
container** (`ros-container`, Ubuntu 20.04), on the drone and on the laptop alike. So this
repository is cloned into and built in the container's catkin workspace `/root/catkin_ws`
(see [Bootstrap](#bootstrap)) — on both machines. That workspace is the host folder
`~/catkin_ws` mounted into the container, so the files survive if the container is recreated.

- **Drone:** Raspberry Pi 5 with **Raspberry Pi OS Bookworm** (Debian 12). Everything that flies
  runs in its container: MAVROS, camera driver, vision nodes, missions. The image and the
  container are described in [docker/drone](docker/drone/) (`Dockerfile`, `docker-compose.yml`;
  how to build and start them is in the comments at the top of those files).
- **Laptop** (ground station and simulation; ours runs Ubuntu 24.04): image
  `droneifsc/ros-noetic:x86` (ROS Noetic + Gazebo 11), started with host networking,
  `--privileged` and X11 access for the windows; the same image and container, built natively
  for x86, are described in [docker/ground_station](docker/ground_station/). The laptop needs the container for
  anything ROS:
  - talking to the drone's ROS over Wi-Fi — `rostopic`, `rqt_image_view`,
    `gaivotas_common/scripts/utils/view_topic.py` (in the container
    `ROS_MASTER_URI=http://<ip address of the Pi>:11311`, the drone's master);
  - rosbags — `rosbag play` / `reindex`, `a10_gaivotas_ccd2026/launch/post_analyzer.launch`
    (`utils/fetch_rosbag.sh` starts the image by itself for the reindex);
  - the simulation — Gazebo + MAVROS (with `ROS_MASTER_URI=http://127.0.0.1:11311`, a local
    master). Only ArduPilot SITL (`sim_vehicle.py`) runs on the laptop host, outside the
    container.

- New here? Start with the [quick start](QUICKSTART.md) — bringing the drone up and running a mission.
- Camera, calibration and AI models: [gaivotas_common](gaivotas_common/README.md).
- Something does not work? See the [FAQ](FAQ.md) — the problems we already ran into.

```
gaivotas_ccd2026/
├── gaivotas_common/        shared nodes, MAVROS launch, submodules
│   ├── launch/
│   │   ├── apm.launch                 (MAVROS for ArduPilot — the ONLY place with the flight-controller connection settings)
│   │   └── apm_config.yaml            (MAVROS config shared by the missions)
│   ├── models/, worlds/               (Gazebo models and the shared arena for the simulation)
│   └── scripts/
│       ├── base_reader.py             (landing-base detection — yolo / mobilenetv2)
│       ├── camera_driver.py           (on-drone camera driver, inside the container; needs libcamera there)
│       ├── landing_target_sender.py   (sends the landing target to MAVROS)
│       ├── stream_keeper.py           (asks the flight controller for telemetry; error if local position is missing)
│       ├── utils/                     (helpers: rosbag download, libcamera build, dataset tools, …)
│       ├── ai_models/                 (submodule -> drone-ifsc/ai_models)
│       └── camera_correction/         (submodule -> drone-ifsc/camera_correction)
├── a2_gaivotas_ccd2026/    mission A2
├── a3_gaivotas_ccd2026/    mission A3 (practically an identical copy of A4)
├── a4_gaivotas_ccd2026/    mission A4 (with the ServoSequence srv)
├── a6_gaivotas_ccd2026/    mission A6
├── a10_gaivotas_ccd2026/   mission A10
├── a11_gaivotas_ccd2026/   mission A11
└── docs/                   diagrams (draw.io): node structure, mission flowcharts
```

Missions call the shared nodes with `pkg="gaivotas_common"` in their launch files and
pass the mission-specific parameters (model, topics) through the launch. The camera
driver runs on the drone, inside the ROS container, and is started separately:
`rosrun gaivotas_common camera_driver.py` (needs libcamera built in the container, see
the script's docstring).

## Connecting to the flight controller (MAVROS)

The flight controller (FCU) runs ArduPilot and speaks **MAVLink**. ROS does not talk MAVLink
directly: **MAVROS** is the ROS node in between. It turns the FCU telemetry into ROS topics
and turns ROS service calls into MAVLink commands, so the mission scripts never touch MAVLink:

| What the mission needs | MAVROS interface |
|---|---|
| is the FCU connected, armed, which mode | topic `/mavros/state` |
| drone position (local frame, metres) | topic `/mavros/local_position/pose` |
| fly to a point | topic `/mavros/setpoint_position/local` |
| arm, change mode, take off | services `/mavros/cmd/arming`, `/mavros/set_mode`, `/mavros/cmd/takeoff` |

Every mission starts MAVROS through the same file, without any arguments:

```xml
<include file="$(find gaivotas_common)/launch/apm.launch">
</include>
```

so the connection settings live **only** in `gaivotas_common/launch/apm.launch`
(the simulation launches are the only ones that override them, with the SITL addresses).
The arguments that matter:

| Argument | Meaning |
|---|---|
| `fcu_url` | how MAVROS reaches the FCU (format below) |
| `tgt_system` | the FCU system ID — must be equal to the FCU parameter `SYSID_THISMAV`, otherwise the FCU ignores the commands (ours: `105`; SITL: `1`) |
| `gcs_url` | optional: lets QGroundControl on another computer connect *through* MAVROS |

`apm.launch` also starts `stream_keeper.py`: MAVROS does not ask the FCU for telemetry by
itself, so this node requests it as soon as the FCU is connected and prints an **error** if
the local position does not arrive. The FCU only sends the local position after its EKF has
an origin (normally a GPS fix), so outdoors it can take a while after power-up; indoors
without GPS it never arrives.

### Our setup: Pixhawk 6X Mini over Ethernet

The FCU is a **Pixhawk 6X Mini** connected to the companion computer (Raspberry Pi) by an
**Ethernet** cable — faster and more robust than a serial link.

- FCU (ArduPilot parameters): `NET_ENABLE = 1`, `NET_DHCP = 0`, own address
  `NET_IPADDR = 192.168.144.14`; network port 1 as a UDP client that sends MAVLink 2 to the
  Raspberry Pi: `NET_P1_TYPE = 1`, `NET_P1_PROTOCOL = 2`, `NET_P1_IP = 192.168.144.10`,
  `NET_P1_PORT = 14550` (reboot the FCU after changing `NET_*`).
- Raspberry Pi: static address `192.168.144.10/24` on `eth0`, without gateway, so the
  internet keeps going through Wi-Fi:

  ```bash
  sudo nmcli connection modify "Wired connection 1" connection.id pixhawk-eth0 \
      ipv4.method manual ipv4.addresses 192.168.144.10/24 ipv4.gateway "" ipv4.dns "" ipv4.never-default yes
  sudo nmcli connection up pixhawk-eth0
  ```

- MAVROS: `fcu_url = udp://192.168.144.10:14550@192.168.144.14`, i.e.
  `udp://<local address:port MAVROS listens on>@<FCU address>`. The FCU's source port is
  random; MAVROS learns it from the first packet.

### Simpler controllers: serial (UART) or USB

Most flight controllers have no Ethernet. Then use a telemetry (TELEM) port:

1. Wiring: FCU TX → Raspberry Pi RX (GPIO 15), FCU RX → Raspberry Pi TX (GPIO 14), GND → GND.
   On the Raspberry Pi enable the serial hardware and disable the serial console
   (`sudo raspi-config` → Interface Options → Serial Port).
2. FCU parameters for that port (`SERIAL2_*` for TELEM2, for example):
   `SERIAL2_PROTOCOL = 2` (MAVLink 2), `SERIAL2_BAUD = 921` (921600 baud; use `57` for
   57600 if the cable is long or noisy).
3. MAVROS: `fcu_url = /dev/serial0:921600` (`<device>:<baud>`). Over the FCU USB port it is
   `/dev/ttyACM0:115200`.

Inside Docker the device has to be passed to the container (`--device /dev/serial0`, or a
privileged container). To try another connection without editing the file:

```bash
roslaunch gaivotas_common apm.launch fcu_url:=/dev/serial0:921600 tgt_system:=1
```

### Checking the connection

```bash
rostopic echo -n1 /mavros/state                 # connected: True  -> MAVROS sees the FCU
rostopic hz /mavros/local_position/pose         # ~20 Hz once the EKF has an origin
```

- `connected: False` — wrong `fcu_url` (address, port, device or baud), cable, or FCU off.
- Connected, but arming / mode changes do nothing — `tgt_system` differs from `SYSID_THISMAV`.
- No local position — see the `stream_keeper` error in the log: usually no GPS fix yet.

## Simulation (Gazebo Classic + ArduPilot SITL)

Each mission has a simulation launch with the same structure: Gazebo with the shared arena
(`gaivotas_common/worlds/arena.world`) plus the mission's own objects spawned from the launch,
the drone model with the ArduPilot plugin, MAVROS pointed at SITL (`tgt_system 1`) and the
vision nodes. The shared arena has the two landing bases; A4 and A6 use it as is, A10 spawns
its ArUco/QR symbols on top and also records a rosbag (`record:=false` to turn it off).

| Mission | Launch |
|---|---|
| A4 | `roslaunch a4_gaivotas_ccd2026 gazebo.launch` |
| A6 | `roslaunch a6_gaivotas_ccd2026 gazebo.launch` |
| A10 | `roslaunch a10_gaivotas_ccd2026 gazebo.launch` |

A3 is practically an identical copy of mission A4, so no simulation of its own was made for it:
use the A4 one.

The real-flight MAVROS settings stay only in `gaivotas_common/launch/apm.launch`; the
simulation launches override just the SITL addresses.

1. Gazebo + MAVROS, in the ROS container — the mission's launch from the table above.

2. ArduPilot SITL, on the host (ArduPilot tree in `~/ardupilot`, `Tools/autotest` in `PATH`):

   ```bash
   cd ~/ardupilot/ArduCopter
   sim_vehicle.py -v ArduCopter -f gazebo-iris --console --map --out=udp:127.0.0.1:14551
   ```

   - `-f gazebo-iris` — SITL does not simulate the physics itself; it exchanges sensor and
     motor data with the Gazebo ArduPilot plugin over UDP 9002/9003 (`fdm_port_in` /
     `fdm_port_out` in `gaivotas_common/models/droneIFSC/model.sdf`). The container runs with
     host networking, so `127.0.0.1` reaches it.
   - `--out=udp:127.0.0.1:14551` — MAVLink for MAVROS (`fcu_url` in the simulation launches listens on
     14551). sim_vehicle already sends to 14550 on its own (QGroundControl).
   - Run it from `ArduCopter/`: SITL keeps its parameters (`eeprom.bin`) and logs in the
     current directory. Add `-w` once to reset the parameters to defaults.

3. Mission: `rosrun <mission package> mission.py`, e.g. `rosrun a10_gaivotas_ccd2026 mission.py`

New to Gazebo? Before digging into these launches, start with
[iq_sim](https://github.com/Intelligent-Quads/iq_sim) — a repository with good, simple examples
of Gazebo simulations for ArduPilot drones (worlds, models, launch files).

## Bootstrap

Inside the ROS container, the same on the drone and on the laptop (ROS is only there):

```bash
cd ~/catkin_ws/src
git clone --recurse-submodules git@github.com:drone-ifsc/gaivotas_ccd2026.git
cd ~/catkin_ws && catkin build
# or:  git clone … && git submodule update --init --recursive
# the --recurse-submodules is important because it pulls the repo with camera calibrations and ai models used for identifying the bases
```

In case of any problems - feel free to open the issue here on Github or write on my email - iaroslav.p@aluno.ifsc.edu.br

# gaivotas_ccd2026

Monorepo for the **gaivotas** team's drone missions in the CCD competition.
Each mission is a catkin package; the nodes shared across missions live in
`gaivotas_common`.

```
gaivotas_ccd2026/
├── gaivotas_common/        shared nodes, MAVROS launch, submodules
│   ├── launch/
│   │   ├── apm.launch                 (MAVROS for ArduPilot — included by every mission)
│   │   └── apm_config.yaml            (MAVROS config shared by the missions)
│   └── scripts/
│       ├── base_reader.py             (landing-base detection — yolo / mobilenetv2)
│       ├── camera_driver.py           (on-drone camera driver, inside the container; needs libcamera there)
│       ├── camera_host_server.py      (same driver run on the drone host, rospypi)
│       ├── landing_target_sender.py   (sends the landing target to MAVROS)
│       ├── ai_models/                 (submodule -> drone-ifsc/ai_models)
│       └── camera_correction/         (submodule -> drone-ifsc/camera_correction)
├── a2_gaivotas_ccd2026/    mission A2
├── a4_gaivotas_ccd2026/    mission A4 (with the ServoSequence srv)
├── a6_gaivotas_ccd2026/    mission A6
├── a10_gaivotas_ccd2026/   mission A10
└── a11_gaivotas_ccd2026/   mission A11
```

Missions call the shared nodes with `pkg="gaivotas_common"` in their launch files and
pass the mission-specific parameters (model, topics) through the launch. The
`camera_host_server.py` runs on the drone and is started separately:
`rosrun gaivotas_common camera_host_server.py`.

MAVROS is started by each mission through the shared launch, overriding only what differs:

```xml
<include file="$(find gaivotas_common)/launch/apm.launch">
    <arg name="fcu_url"    value="$(arg fcu_url)" />
    <arg name="tgt_system" value="$(arg tgt_system)" />
</include>
```

## Simulation (Gazebo Classic + ArduPilot SITL)

Each mission has a simulation launch with the same structure: Gazebo with the shared arena
(`gaivotas_common/worlds/arena.world`) plus the mission's own objects spawned from the launch,
the drone model with the ArduPilot plugin, MAVROS pointed at SITL (`tgt_system 1`), the
vision nodes and rosbag recording (`record:=false` to turn it off).

| Mission | Launch |
|---|---|
| A4 | `roslaunch a4_gaivotas_ccd2026 mission_gazebo.launch` |
| A6 | `roslaunch a6_gaivotas_ccd2026 mission_gazebo.launch` |
| A10 | `roslaunch a10_gaivotas_ccd2026 gazebo.launch` |

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

## Bootstrap

```bash
cd ~/catkin_ws/src
git clone --recurse-submodules git@github.com:drone-ifsc/gaivotas_ccd2026.git
cd ~/catkin_ws && catkin build
# or:  git clone … && git submodule update --init --recursive
```

The models (`ai_models`) are a single submodule shared by every mission — one
`git submodule update` pulls the weights for all of them. Its URL is relative
(`../ai_models.git`), so it follows the protocol you cloned the superproject with
(SSH clone → SSH submodule), which matters on the SSH-only drone.

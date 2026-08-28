# gaivotas_ccd2026

Monorepo for the **gaivotas** team's drone missions in the CCD competition.
Each mission is a catkin package; the nodes shared across missions live in
`gaivotas_common`.

```
gaivotas_ccd2026/
├── gaivotas_common/        shared nodes + ai_models submodule
│   └── scripts/
│       ├── base_reader.py             (landing-base detection — yolo / mobilenetv2)
│       ├── camera_host_server.py      (on-drone camera server)
│       ├── landing_target_sender.py   (sends the landing target to MAVROS)
│       ├── rostopic_2_cv.py           (ROS Image -> OpenCV helper)
│       └── ai_models/                 (submodule -> drone-ifsc/ai_models)
├── a2_gaivotas_ccd2026/    mission A2
├── a4_gaivotas_ccd2026/    mission A4 (with the ServoSequence srv)
├── a6_gaivotas_ccd2026/    mission A6
└── a11_gaivotas_ccd2026/   mission A11
```

Missions call the shared nodes with `pkg="gaivotas_common"` in their launch files and
pass the mission-specific parameters (model, topics) through the launch. The
`camera_host_server.py` runs on the drone and is started separately:
`rosrun gaivotas_common camera_host_server.py`.

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

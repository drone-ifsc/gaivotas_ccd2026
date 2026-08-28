# gaivotas_ccd2026

Monorepo das missões **gaivotas** da competição CCD (equipe IFSC Florianópolis).
Cada missão é um pacote catkin; os nós compartilhados vivem em `gaivotas_common`.

```
gaivotas_ccd2026/
├── gaivotas_common/        nós compartilhados + submódulo ai_models
│   └── scripts/
│       ├── base_reader.py             (detecção da base de pouso — yolo/mobilenetv2)
│       ├── camera_host_server.py      (servidor de câmera no drone)
│       ├── landing_target_sender.py   (envia landing target ao MAVROS)
│       ├── rostopic_2_cv.py           (helper ROS Image -> OpenCV)
│       └── ai_models/                 (submódulo -> drone-ifsc/ai_models)
├── a2_gaivotas_ccd2026/    missão A2
├── a4_gaivotas_ccd2026/    missão A4 (com srv ServoSequence)
├── a6_gaivotas_ccd2026/    missão A6
└── a11_gaivotas_ccd2026/   missão A11
```

As missões usam os nós comuns por `pkg="gaivotas_common"` nos seus launch files e
passam os parâmetros (modelo, tópicos) por launch. O `camera_host_server.py` roda no
drone e é iniciado à parte: `rosrun gaivotas_common camera_host_server.py`.

## Bootstrap

```bash
cd ~/catkin_ws/src
git clone --recurse-submodules git@github.com:drone-ifsc/gaivotas_ccd2026.git
cd ~/catkin_ws && catkin build
# ou:  git clone … && git submodule update --init --recursive
```

Modelos (ai_models) são um submódulo compartilhado por todas as missões — um único
`git submodule update` traz os pesos para todas.

# Quick start — real flight

How to bring the drone up and run a mission. How the connection to the flight controller
works is in the [main README](README.md); camera, calibration and AI models are in
[gaivotas_common](gaivotas_common/README.md); known problems are in the [FAQ](FAQ.md).

Before the first flight on a new machine: the repository is cloned **with submodules** and
built (`catkin build` inside the ROS container), and libcamera is built in the container
(see [Camera in gaivotas_common](gaivotas_common/README.md#camera)).

1. Connect to the drone (Raspberry Pi) from the laptop:

   ```bash
   ssh <your user here>@192.168.0.105
   ```

2. Start everything with the helper script:

   ```bash
   ~/catkin_ws/src/gaivotas_ccd2026/gaivotas_common/scripts/start_ros.sh
   ```

   It opens a `tmux` session called `ros` with four panes:

   | Pane | What runs there |
   |---|---|
   | top left | starts the ROS container (`docker start ros-container`) and `htop` |
   | top right | the camera driver (`rosrun gaivotas_common camera_driver.py`) |
   | bottom left | a free shell inside the container — for you |
   | bottom right | `roscore` |

   tmux basics: `Ctrl+b` then an arrow key moves between panes; `Ctrl+b` then `d` leaves the
   session running in the background; `tmux attach -t ros` comes back to it;
   `tmux kill-session -t ros` closes everything.

3. In the free pane, start the mission nodes (MAVROS, `stream_keeper`, landing-base
   detection, precision landing and the mission-specific nodes), for example for A4:

   ```bash
   roslaunch a4_gaivotas_ccd2026 mission.launch
   ```

   Wait for `FCU conectada` and `Posição local OK` in the output. A `POSIÇÃO LOCAL NÃO
   DEFINIDA` error means the flight controller has no position yet — usually no GPS fix
   (see the [FAQ](FAQ.md)).

4. In another terminal inside the container (it must be a real terminal: the pause key reads
   the keyboard), start the mission script:

   ```bash
   rosrun a4_gaivotas_ccd2026 mission.py
   ```

   - The route comes from `a4_gaivotas_ccd2026/waypoints/a4.json` (another file:
     `_waypoints:=other.json`). Each point is `x` forward, `y` right, `z` up, in metres from
     the take-off position, plus `land` — `true` lands on the point, `false` flies through it:

     ```json
     [
       {"x": 2.0, "y": 4.0, "z": 1.5, "land": true},
       {"x": 0.0, "y": 0.0, "z": 1.5, "land": true}
     ]
     ```

   - **Space** pauses the mission script and resumes it. Whatever the flight controller is
     already doing (flying to the current point, landing) continues during the pause.
   - **Ctrl+C** stops the script: it flies back to the take-off point and lands.
   - Always keep the RC transmitter in hand, ready to take over.

# FAQ — known problems and how to fix them

Problems we actually ran into with this repository, the drone and the simulation.
Each entry: what you see, why it happens, what to do.

- [Git and files](#git-and-files)
- [Flight controller and MAVROS](#flight-controller-and-mavros)
- [Camera and vision](#camera-and-vision)
- [Rosbags](#rosbags)
- [Simulation](#simulation)

## Git and files

### `rosrun` cannot find a node that is obviously there

**Why:** the Python script lost its executable bit, usually after copying it by SFTP —
Remmina, file managers and VS Code create files as `rw-r--r--`.
**Fix:** `chmod +x <script>`. To copy with permissions use `rsync -av`, `scp -p` or `sftp -p`,
or simply `git pull` on the drone (git restores the bit).

### `fatal: detected dubious ownership in repository`

**Why:** the repository on the drone belongs to `root` (it is used from inside the container),
and git refuses to work in it as your normal user.
**Fix:** run git inside the container as root, or allow the path:
`git config --global --add safe.directory /home/<your user here>/catkin_ws/src/gaivotas_ccd2026`.

### `ai_models` / `camera_correction` folders are empty

**Why:** the repository was cloned without its submodules.
**Fix:** `git submodule update --init --recursive` (or clone with `--recurse-submodules`).
The submodule URLs are relative, so they use the same protocol as the main repository — clone
it over SSH on the drone, which has only an SSH key for GitHub.

### `git push` rejected because of a large rosbag

**Why:** a `.bag` file got committed. `.gitignore` only affects files that are not tracked
yet; a file that is already in a commit stays there.
**Fix:** remove it from the unpushed commits (`git rm --cached <file>` and amend/rewrite those
commits) before pushing. Recorded bags belong in `rosbags/`, which is ignored.

### `git pull` / `git fetch` hangs

**Why:** in our case the network path to GitHub was dropping connections for a while; without
a timeout SSH waits about two minutes before giving up.
**Fix:** retry later, or let SSH fail fast and retry by itself — in `~/.ssh/config` under
`Host github.com`: `ConnectTimeout 5` and `ConnectionAttempts 6`.

## Flight controller and MAVROS

### MAVROS does not connect to the FCU over Ethernet

You see `connected: False` in `/mavros/state`, or `bind: Cannot assign requested address` in the
MAVROS log.

**Why:** a wrong `fcu_url`. Its format is `udp://<local address:port MAVROS listens on>@<FCU address>`.
We had `udp://192.168.144.14:14550@` — the FCU's address on the left, so MAVROS tried to listen
on an address the Raspberry Pi does not have.
**Fix:** `udp://192.168.144.10:14550@192.168.144.14`: the Raspberry Pi's `eth0` address and the
port from the FCU parameter `NET_P1_PORT` (configure in Mission Planner/QGC), then the FCU address (`NET_IPADDR`). Check that `eth0`
really has that address: `ip -4 addr show eth0` (setup in the main README,
[Our setup](README.md#our-setup-pixhawk-6x-mini-over-ethernet)).

### MAVROS is connected, but the local position does not arrive (or arrives minutes later)

**Why:** ArduPilot sends the local position only after its EKF has an origin, normally from a
GPS fix. Attitude and IMU arrive right away, the position does not. Indoors without GPS it
never arrives.
**Fix:** wait for a GPS fix outdoors. `stream_keeper.py` prints an error with the GPS state
(fix, number of satellites) while the position is missing.

### Arming or mode changes do nothing, although `/mavros/state` says `connected: True`

**Why:** `tgt_system` in `apm.launch` differs from the flight controller's `SYSID_THISMAV`,
so the controller ignores the commands addressed to another system.
**Fix:** make them equal (ours: 105; SITL: 1).

### The telemetry rates change by themselves (e.g. `SR3_POSITION` goes back to 3)

**Why (most likely):** QGroundControl sends its own stream rates when it connects, and
ArduPilot saves them into the `SRn_*` parameters of the link they arrived on — our rates
(2/2/2/3/10/10/3) are exactly QGroundControl's defaults. MAVROS itself never asks for
telemetry. To confirm: set the value, reboot with QGroundControl closed, read it with
`rosrun mavros mavparam get SR3_POSITION`.
**Fix:** in QGroundControl set the ArduPilot stream rates to "controlled by vehicle", or leave
it to `stream_keeper.py`, which asks for the local position again when its rate drops.

## Camera and vision

### The camera cannot be used inside the container

**Why:** the camera devices are visible (the container is privileged), but libcamera is not
installed there.
**Fix:** build it once with `gaivotas_common/scripts/utils/build_libcamera.sh`. Only one
program can use the camera at a time — stop any other driver first.

### Precision landing corrects too little and the drone lands off-centre

**Why:** the camera calibration is not the one of our camera. The calibration converts pixels
into angles, so with a wrong one the direction to the base sent to the FCU is wrong. The
driver used to load `camera_correction/imx219_3280x2464/ost.yaml`, which was made with a
different, ~64° lens (`fx` 2639 at 3280 px). Our IMX219 has a ~120° lens (`fx` ≈ 510 at
1640 px), so every angle to the base came out about 2.5 times too small.
**Fix:** use a calibration made with this camera and in the same field of view — the default
is now `imx219_1640x1232`. A different output size of the same sensor mode is fine (the driver
scales the matrix); a cropped mode or another camera needs its own calibration. Check with
`rostopic echo -n1 /camera/camera_info`: at 1640×1232 the first value of `K` must be about 510. The best solution really is just make your own calibration ost.yaml, read the README in the `camera_correction` repo

### The image is too dark or washed out

**Why:** the driver does not use automatic exposure: it fixes the shutter time and the gain from
a preset (`~exposure_preset`). The `auto` preset chooses once, from a single frame measured at
start-up, so a frame taken in the shade, on the ground or towards the sky sets the wrong
exposure for the whole flight — that is why the default is now a fixed preset.
**Fix:** pick the preset for the light: `sun` (600 µs, gain 0.6), `day` (1000 µs, gain 1 —
default), `evening` (5000 µs, gain 6), `night` (12000 µs, gain 12), e.g.
`rosrun gaivotas_common camera_driver.py _exposure_preset:=evening`. A longer shutter time gives
a brighter image but more motion blur in flight.

### ArUco markers with ID 50 or higher are never detected

**Why:** `aruco_detect` with `dictionary = 0` uses `DICT_4X4_50`, which only has IDs 0–49.
**Fix:** `dictionary = 1` (`DICT_4X4_100`, IDs 0–99); the IDs 0–49 are the same markers.

### ArUco detection is poor, and with `errorCorrectionRate = 1.0` there are false detections

**Why:** for 4×4 dictionaries any `errorCorrectionRate` below 1.0 means "no bit errors
allowed", which loses markers at an angle or far away. With 1.0, overly loose
`polygonalApproxAccuracyRate` (0.15) and `minMarkerPerimeterRate` (0.01) turn noise into
marker candidates, and some of them decode as random IDs.
**Fix:** `errorCorrectionRate 1.0` together with `polygonalApproxAccuracyRate 0.03–0.05` and
`minMarkerPerimeterRate 0.03`. If junk IDs still appear, list the impossible IDs in
`ignore_fiducials`.

### `zbar` publishes nothing

**Why:** `zbar_ros` reads only raw images (not `…/compressed`) and subscribes to the image only
while something listens to its output.
**Fix:** feed it a raw topic (`/fiducial_images` from `aruco_detect` works) and listen to
`/barcode` (`rostopic echo /barcode`).

## Rosbags

### A recorded bag is `.bag.active` and cannot be opened

**Why:** the recording did not end normally — power cut, the drone switched off, or
`rosbag record` killed before it could close the file. The data is there, but the index that
is written at the end is missing.
**Fix:** `rosbag reindex <name>.bag.active`, then rename it to `<name>.bag`.
`gaivotas_common/scripts/utils/fetch_rosbag.sh` downloads such bags and fixes them by itself.
To avoid it, stop the recording (Ctrl+C on the launch) before powering off.

### Rosbags are huge

**Why:** the raw image topic `/camera/image_raw` was recorded. A raw frame is
width × height × 3 bytes: at 1640×1232 that is about 6 MB per frame, about 30 MB/s at 5 Hz,
while the JPEG on `/camera/image_raw/compressed` is a few tens of KB.
**Fix:** record `/camera/image_raw/compressed` and `/camera/camera_info`, never
`/camera/image_raw` — as the `bag_topics` of `a10_gaivotas_ccd2026/launch/mission.launch` do.

### Playing a bag in `rqt_bag` publishes nothing

**Why:** the standard `rqt_bag` Play button only moves the cursor until you right-click →
Publish → Publish All.
**Fix:** use `rqt_bag_autopublish.py` (already used by `a10_gaivotas_ccd2026/launch/post_analyzer.launch`).

## Simulation

### SITL runs and "flies", but the drone in Gazebo does not move

**Why:** `sim_vehicle.py` was started without `-f gazebo-iris`, so SITL simulates the drone
with its own physics instead of Gazebo.
**Fix:** `sim_vehicle.py -v ArduCopter -f gazebo-iris --console --map --out=udp:127.0.0.1:14551`
(see the main README). The `arducopter` command line must contain `--model gazebo-iris`.

### MAVROS in the simulation does not connect

**Why:** the launch used the real drone's address (`apm.launch` defaults) instead of SITL, or
an old MAVROS / Gazebo from a previous run is still holding the ports.
**Fix:** use the mission's simulation launch (`gazebo.launch`), which passes the SITL address,
and kill leftovers before starting again: `pkill -f roslaunch; pkill gzserver; pkill gzclient`.

### A mission world cannot include the shared arena

**Why:** Gazebo Classic includes models into a world, but not a world into another world —
there are no nested worlds, `<include>` only takes models.
**Fix:** keep one shared world (`gaivotas_common/worlds/arena.world`) and spawn the mission's
own objects from its `gazebo.launch` with `gazebo_ros spawn_model`, one node per object (see
`a10_gaivotas_ccd2026/launch/gazebo.launch`). A new object goes into `gaivotas_common/models` as
a model (`model.config` + `model.sdf`).

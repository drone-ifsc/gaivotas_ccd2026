# gaivotas_common

Nodes, launch files and data shared by all the gaivotas missions: MAVROS connection,
camera driver, landing-base detection, precision landing and helper scripts.
How to bring the drone up and run a mission is in the [quick start](../QUICKSTART.md); how to
connect to the flight controller is in the [main README](../README.md); known problems and
their fixes are in the [FAQ](../FAQ.md).

## Camera

The drone has an **IMX219** camera on the Raspberry Pi CSI connector. `camera_driver.py`
runs inside the ROS container, reads the camera with `rpicam-vid` and publishes:

| Topic | Type |
|---|---|
| `/camera/image_raw` | `sensor_msgs/Image` (bgr8) |
| `/camera/image_raw/compressed` | `sensor_msgs/CompressedImage` (JPEG) — use this one over Wi-Fi and in rosbags |
| `/camera/camera_info` | `sensor_msgs/CameraInfo` (calibration, see below) |

- **libcamera has to be built inside the container once** (the container is Ubuntu 20.04,
  which has no libcamera package, and the host one does not run there). As root in the
  container: `bash utils/build_libcamera.sh` (about 3 minutes on a Raspberry Pi 5; works for
  Pi 4 and Pi 5). Then `docker commit` the container so the build survives if it is
  recreated. Check: `rpicam-hello --list-cameras`.
- **Only one program can use the camera at a time.** If the driver cannot open it, something
  else (another driver, `rpicam-*`) is holding it.
- Main parameters (`_name:=value` on `rosrun`): `sensor_mode` (default `1640:1232` — the
  full field of view with 2×2 binning; a mode such as `640:480` crops the centre of the
  sensor), `width`/`height` (output size), `framerate` (5), `quality` (JPEG, 50),
  `undistort` (true), `calib_file`, `exposure_preset` (`day`, `evening`, `night`, `auto`).
- To see the image from a computer with a screen connected to the same ROS master:
  `rqt_image_view`, then pick `/camera/image_raw` with the `compressed` transport.

## Why `camera_correction` (calibration)

Every lens distorts the image (straight lines bend, points near the edges move), and the
pixel coordinates mean nothing in angles without knowing the camera's focal length and
optical centre. Precision landing needs exactly that: `landing_target_sender.py` turns the
pixel where the base was found into a direction from the drone to the base, using the
**intrinsic parameters** of the camera (`fx`, `fy`, `cx`, `cy`). With wrong or missing
calibration the direction is wrong and the drone lands off-centre, worst when the base is
near the edge of the image.

The `camera_correction` submodule holds the calibration results (`ost.yaml` from the ROS
`camera_calibration` tool: camera matrix and distortion coefficients) for the IMX219:

- `camera_driver.py` loads `~calib_file` (default `camera_correction/imx219_1640x1232/ost.yaml`),
  removes the lens distortion from every frame and publishes `/camera/camera_info`;
- `landing_target_sender.py` reads the intrinsics from `/camera/camera_info`;
- `aruco_detect` also uses `/camera/camera_info` when pose estimation is on.

The calibration must match the **sensor mode** (the field of view). Changing only the output
size of the same mode is fine — the driver scales the matrix — but a cropped mode needs its
own calibration. To calibrate again, print a checkerboard, run the driver with
`_undistort:=false` and:

```bash
rosrun camera_calibration cameracalibrator.py --size <inner corners, e.g. 8x6> \
    --square <square size in metres> image:=/camera/image_raw camera:=/camera
```

Save the result, put the new `ost.yaml` into the `camera_correction` repository (it is a
separate repository on purpose) and update the submodule here.

## AI models (landing-base detection)

The weights live in the `ai_models` submodule (its README has the details). They find the
square landing base and five **keypoints**: the centre and the four corners.

`base_reader.py` takes `/camera/image_raw`, runs the model about 5 times per second (`~rate`)
and publishes:

- `base_reader/pose` (`geometry_msgs/Point`): `x`, `y` — the base centre in pixels;
  `z` — an altitude estimate in metres;
- `base_reader/image_calib/compressed` — the image with the detection drawn on it, for
  debugging.

Backends (`~backend`):

| Backend | Model | Notes |
|---|---|---|
| `yolo` (default) | YOLO11n-pose, NCNN, input 320 px (`base_pouso/yolo11n/320_ncnn_model`) | confidence threshold 0.4; needs `pip install ultralytics` |
| `mobilenetv2` | MobileNetV2 heatmap, TFLite | slower in our tests, kept as a fallback; needs `tflite-runtime` |

`~model` points to another file. Inputs of 640/992/1216 px see smaller (farther) bases but
are slower; `yolo11m` at 1280 px is the "teacher" used offline for pre-labelling, not for
flight.

The altitude estimate is `Z = ALT_SCALE / d`, where `d` is the distance in pixels between the
centre and a corner. `ALT_SCALE` (in `base_reader.py`) depends on the base size and the
camera mode and must be calibrated: hold the camera at a known height `Z`, read `d`, then
`ALT_SCALE = Z × d`.

From the detection to the landing: `base_reader` → `landing_target_sender` (pixel → direction,
`LANDING_TARGET` message) → MAVROS → ArduPilot precision landing (flight-controller parameters
`PLND_ENABLED = 1`, `PLND_TYPE = 1`), which corrects the position while the drone descends in
`LAND` mode.

Training a new model:

1. Record frames from the drone camera (`utils/capture_topic.py`).
2. Label them in Label Studio: keypoint labels `center` and `corner`, plus a rectangle around
   the base. `utils/prelabel_yolo_pose.py` pre-labels the images with an existing model, so you
   only correct the points.
3. Export as Label Studio **JSON** (the "YOLO" export loses the keypoints) and convert:
   `python3 utils/ls_json_to_yolo_pose.py --json export.json --images <images> --out <dataset>`.
4. Train YOLO-pose (we used Kaggle), then export to NCNN from the `.pt` file
   (`utils/pt_2_ncnn.py`) — never convert again from an NCNN folder.
5. Commit the model to the `ai_models` repository and update the submodule here.

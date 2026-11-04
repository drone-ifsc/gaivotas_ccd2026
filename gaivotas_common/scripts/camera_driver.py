#!/usr/bin/env python3
r"""Driver da camera CSI rodando DENTRO do container ROS (substitui o camera_host_server.py,
que rodava no host com rospy do rospypi).

Publica os quadros da camera CSI (IMX219) direto nos topicos ROS, com os mesmos topicos,
parametros e processamento do camera_host_server.py:
    /camera/image_raw             sensor_msgs/Image (bgr8)
    /camera/image_raw/compressed  sensor_msgs/CompressedImage (jpeg)
    /camera/camera_info           sensor_msgs/CameraInfo

########################################################################################
##  ATENCAO: PRECISA DA LIBCAMERA (fork da Raspberry Pi) + rpicam-apps INSTALADOS NO
##  CONTAINER. O Ubuntu 20.04 do container nao tem pacote; a libcamera do host
##  (Raspberry Pi OS / Debian 12) nao serve: exige GLIBC 2.34, o container tem 2.31.
##  Compilar dentro do container (como root), nas mesmas versoes do host, com o script
##  que esta no repositorio (testado no RPi 5; ~3 min):
##
##    bash /root/catkin_ws/src/gaivotas_ccd2026/gaivotas_common/scripts/utils/build_libcamera.sh
##
##  Ele instala libpisp v1.2.1 + libcamera v0.5.2+rpt20250903 (pipelines rpi/vc4 do RPi 4 e
##  rpi/pisp do RPi 5) + rpicam-apps v1.8.1, contornando o que falta no focal: meson via pip
##  (o 0.53 do apt e velho), nlohmann_json 3.11.3 (a libpisp usa ordered_json), dma-heap.h
##  (headers do kernel 5.4) e -Dwerror=false (warnings do gcc 9).
##
##  Teste: rpicam-hello --list-cameras. A instalacao fica na camada do container: para
##  sobreviver a recriacao dele, docker commit.
########################################################################################

Requisitos do container: privileged (ve /dev/video*, /dev/media*, /dev/v4l-subdev*,
/dev/dma_heap). A camera so aceita UM processo por vez.

Execucao (no container, com o roscore no ar):
    rosrun gaivotas_common camera_driver.py

Parametros (via rosparam):
    ~publish_raw    bool — publicar Image decodificada      (default True)
    ~publish_jpeg   bool — publicar CompressedImage         (default True)
    ~sensor_mode    str  — modo de leitura do SENSOR (FoV). '1640:1232' = FoV
                           cheio com binning 2x2 em HW (default). NAO usar
                           640:480 aqui: recorta o centro do sensor.
    ~width          int  — largura de SAIDA (ISP redimensiona)  (default 1640)
    ~height         int  — altura de SAIDA                       (default 1232)
    ~framerate      int  — fps                                   (default 5)
    ~quality        int  — qualidade JPEG 1-100             (default 50)
    ~undistort      bool — corrigir distorcao de lente      (default True)
    ~calib_file     str  — caminho para ost.yaml            (default: camera_correction/imx219_1640x1232/ost.yaml)
    ~publish_camera_info bool — publicar CameraInfo em /camera/camera_info (default True)
    ~frame_id       str  — frame_id de Image/CameraInfo     (default "camera")
    ~exposure_preset str — 'sun'/'day'/'evening'/'night', ou 'auto' (mede o brilho uma vez na
                           partida e escolhe day/evening/night)  (default day)
    ~brightness_day_thresh   float — brilho medio >= disso -> day   (default 40)
    ~brightness_night_thresh float — brilho medio <  disso -> night (default 10)
    ~hsv_correct    bool — aplicar correcao HSV             (default False)
    ~hsv_h_shift    float — deslocamento de matiz [-180..180] (default 0)
    ~hsv_s_gain     float — ganho de saturacao [0..3]       (default 0.8)
    ~hsv_v_gain     float — ganho de valor/brilho [0..3]    (default 0.8)
"""
import os
import signal
import subprocess
import sys
import threading
import traceback

import cv2
import numpy as np
import rospy
import yaml
from sensor_msgs.msg import CameraInfo, CompressedImage, Image


def load_calibration(path):
    """Le ost.yaml e devolve (K, D, w_calib, h_calib)."""
    with open(path) as f:
        data = yaml.safe_load(f)
    K = np.array(data["camera_matrix"]["data"], dtype=np.float64).reshape(3, 3)
    D = np.array(data["distortion_coefficients"]["data"], dtype=np.float64).flatten()
    w = int(data["image_width"])
    h = int(data["image_height"])
    return K, D, w, h


def scale_K(K, w_calib, h_calib, w_actual, h_actual):
    """Escala a matriz K se a resolucao atual difere da resolucao de calibracao."""
    if (w_actual, h_actual) == (w_calib, h_calib):
        return K
    sx = w_actual / w_calib
    sy = h_actual / h_calib
    K = K.copy()
    K[0, 0] *= sx; K[0, 2] *= sx
    K[1, 1] *= sy; K[1, 2] *= sy
    return K


def build_undistort_maps(K, D, w_actual, h_actual):
    """Cria maps para cv2.remap (K ja escalado para a resolucao atual)."""
    map1, map2 = cv2.initUndistortRectifyMap(
        K, D, None, K, (w_actual, h_actual), cv2.CV_16SC2
    )
    return map1, map2


def build_camera_info(K, D, width, height, frame_id, rectified):
    """Monta um CameraInfo constante (so o header.stamp muda a cada frame).

    Se a imagem publicada ja foi retificada (undistort=True), D=0 e P usa a
    propria K, pois a distorcao foi removida usando K como nova camera matrix.
    Caso contrario, publica D real da calibracao (imagem ainda distorcida).
    """
    info = CameraInfo()
    info.header.frame_id = frame_id
    info.width = width
    info.height = height
    info.distortion_model = "plumb_bob"
    info.D = [0.0] * 5 if rectified else [float(v) for v in D]
    info.K = [float(v) for v in K.flatten()]
    info.R = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    info.P = [K[0, 0], K[0, 1], K[0, 2], 0.0,
              K[1, 0], K[1, 1], K[1, 2], 0.0,
              K[2, 0], K[2, 1], K[2, 2], 0.0]
    return info


def apply_hsv_correction(img_bgr, h_shift, s_gain, v_gain):
    """Aplica correcao HSV in-place onde possivel. h_shift em [-180..180], gains > 0."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    if h_shift != 0:
        h = ((h.astype(np.int16) + int(h_shift / 2)) % 180).astype(np.uint8)
    if s_gain != 1.0:
        s = np.clip(s.astype(np.float32) * s_gain, 0, 255).astype(np.uint8)
    if v_gain != 1.0:
        v = np.clip(v.astype(np.float32) * v_gain, 0, 255).astype(np.uint8)
    hsv = cv2.merge([h, s, v])
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


# Presets de exposicao: escolhidos na inicializacao pela luminosidade da cena.
# awb=None -> nao passa --awb (auto white balance).
EXPOSURE_PRESETS = {
    "sun":     {"shutter": 600,  "gain": 0.6,  "awb": "daylight"},
    "day":     {"shutter": 1000,  "gain": 1,  "awb": "daylight"},
    "evening": {"shutter": 5000,  "gain": 6,   "awb": None},
    "night":   {"shutter": 12000, "gain": 12,   "awb": None},
}


def probe_brightness():
    """Captura 1 quadro com exposicao FIXA (preset day) e devolve o brilho medio 0-255.

    A exposicao precisa ser fixa: com AE a cena escura seria "esticada" para brilho
    normal e a medida deixaria de refletir a luz ambiente. Retorna None em erro.
    """
    day = EXPOSURE_PRESETS["day"]
    cmd = ["rpicam-still", "-n", "--immediate", "-t", "1000",
           "--shutter", str(day["shutter"]), "--gain", str(day["gain"]),
           "--awb", day["awb"],
           "--width", "640", "--height", "480", "-e", "jpg", "-o", "-"]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=10)
        if res.returncode != 0 or not res.stdout:
            return None
        arr = np.frombuffer(res.stdout, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        return float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())
    except Exception:
        return None


def choose_preset(brightness, day_thresh, night_thresh):
    """Mapeia o brilho medido (proba com preset day) para um nome de preset."""
    if brightness is None:
        rospy.logwarn("Proba de brilho falhou; usando preset 'day'")
        return "day"
    if brightness >= day_thresh:
        return "day"
    if brightness < night_thresh:
        return "night"
    return "evening"


def build_camera_cmd(width, height, framerate, quality, preset, sensor_mode):
    p = EXPOSURE_PRESETS[preset]
    cmd = [
        "rpicam-vid",
        "-t", "0",
        "-n",                             # sem preview: no RPi4/VC4 o preview
                                          # disputa buffer com o encoder e trava
        # --mode = leitura do SENSOR (define o campo de visao), desacoplado do
        # tamanho de saida. IMX219: modos de FoV cheio sao 3280:2464 (full) e
        # 1640:1232 (binning 2x2, em hardware). Pedir 640:480 aqui recortaria so
        # o centro do sensor. Se width/height == sensor_mode -> saida nativa, sem
        # rescale do ISP (mais leve).
        "--mode", sensor_mode,
        "--width",  str(width),
        "--height", str(height),
        "--framerate", str(framerate),
        "--buffer-count", "4",            # VC4 precisa de buffers p/ ISP+encoder;
                                          # com 1 o pipeline starva e nao emite nada

        "--codec", "mjpeg",
        "--quality", str(quality),
        "--shutter", str(p["shutter"]),   # exposicao fixa [us]
        "--gain", str(p["gain"]),         # analog gain fixo
    ]
    if p["awb"] is not None:
        cmd += ["--awb", p["awb"]]
    cmd += ["--inline", "-o", "-"]
    return cmd


def forward_stderr(pipe, prefix):
    """Forward child stderr without letting the pipe block the camera process."""
    try:
        for raw in iter(pipe.readline, b""):
            line = raw.decode(errors="replace").rstrip()
            if line:
                print(f"[{prefix}] {line}", file=sys.stderr, flush=True)
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def main():
    phase = "startup"
    proc = None
    node_ready = False
    stopping = False

    def set_phase(value):
        nonlocal phase
        phase = value
        print(f"[camera_driver] phase: {phase}", file=sys.stderr, flush=True)

    def stop_camera():
        nonlocal stopping
        if stopping:
            return
        stopping = True
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=2)
            except Exception:
                pass

    def handle_signal(signum, frame):
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = f"signal {signum}"
        print(
            f"[camera_driver] received {name} during phase '{phase}'",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_stack(frame, file=sys.stderr)
        stop_camera()
        if node_ready and not rospy.is_shutdown():
            rospy.signal_shutdown(name)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    set_phase("rospy.init_node")
    rospy.init_node("camera_driver", anonymous=False, disable_signals=True)
    node_ready = True

    set_phase("read ros params")
    publish_raw  = rospy.get_param("~publish_raw",  True)
    publish_jpeg = rospy.get_param("~publish_jpeg", True)
    # FoV CHEIO com resolucao pequena: o sensor le o quadro inteiro com binning
    # 2x2 (1640x1232, FoV completo, em hardware) e o ISP so REDIMENSIONA para a
    # saida (leve, em hardware) -- nao ha recorte de centro. sensor_mode = FoV;
    # width/height = tamanho de saida (default 1640x1232 = o proprio modo, sem
    # rescale; 820x616 = metade exata, mesmo aspecto). Para menor: ~width/~height
    # (mantenha ~1.331 de aspecto). NAO ponha 640:480 em ~sensor_mode: isso recorta o centro.
    sensor_mode  = str(rospy.get_param("~sensor_mode", "1640:1232"))
    width        = rospy.get_param("~width",  1640)
    height       = rospy.get_param("~height", 1232)
    framerate    = rospy.get_param("~framerate", 5)
    quality      = rospy.get_param("~quality", 50)
    undistort    = rospy.get_param("~undistort",  True)
    default_calib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera_correction/imx219_1640x1232/ost.yaml")
    calib_file   = rospy.get_param("~calib_file", default_calib)
    publish_camera_info = rospy.get_param("~publish_camera_info", True)
    frame_id     = rospy.get_param("~frame_id", "camera")

    hsv_correct  = rospy.get_param("~hsv_correct",  False)
    hsv_h_shift  = float(rospy.get_param("~hsv_h_shift", 0.0))
    hsv_s_gain   = float(rospy.get_param("~hsv_s_gain",  0.8))
    hsv_v_gain   = float(rospy.get_param("~hsv_v_gain",  0.8))
    if hsv_correct:
        rospy.loginfo("HSV correction ativado: h_shift=%.1f s_gain=%.2f v_gain=%.2f",
                      hsv_h_shift, hsv_s_gain, hsv_v_gain)
    rospy.loginfo(
        "Camera params: %dx%d@%dfps raw=%s jpeg=%s undistort=%s hsv=%s quality=%d",
        width, height, framerate, publish_raw, publish_jpeg, undistort,
        hsv_correct, quality,
    )
    try:
        sm_w, sm_h = (int(v) for v in sensor_mode.replace("x", ":").split(":")[:2])
    except (ValueError, IndexError):
        sm_w = sm_h = 0
    if (width, height) == (sm_w, sm_h):
        rospy.loginfo("Sensor mode %s -> saida nativa (FoV cheio, sem rescale)", sensor_mode)
    else:
        rospy.loginfo("Sensor mode %s (FoV cheio) -> ISP redimensiona p/ %dx%d "
                      "(binning full + downscale em HW, sem recorte)",
                      sensor_mode, width, height)

    if not (publish_raw or publish_jpeg):
        rospy.logfatal("publish_raw=False и publish_jpeg=False — nada para publicar")
        sys.exit(1)

    # Calibracao: carrega uma vez. Necessaria para undistort e/ou CameraInfo.
    map1 = map2 = None
    camera_info_msg = None
    if undistort or publish_camera_info:
        try:
            K, D, w_calib, h_calib = load_calibration(calib_file)
            K = scale_K(K, w_calib, h_calib, width, height)
        except Exception as e:
            if undistort:
                rospy.logfatal("Falha ao carregar calibracao %s: %s", calib_file, e)
                sys.exit(1)
            rospy.logwarn("Sem calibracao (%s): CameraInfo desativado", e)
            publish_camera_info = False

    if undistort:
        set_phase("build undistort maps")
        map1, map2 = build_undistort_maps(K, D, width, height)
        rospy.loginfo("Undistort ativado. Calib: %s (calib %dx%d -> atual %dx%d)",
                      calib_file, w_calib, h_calib, width, height)

    if publish_camera_info:
        camera_info_msg = build_camera_info(K, D, width, height, frame_id, rectified=undistort)
        rospy.loginfo("CameraInfo ativado em /camera/camera_info (frame_id=%s, rectified=%s)",
                      frame_id, undistort)

    pub_jpeg = (rospy.Publisher("/camera/image_raw/compressed",
                                CompressedImage, queue_size=1)
                if publish_jpeg else None)
    pub_raw  = (rospy.Publisher("/camera/image_raw",
                                Image, queue_size=1)
                if publish_raw else None)
    pub_info = (rospy.Publisher("/camera/camera_info",
                                CameraInfo, queue_size=1)
                if publish_camera_info else None)

    # Preset de exposicao: 'auto' -> mede o brilho da cena (camera ainda livre,
    # antes do rpicam-vid) e escolhe day/evening/night pelos thresholds.
    preset = str(rospy.get_param("~exposure_preset", "day")).lower()
    day_thresh = float(rospy.get_param("~brightness_day_thresh", 40.0))
    night_thresh = float(rospy.get_param("~brightness_night_thresh", 10.0))

    if preset == "auto":
        set_phase("brightness probe")
        brightness = probe_brightness()
        preset = choose_preset(brightness, day_thresh, night_thresh)
        rospy.loginfo("Brightness probe: %s -> preset '%s'",
                      f"{brightness:.1f}" if brightness is not None else "falhou", preset)
    elif preset not in EXPOSURE_PRESETS:
        rospy.logwarn("~exposure_preset invalido '%s'; usando 'day'", preset)
        preset = "day"

    p = EXPOSURE_PRESETS[preset]
    rospy.loginfo("Exposure preset '%s': shutter=%dus gain=%s awb=%s",
                  preset, p["shutter"], p["gain"], p["awb"] or "auto")

    cmd = build_camera_cmd(width, height, framerate, quality, preset, sensor_mode)
    rospy.loginfo("Starting: %s", " ".join(cmd))

    set_phase("start rpicam-vid")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )
    threading.Thread(
        target=forward_stderr,
        args=(proc.stderr, "rpicam-vid"),
        daemon=True,
    ).start()

    rospy.on_shutdown(stop_camera)

    rospy.loginfo("Camera up. publish_jpeg=%s publish_raw=%s",
                  publish_jpeg, publish_raw)

    set_phase("read camera stream")
    buf = bytearray()
    READ = 65536
    SOI = b"\xff\xd8"
    EOI = b"\xff\xd9"

    try:
        while not rospy.is_shutdown():
            chunk = proc.stdout.read(READ)
            if not chunk:
                rc = proc.poll()
                rospy.logwarn("rpicam-vid stdout closed (returncode=%s)", rc)
                break
            buf.extend(chunk)

            # Извлекаем все полные JPEG из буфера (последний кадр публикуем)
            while True:
                soi = buf.find(SOI)
                eoi = buf.find(EOI, soi + 2) if soi != -1 else -1
                if soi == -1 or eoi == -1:
                    break
                jpg = bytes(buf[soi:eoi + 2])
                del buf[:eoi + 2]

                stamp = rospy.Time.now()

                # Decodifica somente quando precisa (raw publish OU undistort OU hsv_correct)
                needs_decode = pub_raw is not None or undistort or hsv_correct
                img = None
                if needs_decode:
                    arr = np.frombuffer(jpg, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is None:
                        continue
                    if undistort:
                        img = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
                    if hsv_correct:
                        img = apply_hsv_correction(img, hsv_h_shift, hsv_s_gain, hsv_v_gain)

                # Re-encode JPEG apenas se houve modificacao na imagem (undistort ou hsv)
                modified = undistort or hsv_correct

                if pub_info is not None:
                    camera_info_msg.header.stamp = stamp
                    pub_info.publish(camera_info_msg)

                if pub_jpeg is not None:
                    msg = CompressedImage()
                    msg.header.stamp = stamp
                    msg.header.frame_id = frame_id
                    msg.format = "jpeg"
                    if modified:
                        ok, jpg_enc = cv2.imencode(".jpg", img,
                                                   [cv2.IMWRITE_JPEG_QUALITY, quality])
                        if not ok:
                            continue
                        msg.data = jpg_enc.tobytes()
                    else:
                        msg.data = jpg
                    pub_jpeg.publish(msg)

                if pub_raw is not None:
                    raw = Image()
                    raw.header.stamp = stamp
                    raw.header.frame_id = frame_id
                    raw.height = img.shape[0]
                    raw.width  = img.shape[1]
                    raw.encoding = "bgr8"
                    raw.is_bigendian = 0
                    raw.step = img.shape[1] * 3
                    raw.data = img.tobytes()
                    pub_raw.publish(raw)
    finally:
        stop_camera()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass

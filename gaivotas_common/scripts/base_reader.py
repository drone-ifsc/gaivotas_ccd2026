#!/usr/bin/env python3
import cv2
import numpy as np
import os
import time
import rospy
from std_msgs.msg import Float32
from sensor_msgs.msg import Image, CompressedImage
from geometry_msgs.msg import Point
from cv_bridge import CvBridge

from rostopic_2_cv import *
# NB: ultralytics (YOLO) e tflite-runtime sao importados sob demanda em main(),
# conforme o backend escolhido — assim o dispositivo so precisa da dep que usa.

# foco_px * distancia_real_entre_keypoints [px*m]. Calibrar: a uma altura Z conhecida,
# ALT_SCALE = Z * d_px medido. Sem isso, dist_2_alt nao esta em metros.
ALT_SCALE = 230 #250

def dist_2_pts(x1, y1, x2, y2):
	return np.sqrt((x2 - x1)**2 + (y2 - y1)**2)

def find(frame, model):
	h_img, w_img = frame.shape[:2]
	results = model(np.ascontiguousarray(frame), verbose=False, imgsz=320, conf=0.4)

	if not results or results[0].keypoints is None or len(results[0].keypoints) == 0:
		return None

	boxes = results[0].boxes
	if len(boxes) == 0:
		return None

	best_idx = int(boxes.conf.argmax())

	kps = results[0].keypoints.xy[best_idx].cpu().numpy()  # (2, 2)
	if kps.shape[0] < 2:
		rospy.logwarn("No keypoints detected inside the bbox")
		return None

	center = np.array([kps[0][0], kps[0][1]], dtype=float)
	
	corners_quantity = kps.shape[0] - 1
	corners = [np.array([kps[i][0], kps[i][1]], dtype=float) for i in range(1, corners_quantity + 1)]

	x, y = int(center[0]), int(center[1])

	d = dist_2_pts(center[0], center[1], corners[0][0], corners[0][1])
	if d < 10:
		return None

	cv2.circle(frame, (x, y), 2, (0, 255, 0), 3, cv2.LINE_AA)
	cv2.circle(frame, (int(corners[0][0]), int(corners[0][1])), 6, (0, 165, 255), -1)
	# Altura ~ inversamente proporcional a distancia (px) entre os keypoints:
	#   d_px = (foco_px * dist_real_kp) / Z  ->  Z = ALT_SCALE / d_px
	#   ALT_SCALE = foco_px * dist_real_kp [px*m], calibrar empiricamente.
	dist_2_alt = np.clip(ALT_SCALE / d, 0.0, 6.0)

	return x, y, dist_2_alt


def load_tflite(model_path, num_threads=16):
	"""Carrega o modelo MobileNetV2 heatmap (saida: 5 keypoints (x,y) normalizados
	via soft-argmax embutido). Usa tflite-runtime (leve, edge) com fallback p/ tensorflow."""
	try:
		from tflite_runtime.interpreter import Interpreter          # runtime leve (edge/RPi)
	except ImportError:
		try:
			from ai_edge_litert.interpreter import Interpreter      # novo runtime (TF >= 2.16)
		except ImportError:
			import tensorflow as tf                                 # fallback: tf.lite.Interpreter
			Interpreter = tf.lite.Interpreter
	interp = Interpreter(model_path=model_path, num_threads=num_threads)
	interp.allocate_tensors()
	inp = interp.get_input_details()[0]
	out = interp.get_output_details()[0]
	ih, iw = int(inp['shape'][1]), int(inp['shape'][2])
	return {'interp': interp, 'in': inp, 'out': out, 'iw': iw, 'ih': ih}


def find_tflite(frame, tfl):
	"""Mesma interface de find(): retorna (x, y, dist_2_alt) ou None.
	Keypoints: 0 = centro, 1..4 = cantos (mesma ordem do YOLO-pose)."""
	h_img, w_img = frame.shape[:2]
	# Resize p/ o tamanho de entrada do modelo (mesmo squash de aspecto do treino).
	img = cv2.resize(frame, (tfl['iw'], tfl['ih']))
	img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
	img = img / 127.5 - 1.0                                   # preprocess do mobilenet_v2
	inp_arr = np.expand_dims(img, 0).astype(tfl['in']['dtype'])
	tfl['interp'].set_tensor(tfl['in']['index'], inp_arr)
	_t0 = time.perf_counter()
	tfl['interp'].invoke()
	_inv_ms = (time.perf_counter() - _t0) * 1000.0
	rospy.loginfo_throttle(2.0, "tflite invoke: %.1f ms (teto ~%.1f Hz)", _inv_ms, 1000.0 / max(_inv_ms, 1e-3))
	kps_n = tfl['interp'].get_tensor(tfl['out']['index'])[0].reshape(-1, 2)  # (K,2) em [0,1]
	if kps_n.shape[0] < 2:
		return None

	kps = kps_n * np.array([w_img, h_img], dtype=np.float32)  # -> pixels do frame original
	center = kps[0]
	corner = kps[1]
	x, y = int(center[0]), int(center[1])

	d = dist_2_pts(center[0], center[1], corner[0], corner[1])
	if d < 10:
		return None

	cv2.circle(frame, (x, y), 2, (0, 255, 0), 3, cv2.LINE_AA)
	cv2.circle(frame, (int(corner[0]), int(corner[1])), 6, (0, 165, 255), -1)
	dist_2_alt = np.clip(ALT_SCALE / d, 0.0, 6.0)

	return x, y, dist_2_alt


def main():
	rospy.init_node('base_reader', anonymous=False)

	publish_image = rospy.get_param('~publish_image', True)
	rate_hz = rospy.get_param('~rate', 5)


	ai_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_models')

	# Backend de deteccao: 'yolo' (ncnn, ultralytics) ou 'mobilenetv2' (tflite).
	backend = rospy.get_param('~backend', 'yolo').lower()

	if backend == 'mobilenetv2':
		model_path = rospy.get_param('~model',
							  os.path.join(ai_dir, 'base_pouso/mobilenetv2/mobilenetv2_heatmap_pose_fp16.tflite'))
		num_threads = int(rospy.get_param('~num_threads', 4))   # ~ n de nucleos fisicos; 16 oversubscreve
		model = load_tflite(model_path, num_threads=num_threads)
		find_fn = find_tflite
		rospy.loginfo("Backend MobileNetV2 (tflite) carregado: %s (entrada %dx%d)",
					  model_path, model['iw'], model['ih'])
	elif backend == 'yolo':
		from ultralytics import YOLO
		model_path = rospy.get_param('~model',
							  os.path.join(ai_dir, 'base_pouso/yolo11n/320_ncnn_model'))
		model = YOLO(model_path, task='pose')
		find_fn = find
		rospy.loginfo("Backend YOLO Pose (ncnn) carregado: %s", model_path)
	else:
		rospy.logerr("Backend invalido: '%s' (use 'yolo' ou 'mobilenetv2')", backend)
		rospy.signal_shutdown("backend invalido")
		return


	def _on_shutdown():
		rospy.loginfo("Saida forcada para liberar threads do NCNN/torch")
		os._exit(0)
	rospy.on_shutdown(_on_shutdown)

	bridge = CvBridge() if publish_image else None
	pose_pub = rospy.Publisher('base_reader/pose', Point, queue_size=1)
	calib_pub = rospy.Publisher('base_reader/image_calib/compressed', CompressedImage, queue_size=1) if publish_image else None

	gaugecam = WebcamNode()
	rospy.loginfo("webcam_opencv rodando. Escutando /camera/image_raw...")

	rate = rospy.Rate(rate_hz)

	rospy.loginfo("No base_reader iniciado (model=%s, publish_image=%s, rate=%dHz)", model_path, publish_image, rate_hz)

	while not rospy.is_shutdown():
		frame = gaugecam.cv_image

		if frame is None:
			rospy.logwarn("Sem frame da camera. Tentando novamente...")
			rate.sleep()
			continue

		clean_frame = frame.copy()
		result = find_fn(frame, model)

		if result is None:
			cv2.putText(frame, "Nao detectado", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
		else:
			x, y, dist_2_alt = result
			rospy.loginfo("Detectado: x=%d y=%d alt~%.3f", x, y, dist_2_alt)
			msg = Point()
			msg.x = float(x)
			msg.y = float(y)
			msg.z = float(dist_2_alt)
			pose_pub.publish(msg)
			
		if calib_pub is not None:
			_, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
			msg = CompressedImage()
			msg.header.stamp = rospy.Time.now()
			msg.format = 'jpeg'
			msg.data = jpeg.tobytes()
			calib_pub.publish(msg)

		rate.sleep()

if __name__=='__main__':
	main()

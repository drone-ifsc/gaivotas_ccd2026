#!/usr/bin/env python3
import cv2
import numpy as np
import os
import time
import rospy
from std_msgs.msg import Float32
from sensor_msgs.msg import Image, CompressedImage
from aruco_opencv_msgs.msg import ArucoDetection
from geometry_msgs.msg import Point
from cv_bridge import CvBridge

from rostopic_2_cv import *

def dist_2_pts(x1, y1, x2, y2):
	return np.sqrt((x2 - x1)**2 + (y2 - y1)**2)


def main():
	rospy.init_node('aruco_reader', anonymous=False)

	publish_image = rospy.get_param('~publish_image', True)
	rate_hz = rospy.get_param('~rate', 5)



	def _on_shutdown():
		rospy.loginfo("Saida forcada")
		os._exit(0)
	rospy.on_shutdown(_on_shutdown)

	bridge = CvBridge() if publish_image else None
	pose_pub = rospy.Publisher('aruco_reader/pose', Point, queue_size=1)
	calib_pub = rospy.Publisher('aruco_reader/image_calib/compressed', CompressedImage, queue_size=1) if publish_image else None

	gaugecam = WebcamNode()
	rospy.loginfo("webcam_opencv rodando. Escutando /camera/image_raw...")

	rate = rospy.Rate(rate_hz)

	while not rospy.is_shutdown():
		frame = gaugecam.cv_image

		if frame is None:
			rospy.logwarn("Sem frame da camera. Tentando novamente...")
			rate.sleep()
			continue

		dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
		parameters = cv2.aruco.DetectorParameters_create()
	
		gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
		corners, ids, rejected = cv2.aruco.detectMarkers(gray, dictionary, parameters)

		clean_frame = frame.copy()

		if ids is None:
			cv2.putText(frame, "Nao detectado", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
		else:
			rospy.loginfo("Detectado: "	, ids.flatten())
			cv2.aruco.drawDetectedMarkers(frame, corners, ids)
			#msg = Point()
			#msg.x = float(x)
			#msg.y = float(y)
			#msg.z = float(dist_2_alt)
			#pose_pub.publish(msg)
			
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

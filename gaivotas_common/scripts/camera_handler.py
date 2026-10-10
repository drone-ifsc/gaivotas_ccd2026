#!/usr/bin/env python3
import cv2
from sensor_msgs.msg import CompressedImage, Image
from sensor_msgs.msg import CameraInfo
import rospy
from cv_bridge import CvBridge, CvBridgeError
import yaml

class CameraHandler:
    def __init__(self):
        rospy.init_node('camera_handler')
        
        # Parameters
        self.publish_raw  = rospy.get_param("~publish_raw",  True)
        self.publish_jpeg = rospy.get_param("~publish_jpeg", True)
        self.quality      = rospy.get_param("~quality", 50)
        self.camera_info_topic = rospy.get_param('~camera_info_topic', '/camera/camera_info')
        self.frame_id = rospy.get_param('~frame_id', 'notebook_camera')
        self.ost_file = rospy.get_param('~ost_file', '/home/yabrik/catkin_ws/src/gauge_reader/camera_correction/fisheye_camera/ost.yaml')  # Path to the camera calibration file
        
        # Initialize camera capture
        rospy.loginfo("Initializing camera...")
        self.cvcam = cv2.VideoCapture(0)  # Open default camera
        if not self.cvcam.isOpened():
            rospy.logerr("Could not open camera.")
            return
        
        # Initialize CvBridge
        self.bridge = CvBridge()
        
        # Publishers for image and camera info
        self.pub_jpeg = (rospy.Publisher("/camera/image_raw/compressed",
                                CompressedImage, queue_size=1)
                if self.publish_jpeg else None)
        self.pub_raw  = (rospy.Publisher("/camera/image_raw",
                                Image, queue_size=1)
                if self.publish_raw else None)
        self.camera_info_pub = rospy.Publisher(self.camera_info_topic, CameraInfo, queue_size=10)
        
        # Load camera info from calibration file
        self.camera_info = self.get_camera_info()
        if self.camera_info is None:
            rospy.logwarn("Camera calibration not loaded. Camera info will not be published.")

        rospy.loginfo("Camera Handler initialized with topics: %s, %s and %s", self.pub_raw.name, self.pub_jpeg.name, self.camera_info_topic)
        while not rospy.is_shutdown():
            self.publish_camera_data()
    def publish_camera_data(self):
        # Simulate capturing an image (replace with actual camera capture code)
        try:
            # Create a dummy image (for demonstration purposes)
            sucess, cvimage = self.cvcam.read()  # Replace with actual image capture
            if cvimage is None or not sucess:
                rospy.logerr("Failed to read image.")
                return
            
            self.stamp = rospy.Time.now()

            if self.pub_raw is not None:
            # Convert OpenCV image to ROS Image message
                ros_image = self.bridge.cv2_to_imgmsg(cvimage, encoding="bgr8")
                ros_image.header.stamp = self.stamp
                ros_image.header.frame_id = self.frame_id
                self.pub_raw.publish(ros_image)
            
            if self.pub_jpeg is not None:
                msg = CompressedImage()
                msg.header.stamp = self.stamp
                msg.header.frame_id = self.frame_id
                msg.format = "jpeg"
                ok, jpg_enc = cv2.imencode(".jpg", cvimage,
                                                   [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                if not ok:
                    rospy.logwarn("No image on compressed topic published")
                msg.data = jpg_enc.tobytes()
                self.pub_jpeg.publish(msg)


            if self.camera_info is not None:
                self.camera_info.header = ros_image.header
                self.camera_info_pub.publish(self.camera_info)

        except CvBridgeError as e:
            rospy.logerr("CvBridge Error: %s", e)

    def get_camera_info(self):
        try:
            with open(self.ost_file, 'r') as file:
                data = yaml.safe_load(file)
                camera_info = CameraInfo()

                camera_info.width = data['image_width']
                camera_info.height = data['image_height']

                camera_info.distortion_model = data['distortion_model']

                camera_info.D = data["distortion_coefficients"]["data"]  # Distortion coefficients
                camera_info.K = data["camera_matrix"]["data"]  # Intrinsic parameters
                camera_info.R = data["rectification_matrix"]["data"] # Rotation matrix
                camera_info.P = data["projection_matrix"]["data"] # Projection matrix
                
                camera_info.binning_x = 0
                camera_info.binning_y = 0

                camera_info.roi.x_offset = 0
                camera_info.roi.y_offset = 0
                camera_info.roi.height = 0
                camera_info.roi.width = 0
                camera_info.roi.do_rectify = False

                return camera_info
            print(data)
        except FileNotFoundError:
            print(f"Error: The file {self.ost_file} was not found.")
        except yaml.YAMLError as exc:
            print(f"Error parsing YAML: {exc}")
    def __del__(self):
        if self.cvcam.isOpened():
            self.cvcam.release()
        rospy.loginfo("Camera Handler node shutting down.")
if __name__ == '__main__':
    try:
        camera_handler_node = CameraHandler()
        rospy.spin()
    except rospy.ROSInterruptException:
        cv2.destroyAllWindows()
        camera_handler_node.__del__()
        pass

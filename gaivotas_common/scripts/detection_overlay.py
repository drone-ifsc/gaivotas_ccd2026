#!/usr/bin/env python3
"""Overlay legivel das deteccoes: ID dos ArUco em letra grande e o texto de cada
codigo de barras/QR escrito AO LADO dele, nunca por cima.

O aruco_detect desenha o ID com a fonte fixa do OpenCV (minuscula em imagens grandes) e
o zbar_ros so publica o texto lido, sem a posicao. Este no:
  - recebe a imagem da camera (compressed) e os vertices do aruco_detect, casados pelo
    carimbo de tempo (o aruco_detect repassa o header da imagem);
  - le os codigos na mesma imagem com a libzbar (pyzbar), a mesma usada pelo zbar_ros;
  - publica a imagem anotada em ~image (raw) e ~image/compressed.

Sem o aruco_detect rodando nada e publicado: ele e quem dita o ritmo dos quadros.

Parametros privados:
    ~image_topic    (str):   CompressedImage de entrada (default '/camera/image_raw/compressed')
    ~vertices_topic (str):   fiducial_msgs/FiducialArray (default '/fiducial_vertices')
    ~text_scale     (float): altura do texto como fracao da altura da imagem (default 0.035)
    ~jpeg_quality   (int):   qualidade de ~image/compressed (default 80)

Dependencia: pip3 install pyzbar  (usa a libzbar0 que o zbar_ros ja instala).
"""
import cv2
import message_filters
import numpy as np
import rospy
from cv_bridge import CvBridge
from fiducial_msgs.msg import FiducialArray
from sensor_msgs.msg import CompressedImage, Image

try:
    from pyzbar import pyzbar
except ImportError:
    pyzbar = None

FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_PX = 22.0                  # altura aproximada do texto com escala 1.0
ARUCO_COLOR = (0, 140, 0)       # BGR
CODE_COLOR = (190, 60, 0)
MAX_TEXT = 40


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def draw_label(img, text, poly, color, scale, taken):
    """Escreve `text` numa caixa ao lado do poligono: acima, a direita, a esquerda ou
    abaixo, na primeira posicao que nao cubra nenhuma deteccao nem outra legenda.
    `taken` = retangulos (x0, y0, x1, y1) ja ocupados; a caixa escolhida entra nele."""
    h, w = img.shape[:2]
    thick = max(1, int(round(scale * 2)))
    (tw, th), base = cv2.getTextSize(text, FONT, scale, thick)
    pad = max(2, th // 3)
    bw, bh = tw + 2 * pad, th + base + 2 * pad
    x0, y0 = poly.min(axis=0)
    x1, y1 = poly.max(axis=0)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    candidates = [(cx - bw / 2.0, y0 - pad - bh),       # acima
                  (x1 + pad, cy - bh / 2.0),            # direita
                  (x0 - pad - bw, cy - bh / 2.0),       # esquerda
                  (cx - bw / 2.0, y1 + pad)]            # abaixo
    boxes = []
    for bx, by in candidates:
        # Puxa para dentro da imagem; se com isso cair sobre a propria deteccao,
        # o teste de sobreposicao abaixo descarta a posicao.
        bx = int(max(0, min(bx, w - bw)))
        by = int(max(0, min(by, h - bh)))
        boxes.append((bx, by, bx + bw, by + bh))
    box = next((b for b in boxes if not any(overlaps(b, t) for t in taken)), boxes[0])
    taken.append(box)
    cv2.rectangle(img, box[:2], box[2:], color, -1)
    cv2.putText(img, text, (box[0] + pad, box[1] + pad + th), FONT, scale,
                (255, 255, 255), thick, cv2.LINE_AA)


class DetectionOverlay:
    def __init__(self):
        rospy.init_node('detection_overlay')

        image_topic = rospy.get_param('~image_topic', '/camera/image_raw/compressed')
        vertices_topic = rospy.get_param('~vertices_topic', '/fiducial_vertices')
        self.text_scale = float(rospy.get_param('~text_scale', 0.035))
        self.jpeg_quality = int(rospy.get_param('~jpeg_quality', 80))

        self.bridge = CvBridge()
        self.raw_pub = rospy.Publisher('~image', Image, queue_size=1)
        self.jpeg_pub = rospy.Publisher('~image/compressed', CompressedImage, queue_size=1)

        if pyzbar is None:
            rospy.logerr("pyzbar nao instalado (pip3 install pyzbar): so os ArUco serao anotados")

        # buff_size grande: sem isso o rospy acumula quadros JPEG antigos no socket.
        subs = [message_filters.Subscriber(image_topic, CompressedImage, queue_size=5, buff_size=2 ** 24),
                message_filters.Subscriber(vertices_topic, FiducialArray, queue_size=5)]
        self.sync = message_filters.TimeSynchronizer(subs, queue_size=20)
        self.sync.registerCallback(self.callback)

        rospy.loginfo("detection_overlay: %s + %s -> %s", image_topic, vertices_topic,
                      rospy.resolve_name('~image'))

    def callback(self, img_msg, fid_msg):
        want_raw = self.raw_pub.get_num_connections() > 0
        want_jpeg = self.jpeg_pub.get_num_connections() > 0
        if not (want_raw or want_jpeg):
            return

        img = cv2.imdecode(np.frombuffer(img_msg.data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            rospy.logwarn_throttle(5.0, "Falha ao decodificar a imagem compressed")
            return

        # (texto, poligono Nx2, cor) de cada deteccao
        items = []
        for f in fid_msg.fiducials:
            poly = np.array([[f.x0, f.y0], [f.x1, f.y1], [f.x2, f.y2], [f.x3, f.y3]], np.int32)
            items.append(("ID %d" % f.fiducial_id, poly, ARUCO_COLOR))
        if pyzbar is not None:
            for code in pyzbar.decode(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)):
                # A fonte Hershey so tem ASCII.
                text = code.data.decode('utf-8', 'replace').encode('ascii', 'replace').decode()
                if len(text) > MAX_TEXT:
                    text = text[:MAX_TEXT - 3] + '...'
                r = code.rect
                pts = [[p.x, p.y] for p in code.polygon] if len(code.polygon) >= 3 else \
                    [[r.left, r.top], [r.left + r.width, r.top],
                     [r.left + r.width, r.top + r.height], [r.left, r.top + r.height]]
                items.append((text, np.array(pts, np.int32), CODE_COLOR))

        h = img.shape[0]
        scale = self.text_scale * h / FONT_PX
        line = max(2, h // 300)
        for _, poly, color in items:
            cv2.polylines(img, [poly], True, color, line, cv2.LINE_AA)
        taken = [tuple(poly.min(axis=0)) + tuple(poly.max(axis=0)) for _, poly, _ in items]
        for text, poly, color in items:
            draw_label(img, text, poly, color, scale, taken)

        if want_raw:
            out = self.bridge.cv2_to_imgmsg(img, encoding='bgr8')
            out.header = img_msg.header
            self.raw_pub.publish(out)
        if want_jpeg:
            ok, jpeg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
            if ok:
                self.jpeg_pub.publish(CompressedImage(header=img_msg.header, format='jpeg',
                                                      data=jpeg.tobytes()))


if __name__ == '__main__':
    try:
        DetectionOverlay()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass

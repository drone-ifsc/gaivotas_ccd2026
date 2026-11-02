#!/usr/bin/env python3
"""Garante os streams da FCU que as missões usam e acusa ERRO se a posição local não chega.

Substitui o "sleep N && mavsys rate --raw-sensors 20" dos launches. Aquele pedido saía uma
vez só, num tempo fixo: se o MAVROS ainda não tivesse ouvido a FCU (ele só aprende a porta
da FCU no primeiro pacote recebido), o pedido se perdia e nada era repetido. Além disso ele
pedia só RAW_SENSORS; a posição local fica em outro grupo e nunca era pedida.

Este nó:
  1. espera /mavros/state com connected=True;
  2. pede LOCAL_POSITION_NED a ~position_rate Hz (MAV_CMD_SET_MESSAGE_INTERVAL), o grupo
     RAW_SENSORS (IMU, pressão) a ~raw_sensors_rate Hz e GPS_RAW_INT a 2 Hz (para o
     diagnóstico: fix e satélites);
  3. vigia /mavros/local_position/pose: sem mensagens por ~timeout s, publica ERRO com o
     estado do GPS e refaz o pedido. A FCU só envia posição local depois que o EKF tem
     origem (normalmente com fix de GPS) — sem GPS o pedido sozinho não resolve;
  4. se a posição local cai abaixo de metade da taxa pedida (um GCS como o QGroundControl,
     ao conectar, manda as taxas dele e a FCU aplica no canal inteiro), avisa e pede de novo;
  5. se a FCU reconecta (connected False -> True), pede tudo de novo.

Lembrete — o pedido equivalente à mão, no terminal (era o que cada launch fazia):
    rosrun mavros mavsys rate --raw-sensors 20     # grupo RAW_SENSORS (IMU, pressão)
    rosrun mavros mavsys rate --position 20        # grupo POSITION (inclui LOCAL_POSITION_NED)

Parâmetros privados:
    ~position_rate    (float): Hz de LOCAL_POSITION_NED (default 20)
    ~raw_sensors_rate (int):   Hz do grupo RAW_SENSORS; 0 = não pedir (default 20)
    ~timeout          (float): s sem posição local até acusar erro e repetir o pedido (default 10)
"""
import collections

import rospy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import State
from mavros_msgs.srv import CommandLong, StreamRate, StreamRateRequest
from sensor_msgs.msg import NavSatFix, NavSatStatus
from std_msgs.msg import UInt32

MAV_CMD_SET_MESSAGE_INTERVAL = 511
LOCAL_POSITION_NED = 32
GPS_RAW_INT = 24
GPS_RATE = 2.0

GPS_STATUS = {
    NavSatStatus.STATUS_NO_FIX: "sem fix",
    NavSatStatus.STATUS_FIX: "com fix",
    NavSatStatus.STATUS_SBAS_FIX: "com fix (SBAS)",
    NavSatStatus.STATUS_GBAS_FIX: "com fix (GBAS/RTK)",
}


class StreamKeeper:
    def __init__(self):
        rospy.init_node("stream_keeper")
        self.position_rate = float(rospy.get_param("~position_rate", 20.0))
        self.raw_sensors_rate = int(rospy.get_param("~raw_sensors_rate", 20))
        self.timeout = float(rospy.get_param("~timeout", 10.0))

        self.connected = False
        self.pose_times = collections.deque(maxlen=200)   # instantes das últimas posições locais
        self.gps_status = None
        self.satellites = None

        rospy.Subscriber("/mavros/state", State, self.on_state)
        rospy.Subscriber("/mavros/local_position/pose", PoseStamped, self.on_pose)
        rospy.Subscriber("/mavros/global_position/raw/fix", NavSatFix, self.on_fix)
        rospy.Subscriber("/mavros/global_position/raw/satellites", UInt32, self.on_satellites)

        self.cmd = rospy.ServiceProxy("/mavros/cmd/command", CommandLong)
        self.stream_rate = rospy.ServiceProxy("/mavros/set_stream_rate", StreamRate)

    def on_state(self, msg):
        self.connected = msg.connected

    def on_pose(self, msg):
        self.pose_times.append(rospy.Time.now())

    def on_fix(self, msg):
        self.gps_status = msg.status.status

    def on_satellites(self, msg):
        self.satellites = msg.data

    def pose_rate(self, now, window=2.0):
        return sum(1 for t in self.pose_times if (now - t).to_sec() <= window) / window

    def gps_text(self):
        if self.gps_status is None:
            return "sem dados de GPS"
        sats = "?" if self.satellites is None else self.satellites
        return "GPS %s, %s satélites" % (GPS_STATUS.get(self.gps_status, self.gps_status), sats)

    def set_interval(self, msg_id, rate_hz):
        return self.cmd(broadcast=False, command=MAV_CMD_SET_MESSAGE_INTERVAL, confirmation=0,
                        param1=msg_id, param2=1e6 / rate_hz,
                        param3=0, param4=0, param5=0, param6=0, param7=0)

    def request(self):
        """Pede os streams à FCU. Retorna True se a FCU aceitou o pedido da posição local."""
        try:
            rospy.wait_for_service("/mavros/cmd/command", 5.0)
            resp = self.set_interval(LOCAL_POSITION_NED, self.position_rate)
            self.set_interval(GPS_RAW_INT, GPS_RATE)
            if not resp.success:
                rospy.logwarn("FCU não confirmou SET_MESSAGE_INTERVAL de LOCAL_POSITION_NED (result=%d)",
                              resp.result)
            if self.raw_sensors_rate > 0:
                rospy.wait_for_service("/mavros/set_stream_rate", 5.0)
                self.stream_rate(stream_id=StreamRateRequest.STREAM_RAW_SENSORS,
                                 message_rate=self.raw_sensors_rate, on_off=True)
            rospy.loginfo("Streams pedidos: LOCAL_POSITION_NED %.0f Hz, RAW_SENSORS %d Hz",
                          self.position_rate, self.raw_sensors_rate)
            return resp.success
        except (rospy.ROSException, rospy.ServiceException) as e:
            rospy.logwarn("Falha ao pedir streams à FCU: %s", e)
            return False

    def spin(self):
        rate = rospy.Rate(2)
        was_connected = False
        requested_at = None     # quando foi o último pedido (None = ainda não pediu)
        pose_ok = False
        rospy.loginfo("stream_keeper: aguardando conexão com a FCU...")

        while not rospy.is_shutdown():
            now = rospy.Time.now()

            if self.connected and not was_connected:
                rospy.loginfo("FCU conectada: pedindo streams")
                self.request()
                requested_at, pose_ok = now, False
            elif was_connected and not self.connected:
                rospy.logwarn("FCU desconectada: os streams serão pedidos de novo na reconexão")
            was_connected = self.connected

            if self.connected and requested_at is not None:
                last = self.pose_times[-1] if self.pose_times else None
                fresh = last is not None and (now - last).to_sec() < self.timeout
                first = next((t for t in self.pose_times if t >= requested_at), None)
                if fresh and not pose_ok and first is not None and (now - first).to_sec() >= 2.0:
                    rospy.loginfo("Posição local OK: %.1f Hz", self.pose_rate(now))
                    pose_ok = True
                elif not fresh and (now - requested_at).to_sec() >= self.timeout:
                    since = "nunca chegou" if last is None else "parou há %.0f s" % (now - last).to_sec()
                    rospy.logerr("POSIÇÃO LOCAL NÃO DEFINIDA: /mavros/local_position/pose %s. %s. "
                                 "A FCU só envia LOCAL_POSITION_NED depois que o EKF tem origem "
                                 "(fix de GPS). Pedido refeito.", since, self.gps_text())
                    self.request()
                    requested_at, pose_ok = now, False
                elif (pose_ok and (now - requested_at).to_sec() >= 3.0
                      and self.pose_rate(now, 3.0) < 0.5 * self.position_rate):
                    rospy.logwarn("Posição local caiu para %.1f Hz (pedido: %.0f Hz): outro GCS "
                                  "(ex.: QGroundControl) pode ter mudado os streams. Pedido refeito.",
                                  self.pose_rate(now, 3.0), self.position_rate)
                    self.request()
                    requested_at = now

            rate.sleep()


if __name__ == "__main__":
    try:
        StreamKeeper().spin()
    except rospy.ROSInterruptException:
        pass

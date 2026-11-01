#!/usr/bin/env python3
import rospy
from mavros_msgs.msg import OverrideRCIn
from std_srvs.srv import Trigger, TriggerResponse


# RC6 em numeracao 1-based -> indice 5 no array
RC_INDEX = 5

# Sentinelas do MAVROS no OverrideRCIn:
#   0     -> CHAN_RELEASE  (libera o canal, volta ao RC do operador)
#   65535 -> CHAN_NOCHANGE (mantem o estado atual; nao toca neste canal)
CHAN_NOCHANGE = 65535
CHAN_RELEASE = 0


class RcOverrideService:
    def __init__(self):
        rospy.init_node('rc_override_service')

        # Ajustaveis via rosparam / launch
        self.pwm_value = int(rospy.get_param('~pwm', 1200))
        self.duration = float(rospy.get_param('~duration', 4))
        self.rate_hz = float(rospy.get_param('~rate', 20.0))

        self.pub = rospy.Publisher('/mavros/rc/override', OverrideRCIn, queue_size=1)
        self.srv = rospy.Service('~trigger_servo', Trigger, self._handle)
        rospy.loginfo("rc_override_service pronto: pwm=%d duration=%.1fs rate=%.0fHz",
                      self.pwm_value, self.duration, self.rate_hz)

    def _build_msg(self, ch_value):
        msg = OverrideRCIn()
        # Todos os outros canais ficam em NOCHANGE -> nada e tocado fora do RC
        msg.channels = [CHAN_NOCHANGE] * len(msg.channels)
        msg.channels[RC_INDEX] = ch_value
        return msg

    def _handle(self, req):
        n_subs = self.pub.get_num_connections()
        if n_subs == 0:
            err = "Nenhum subscriber em /mavros/rc/override (mavros nao esta escutando)"
            rospy.logerr(err)
            return TriggerResponse(success=False, message=err)

        override_msg = self._build_msg(self.pwm_value)
        release_msg = self._build_msg(CHAN_RELEASE)

        rospy.loginfo("Override RC%d=%d por %.1fs (subs=%d, channels=%s)",
                      RC_INDEX+1, self.pwm_value, self.duration, n_subs,
                      list(override_msg.channels))
        rate = rospy.Rate(self.rate_hz)
        t_end = rospy.Time.now() + rospy.Duration(self.duration)
        while not rospy.is_shutdown() and rospy.Time.now() < t_end:
            self.pub.publish(override_msg)
            rate.sleep()

        # Libera RC explicitamente para o operador retomar controle do servo
        for _ in range(3):
            self.pub.publish(release_msg)
            rospy.sleep(0.05)

        return TriggerResponse(
            success=True,
            message=f"RC{RC_INDEX+1} override publicado (verifique /mavros/rc/in para confirmar aceitacao do FC)")


if __name__ == '__main__':
    RcOverrideService()
    rospy.spin()

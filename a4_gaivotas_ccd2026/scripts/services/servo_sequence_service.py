#!/usr/bin/env python3
import rospy
from mavros_msgs.srv import CommandLong
from a4_gaivotas_ccd2026.srv import ServoSequence, ServoSequenceResponse


MAV_CMD_DO_SET_SERVO = 183


class ServoSequenceService:
    def __init__(self):
        rospy.init_node('servo_sequence_service')

        rospy.loginfo("Aguardando /mavros/cmd/command...")
        rospy.wait_for_service('/mavros/cmd/command')
        self.cmd = rospy.ServiceProxy('/mavros/cmd/command', CommandLong)

        self.srv = rospy.Service('~run', ServoSequence, self._handle)
        rospy.loginfo("servo_sequence_service pronto")

    def _set_servo(self, channel, pwm):
        """Envia MAV_CMD_DO_SET_SERVO. Retorna (success, result_code)."""
        resp = self.cmd(
            broadcast=False,
            command=MAV_CMD_DO_SET_SERVO,
            confirmation=0,
            param1=float(channel),
            param2=float(pwm),
            param3=0.0, param4=0.0, param5=0.0, param6=0.0, param7=0.0,
        )
        return resp.success, resp.result

    def _handle(self, req):
        if not (1 <= req.servo <= 16):
            return ServoSequenceResponse(False, f"servo fora do range [1..16]: {req.servo}")
        if req.delay_sec < 0:
            return ServoSequenceResponse(False, f"delay_sec negativo: {req.delay_sec}")

        rospy.loginfo("Pulso 1: SERVO%d=%d", req.servo, req.pwm_first)
        ok, code = self._set_servo(req.servo, req.pwm_first)
        if not ok:
            return ServoSequenceResponse(False, f"FC rejeitou pulso 1 (result={code})")

        rospy.sleep(req.delay_sec)

        rospy.loginfo("Pulso 2: SERVO%d=%d", req.servo, req.pwm_second)
        ok, code = self._set_servo(req.servo, req.pwm_second)
        if not ok:
            return ServoSequenceResponse(False, f"FC rejeitou pulso 2 (result={code})")

        return ServoSequenceResponse(True, f"SERVO{req.servo}: {req.pwm_first} -> {req.delay_sec}s -> {req.pwm_second}")


if __name__ == '__main__':
    ServoSequenceService()
    rospy.spin()

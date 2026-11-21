"""Service mode switching talks to the installed robotd, not only the R17 helper."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controls import ControlError
from service_control import SWITCH_MODE_SCRIPT, ServiceTransport


class SwitchModeTests(unittest.TestCase):
    def test_r18_unit_is_the_path_when_the_r17_helper_is_absent(self):
        transport = ServiceTransport.__new__(ServiceTransport)
        transport._manage = Mock(return_value={"mode": "commissioning", "message": "已切换到 commissioning"})
        result = transport.switch_mode("commissioning", password="secret")
        argv = transport._manage.call_args.args[0]
        self.assertEqual(argv[:2], ["/bin/bash", "-c"])
        self.assertIs(argv[2], SWITCH_MODE_SCRIPT)
        self.assertEqual(argv[-1], "commissioning")
        self.assertIn("/opt/robot/daemon/current/bin/robotd", argv[2])
        self.assertIn("/opt/robot/feetech-ft5-r5/service.sh", argv[2])
        self.assertNotIn('"/opt/robot/feetech-ft5-r5/service.sh", *args', argv[2])
        self.assertEqual(result["mode"], "commissioning")
        self.assertEqual(transport._manage.call_args.kwargs["password"], "secret")

    def test_r18_motion_switch_enables_motion_flag(self):
        self.assertIn("motion_enabled = true", SWITCH_MODE_SCRIPT)
        self.assertIn('if [ "$target" = motion ]; then', SWITCH_MODE_SCRIPT)
        self.assertIn("imu_mount_verified", SWITCH_MODE_SCRIPT)
        self.assertIn("feetech_calibration", SWITCH_MODE_SCRIPT)

    def test_unknown_mode_is_refused_before_ssh(self):
        transport = ServiceTransport.__new__(ServiceTransport)
        transport._manage = Mock()
        with self.assertRaises(ControlError):
            transport.switch_mode("debug")
        transport._manage.assert_not_called()


if __name__ == "__main__":
    unittest.main()

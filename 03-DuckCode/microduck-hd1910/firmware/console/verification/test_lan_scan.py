import socket
import threading
import unittest

import lan_scan


class SubnetTests(unittest.TestCase):
    def test_wifi_and_ethernet_are_both_scanned(self):
        subnets = lan_scan.select_subnets([
            ("wlan0", "192.168.8.20"),
            ("eth0", "10.0.0.8"),
            ("rmnet_data0", "10.42.0.4"),
        ])
        self.assertEqual([item["prefix"] for item in subnets], ["192.168.8", "10.0.0"])
        self.assertEqual(subnets[0]["selves"], ["192.168.8.20"])

    def test_public_and_virtual_adapters_are_not_targets(self):
        subnets = lan_scan.select_subnets([
            ("wlan0", "8.8.8.8"),
            ("Tailscale Tunnel", "100.113.225.41"),
            ("vEthernet (WSL)", "172.31.16.1"),
            ("以太网", "192.168.6.15"),
        ])
        self.assertEqual(subnets, [{"prefix": "192.168.6", "name": "以太网", "selves": ["192.168.6.15"]}])

    def test_two_own_addresses_on_one_subnet_are_skipped_once(self):
        subnets = lan_scan.select_subnets([("wlan0", "192.168.1.4"), ("wlan1", "192.168.1.9")])
        self.assertEqual(subnets[0]["selves"], ["192.168.1.4", "192.168.1.9"])
        hosts = lan_scan.hosts_for(subnets[0])
        self.assertEqual(len(hosts), 252)
        self.assertNotIn("192.168.1.4", hosts)
        self.assertNotIn("192.168.1.9", hosts)

    def test_private_ranges(self):
        self.assertTrue(lan_scan.is_private_ipv4("10.1.2.3"))
        self.assertTrue(lan_scan.is_private_ipv4("172.16.0.1"))
        self.assertTrue(lan_scan.is_private_ipv4("192.168.6.151"))
        self.assertFalse(lan_scan.is_private_ipv4("172.15.0.1"))
        self.assertFalse(lan_scan.is_private_ipv4("8.8.8.8"))
        self.assertFalse(lan_scan.is_private_ipv4("169.254.1.1"))
        self.assertIsNone(lan_scan.parse_ipv4("192.168.1"))
        self.assertIsNone(lan_scan.parse_ipv4("192.168.1.256"))


class ProbeTests(unittest.TestCase):
    def test_open_port_and_refused_classification(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def accept_one():
            conn, _ = server.accept()
            conn.close()

        threading.Thread(target=accept_one, daemon=True).start()
        try:
            self.assertEqual(lan_scan.probe_port("127.0.0.1", port, 0.5), "open")
        finally:
            server.close()
        self.assertTrue(lan_scan._refused(ConnectionRefusedError(111, "Connection refused")))
        self.assertTrue(lan_scan._refused(OSError(10061, "由于目标计算机积极拒绝，无法连接。")))
        refused = OSError("connect failed")
        refused.winerror = 10061
        self.assertTrue(lan_scan._refused(refused))
        self.assertFalse(lan_scan._refused(TimeoutError("timed out")))

    def test_host_is_up_when_ssh_refuses_and_only_open_ssh_counts(self):
        self.assertIsNotNone(lan_scan._probe_host("127.0.0.1", threading.Event()))
        refused = {"ip": "192.168.1.9", "ssh_open": False}
        opened = {"ip": "192.168.1.2", "ssh_open": True}
        opened_later = {"ip": "192.168.1.20", "ssh_open": True}
        devices = [refused, opened_later, opened]
        devices.sort(key=lambda device: (0 if device["ssh_open"] else 1, *(int(part) for part in device["ip"].split("."))))
        self.assertEqual([device["ip"] for device in devices], ["192.168.1.2", "192.168.1.20", "192.168.1.9"])


if __name__ == "__main__":
    unittest.main()

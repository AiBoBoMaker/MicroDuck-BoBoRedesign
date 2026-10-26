import unittest
from embedded_ssh import parse_ssh, relay_command


class ParseTests(unittest.TestCase):
    def test_forward_keeps_the_unix_socket_intact(self):
        target, forwards, no_command, command, timeout = parse_ssh([
            'ssh', '-T', '-o', 'ConnectTimeout=6', '-N', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'LogLevel=DEBUG1', '-L', '127.0.0.1:4321:/run/robotd.sock', 'radxa@192.168.1.139'])
        self.assertEqual(target, 'radxa@192.168.1.139')
        self.assertEqual(forwards, ['127.0.0.1:4321:/run/robotd.sock'])
        self.assertTrue(no_command)
        self.assertEqual(command, [])
        self.assertEqual(timeout, 6)

    def test_remote_command_stays_one_argument(self):
        target, forwards, no_command, command, timeout = parse_ssh(
            ['ssh', '-T', '-o', 'BatchMode=yes', 'radxa@192.168.1.139', 'python3 -u -'])
        self.assertEqual(target, 'radxa@192.168.1.139')
        self.assertEqual(command, ['python3 -u -'])
        self.assertFalse(no_command)
        self.assertEqual(forwards, [])
        self.assertEqual(timeout, 8)

    def test_relay_names_the_socket_as_an_argument(self):
        command = relay_command('/run/robotd.sock')
        self.assertTrue(command.startswith('python3 -u -c '))
        self.assertTrue(command.endswith(' /run/robotd.sock'))
        self.assertIn('AF_UNIX', command)


if __name__ == '__main__':
    unittest.main()

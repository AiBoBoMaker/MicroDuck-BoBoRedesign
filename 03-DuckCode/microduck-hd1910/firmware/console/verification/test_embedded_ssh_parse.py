import subprocess
import sys
import threading
import unittest
from embedded_ssh import _RELAY, parse_ssh, relay_command


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
        self.assertIn('os.read(sys.stdin.fileno(),65536)', command)
        self.assertNotIn('stdin.buffer.read', command)

    def test_relay_forwards_a_short_request_before_stdin_closes(self):
        preamble = (
            'import socket,sys\n'
            'class _Peer:\n'
            '    def recv(self, n):\n'
            '        return b""\n'
            '    def sendall(self, data):\n'
            '        sys.stdout.buffer.write(data)\n'
            '        sys.stdout.buffer.flush()\n'
            '    def shutdown(self, how):\n'
            '        pass\n'
            'socket.socket=lambda *args, **kwargs: _Peer()\n'
        )
        script = preamble + _RELAY.replace(
            's=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)\ns.connect(sys.argv[1])\n',
            's=socket.socket()\n', 1)
        proc = subprocess.Popen([sys.executable, '-u', '-c', script, 'unused'],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            proc.stdin.write(b'{"id":1}\n')
            proc.stdin.flush()
            box = []
            reader = threading.Thread(target=lambda: box.append(proc.stdout.read(9)))
            reader.start()
            reader.join(2)
            if reader.is_alive() or box != [b'{"id":1}\n']:
                proc.kill()
                reader.join(1)
                self.fail('short request was not forwarded before stdin closed: '
                          + proc.stderr.read().decode() + ' got ' + repr(box))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                stream.close()


if __name__ == '__main__':
    unittest.main()

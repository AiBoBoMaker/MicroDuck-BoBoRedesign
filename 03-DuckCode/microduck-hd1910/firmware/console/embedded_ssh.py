"""In-process SSH for the phone build. Desktop keeps using the OpenSSH binary.

The console speaks to Zero through `ssh` child processes: a remote command, or
`ssh -L` onto a Unix socket. Android has no OpenSSH, so those launches become
Paramiko sessions. A local TCP port still stands in for the Unix socket, and
the remote `python3` relay opens that socket only after a client connects.
"""
import os
import shlex
import socket
import subprocess
import threading
from pathlib import Path

_POOL = {}
_POOL_LOCK = threading.Lock()
_OPEN_LOCK = threading.Lock()

# os.read, not stdin.buffer.read: on a pipe, BufferedReader.read keeps reading
# until it fills the requested size or sees EOF. The first robotd/tofd request
# is a short JSON line, so that read never returns and no reply ever comes back.
_RELAY = """
import os,socket,sys,threading
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
s.connect(sys.argv[1])
def outbound():
    try:
        while True:
            data=s.recv(65536)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except Exception:
        pass
thread=threading.Thread(target=outbound)
thread.start()
try:
    while True:
        data=os.read(sys.stdin.fileno(),65536)
        if not data:
            break
        s.sendall(data)
finally:
    try:
        s.shutdown(socket.SHUT_WR)
    except Exception:
        pass
    thread.join()
"""


def relay_command(path):
    return 'python3 -u -c ' + shlex.quote(_RELAY) + ' ' + shlex.quote(path)


def parse_ssh(argv):
    target = None
    forwards = []
    no_command = False
    command = []
    timeout = 8
    index = 1
    while index < len(argv):
        item = argv[index]
        if item == '-N':
            no_command = True
            index += 1
            continue
        if item == '-T':
            index += 1
            continue
        if item == '-o' and index + 1 < len(argv):
            key, _, value = argv[index + 1].partition('=')
            if key == 'ConnectTimeout' and value.isdigit():
                timeout = max(1, min(int(value), 30))
            index += 2
            continue
        if item == '-L' and index + 1 < len(argv):
            forwards.append(argv[index + 1])
            index += 2
            continue
        if item.startswith('-'):
            index += 1
            continue
        target = item
        command = argv[index + 1:]
        break
    return target, forwards, no_command, command, timeout


def _known_hosts():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return Path(base) / 'MicroduckConsole' / 'known_hosts'


def _password(env, target):
    if env and env.get('MICRODUCK_SSH_PASSWORD'):
        return env.get('MICRODUCK_SSH_PASSWORD')
    from ssh_connect import login_password
    return login_password(target)


def _client(target, password, timeout):
    import paramiko
    with _POOL_LOCK:
        found = _POOL.get(target)
        if found and found[0] == password:
            transport = found[1].get_transport()
            if transport is not None and transport.is_active():
                return found[1]
        path = _known_hosts()
        client = paramiko.SSHClient()
        if path.exists():
            client.load_host_keys(str(path))

        class AcceptNew(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                client.get_host_keys().add(hostname, key.get_name(), key)
                path.parent.mkdir(parents=True, exist_ok=True)
                client.save_host_keys(str(path))

        client.set_missing_host_key_policy(AcceptNew())
        user, host = target.split('@', 1)
        try:
            client.connect(host, port=22, username=user, password=password or None,
                           timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
                           look_for_keys=False, allow_agent=False)
        except paramiko.BadHostKeyException as exc:
            raise OSError('REMOTE HOST IDENTIFICATION HAS CHANGED: ' + str(exc)) from exc
        except paramiko.AuthenticationException as exc:
            raise OSError('Permission denied (' + str(exc) + ')') from exc
        except (paramiko.SSHException, socket.timeout, OSError) as exc:
            raise OSError(str(exc) or type(exc).__name__) from exc
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise OSError('SSH 连接没有建立')
        transport.set_keepalive(5)
        _POOL[target] = (password, client)
        return client


def _open_exec(client, command, timeout):
    with _OPEN_LOCK:
        channel = client.get_transport().open_session(timeout=timeout)
        channel.exec_command(command)
        return channel


class EmbeddedSSHProcess:
    def __init__(self, argv, stdin=None, stdout=None, stderr=None, env=None, **_ignored):
        self.args = list(argv)
        self.returncode = None
        self.pid = os.getpid()
        self.stdin = self.stdout = self.stderr = None
        self._stdin_r = self._stdout_w = self._stderr_w = None
        self._stop = threading.Event()
        self._done = threading.Event()
        self._channels = []
        self._conns = []
        self._listener = None
        self._env = env
        self.stdin, self._stdin_r = _stdio(stdin, write=True)
        self._stdout_w, self.stdout = _stdio(stdout, write=True)
        self._stderr_w, self.stderr = _stdio(stderr, write=True)
        threading.Thread(target=self._run, name='embedded-ssh', daemon=True).start()

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def terminate(self):
        self.kill()

    def kill(self):
        self._stop.set()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        for conn in list(self._conns):
            try:
                conn.close()
            except OSError:
                pass
        for channel in list(self._channels):
            try:
                channel.close()
            except Exception:
                pass
        self._finish(-15)

    def _finish(self, code):
        if self._done.is_set():
            return
        for stream in (self._stdin_r, self._stdout_w, self._stderr_w):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass
        self.returncode = code
        self._done.set()

    def _fail(self, message):
        if self._stderr_w is not None:
            try:
                self._stderr_w.write((message.rstrip() + '\n').encode())
                self._stderr_w.flush()
            except OSError:
                pass
        self._finish(255)

    def _run(self):
        try:
            target, forwards, no_command, command, timeout = parse_ssh(self.args)
            if not target:
                raise OSError('SSH 地址无效')
            password = _password(self._env, target)
            client = _client(target, password, timeout)
            if no_command or forwards:
                self._forward(client, forwards, timeout)
                return
            remote = command[0] if len(command) == 1 else shlex.join(command)
            if not remote:
                raise OSError('SSH 没有要执行的命令')
            self._exec(client, remote, timeout)
        except Exception as exc:
            self._fail(str(exc) or type(exc).__name__)

    def _forward(self, client, forwards, timeout):
        if len(forwards) != 1:
            raise OSError('只支持一条 Unix socket 转发')
        bind_host, port_text, remote_path = forwards[0].split(':', 2)
        port = int(port_text)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener = listener
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((bind_host, port))
        listener.listen(8)
        listener.settimeout(0.4)
        if self._stderr_w is not None:
            self._stderr_w.write(f'Local forwarding listening on {bind_host} port {port}.\n'.encode())
            self._stderr_w.write(b'debug1: Entering interactive session.\n')
            self._stderr_w.flush()
        while not self._stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._conns.append(conn)
            threading.Thread(target=self._bridge, args=(client, conn, remote_path, timeout), daemon=True).start()
        self._finish(0)

    def _bridge(self, client, conn, remote_path, timeout):
        channel = None
        try:
            channel = _open_exec(client, relay_command(remote_path), timeout)
            channel.settimeout(0.4)
            self._channels.append(channel)

            def inbound():
                try:
                    while not self._stop.is_set():
                        data = conn.recv(65536)
                        if not data:
                            break
                        channel.sendall(data)
                except Exception:
                    pass
                finally:
                    try:
                        channel.shutdown_write()
                    except Exception:
                        pass

            threading.Thread(target=inbound, daemon=True).start()
            while not self._stop.is_set():
                try:
                    data = channel.recv(65536)
                except socket.timeout:
                    if channel.exit_status_ready():
                        break
                    continue
                if not data:
                    break
                conn.sendall(data)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass

    def _exec(self, client, command, timeout):
        channel = _open_exec(client, command, timeout)
        channel.settimeout(0.4)
        self._channels.append(channel)

        def pump_in():
            try:
                if self._stdin_r is None:
                    return
                while not self._stop.is_set():
                    data = self._stdin_r.read(65536)
                    if not data:
                        break
                    channel.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    channel.shutdown_write()
                except Exception:
                    pass

        def pump_err():
            try:
                while not self._stop.is_set():
                    try:
                        data = channel.recv_stderr(65536)
                    except socket.timeout:
                        if channel.exit_status_ready():
                            break
                        continue
                    if not data:
                        break
                    if self._stderr_w is not None:
                        self._stderr_w.write(data)
                        self._stderr_w.flush()
            except Exception:
                pass

        threading.Thread(target=pump_in, daemon=True).start()
        threading.Thread(target=pump_err, daemon=True).start()
        try:
            while not self._stop.is_set():
                try:
                    data = channel.recv(65536)
                except socket.timeout:
                    if channel.exit_status_ready() and not channel.recv_ready():
                        break
                    continue
                if not data:
                    break
                if self._stdout_w is not None:
                    self._stdout_w.write(data)
                    self._stdout_w.flush()
        except Exception as exc:
            self._fail(str(exc) or type(exc).__name__)
            return
        channel.settimeout(2)
        try:
            code = channel.recv_exit_status()
        except socket.timeout:
            code = channel.exit_status if channel.exit_status_ready() else 0
        self._finish(code)


def _stdio(target, write):
    """Return (write_end, read_end) for a PIPE, or Nones for DEVNULL."""
    if target is None or target == subprocess.DEVNULL:
        return None, None
    if target != subprocess.PIPE:
        raise OSError('内置 SSH 只支持管道和空输入输出')
    read, written = os.pipe()
    read_file = os.fdopen(read, 'rb', buffering=0)
    write_file = os.fdopen(written, 'wb', buffering=0)
    if write:
        return write_file, read_file
    return read_file, write_file

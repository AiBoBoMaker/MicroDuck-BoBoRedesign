import os
import runpy
import sys


def main(root):
    """Run the desktop console inside the phone and serve it on 127.0.0.1:8090."""
    root = os.fspath(root)
    os.environ['MICRODUCK_EMBEDDED_SSH'] = '1'
    os.environ['HOME'] = root
    os.environ['XDG_CONFIG_HOME'] = os.path.join(root, 'config')
    os.chdir(root)
    if root not in sys.path:
        sys.path.insert(0, root)
    sys.argv = ['console.py', '--dashboard', '--feetech', '--port', '8090']
    try:
        runpy.run_path(os.path.join(root, 'console.py'), run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise RuntimeError('中控退出，代码 %s' % (exc.code,))

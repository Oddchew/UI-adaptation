import json
import os
import socket
import subprocess
import sys
import threading
import time
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BrowserIntegration(unittest.TestCase):
    def test_errors_show_and_hide_with_browser_confirmation(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        tempdir = tempfile.TemporaryDirectory()
        env = dict(os.environ, MODULE_A_PORT=str(port), MODULE_A_USE_SC='0', PYTHONUTF8='1', MODULE_C_DB=str(Path(tempdir.name) / 'test.sqlite3'))
        server = subprocess.Popen([sys.executable, str(ROOT / 'integration/server.py')], cwd=ROOT,
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f'http://127.0.0.1:{port}'
        def request(path, body=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)
        stop = threading.Event()
        def browser():
            while not stop.is_set():
                try:
                    for cmd in request('/api/runtime/pending?user_id=u&session_id=s')['commands']:
                        request('/api/runtime/ack', {'token': cmd['token'], 'success': True})
                except Exception:
                    pass
                stop.wait(.03)
        thread = threading.Thread(target=browser, daemon=True)
        try:
            for _ in range(100):
                try:
                    if request('/api/health')['ok']: break
                except OSError:
                    time.sleep(.05)
            else: self.fail('server did not start')
            thread.start()
            common = {'user_id': 'u', 'interface_id': 'python_tutor_model', 'session_id': 's'}
            error = dict(common, event_type='error', element_id='code_editor', error_code='syntax')
            self.assertFalse(request('/api/event', error)['ui']['hints_panel']['visible'])
            self.assertTrue(request('/api/event', error)['ui']['hints_panel']['visible'])
            self.assertFalse(request('/api/event', dict(common, event_type='hint_hide', element_id='hints_panel'))['ui']['hints_panel']['visible'])
            self.assertFalse(request('/api/event', error)['ui']['hints_panel']['visible'])
        finally:
            stop.set()
            if thread.is_alive(): thread.join(timeout=5)
            server.terminate()
            server.wait(timeout=5)
            tempdir.cleanup()


if __name__ == '__main__':
    unittest.main()

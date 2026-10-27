"""Kindle用シェルを模擬コマンドで実行し、待機と復帰を検証する。"""
from pathlib import Path
import subprocess
import tempfile
import unittest


class ScriptletTest(unittest.TestCase):
    def run_script(self, stop):
        source = (Path(__file__).parent / 'kindle/aimonitor_start.sh').read_text()
        # バックグラウンド化だけ外し、製品コードのループを同期実行する。
        source = source.replace(') </dev/null >/dev/null 2>&1 &', ')').replace('echo $! > "$PIDFILE"', '')
        with tempfile.TemporaryDirectory() as tmp:
            source = source.replace('/tmp/aimonitor', tmp + '/aimonitor')
            mocks = '''
elapsed=0
requests=0
sleep() { elapsed=$((elapsed + $1)); }
curl() {
  requests=$((requests + 1))
  echo "FETCH $elapsed"
  : > "$IMG.tmp"
  [ "$requests" -gt 4 ]
}
wget() { echo UNEXPECTED_WGET; return 1; }
eips() { echo DRAW; }
lipc-set-prop() { :; }
lipc-get-prop() {
  if STOP; then echo screenSaver; else echo awake; fi
}
'''.replace('STOP', stop)
            return subprocess.run(['sh'], input=(mocks + source).replace('lipc-set-prop', 'mock_set_prop').replace('lipc-get-prop', 'mock_get_prop'), text=True,
                                  capture_output=True, timeout=5, check=True).stdout

    def test_backoff_cap_and_success_reset(self):
        output = self.run_script('[ "$requests" -ge 6 ]')
        self.assertEqual([line for line in output.splitlines() if line.startswith('FETCH')],
                         ['FETCH 3', 'FETCH 603', 'FETCH 1803', 'FETCH 3603', 'FETCH 5403', 'FETCH 5703'])
        self.assertEqual(output.count('DRAW'), 2)
        self.assertNotIn('UNEXPECTED_WGET', output)

    def test_power_button_stops_during_backoff(self):
        output = self.run_script('[ "$elapsed" -ge 8 ]')
        self.assertEqual(output.splitlines(), ['FETCH 3'])


if __name__ == '__main__':
    unittest.main()

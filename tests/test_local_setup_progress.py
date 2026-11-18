import re
from pathlib import Path
import subprocess
import unittest

from server.nodekit.local_setup_progress import PREFIX, REMOTE_STAGES, StageReader


class ProgressTests(unittest.TestCase):
    def test_chunk_boundaries_and_log_injection_never_leak_raw_output(self):
        seen = []
        reader = StageReader(seen.append)
        reader(b'private password\n' + PREFIX[:8])
        reader(PREFIX[8:] + b'dependencies\n' + PREFIX + b'core\n')
        reader(b'prefix ' + PREFIX + b'gateway\n')
        reader(PREFIX + b'cleanup\n' + PREFIX + b'unknown-secret\n')
        reader(b'x' * 100000 + PREFIX + b'services\n')
        reader(PREFIX + b'services\n' + PREFIX + b'deploy')
        self.assertEqual(seen, ['dependencies', 'core', 'services'])
        self.assertLessEqual(len(reader.pending), 128)

    def test_install_script_markers_match_real_steps_and_require_setup_job(self):
        script = (Path(__file__).resolve().parents[1] / 'deploy/install.sh').read_text()
        self.assertEqual(tuple(re.findall(r'^progress ([a-z_]+)$', script, re.M)), REMOTE_STAGES)
        function = next(line for line in script.splitlines() if line.startswith('progress()'))
        p = subprocess.run(['/bin/bash', '-c', "SETUP_JOB=''; " + function + "; progress core; SETUP_JOB=fixture; progress dependencies"], capture_output=True, check=True)
        self.assertEqual(p.stdout, b'\n' + PREFIX + b'dependencies\n')


if __name__ == '__main__':
    unittest.main()

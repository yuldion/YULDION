"""The independent actor must import and validate without optional rehearsal tools."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class OptionalIsolationTest(unittest.TestCase):
    def test_core_does_not_import_authoring_tools(self):
        root = Path(__file__).resolve().parents[1]
        code = '''
import sys
from pathlib import Path
from yuldion.engine import Engine
from yuldion.cli import main
from yuldion.config import load_config
config = load_config(Path('examples/hamlet.json'))
assert len(config.script) > 0
assert not any(name.startswith('yuldion.tools') for name in sys.modules)
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=root,
                                env={**os.environ, 'PYTHONPATH':str(root/'src')},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

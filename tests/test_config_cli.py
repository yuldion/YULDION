from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import json
import unittest
from yuldion.cli import main
from yuldion.config import load_config
from yuldion.errors import YuldionError
from yuldion.stimuli import FileStimuli

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples/hamlet.json'

class ConfigTests(unittest.TestCase):
    def test_validate_never_imports_model_plugins(self):
        with patch('yuldion.config.importlib.import_module') as importer, redirect_stdout(io.StringIO()):
            self.assertEqual(main(['validate', '--config', str(EXAMPLE)]), 0)
            importer.assert_not_called()

    def test_unconfigured_doctor_and_run_fail_without_inference(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['doctor', '--config', str(EXAMPLE)]), 2)
            self.assertEqual(main(['run', '--config', str(EXAMPLE)]), 2)

    def test_malformed_config_is_rejected(self):
        template = json.loads(EXAMPLE.read_text())
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            for mutation in [dict(schema_version=2), dict(script=[]), dict(adapters={})]:
                path.write_text(json.dumps({**template, **mutation}))
                with self.assertRaises(YuldionError): load_config(path)

    def test_relative_output_path_is_relative_to_config(self):
        config = load_config(EXAMPLE)
        self.assertEqual(config.output_dir.resolve(), EXAMPLE.parents[1] / 'outputs')

    def test_partial_stimulus_line_waits_and_future_stimulus_is_not_consumed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.jsonl'
            row = json.dumps({'id':'p1','kind':'external_text','text':'A real supplied cue.','after_segment':2})
            path.write_text(row)
            stimuli = FileStimuli(path)
            self.assertEqual(stimuli(2), [])
            path.write_text(row+'\n')
            self.assertEqual(stimuli(1), [])
            self.assertEqual(len(stimuli(2)), 1)
            self.assertEqual(stimuli(3), [])

if __name__ == '__main__': unittest.main()

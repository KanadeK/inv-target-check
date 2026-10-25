"""Actual Sphinx integration; development-only dependency, required in CI."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from inv_target_check import audit


@unittest.skipUnless(importlib.util.find_spec('sphinx'), 'install Sphinx to run builder integration')
class SphinxIntegration(unittest.TestCase):
    def test_real_builders_and_mutated_output(self):
        source = Path(__file__).resolve().parents[1] / 'examples/docs'
        with tempfile.TemporaryDirectory() as temp:
            for builder in ['html', 'dirhtml']:
                with self.subTest(builder=builder):
                    output = Path(temp) / builder
                    run = subprocess.run([sys.executable, '-m', 'sphinx', '-b', builder, '-W', str(source), str(output)],
                                         capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    result = audit(output / 'objects.inv', output)
                    self.assertTrue(result['passed'], result)
                    self.assertGreaterEqual(result['entries'], 5)
                    # The index can remain stale even when a deployment loses a page.
                    page = output / ('api/index.html' if builder == 'dirhtml' else 'api.html')
                    page.unlink()
                    self.assertFalse(audit(output / 'objects.inv', output)['passed'])

    def test_singlehtml_inventory_reports_actual_missing_targets(self):
        # singlehtml can export labels for index/search pages it does not build.
        # Check the target bytes directly, rather than assuming a clean build
        # guarantees a clean inventory or teaching the auditor to ignore rows.
        source = Path(__file__).resolve().parents[1] / 'examples/docs'
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            run = subprocess.run([sys.executable, '-m', 'sphinx', '-b', 'singlehtml', '-W', str(source), str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            result = audit(output / 'objects.inv', output)
            absent = [item for item in result['results'] if item['code'] == 'missing-file']
            self.assertTrue(absent)
            for item in absent:
                self.assertFalse((output / item['file']).is_file())
            self.assertFalse(result['passed'])

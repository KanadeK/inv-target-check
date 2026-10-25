from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from inv_target_check import AuditError, audit, read_inventory
from inv_target_check.core import parse_entry

HEADER = b'# Sphinx inventory version 2\n# Project: Test\n# Version: 1\n# zlib\n'


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'html'
        self.root.mkdir()
        self.inv = self.base / 'objects.inv'
        (self.root / 'index.html').write_text('<h1 id="hello">Hi</h1>', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def inventory(self, rows):
        self.inv.write_bytes(HEADER + zlib.compress(('\n'.join(rows) + '\n').encode('utf-8')))

    def check(self, uri, **kwargs):
        self.inventory([f'hello py:function 1 {uri} -'])
        return audit(self.inv, self.root, **kwargs)

    def test_dollar_and_fragment(self):
        r = self.check('index.html#$')
        self.assertTrue(r['passed'])
        self.assertEqual(r['results'][0]['target'], 'index.html#hello')

    def test_names_spaces_roles_colons_and_empty_uri(self):
        e = parse_entry('a long name rst:directive:option -1 index.html#hello Display name', 5)
        self.assertEqual(e.name, 'a long name')
        self.assertEqual(e.role, 'rst:directive:option')
        self.assertEqual(e.display_name, 'Display name')
        self.inventory(['index std:doc -1  Home page'])
        self.assertTrue(audit(self.inv, self.root)['passed'])

    def test_missing_file_and_anchor_separate(self):
        self.assertEqual(self.check('missing.html')['results'][0]['code'], 'missing-file')
        self.assertEqual(self.check('index.html#absent')['results'][0]['code'], 'missing-anchor')

    def test_entity_unicode_and_legacy_anchor(self):
        (self.root / 'café.html').write_text('<p id="café&amp;x"></p><a name="old"></a>', encoding='utf-8')
        for uri in ['caf%C3%A9.html#caf%C3%A9%26x', 'caf%C3%A9.html#old']:
            self.assertTrue(self.check(uri)['passed'])

    def test_query_empty_fragment_and_top(self):
        for uri in ['index.html?q=1#hello', 'index.html#', 'index.html#TOP']:
            self.assertTrue(self.check(uri)['passed'])

    def test_anchor_case_sensitive(self):
        self.assertFalse(self.check('index.html#HELLO')['passed'])

    def test_file_case_sensitive_on_all_platforms(self):
        self.assertEqual(self.check('INDEX.html')['results'][0]['code'], 'missing-file')

    def test_dirhtml_and_missing_directory(self):
        (self.root / 'guide').mkdir()
        (self.root / 'guide/index.html').write_text('<span id="hello">x</span>', encoding='utf-8')
        self.assertTrue(self.check('guide/#hello')['passed'])
        self.assertFalse(self.check('index.html/#hello')['passed'])
        self.assertFalse(self.check('missing/#hello')['passed'])

    def test_safe_dot_normalization(self):
        self.assertTrue(self.check('guide/../index.html#hello')['passed'])

    def test_external_requires_explicit_allowance(self):
        r = self.check('https://example.org/api#hello')
        self.assertFalse(r['passed'])
        self.assertEqual(r['summary']['unverified'], 1)
        self.assertTrue(self.check('https://example.org/api', allow_external=True)['passed'])
        self.assertTrue(self.check('//example.org/api', allow_external=True)['passed'])

    def test_base_url_mapping(self):
        for uri in ['/docs/index.html#hello', 'https://EXAMPLE.com:443/docs/index.html#hello', 'index.html#hello']:
            self.assertTrue(self.check(uri, base_url='https://example.com/docs/')['passed'])
        self.assertFalse(self.check('/index.html#hello', base_url='https://example.com/docs/')['passed'])
        self.assertFalse(self.check('/docs/index.html#hello')['passed'])

    def test_base_encoded_path(self):
        self.assertTrue(self.check('/caf%C3%A9/index.html#hello', base_url='https://example.com/caf%C3%A9/')['passed'])

    def test_port_zero_is_not_default_port(self):
        result = self.check('https://example.com:0/docs/index.html', base_url='https://example.com/docs/')
        self.assertEqual(result['summary']['unverified'], 1)

    def test_traversal_ads_backslash_encoded_separators(self):
        for uri in ['../outside.html', '%2e%2e/outside', 'index.html:stream', 'a%5cb', 'a%2fb',
                    'a\\b', '%00', 'index.html#bad%FF', 'index.html#bad%ZZ', 'https://[']:
            with self.subTest(uri=uri):
                self.assertFalse(self.check(uri)['passed'])
        self.assertFalse(self.check('../outside', base_url='https://example.com/docs/')['passed'])

    def test_invalid_base_is_input_error(self):
        for base in ['/', 'file:///docs/', 'https://example.com/docs', 'https://u:p@example.com/',
                     'https://example.com/a/?x', 'https://[']:
            with self.assertRaises(AuditError):
                self.check('index.html', base_url=base)

    def test_non_html_fragment_and_bad_encoding(self):
        (self.root / 'x.txt').write_text('text')
        self.assertEqual(self.check('x.txt#hello')['results'][0]['code'], 'non-html-fragment')
        (self.root / 'bad.html').write_bytes(b'\xff')
        self.assertFalse(self.check('bad.html#hello')['passed'])

    def test_symlink_escape(self):
        outside = self.base / 'outside.html'
        outside.write_text('<p id="hello"></p>', encoding='utf-8')
        try:
            (self.root / 'link.html').symlink_to(outside)
        except OSError:
            self.skipTest('symlink creation unavailable')
        self.assertFalse(self.check('link.html#hello')['passed'])

    def test_internal_symlink(self):
        try:
            (self.root / 'link.html').symlink_to('index.html')
        except OSError:
            self.skipTest('symlink creation unavailable')
        self.assertTrue(self.check('link.html#hello')['passed'])

    def test_corruption_truncation_trailing_bytes_rejected(self):
        for data in [b'not inventory', HEADER + b'bad', HEADER + zlib.compress(b'x')[:-2],
                     HEADER + zlib.compress(b'hello py:function 1 index.html -\n') + b'trailing',
                     HEADER + zlib.compress(b'\xff')]:
            self.inv.write_bytes(data)
            with self.assertRaises(AuditError):
                read_inventory(self.inv)

    def test_empty_and_malformed_rows_rejected(self):
        for rows in [[], ['not a valid row'], ['x py:function x index.html -'], ['x py:function 1 index.html']]:
            self.inventory(rows)
            with self.assertRaises(AuditError):
                read_inventory(self.inv)

    def test_header_crlf_and_metadata(self):
        self.inventory(['hello py:function 1 index.html -'])
        self.inv.write_bytes(self.inv.read_bytes().replace(HEADER, HEADER.replace(b'\n', b'\r\n')))
        meta, entries = read_inventory(self.inv)
        self.assertEqual(meta, {'project': 'Test', 'version': '1'})
        self.assertEqual(len(entries), 1)

    def test_resource_limits(self):
        self.inventory(['hello py:function 1 index.html -'])
        with patch('inv_target_check.core.MAX_EXPANDED', 8):
            with self.assertRaises(AuditError):
                read_inventory(self.inv)
        with patch('inv_target_check.core.MAX_INPUT', 8):
            with self.assertRaises(AuditError):
                read_inventory(self.inv)
        with patch('inv_target_check.core.MAX_ENTRIES', 0):
            with self.assertRaises(AuditError):
                read_inventory(self.inv)
        with patch('inv_target_check.core.MAX_HTML', 2):
            self.assertFalse(self.check('index.html#hello')['passed'])
        with patch('inv_target_check.core.MAX_LINE', 4):
            with self.assertRaises(AuditError):
                read_inventory(self.inv)

    def test_multiple_rows_complete_deterministic_report(self):
        self.inventory(['hello py:function 1 index.html#$ -', 'lost std:label -1 index.html#gone Lost',
                        'remote std:doc -1 https://else.example/ Remote'])
        a = audit(self.inv, self.root)
        self.assertEqual(a, audit(self.inv, self.root))
        self.assertEqual(a['summary'], {'ok': 1, 'failed': 1, 'unverified': 1})

    def test_cli_exit_and_json(self):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        self.inventory(['hello py:function 1 index.html#$ -'])
        command = [sys.executable, '-m', 'inv_target_check', str(self.inv), str(self.root), '--json']
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])
        self.inventory(['lost py:function 1 missing.html -'])
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1)
        self.inv.write_bytes(b'bad')
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()

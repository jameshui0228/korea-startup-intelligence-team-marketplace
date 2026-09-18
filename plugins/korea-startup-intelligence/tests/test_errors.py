import json
import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ksi_lib.errors import explain


class ErrorGuidanceTest(unittest.TestCase):
    def test_json_location_not_input(self):
        value = explain(json.JSONDecodeError('bad', 'private-value', 2))
        self.assertEqual(value['code'], 'invalid_json')
        self.assertNotIn('private-value', json.dumps(value))

    def test_system_errors_do_not_echo_sensitive_paths(self):
        for exc in (OSError('/private/token'), sqlite3.OperationalError('/private/db')):
            self.assertNotIn('/private', json.dumps(explain(exc)))

    def test_conflict_and_evidence_recovery(self):
        self.assertEqual(explain(ValueError('편집 충돌 revision=2'))['code'], 'edit_conflict')
        self.assertEqual(explain(ValueError('Missing evidence'))['code'], 'evidence_required')


if __name__ == '__main__':
    unittest.main()

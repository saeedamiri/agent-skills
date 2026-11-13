"""Behavior checks for semantic, byte-preserving profile migration."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tomllib

import install


class ProfileMigrationTests(unittest.TestCase):
    def profile(self, original):
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(directory.cleanup)
        profile = Path(directory.name) / 'profile.toml'
        profile.write_bytes(original)
        return profile

    def refresh(self, profile):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            install.refresh_router_profile(profile)
        return output.getvalue()

    def test_customized_syntax_migrates_without_changing_other_values(self):
        cases = (
            b"['features'] # retained comment",
            b'["\\u0066eatures"]\r\nhooks = true',
            b'"features" . "hooks" = true\n[other]\nvalue = 7\n',
            b'"features" = {} # keep\n',
            b'features = { nested = { number = 7 }, items = [1, 2] }\n',
            b'[features.nested]\nvalue = 7\n',
            b'[[features.entries]]\nname = "first"\n',
            b'notes = """\n[features]\nfeatures = {}\n"""\n',
            b"notes = '''\n[features]\nfeatures = {}\n'''\n",
            b'notes = """escaped \\" quote and \\\\ slash"""\n',
            b'notes = """four quotes""""\n[features]',
            b"notes = '''five quotes'''''\n[features]\n",
            b'values = [\n[1, 2],\n"[features]",\n]\n[features]\n',
            b'number = nan\n[features]\nhooks = true\n',
            b'# [features]\n# features = {}\n',
        )
        for original in cases:
            with self.subTest(original=original):
                before = tomllib.loads(original.decode(), parse_float=str)
                profile = self.profile(original)
                self.assertIn('updated', self.refresh(profile))
                upgraded = profile.read_bytes()
                after = tomllib.loads(upgraded.decode(), parse_float=str)
                self.assertIs(after['features'].pop('subagent_default_context_limits'), True)
                if 'features' not in before:
                    del after['features']
                self.assertEqual(after, before)
                # Every original byte remains in order around one insertion.
                prefix = 0
                while prefix < len(original) and original[prefix] == upgraded[prefix]:
                    prefix += 1
                inserted = len(upgraded) - len(original)
                self.assertGreater(inserted, 0)
                self.assertEqual(upgraded[prefix + inserted:], original[prefix:])
                backups = [path for path in profile.parent.iterdir() if path != profile]
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)
                self.assertIn('ok', self.refresh(profile))
                self.assertEqual(profile.read_bytes(), upgraded)
                self.assertEqual(len(list(profile.parent.iterdir())), 2)

    def test_equivalent_explicit_preferences_are_never_rewritten(self):
        for original in (
                b"['features']\n'subagent_default_context_limits' = false\n",
                b'"features" . "subagent_default_context_limits" = false\n',
                b'"\\u0066eatures" = { "subagent_default_context_\\u006cimits" = false }\n',
                b'[features]\nsubagent_default_context_limits = "custom"\n',
                b'[features.subagent_default_context_limits]\ncustom = true\n'):
            with self.subTest(original=original):
                profile = self.profile(original)
                self.assertIn('explicitly set', self.refresh(profile))
                self.assertEqual(profile.read_bytes(), original)
                self.assertEqual(list(profile.parent.iterdir()), [profile])

    def test_invalid_or_incompatible_input_is_reported_without_writes(self):
        for original, reason in (
                (b'features = false\n', 'not a table'),
                (b'[[features]]\nhooks = true\n', 'not a table'),
                (b'[features\n', 'invalid TOML'),
                (b'features = {}\n[features]\n', 'invalid TOML'),
                (b'\xff', 'not UTF-8')):
            with self.subTest(original=original):
                profile = self.profile(original)
                self.assertIn(reason, self.refresh(profile))
                self.assertEqual(profile.read_bytes(), original)
                self.assertEqual(list(profile.parent.iterdir()), [profile])

    def test_missing_standard_parser_leaves_existing_profile_untouched(self):
        original = b'[features]\nhooks = true\n'
        profile = self.profile(original)
        with patch.object(install, 'tomllib', None):
            self.assertIn('requires Python 3.11+', self.refresh(profile))
        self.assertEqual(profile.read_bytes(), original)
        self.assertEqual(list(profile.parent.iterdir()), [profile])


if __name__ == '__main__':
    unittest.main()

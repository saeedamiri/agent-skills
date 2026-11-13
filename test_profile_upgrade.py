"""Regression checks for preserving customized profiles during an upgrade."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import tomllib

import install


class ProfileUpgradeTests(unittest.TestCase):
    def upgrade(self, original):
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(directory.cleanup)
        profile = Path(directory.name) / 'profile.toml'
        profile.write_bytes(original)
        with contextlib.redirect_stdout(io.StringIO()):
            install.refresh_router_profile(profile)
        return profile

    def test_valid_table_spellings_remain_loadable(self):
        for original in (b'[features]', b'["features"]\nhooks = true\n',
                         b'features = { hooks = true }\n',
                         b'features.hooks = true\n'):
            with self.subTest(original=original):
                before = tomllib.loads(original.decode())
                profile = self.upgrade(original)
                after = tomllib.loads(profile.read_text(encoding='utf-8'))
                self.assertIs(after['features']['subagent_default_context_limits'], True)
                del after['features']['subagent_default_context_limits']
                self.assertEqual(after, before)

    def test_explicit_false_with_quoted_or_dotted_keys_is_unchanged(self):
        for original in (
                b'[features]\n"subagent_default_context_limits" = false\n',
                b'features.subagent_default_context_limits = false\n',
                b'features = { subagent_default_context_limits = false }\n'):
            with self.subTest(original=original):
                self.assertIs(tomllib.loads(original.decode())['features']['subagent_default_context_limits'], False)
                profile = self.upgrade(original)
                self.assertEqual(profile.read_bytes(), original)
                self.assertEqual(list(profile.parent.iterdir()), [profile])

    def test_table_text_in_multiline_value_is_preserved(self):
        original = b'notes = """\n[features]\nhooks = true\n"""\n'
        before = tomllib.loads(original.decode())
        profile = self.upgrade(original)
        after = tomllib.loads(profile.read_text(encoding='utf-8'))
        self.assertEqual(after['notes'], before['notes'])
        self.assertIs(after['features']['subagent_default_context_limits'], True)

    def test_invalid_profile_is_left_untouched(self):
        for original in (b'[features\nhooks = true\n', b'notes = "unterminated\n'):
            with self.subTest(original=original):
                with self.assertRaises(tomllib.TOMLDecodeError):
                    tomllib.loads(original.decode())
                profile = self.upgrade(original)
                self.assertEqual(profile.read_bytes(), original)

    def test_backup_collision_and_repeat_upgrade_preserve_bytes(self):
        original = (b'model_auto_compact_token_limit = 202000\r\n'
                    b'[features]\r\nhooks = true\r\n'
                    b'[hooks.state]\r\ntrusted_hash = "saved"\r\n')
        profile = self.upgrade(original)
        first = profile.read_bytes()
        backups = [item for item in profile.parent.iterdir() if item != profile]
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        profile.write_bytes(original)
        with contextlib.redirect_stdout(io.StringIO()):
            install.refresh_router_profile(profile)
            install.refresh_router_profile(profile)
        backups = [item for item in profile.parent.iterdir() if item != profile]
        self.assertEqual(len(backups), 2)
        self.assertTrue(all(item.read_bytes() == original for item in backups))
        self.assertEqual(profile.read_bytes(), first)
        self.assertEqual(first.replace(b'subagent_default_context_limits = true\r\n', b''), original)


if __name__ == '__main__':
    unittest.main()

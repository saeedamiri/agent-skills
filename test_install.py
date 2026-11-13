"""Focused installer upgrade and repeat-install checks; no user files are changed."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install


class InstallerTests(unittest.TestCase):
    def test_upgrade_adds_compaction_hook_without_changing_trusted_tool_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'hooks.json'
            old = {'hooks': {
                event: [{'matcher': '*', 'hooks': [{'type': 'command', 'command': f'python "{install.HOOK}"', 'timeout': 10}]}]
                for event in ('PreToolUse', 'PostToolUse')
            }}
            old['hooks']['Stop'] = [{'hooks': [{'type': 'command', 'command': 'echo finished'}]}]
            original = json.dumps(old)
            target.write_text(original, encoding='utf-8')
            template = install.ROOT / 'adapters' / 'codex' / 'hooks.json'
            with contextlib.redirect_stdout(io.StringIO()):
                install.merge_hooks(target, template)
                first = target.read_bytes()
                install.merge_hooks(target, template)
            result = json.loads(first)
            self.assertEqual(first, target.read_bytes())
            for event in ('PreToolUse', 'PostToolUse', 'Stop'):
                self.assertEqual(old['hooks'][event], result['hooks'][event])
            self.assertEqual(len(result['hooks']['SessionStart']), 1)
            self.assertEqual(target.with_name('hooks.json.bak-agent-skills').read_text(encoding='utf-8'), original)

    def test_adapter_installs_profile_and_senior_roles_then_preserves_customization(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            base = home / 'custom-home'
            with patch.object(install, 'HOME', home), patch.dict(install.os.environ, {'CODEX_HOME': str(base)}), \
                    patch.object(install, 'link_dir'), patch.object(install, 'router_path') as path_setup, \
                    contextlib.redirect_stdout(io.StringIO()):
                install.codex()
                profile = base / 'gpt.config.toml'
                content = profile.read_text(encoding='utf-8')
                self.assertIn('approvals_reviewer = "auto_review"', content)
                self.assertIn('model_auto_compact_token_limit = 202000', content)
                self.assertIn('subagent_default_context_limits = true', content)
                self.assertIn((install.ROOT / 'cycle-router' / 'SKILL.md').as_posix(), content)
                self.assertNotIn('{ROUTER_SKILL}', content)
                for tier in ('astra', 'sol'):
                    self.assertTrue((base / 'agents' / f'advanced-research-{tier}.toml').is_file())
                customized = content + '\n# Local customization and saved hook trust\n'
                profile.write_text(customized, encoding='utf-8')
                hooks = (base / 'hooks.json').read_bytes()
                install.codex()
                self.assertEqual(profile.read_text(encoding='utf-8'), customized)
                self.assertEqual((base / 'hooks.json').read_bytes(), hooks)
                self.assertEqual(path_setup.call_count, 2)

    def test_upgrade_enables_child_context_defaults_without_changing_profile_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            base = home / 'custom-home'
            base.mkdir()
            profile = base / 'gpt.config.toml'
            old = (b'model_auto_compact_token_limit = 202000\r\n'
                   b'[features]\r\nhooks = true\r\nmulti_agent = true\r\n'
                   b'[hooks.state]\r\ntrusted_hash = "saved"\r\n')
            profile.write_bytes(old)
            with patch.object(install, 'HOME', home), patch.dict(install.os.environ, {'CODEX_HOME': str(base)}), \
                    patch.object(install, 'link_dir'), patch.object(install, 'router_path'), \
                    contextlib.redirect_stdout(io.StringIO()):
                install.codex()
                upgraded = profile.read_bytes()
                install.codex()
            self.assertEqual(profile.read_bytes(), upgraded)
            self.assertEqual(upgraded, old.replace(b'[features]\r\n',
                                                    b'[features]\r\nsubagent_default_context_limits = true\r\n'))
            self.assertEqual(profile.with_name('gpt.config.toml.bak-agent-skills').read_bytes(), old)

    def test_explicit_child_context_preference_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'gpt.config.toml'
            original = '[features]\nsubagent_default_context_limits = false\n'
            profile.write_text(original, encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                install.refresh_router_profile(profile)
            self.assertEqual(profile.read_text(encoding='utf-8'), original)
            self.assertFalse(profile.with_name('gpt.config.toml.bak-agent-skills').exists())

    def test_upgrade_adds_feature_section_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'gpt.config.toml'
            original = 'model_auto_compact_token_limit = 202000\n'
            profile.write_text(original, encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                install.refresh_router_profile(profile)
            self.assertEqual(profile.read_text(encoding='utf-8'),
                             original + '[features]\nsubagent_default_context_limits = true\n')
            self.assertEqual(profile.with_name('gpt.config.toml.bak-agent-skills').read_text(encoding='utf-8'),
                             original)


if __name__ == '__main__':
    unittest.main()

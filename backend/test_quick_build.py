from contextlib import nullcontext, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from pipeline import Pipeline, load, operation_lock, save, tree
from sidecar import dispatch, operate, project, recent_file, terminal


class QuickBuildTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'mod'
        self.server = self.root / 'server'
        self.client = self.root / 'client'
        self.tools = self.root / 'tools'
        self.store = self.root / 'store'
        for folder in (self.source, self.server, self.client):
            folder.mkdir()
        for addon in ('One', 'Two'):
            folder = self.source / 'addons' / addon
            folder.mkdir(parents=True)
            (folder / 'config.cpp').write_text('class CfgPatches {};', encoding='ascii')
        (self.source / 'addons/Two/$PBOPREFIX$').write_text(r'Example\Two', encoding='ascii')
        for name in ('AddonBuilder/AddonBuilder', 'DsUtils/DSSignFile', 'DsUtils/DSCheckSignatures'):
            exe = self.tools / f'Bin/{name}.exe'
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b'fake tool')
        self.private = self.root / 'Example.biprivatekey'
        self.public = self.root / 'Example.bikey'
        self.private.write_bytes(b'private')
        self.public.write_bytes(b'public')
        for name, value in (
            ('pipeline.STORE', self.store), ('sidecar.STORE', self.store),
            ('pipeline.KIT', self.root / 'no-legacy-kit.json'), ('pipeline.steam_installs', Mock(return_value=[])),
            ('test_workflow.steam_installs', Mock(return_value=[])),
            ('sidecar.operation_lock', Mock(side_effect=nullcontext)),
        ):
            patched = patch(name, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.settings = {**project(self.source)['settings'], 'server': str(self.server), 'client': str(self.client),
                         'tools': str(self.tools), 'private': str(self.private), 'public': str(self.public),
                         'addon_options': json.dumps({'addons/One': {'name': 'CustomOne', 'prefix': r'Example\One'}})}
        self.args = []

    def fake_tool(self, args, cwd):
        self.args.append(args)
        exe = args[0].stem
        if exe == 'AddonBuilder':
            (args[2] / (args[1].name + '.pbo')).write_bytes(args[1].name.encode())
        elif exe == 'DSSignFile':
            args[2].with_name(args[2].name + '.Example.bisign').write_bytes(b'signature')
        elif exe != 'DSCheckSignatures':
            self.fail(exe)
        return ''

    def run_quick(self, tool=None):
        event = Mock()
        with patch.object(Pipeline, 'run', side_effect=tool or self.fake_tool), \
                patch('sidecar.TestPipeline.test', side_effect=AssertionError('launched a test')), \
                patch('sidecar.publish', side_effect=AssertionError('published to Workshop')):
            report = operate(self.source, {'action': 'quick', 'settings': self.settings}, event, report_only=True)
        return report, [call.kwargs['stage'] for call in event.call_args_list if call.args == ('progress',)]

    def test_setup_persists_independent_projects_and_remembers_the_last(self):
        settings = project(self.source)['settings']
        self.assertEqual(settings['addons'], 'addons/One\naddons/Two')
        self.assertTrue(all(settings[key] for key in ('copy_server', 'copy_client', 'sign')))
        self.assertFalse(settings['open_dayz'])
        self.assertFalse(settings['publish_workshop'])
        dispatch({'command': 'saveQuick', 'root': str(self.source), 'settings': self.settings}, Mock())
        second = self.root / 'other'
        second.mkdir()
        save(self.store / 'environment.json', {'server': 'shared-server', 'sign': False})
        dispatch({'command': 'open', 'root': str(second)}, Mock())
        dispatch({'command': 'saveQuickToggles', 'root': str(self.source), 'copy_client': False}, Mock())
        saved = dispatch({'command': 'open', 'root': str(self.source)}, Mock())
        self.assertEqual(saved['settings'], {**self.settings, 'copy_client': False})
        self.assertEqual(load(recent_file()), {'project': str(self.source)})
        self.assertNotEqual(project(second)['settings']['server'], self.settings['server'])
        self.assertTrue(project(second)['settings']['sign'])

    def test_quick_packs_all_then_signs_and_installs_both_destinations(self):
        self.settings.update(publish_workshop=True, open_dayz=True)
        report, stages = self.run_quick()
        self.assertEqual(report['status'], 'complete', report.get('error'))
        self.assertEqual(stages, [0, 1, 2, 3, 4])
        self.assertEqual([args[0].stem for args in self.args],
                         ['AddonBuilder', 'AddonBuilder', 'DSSignFile', 'DSSignFile', 'DSCheckSignatures'])
        self.assertIn(r'-prefix=Example\One', self.args[0])
        self.assertIn(r'-prefix=Example\Two', self.args[1])
        self.assertEqual(set(report['files']), {'Addons/CustomOne.pbo', 'Addons/CustomOne.pbo.Example.bisign',
                                                'Addons/Two.pbo', 'Addons/Two.pbo.Example.bisign', 'Keys/Example.bikey'})
        server_target, client_target = (path / self.settings['mod'] for path in (self.server, self.client))
        self.assertEqual(tree(server_target), tree(client_target))
        self.assertEqual((self.server / 'Keys/Example.bikey').read_bytes(), self.public.read_bytes())
        self.assertFalse((self.client / 'Keys').exists())
        self.assertFalse(report['serverReady'])
        self.assertFalse(report['clientLaunched'])

    def test_build_only_allows_missing_deployment_paths_and_keys(self):
        self.settings.update(copy_server=False, copy_client=False, sign=False, server='', client='', private='', public='')
        report, stages = self.run_quick()
        self.assertEqual(report['status'], 'complete', report.get('error'))
        self.assertEqual(stages, [0, 1])
        self.assertEqual(report['updated'], [])
        self.assertEqual(report['files'], ['Addons/CustomOne.pbo', 'Addons/Two.pbo'])

    def test_cli_quick_uses_the_saved_project(self):
        dispatch({'command': 'saveQuick', 'root': str(self.source), 'settings': self.settings}, Mock())
        output = io.StringIO()
        with patch.object(Pipeline, 'run', side_effect=self.fake_tool), redirect_stdout(output):
            self.assertEqual(terminal(['--project', str(self.source), '--json', 'quick']), 0, output.getvalue())
        report = json.loads(output.getvalue().splitlines()[-1])['value']
        self.assertEqual(report['action'], 'quick')
        self.assertTrue(report['installed'])

    def test_failed_build_preserves_previously_installed_pbos(self):
        old = self.old_targets()

        def fail_build(args, cwd):
            if args[0].stem == 'AddonBuilder' and args[1].name == 'Two':
                raise RuntimeError('AddonBuilder process failed.')
            return self.fake_tool(args, cwd)

        report, stages = self.run_quick(fail_build)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('Two.pbo', report['error'])
        self.assertEqual(stages, [0, 1])
        self.assertEqual([tree(path) for path in old], [old[path] for path in old])

    def test_failed_signing_preserves_previously_installed_pbos(self):
        old = self.old_targets()

        def fail_signing(args, cwd):
            if args[0].stem == 'DSSignFile' and args[2].name == 'Two.pbo':
                raise RuntimeError('Signer process failed.')
            return self.fake_tool(args, cwd)

        report, stages = self.run_quick(fail_signing)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('Two.pbo', report['error'])
        self.assertEqual(stages, [0, 1, 2])
        self.assertEqual([tree(path) for path in old], [old[path] for path in old])
        self.assertFalse((self.server / 'Keys/Example.bikey').exists())

    def test_commit_failure_on_second_destination_restores_both_and_key(self):
        old = self.old_targets()
        client = self.client / self.settings['mod']
        rename = Path.rename

        def fail_install(path, target):
            if target == client and path.name.startswith('.dayz-stage-'):
                raise PermissionError(13, 'locked', str(target), 32)
            return rename(path, target)

        with patch.object(Path, 'rename', fail_install):
            report, stages = self.run_quick()
        self.assertEqual(report['status'], 'failed')
        self.assertIn(str(client), report['error'])
        self.assertEqual(stages, [0, 1, 2, 3, 4])
        self.assertEqual([tree(path) for path in old], [old[path] for path in old])
        self.assertFalse((self.server / 'Keys/Example.bikey').exists())
        self.assertFalse(list(self.server.glob('.dayz-*')))
        self.assertFalse(list(self.client.glob('.dayz-*')))

    def test_verification_failure_rolls_back_committed_changes(self):
        old = self.old_targets()
        client = self.client / self.settings['mod']

        def failed_check(path):
            return {} if path == client else tree(path)

        with patch('quick_build.tree', side_effect=failed_check):
            report, _ = self.run_quick()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual([tree(path) for path in old], [old[path] for path in old])
        self.assertFalse((self.server / 'Keys/Example.bikey').exists())

    def test_rollback_of_quick_install_uses_no_game_process(self):
        old = self.old_targets()
        report, _ = self.run_quick()
        self.assertEqual(report['status'], 'complete', report.get('error'))
        self.settings.update(copy_server=False, copy_client=False, tools='')
        with patch.object(Pipeline, 'stop', side_effect=AssertionError('stopped a game process')):
            report = operate(self.source, {'action': 'rollback', 'settings': self.settings}, Mock(), report_only=True)
        self.assertEqual(report['status'], 'complete', report.get('error'))
        self.assertEqual([tree(path) for path in old], [old[path] for path in old])
        self.assertFalse((self.server / 'Keys/Example.bikey').exists())

    def test_another_instance_cannot_start_a_concurrent_operation(self):
        with operation_lock(), self.assertRaises(RuntimeError), operation_lock():
            self.fail('Acquired an existing operation lock')

    def old_targets(self):
        old = {}
        for base in (self.server, self.client):
            target = base / self.settings['mod']
            addons = target / 'Addons'
            addons.mkdir(parents=True)
            (addons / 'Old.pbo').write_bytes(base.name.encode())
            old[target] = tree(target)
        return old


if __name__ == '__main__':
    unittest.main()

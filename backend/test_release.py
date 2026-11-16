import subprocess
import io
import json
import tempfile
import unittest
import shlex
import shutil
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from pipeline import digest, load, save
from console import command
from remote import ACTIVATE, LinuxDayZ, select_build
from sidecar import dispatch, operate, publish, terminal, workshop_item
from test_workflow import TestPipeline


BUILD = '20261115-112233-aaaabbbb'
LOCAL = '20261115-112244-ccccdddd'


class Releases(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.settings = {'workshop': 'https://steamcommunity.com/sharedfiles/filedetails/?id=789',
                         'steam_owner': '76561198000000000'}

    def test_portable_project_selection_is_local_to_each_install(self):
        install = self.root / 'DMC'
        second_install = self.root / 'DMC copy'
        external = self.root / 'My other mod'
        old_profile = self.root / 'profile'
        for folder in (install, second_install, external):
            folder.mkdir()
        save(old_profile / 'recent.json', {'project': str(external)})

        def request(command, **fields):
            return dispatch(dict(command=command, **fields), Mock())

        with patch('sidecar.STORE', old_profile), patch('sidecar.install_directory', return_value=install) as location:
            initial = request('hello')
            workspace = install / 'projekt'
            self.assertEqual(Path(initial['workspace']), workspace.resolve())
            self.assertTrue(workspace.is_dir())
            self.assertIsNone(initial['recent'])

            opened = request('open', root=str(workspace))
            self.assertEqual(Path(opened['root']), workspace.resolve())
            self.assertFalse(next(check for check in opened['details']['checks'] if check['key'] == 'sources')['ok'])

            (external / 'config.cpp').write_text('class CfgPatches {};', encoding='utf-8')
            selected = request('open', root=str(external))
            self.assertEqual(Path(selected['root']), external.resolve())
            self.assertEqual(request('hello')['recent'], selected['root'])

            location.return_value = second_install
            self.assertIsNone(request('hello')['recent'])
            self.assertTrue((second_install / 'projekt').is_dir())
            location.return_value = install
            external.rename(self.root / 'Moved mod')
            self.assertIsNone(request('hello')['recent'])

    def test_workshop_item_links(self):
        self.assertEqual(workshop_item(self.settings['workshop']), 789)
        with self.assertRaises(ValueError):
            workshop_item('https://example.com/sharedfiles/filedetails/?id=789')

    def test_remote_selects_confirmed_workshop_build_or_verified_local_build(self):
        for build in (BUILD, LOCAL):
            save(self.root / 'builds' / build / 'manifest.json', {'id': build})
        save(self.root / 'local-ready.json', {'buildId': LOCAL})
        save(self.root / 'workshop-confirmed.json', {'buildId': BUILD, 'item': '789', 'status': 'confirmed'})
        self.assertEqual(select_build(self.root, {}, load)['id'], LOCAL)
        self.assertEqual(select_build(self.root, {'publish_workshop': True}, load, 789)['id'], BUILD)
        with self.assertRaises(ValueError):
            select_build(self.root, {'publish_workshop': True}, load, 999)

    def test_manual_publication_refuses_changed_sources(self):
        pipeline = TestPipeline.__new__(TestPipeline)
        pipeline.state = self.root
        pipeline.s = self.settings
        package = self.root / 'builds' / BUILD / '@Test'
        package.mkdir(parents=True)
        manifest = {'id': BUILD, 'inputs': {'sources': 'original'}}
        save(package.parent / 'manifest.json', manifest)
        with patch.object(pipeline, 'verify', return_value=package), \
             patch.object(pipeline, 'build_inputs', return_value={'sources': 'edited'}), \
             patch.object(pipeline, 'publish') as upload:
            with self.assertRaises(ValueError):
                publish(pipeline, manifest)
            upload.assert_not_called()

    def test_failed_publication_retries_same_package(self):
        pipeline = Mock(state=self.root, s=self.settings, report={})
        manifest = {'id': BUILD}
        pipeline.publish.side_effect = [RuntimeError('Steam rejected the request'), None]
        with self.assertRaises(RuntimeError):
            publish(pipeline, manifest)
        self.assertEqual(load(self.root / 'workshop-attempt.json')['status'], 'failed')
        self.assertFalse((self.root / 'workshop-confirmed.json').exists())
        publish(pipeline, manifest, retry=True)
        self.assertEqual(load(self.root / 'workshop-confirmed.json')['buildId'], BUILD)
        self.assertEqual([call.args for call in pipeline.publish.call_args_list], [(manifest, 789)] * 2)

    def test_steam_timeout_records_uncertain_and_preserves_confirmed_build(self):
        pipeline = Mock(state=self.root, s=self.settings, report={})
        pipeline.publish.side_effect = TimeoutError()
        save(self.root / 'workshop-confirmed.json', {'buildId': LOCAL})
        with self.assertRaises(TimeoutError):
            publish(pipeline, {'id': BUILD})
        self.assertEqual(load(self.root / 'workshop-attempt.json')['status'], 'uncertain')
        self.assertEqual(load(self.root / 'workshop-confirmed.json')['buildId'], LOCAL)
        with self.assertRaises(ValueError):
            publish(pipeline, {'id': BUILD}, retry=True)
        pipeline.publish.assert_called_once()

    def test_f5_publishes_the_exact_locally_ready_manifest(self):
        manifest = {'id': BUILD}
        pipeline = Mock(state=self.root)
        pipeline.test.return_value = manifest
        settings = {**self.settings, 'publish_workshop': True}

        def construct(root, settings, log, progress, report):
            report['serverReady'] = True
            return pipeline

        with patch('sidecar.state', return_value=self.root), patch('sidecar.operation_lock', nullcontext), \
             patch('sidecar.validate_project'), patch('sidecar.save_settings'), \
             patch('sidecar.TestPipeline', side_effect=construct), patch('sidecar.publish') as upload:
            report = operate(self.root, {'action': 'test', 'settings': settings}, Mock(), report_only=True)
            self.assertEqual(report['status'], 'complete')
            upload.assert_called_once_with(pipeline, manifest)
            pipeline.test.side_effect = RuntimeError('Server did not start')
            upload.reset_mock()
            report = operate(self.root, {'action': 'test', 'settings': settings}, Mock(), report_only=True)
            self.assertEqual(report['status'], 'failed')
            upload.assert_not_called()

    def test_terminal_update_reads_saved_settings_without_resaving_them(self):
        work = self.root
        pipeline = Mock(state=work)
        pipeline.test.return_value = {'id': BUILD}
        settings = {**self.settings, 'publish_workshop': True, 'remote_host': 'stage.example'}

        def construct(root, values, log, progress, report):
            self.assertEqual(values, settings)
            report.update(serverReady=True, buildId=BUILD)
            return pipeline

        def upload(pipeline, manifest):
            self.assertEqual(manifest['id'], BUILD)

        with patch('sidecar.state', return_value=work), patch('sidecar.operation_lock', nullcontext), \
             patch('sidecar.project', return_value={'configured': True, 'settings': settings}), \
             patch('sidecar.validate_project'), patch('sidecar.save_settings') as write, \
             patch('sidecar.TestPipeline', side_effect=construct), patch('sidecar.publish', side_effect=upload), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(terminal(['--project', str(work), '--json', 'update']), 0)
        write.assert_not_called()
        report = json.loads(output.getvalue().splitlines()[-1])['value']
        self.assertEqual(report['action'], 'test')
        self.assertEqual(report['buildId'], BUILD)
        self.assertEqual(load(next((work / 'operations').glob('*.json'))), report)

    def test_gui_and_terminal_share_project_settings_in_both_directions(self):
        source = self.root / "My mod's source"
        source.mkdir()
        (source / 'config.cpp').write_text('class CfgPatches { class Test {}; };', encoding='utf-8')
        with patch('sidecar.STORE', self.root / 'profile'), patch('sidecar.operation_lock', nullcontext), \
             patch('sidecar.details', return_value={}), patch('sidecar.defaults', return_value={
                 'addons': '.', 'mod': '@Test', 'publish_workshop': False, 'open_dayz': False}):
            shared = {'addons': '.', 'mod': '@Test', 'publish_workshop': True, 'open_dayz': False,
                      'environment_override': True}
            dispatch(dict(command='save', root=str(source), settings=shared), Mock())
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(terminal(['--project', str(source), '--json', 'config', '--get', 'publish_workshop']), 0)
            self.assertTrue(json.loads(output.getvalue())['value']['publish_workshop'])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(terminal(['--project', str(source), 'config', '--set', 'open_dayz', 'true']), 0)
            snapshot = dispatch(dict(command='snapshot', root=str(source)), Mock())
            self.assertTrue(snapshot['settings']['open_dayz'])
            self.assertTrue(snapshot['settings']['publish_workshop'])

    def test_powershell_command_quotes_project_and_pins_remote_build(self):
        root = self.root / "My mod's source"
        text = command(root, 'remote', BUILD)
        self.assertTrue(text.startswith("& '"))
        self.assertIn("My mod''s source' remote --build-id '", text)
        self.assertTrue(text.endswith(f"'{BUILD}'"))


class RemoteDeployment(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.package = Path(work.name) / '@Test'
        self.package.mkdir()
        file = self.package / 'test.pbo'
        file.write_bytes(b'test')
        self.manifest = {'files': {file.name: digest(file)}}
        self.transport = Mock()
        self.stage = '/srv/dayz/.dmc-stage.ABC12345'
        self.remote = LinuxDayZ(dict(mod='@Test', remote_root='/srv/dayz', remote_keys='/srv/dayz/keys',
                                     remote_service='dayz.service', remote_readiness='test -e /srv/dayz/ready'),
                                self.transport)

    @staticmethod
    def result(code=0, output=''):
        return subprocess.CompletedProcess([], code, stdout=output.encode(), stderr=b'')

    def test_failed_transfer_does_not_call_activation(self):
        self.transport.shell.side_effect = [self.result(), self.result(output=self.stage)]
        self.transport.sftp.side_effect = [self.result(), self.result(1)]
        with self.assertRaisesRegex(RuntimeError, 'live mod was untouched'):
            self.remote.install(self.package, self.manifest, Mock())
        self.assertEqual(self.transport.shell.call_count, 2)

    def test_successful_stage_reports_ready_and_sends_hashes(self):
        self.transport.sftp.return_value = self.result()
        self.transport.shell.side_effect = [self.result(), self.result(output=self.stage), self.result(),
                                            self.result(output='DMC_READY\n')]
        result = self.remote.install(self.package, self.manifest, Mock())
        self.assertEqual(result, {'status': 'ready', 'staging': self.stage})
        self.assertIn(self.manifest['files']['test.pbo'], self.transport.shell.call_args_list[2].args[0])
        self.assertEqual(self.transport.shell.call_args.args[0], ACTIVATE)

    def test_rollback_outcomes_are_distinct(self):
        self.transport.sftp.return_value = self.result()
        for marker, expected in [('DMC_ROLLBACK_OK', 'rolled_back'), ('DMC_ROLLBACK_FAILED', 'rollback_failed')]:
            with self.subTest(marker=marker):
                self.transport.shell.side_effect = [self.result(), self.result(output=self.stage), self.result(),
                                                    self.result(2, marker)]
                self.assertEqual(self.remote.install(self.package, self.manifest, Mock())['status'], expected)

    def test_sftp_only_never_runs_ssh(self):
        self.transport.sftp.return_value = self.result()
        remote = LinuxDayZ(dict(mod='@Test', remote_root='/srv/dayz', remote_files_only=True), self.transport)
        self.assertEqual(remote.install(self.package, self.manifest, Mock())['status'], 'uploaded')
        self.transport.shell.assert_not_called()

    def test_activation_script_restores_previous_files_and_preserves_unrelated_keys(self):
        shell = shutil.which('sh')
        git_shell = Path('C:/Program Files/Git/bin/sh.exe')
        if shell is None and git_shell.is_file():
            shell = str(git_shell)
        if shell is None:
            self.skipTest('A POSIX shell is required for the transaction test.')
        root = self.package.parent
        live = self.package
        stage = root / 'stage'
        staged = stage / live.name
        staged_keys = staged / 'Keys'
        staged_keys.mkdir(parents=True)
        (staged / 'test.pbo').write_bytes(b'new')
        (staged_keys / 'fresh.bikey').write_bytes(b'fresh')
        keys = root / 'keys'
        keys.mkdir()
        (keys / 'another.bikey').write_bytes(b'unchanged')
        (root / 'mission').mkdir()
        (root / 'mission' / 'storage').write_bytes(b'players')
        (stage / 'checksums').write_bytes(''.join(
            f'{digest(file)}  {file.relative_to(staged).as_posix()}\n'
            for file in [staged / 'test.pbo', staged_keys / 'fresh.bikey']).encode())
        health = f'test "$(cat {shlex.quote((live / "test.pbo").as_posix())})" = test'
        commands = """
flock() { return 0; }
sleep() { return 0; }
sudo() { shift; systemctl "$@"; }
systemctl() {
    case "$1" in
        is-active) return 0 ;;
        stop|start) return 0 ;;
        show) printf 'inactive\\n' ;;
    esac
}
"""
        result = subprocess.run(
            [shell, '-c', commands + ACTIVATE, 'test', root.as_posix(), keys.as_posix(), 'dayz.service',
             stage.as_posix(), live.name, health], capture_output=True, timeout=30)
        self.assertIn(b'DMC_ROLLBACK_OK', result.stdout, result.stderr.decode(errors='replace'))
        self.assertEqual((live / 'test.pbo').read_bytes(), b'test')
        self.assertFalse((keys / 'fresh.bikey').exists())
        self.assertEqual((keys / 'another.bikey').read_bytes(), b'unchanged')
        self.assertEqual((root / 'mission' / 'storage').read_bytes(), b'players')


if __name__ == '__main__':
    unittest.main()

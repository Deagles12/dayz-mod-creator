"""Shared machine settings and verified local test workflow."""
import re
import subprocess
import time
from pathlib import Path

from locale_studio import tr
from pipeline import Pipeline, digest, linked, lines, load, require, save, steam_installs, tree

MACHINE = ('tools','server','client','server_exe','client_exe','config','profiles','client_profiles',
           'port','address','timeout','base','server_only','server_args','client_args','sign','private','public',
           'client_mods_root','connection_timeout')


def workshop_locations():
    for common in steam_installs():
        yield common.parent / 'workshop/content/221100'


class TestPipeline(Pipeline):
    def __init__(self, root, settings, log, progress, report):
        super().__init__(root, settings, log, progress)
        self.report = report
        for target in self.targets:
            self.validate_target(target)
        if settings['shared']:
            requested = (self.path('client_mods_root', self.client)
                         if settings.get('client_mods_root', '').strip() else self.state / 'test-client')
            resolved = requested.resolve()
            if (any(part.lower() in {'workshop', '!workshop'} for part in requested.parts + resolved.parts)
                    or any(resolved.is_relative_to(path.resolve()) for path in workshop_locations())):
                raise ValueError(tr('Вибери окрему локальну папку тестових модів. Steam керує вмістом Workshop.',
                                    'Choose a separate local test mods folder. Steam manages Workshop content.'))
            if ';' in str(resolved):
                raise ValueError(tr('У шляху модів не допускається крапка з комою.', 'The mods path cannot contain semicolons.'))
            target = resolved / self.mod
            self.validate_target(target)
            self.targets = list(dict.fromkeys([self.targets[0], target]))

    def validate_target(self, target):
        path = target.resolve()
        if path.is_relative_to(self.root) or self.root.is_relative_to(path):
            raise ValueError(tr('Папка встановлення перетинається з вихідним проєктом.',
                                'The installation path overlaps the source project.'))
        if (any(part.lower() in {'workshop', '!workshop'} for part in path.parts)
                or any(path.is_relative_to(root.resolve()) for root in workshop_locations())):
            raise ValueError(tr('Вибери папку тестових модів поза каталогом Steam Workshop.',
                                'Choose a local test folder outside Steam Workshop.'))

    def dependency_keys(self):
        result = {}
        folders = self.dependencies('base') + self.dependencies('server_only')
        for folder in folders:
            for key in (folder / 'Keys').glob('*.bikey'):
                if linked(key):
                    raise ValueError(tr('Ключ залежності є посиланням: {}', 'Dependency key is a link: {}').format(key))
                existing = result.get(key.name.casefold())
                if existing and digest(existing) != digest(key):
                    raise ValueError(tr('Залежності мають різні ключі з ім’ям {}.', 'Dependencies provide different keys named {}.').format(key.name))
                result[key.name.casefold()] = key
        return list(result.values())

    def dependencies(self, key):
        return list(dict.fromkeys(self.resolve_dependency(entry) for entry in lines(self.s[key])))

    def resolve_dependency(self, entry):
        if re.fullmatch(r'(?:workshop:)?\d+', entry, re.I):
            item = entry.split(':')[-1]
            path = next((root / item for root in workshop_locations() if (root / item).is_dir()), None)
            if path is None:
                raise ValueError(tr('Підпишись на Workshop item {} у Steam і дочекайся завантаження.',
                                    'Subscribe to Workshop item {} in Steam and wait for the download.').format(item))
        else:
            path = next((root / entry for root in (self.server, self.client) if (root / entry).is_dir()),
                        self.server / entry)
        path = path.resolve()
        if ';' in str(path) or not path.is_dir() or not any((path / 'Addons').glob('*.pbo')):
            raise ValueError(tr('Залежність {} не містить PBO. Вибери папку встановленого мода або введи його Workshop ID.',
                                'Dependency {} has no PBO files. Choose an installed mod folder or enter its Workshop ID.').format(path))
        if path in self.targets:
            raise ValueError(tr('Прибери поточний мод зі списку залежностей.', 'Remove this project’s mod from the dependency list.'))
        return path

    def verified_install(self, manifest):
        self.install(manifest, self.dependency_keys())
        self.check_install(manifest)

    def check_install(self, manifest):
        for target in self.targets:
            if tree(target) != manifest['files']:
                raise RuntimeError(tr('Копія мода відрізняється: {}. Скористайся відкатом.',
                                      'The installed copy differs: {}. Use rollback.').format(target))
        keys = [self.server / name for name in manifest['files'] if name.lower().startswith('keys/') and name.lower().endswith('.bikey')]
        for key in keys:
            if digest(require(key)) != manifest['files']['Keys/' + key.name]:
                raise RuntimeError(tr('Серверний ключ відрізняється: {}', 'Server key differs: {}').format(key))
        dependencies = self.dependency_keys()
        for key in dependencies:
            target = self.server / 'keys' / key.name
            if digest(require(target)) != digest(key):
                raise RuntimeError(tr('Ключ залежності змінився: {}. Запусти новий тест.',
                                      'A dependency key changed: {}. Start a new test.').format(key.name))
        self.report['updated'] = list(dict.fromkeys(map(str, [*self.targets, *keys, *(self.server / 'keys' / key.name for key in dependencies)])))
        self.report['files'] = list(manifest['files'])
        self.report['installed'] = True

    def current_package(self, manifest):
        package = self.verify(manifest)
        if (manifest.get('id') != package.parent.name or
                load(require(package.parent / 'manifest.json')) != manifest or
                manifest.get('inputs') != self.build_inputs()):
            raise ValueError(tr('Вихідні файли або параметри змінилися. Створи нову збірку через F5.',
                                'Sources or build settings changed. Create a new build with F5.'))
        return package

    def package_checkpoint(self, manifest):
        return dict(sources=self.source_snapshot(), settings=self.checkpoint_settings(), manifest=manifest,
                    installed=False, targets=list(map(str, self.targets)))

    def test(self, resume=None, deploy_only=False, start_client=None, publish_after=False):
        server, client, server_args, client_args, port, timeout, require_signing = self.game_settings()
        if require_signing and self.s['shared'] and not self.s['sign']:
            raise ValueError(tr('Увімкни підпис і вибери ключі у спільному профілі.',
                                'Enable signing and choose keys in the shared profile.'))
        self.dependency_keys()
        if self.profiles.exists() and not self.profiles.is_dir():
            raise NotADirectoryError(self.profiles)
        if resume and resume.get('settings') != self.checkpoint_settings():
            raise ValueError(tr('Налаштування пакета змінилися. Натисни «Зібрати та протестувати».',
                                'Package settings changed. Click Build and test.'))
        if resume and resume.get('sources') != self.source_snapshot():
            raise ValueError(tr('Вихідні файли змінилися. Натисни «Зібрати та протестувати».',
                                'Source files changed. Click Build and test.'))
        manifest = resume['manifest'] if resume else self.build()
        self.verify(manifest)
        if manifest.get('inputs'):
            self.current_package(manifest)
        self.report.update(built=True, signed=manifest['signed'], files=list(manifest['files']), buildId=manifest.get('id'))
        checkpoint = self.package_checkpoint(manifest)
        checkpoint['publishAfter'] = publish_after
        save(self.state / 'package-checkpoint.json', checkpoint)
        checkpoint['installed'] = bool(resume and resume['installed'])
        if checkpoint['installed']:
            if checkpoint['targets'] != resume['targets']:
                raise ValueError(tr('Папки встановлення змінилися. Запусти нову збірку.',
                                    'Installation folders changed. Start a new build.'))
            self.check_install(manifest)
        save(self.state / 'retry.json', checkpoint)
        reuse_pid = None
        readiness_path = self.state / 'server-readiness.json'
        readiness = load(readiness_path) if readiness_path.is_file() else {}
        if not deploy_only and resume and checkpoint['installed'] and resume.get('serverPid') and resume.get('endpoint') == server_args and readiness.get('ready') and readiness.get('pid') == resume['serverPid']:
            pid = int(resume['serverPid'])
            owns_port = self.ps(f"@(Get-NetUDPEndpoint -LocalPort {port} -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq {pid}).Count")
            if owns_port.isdecimal() and int(owns_port) > 0:
                reuse_pid = pid
        if reuse_pid:
            self.stop(server, client, clients_only=True)
            class RunningServer:
                pid = reuse_pid
                returncode = None

                def poll(inner):
                    return None if self.ps(f'(Get-Process -Id {inner.pid} -ErrorAction SilentlyContinue).Id') else 1
            self.wait_ready(RunningServer(), port, timeout, {})
            self.report['serverReady'] = True
            checkpoint.update(serverPid=reuse_pid, endpoint=server_args)
            save(self.state / 'retry.json', checkpoint)
            process = None
        else:
            self.progress(3, ('Готую локальні папки й зупиняю попередній тест', 'Preparing local folders and stopping the previous test'))
            self.stop(server, client, port)
            if not checkpoint['installed']:
                self.verified_install(manifest)
                checkpoint['installed'] = True
                save(self.state / 'retry.json', checkpoint)
                save(self.state / 'deployment.json', checkpoint)
            if deploy_only:
                return
            self.progress(4, ('Запускаю сервер і чекаю на місію', 'Starting the server and waiting for the mission'))
            self.profiles.mkdir(parents=True, exist_ok=True)
            offsets = {p: p.stat().st_size for p in self.profiles.iterdir() if p.is_file() and self.is_game_log(p)}
            with (self.state / 'server-console.log').open('wb') as console:
                process = subprocess.Popen([str(server), *server_args], cwd=server.parent, stdout=console,
                                           stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_CONSOLE,
                                           startupinfo=self.hidden_startup())
            self.remember_session(process, 'servers')
            self.wait_ready(process, port, timeout, offsets)
            self.report['serverReady'] = True
            save(self.state / 'tested.json', manifest)
            checkpoint.update(serverPid=process.pid, endpoint=server_args)
            save(self.state / 'retry.json', checkpoint)
        save(self.state / 'deployment.json', checkpoint)
        open_dayz = self.s.get('open_dayz', False) if start_client is None else start_client
        if open_dayz:
            self.progress(5, ('Запускаю DayZ', 'Launching DayZ'))
            try:
                client_process = subprocess.Popen([str(client), *client_args], cwd=client.parent)
                time.sleep(2)
                self.remember_session(client_process, 'clients')
                self.report['clientLaunched'] = True
            except OSError as error:
                self.report['clientError'] = str(error)
                self.log(f'Warning: {error}')
        (self.state / 'retry.json').unlink(missing_ok=True)
        return manifest

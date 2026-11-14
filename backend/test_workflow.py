"""Shared machine settings and verified local test workflow."""
import re
import subprocess
import time
from pathlib import Path

from locale_studio import tr
from pipeline import Pipeline, digest, linked, lines, require, save, steam_installs, tree

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
        if settings['shared'] and settings.get('client_mods_root', '').strip():
            requested = self.path('client_mods_root', self.client)
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
        resolved = []
        candidates = [self.server, self.client]
        workshop = list(workshop_locations())
        for entry in lines(self.s[key]):
            if re.fullmatch(r'(?:workshop:)?\d+', entry, re.I):
                item = entry.split(':')[-1]
                path = next((root / item for root in workshop if (root / item).is_dir()), None)
                if path is None:
                    raise ValueError(tr('Підпишись на Workshop item {} у Steam і дочекайся завантаження.',
                                        'Subscribe to Workshop item {} in Steam and wait for the download.').format(item))
            else:
                path = next((root / entry for root in candidates if (root / entry).is_dir()), self.server / entry)
            path = path.resolve()
            if ';' in str(path) or not path.is_dir() or not any((path / 'Addons').glob('*.pbo')):
                raise ValueError(tr('Залежність {} не містить PBO. Вибери папку встановленого мода або введи його Workshop ID.',
                                    'Dependency {} has no PBO files. Choose an installed mod folder or enter its Workshop ID.').format(path))
            if path in self.targets:
                raise ValueError(tr('Прибери поточний мод зі списку залежностей.', 'Remove this project’s mod from the dependency list.'))
            if path not in resolved:
                resolved.append(path)
        return resolved

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

    def checkpoint_settings(self):
        keys = ('addons','mod','addon_name','prefix','metadata','extra','pack','prep_exe','prep_args','sign','private','public')
        return {key: self.s.get(key) for key in keys}

    def source_snapshot(self):
        result = {}
        for folder in lines(self.s['addons']):
            path = (self.root / folder).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError(tr('Джерело має бути в папці проєкту.', 'Source must be in the project folder.'))
            result[folder] = tree(path)
        for file in [self.s.get('metadata', ''), *lines(self.s.get('extra', ''))]:
            if file.strip():
                result['file:' + file] = digest(require(self.root / file))
        return result

    def package_checkpoint(self, manifest):
        return dict(sources=self.source_snapshot(), settings=self.checkpoint_settings(), manifest=manifest,
                    installed=False, targets=list(map(str, self.targets)))

    def test(self, resume=None, deploy_only=False):
        server, client, server_args, client_args, port, timeout, require_signing = self.game_settings()
        if require_signing and self.s['shared'] and not self.s['sign']:
            raise ValueError(tr('Увімкни підпис і вибери ключі у спільному профілі.',
                                'Enable signing and choose keys in the shared profile.'))
        if resume and resume.get('settings') != self.checkpoint_settings():
            raise ValueError(tr('Налаштування пакета змінилися. Натисни «Зібрати та протестувати».',
                                'Package settings changed. Click Build and test.'))
        connection_timeout = int(self.s.get('connection_timeout') or 120)
        if not 10 <= connection_timeout <= 600:
            raise ValueError(tr('Час очікування клієнта має бути від 10 до 600 секунд.',
                                'Client timeout must be between 10 and 600 seconds.'))
        if resume and resume.get('sources') != self.source_snapshot():
            raise ValueError(tr('Вихідні файли змінилися. Натисни «Зібрати та протестувати».',
                                'Source files changed. Click Build and test.'))
        manifest = resume['manifest'] if resume else self.build()
        self.verify(manifest)
        self.report.update(built=True, signed=manifest['signed'], files=list(manifest['files']))
        checkpoint = self.package_checkpoint(manifest)
        save(self.state / 'package-checkpoint.json', checkpoint)
        checkpoint['installed'] = bool(resume and resume['installed'])
        if checkpoint['installed']:
            if checkpoint['targets'] != resume['targets']:
                raise ValueError(tr('Папки встановлення змінилися. Запусти нову збірку.',
                                    'Installation folders changed. Start a new build.'))
            self.check_install(manifest)
        save(self.state / 'retry.json', checkpoint)
        reuse_pid = None
        if not deploy_only and resume and checkpoint['installed'] and resume.get('serverPid') and resume.get('endpoint') == server_args:
            pid = int(resume['serverPid'])
            owns_port = self.ps(f"@(Get-NetUDPEndpoint -LocalPort {port} -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq {pid}).Count")
            if owns_port.isdecimal() and int(owns_port) > 0:
                reuse_pid = pid
        if reuse_pid:
            self.stop(server, client, clients_only=True)
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
            self.wait_ready(process, port, timeout, offsets)
            self.report['serverReady'] = True
            save(self.state / 'tested.json', manifest)
            checkpoint.update(serverPid=process.pid, endpoint=server_args)
            save(self.state / 'retry.json', checkpoint)
        offsets = {p: p.stat().st_size for p in self.profiles.glob('*.RPT')}
        self.progress(5, ('Запускаю гру й перевіряю підключення', 'Launching the game and verifying its connection'))
        subprocess.Popen([str(client), *client_args], cwd=client.parent)
        self.report['clientLaunched'] = True
        deadline = time.monotonic() + connection_timeout
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(tr('Сервер завершився, поки клієнт підключався.', 'The server exited while the client was connecting.'))
            if reuse_pid:
                alive = self.ps(f'(Get-Process -Id {reuse_pid} -ErrorAction SilentlyContinue).Id')
                if not alive:
                    raise RuntimeError(tr('Сервер зупинився. Повтори запуск.', 'The server stopped. Retry startup.'))
            for path in self.profiles.glob('*.RPT'):
                with path.open('rb') as stream:
                    stream.seek(offsets.get(path, 0))
                    text = stream.read().decode('utf-8', errors='replace')
                if re.search(r'(?im)^.*Player .*?(?:has connected\.|\(steamID=\d+.*?\) is connected)\s*$', text):
                    self.report['connected'] = True
                    save(self.state / 'deployment.json', checkpoint)
                    (self.state / 'retry.json').unlink(missing_ok=True)
                    return
            time.sleep(2)
        raise TimeoutError(tr('Гра запущена, але сервер не підтвердив підключення. Перевір Steam, запит пароля та повідомлення у грі.',
                              'The game was launched but the server did not confirm a connection. Check Steam, the password prompt and any in-game messages.'))

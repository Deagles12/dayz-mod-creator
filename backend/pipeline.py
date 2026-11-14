from locale_studio import tr

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
KIT = Path.home() / 'Desktop/DayZ_Modding_Kit/settings.json'
STORE = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DayZ Mod Studio'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def digest(path):
    with path.open('rb') as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def linked(path):
    return bool(getattr(path.lstat(), 'st_file_attributes', 0) & 1024)


def tree(root):
    if linked(root):
        raise ValueError(tr('Посилання або junction: {}', 'Symbolic link or junction: {}').format(root))
    result = {}
    for directory, folders, files in os.walk(root):
        for name in folders + files:
            path = Path(directory) / name
            if linked(path):
                raise ValueError(tr('Посилання або junction: {}', 'Symbolic link or junction: {}').format(path))
        for name in files:
            path = Path(directory) / name
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def required_addons(source):
    text = source.read_text(encoding='utf-8-sig', errors='replace')
    matches = re.findall(r'requiredAddons\s*\[\s*\]\s*=\s*\{([^}]*)\}', text, re.I)
    return set(re.findall(r'"([^"]+)"', ' '.join(matches)))


def detect_dependencies(root, addons, server, client, existing):
    dependencies = set()
    for addon in addons:
        config = root / addon / 'config.cpp'
        if config.is_file():
            dependencies.update(name.casefold() for name in required_addons(config)
                                if not name.upper().startswith('DZ_'))
    found = []
    for directory in (server, client):
        if not directory.is_dir():
            continue
        for mod in sorted(directory.glob('@*')):
            if mod.name.casefold() in existing:
                continue
            names = {path.stem.casefold() for path in (mod / 'Addons').glob('*.pbo')}
            if dependencies & names:
                found.append(str(mod))
                existing.add(mod.name.casefold())
    return found


def windows_args(command):
    count = ctypes.c_int()
    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
    args = parse(command, ctypes.byref(count))
    if not args:
        return []
    try:
        return [args[index] for index in range(count.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(args)


@contextmanager
def operation_lock():
    import msvcrt
    STORE.mkdir(parents=True, exist_ok=True)
    with (STORE / 'operation.lock').open('a+b') as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError(tr('Інша копія DayZ Mod Studio уже виконує операцію.', 'Another instance of DayZ Mod Studio is running an operation.')) from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def discover(root):
    ignored = {'.git', '.dayz-studio', 'build', 'backups', 'work', 'tests', 'tools',
               'releases', 'release', 'outputs', 'node_modules', 'assets', 'missions'}
    candidates = []
    for directory, folders, files in os.walk(root):
        parent = Path(directory)
        folders[:] = [name for name in folders if name.lower() not in ignored
                      and not name.startswith(('.', '@')) and not linked(parent / name)
                      and len(parent.relative_to(root).parts) < 5]
        if 'config.cpp' in files and not linked(parent / 'config.cpp'):
            source = (parent / 'config.cpp').read_text(encoding='utf-8-sig', errors='replace')
            if re.search(r'\bclass\s+CfgPatches\b', source, re.I):
                candidates.append(parent.relative_to(root).as_posix())
                folders[:] = []
    return sorted(candidates)


def steam_installs():
    import winreg
    libraries = set()
    for hive, key, field in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                              (winreg.HKEY_LOCAL_MACHINE, r'Software\WOW6432Node\Valve\Steam', 'InstallPath')):
        try:
            with winreg.OpenKey(hive, key) as registry:
                libraries.add(Path(winreg.QueryValueEx(registry, field)[0]))
        except OSError:
            continue
    for steam in list(libraries):
        try:
            vdf = (steam / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for match in re.findall(r'"path"\s+"([^"]+)"', vdf, re.I):
            libraries.add(Path(match.replace(chr(92) * 2, chr(92))))
    return [library / 'steamapps/common' for library in sorted(libraries)]


def detect_installs(settings):
    markers = {'tools': ('DayZ Tools', 'Bin/AddonBuilder/AddonBuilder.exe'),
               'server': ('DayZServer', 'DayZServer_x64.exe'),
               'client': ('DayZ', 'DayZ_BE.exe')}
    libraries = steam_installs()
    result = {}
    for key, (folder, marker) in markers.items():
        configured = Path(settings[key]) if settings.get(key) else None
        if configured and (configured / marker).is_file():
            result[key] = str(configured)
            continue
        found = next((library / folder for library in libraries if (library / folder / marker).is_file()), None)
        if found:
            result[key] = str(found)
    return result


def defaults(root):
    machine = load(KIT) if KIT.is_file() else {}
    project_file = root / 'settings.json'
    project = load(project_file) if project_file.is_file() else {}
    kit = {**machine, **project}
    addons = discover(root)
    source = project.get('SourceDir')
    if source and (root / source / 'config.cpp').is_file():
        addons = [source]
    metadata = next((name for name in ('mod.cpp', 'Source/mod.cpp', 'mod/mod.cpp')
                     if (root / name).is_file()), '')
    inferred_pack = not any(any(path.suffix.lower() in {'.p3d', '.rtm'}
                               for path in (root / addon).rglob('*')) for addon in addons)
    mod = project.get('ModFolder', '@' + (re.sub(r'[^a-zA-Z0-9_-]', '', root.name) or 'MyMod'))
    install_paths = dict(tools=kit.get('ToolsPath', 'F:/Steam/steamapps/common/DayZ Tools'),
                         server=kit.get('ServerRoot', 'F:/Steam/steamapps/common/DayZServer'),
                         client=kit.get('ClientRoot', 'F:/Steam/steamapps/common/DayZ'))
    install_paths.update(detect_installs(install_paths))
    server = Path(install_paths['server'])
    server_mods = list(kit.get('BaseMods', []))
    server_only = list(kit.get('BaseServerMods', []))
    if not project:
        server_mods = [item for item in server_mods if (server / item).is_dir() and item != mod]
        server_only = [item for item in server_only if (server / item).is_dir() and item != mod]
    client = install_paths['client']
    server_mods += detect_dependencies(root, addons, server, Path(client),
                                      {Path(item).name.casefold() for item in [mod, *server_mods, *server_only]})
    return dict(addons='\n'.join(addons), addon_name=project.get('AddonName', ''),
                prefix=project.get('Prefix', ''), mod=mod, metadata=metadata,
                tools=install_paths['tools'],
                server=str(server), client=client,
                server_exe='DayZServer_x64.exe', client_exe='DayZ_BE.exe',
                config=kit.get('ServerConfig', 'serverDZ.cfg'),
                profiles=kit.get('Profiles', 'profiles'), port=str(kit.get('Port', 2302)),
                address=kit.get('ConnectAddress', '127.0.0.1'),
                timeout=str(kit.get('ReadyTimeoutSeconds', 300)),
                base='\n'.join(server_mods), server_only='\n'.join(server_only),
                server_args='-dologs\n-adminlog\n-freezecheck',
                client_args='', client_profiles='', pack=bool(project.get('PackOnly', inferred_pack)),
                shared=bool(project.get('LoadOnClient', True)), separate=True,
                sign=bool(project.get('SignPbo', False)),
                private=project.get('PrivateKey', ''), public=project.get('PublicKey', ''),
                prep_exe='', prep_args='', extra='', workshop='', steam_owner='', notes='')


def lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def require(path):
    if not path.is_file():
        raise FileNotFoundError(tr('Файл не знайдено: {}', 'File not found: {}').format(path))
    return path


def transact(changes):
    """Each tuple is (target, source or None, persistent backup)."""
    prepared = []
    try:
        for target, source, backup in changes:
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = target.with_name('.dayz-stage-' + uuid.uuid4().hex)
            old = target.with_name('.dayz-old-' + uuid.uuid4().hex)
            exists = target.exists()
            if (exists or target.is_symlink()) and linked(target):
                raise ValueError(tr('Посилання або junction: {}', 'Symbolic link or junction: {}').format(target))
            prepared.append([target, stage, old, source is not None, False, False])
            for origin, destination in ((target if exists else None, backup), (source, stage)):
                if origin is None:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                if origin.is_dir():
                    expected = tree(origin)
                    shutil.copytree(origin, destination)
                    if tree(destination) != expected:
                        raise ValueError(tr('Копія відрізняється: {}', 'Copied content differs: {}').format(destination))
                else:
                    shutil.copy2(origin, destination)
                    if digest(destination) != digest(origin):
                        raise ValueError(tr('Копія відрізняється: {}', 'Copied content differs: {}').format(destination))
        for item in prepared:
            target, stage, old, has_source, _, _ = item
            if target.exists():
                target.rename(old)
                item[4] = True
            if has_source:
                stage.rename(target)
                item[5] = True
    except BaseException:
        for target, stage, old, _, moved, installed in reversed(prepared):
            if installed:
                target.rename(stage)
            if moved:
                old.rename(target)
        raise
    finally:
        for _, stage, _, _, _, _ in prepared:
            remove(stage)
    for _, _, old, _, _, _ in prepared:
        try:
            remove(old)
        except OSError:
            pass


def remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


class Pipeline:
    def __init__(self, root, settings, log=print, progress=lambda *args: None):
        self.root = root.resolve()
        self.s = settings
        self.log = log
        self.progress = progress
        self.state = STORE / 'projects' / hashlib.sha256(str(self.root).casefold().encode()).hexdigest()[:20]
        self.state = self.state.resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.server = self.path('server')
        self.client = self.path('client')
        self.tools = self.path('tools')
        self.profiles = self.path('profiles', self.server)
        self.mod = settings['mod']
        if not re.fullmatch(r'@[\w-]+', self.mod):
            raise ValueError(tr('Папка мода має формат @MyMod.', 'The mod folder must use the @MyMod format.'))
        if any(';' in str(path) for path in (self.server, self.client)):
            raise ValueError(tr('Шляхи сервера та клієнта не можуть містити крапку з комою.', 'Server and client paths cannot contain semicolons.'))
        self.targets = [self.server / self.mod]
        if settings['shared'] and settings['separate'] and self.client != self.server:
            self.targets.append(self.client / self.mod)

    def path(self, key, base=None):
        value = self.s[key].strip()
        if not value:
            raise ValueError(tr('Порожнє поле: {}', 'Required setting is empty: {}').format(key))
        path = Path(os.path.expandvars(os.path.expanduser(value)))
        return Path(os.path.abspath((base or self.root) / path))

    def run(self, args, cwd, timeout=900):
        self.log(f'▶ {Path(args[0]).name}')
        with subprocess.Popen([str(arg) for arg in args], cwd=cwd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, creationflags=HIDDEN) as process:
            timer = threading.Timer(timeout, lambda: process.kill() if process.poll() is None else None)
            timer.start()
            output = []
            try:
                for line in process.stdout:
                    line = line.decode('utf-8', errors='replace').rstrip()
                    self.log(line)
                    output.append(line)
                if process.wait():
                    raise RuntimeError(tr('{}: код {}', '{} exited with code {}').format(Path(args[0]).name, process.returncode))
            finally:
                timer.cancel()
        return '\n'.join(output)

    def check_tools(self):
        require(self.tools / 'Bin/AddonBuilder/AddonBuilder.exe')
        if self.s['sign']:
            for name in ('DSSignFile', 'DSCheckSignatures'):
                require(self.tools / f'Bin/DsUtils/{name}.exe')
            private, public = (require(self.path(key)) for key in ('private', 'public'))
            if private.suffix.lower() != '.biprivatekey' or public.suffix.lower() != '.bikey' or private.stem != public.stem:
                raise ValueError(tr('Вибери пару однойменних .biprivatekey та .bikey.', 'Choose a matching .biprivatekey and .bikey pair.'))

    def build(self):
        self.check_tools()
        self.progress(1, ('Збірка PBO', 'Building PBO files'))
        started = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        run = self.state / 'builds' / started
        package = run / self.mod
        addons = package / 'Addons'
        addons.mkdir(parents=True)
        if self.s['prep_exe'].strip():
            self.run([require(self.path('prep_exe')), *lines(self.s['prep_args'])], self.root)
        sources = lines(self.s['addons'])
        if not sources:
            raise ValueError(tr('Додай принаймні одну папку зі своїм config.cpp.', 'Add at least one addon directory containing config.cpp.'))
        used = set()
        for relative in sources:
            root = self.root / relative
            if not root.is_dir() or not root.resolve().is_relative_to(self.root):
                raise ValueError(tr('Джерело має бути всередині проєкту: {}', 'The source must be inside the project: {}').format(root))
            require(root / 'config.cpp')
            source_files = tree(root)
            sensitive = {'.biprivatekey', '.pem', '.pfx', '.p12', '.key'}
            ignored = {'.git', '.dayz-studio', '__pycache__', '.venv'}
            def exclude(directory, names):
                return {name for name in names if name.lower() in ignored or
                        name.lower().startswith('.env') or Path(name).suffix.lower() in sensitive}
            if any(Path(name).suffix.lower() in sensitive for name in source_files):
                raise ValueError(tr('Прибери приватні ключі з джерела: {}', 'Move private keys out of the addon source: {}').format(root))
            name = self.s['addon_name'].strip() if len(sources) == 1 else ''
            name = name or root.name
            if not re.fullmatch(r'[\w-]+', name) or name.casefold() in used:
                raise ValueError(tr('Некоректна або повторна назва PBO: {}', 'Invalid or duplicate PBO name: {}').format(name))
            used.add(name.casefold())
            prefix_file = root / '$PBOPREFIX$'
            declared = prefix_file.read_text(encoding='utf-8-sig').strip() if prefix_file.is_file() else ''
            configured = self.s['prefix'].strip() if len(sources) == 1 else ''
            if configured and declared and configured != declared:
                raise ValueError(tr('Prefix відрізняється від $PBOPREFIX$: {}', 'The selected prefix differs from $PBOPREFIX$: {}').format(root))
            prefix = configured or declared or name
            dependencies = required_addons(root / 'config.cpp')
            self.log(f'{name}: requiredAddons ' + ', '.join(sorted(dependencies)))
            self.log(f'{name}: prefix {prefix}')
            stage = run / 'stage' / name
            shutil.copytree(root, stage, ignore=exclude)
            temp = run / 'temp' / name
            temp.mkdir(parents=True)
            args = [self.tools / 'Bin/AddonBuilder/AddonBuilder.exe', stage, addons,
                    '-prefix=' + prefix, '-temp=' + str(temp), '-toolsDirectory=' + str(self.tools), '-clear']
            if self.s['pack']:
                args.append('-packonly')
            output = self.run(args, run)
            if re.search(r'(?im)^.*?(?:\[ERROR\]|\berror\s*[:!]|error\s+\d+|build failed)', output):
                raise RuntimeError(tr('AddonBuilder повідомив про помилку.', 'AddonBuilder reported an error.'))
            pbo = require(addons / (name + '.pbo'))
            if not pbo.stat().st_size:
                raise ValueError(tr('Порожній PBO: {}', 'The PBO is empty: {}').format(pbo))
            if self.s['sign']:
                key = self.path('private')
                self.run([self.tools / 'Bin/DsUtils/DSSignFile.exe', key, pbo], run)
                require(addons / f'{pbo.name}.{key.stem}.bisign')
            self.log(tr('Готово: {}', 'Built: {}').format(pbo.name))
        if self.s['sign']:
            self.progress(2, ('Перевірка підписів', 'Verifying signatures'))
            keys = package / 'Keys'
            keys.mkdir()
            shutil.copy2(self.path('public'), keys)
            result = self.run([self.tools / 'Bin/DsUtils/DSCheckSignatures.exe', addons, keys], run)
            if re.search(r'(?im)\b(?:bad signature|wrong signature|not signed|verification failed|signature mismatch)\b', result):
                raise RuntimeError(tr('Перевірка підписів завершилась помилкою.', 'Signature verification failed.'))
        extras = ['meta.cpp'] if (self.root / 'meta.cpp').is_file() else []
        extras += lines(self.s['extra'])
        for entry in extras:
            path = require(self.root / entry)
            if not path.resolve().is_relative_to(self.root) or linked(path) or path.suffix.lower() not in {
                '.cpp', '.md', '.txt', '.paa', '.png', '.jpg', '.jpeg', '.xml'
            } or path.name.startswith('.'):
                raise ValueError(tr('Непідтримуваний файл пакета: {}', 'Unsupported package file: {}').format(entry))
            shutil.copy2(path, package / path.name)
        if self.s['metadata'].strip():
            metadata = require(self.path('metadata'))
            if metadata.suffix.lower() != '.cpp':
                raise ValueError(tr('Метадані мають бути файлом .cpp.', 'Metadata must be a .cpp file.'))
            shutil.copy2(metadata, package / 'mod.cpp')
        manifest = dict(package=str(package), files=tree(package), signed=self.s['sign'])
        save(run / 'manifest.json', manifest)
        save(self.state / 'latest.json', manifest)
        self.log(tr('Збірка: {}', 'Build package: {}').format(package))
        return manifest


    def game_settings(self):
        server = require(self.path('server_exe', self.server))
        config = require(self.path('config', self.server))
        client = require(self.path('client_exe', self.client))
        port = int(self.s['port'])
        timeout = int(self.s['timeout'])
        if not 1024 <= port <= 65535 or not 5 <= timeout <= 1800:
            raise ValueError(tr('Порт: 1024–65535. Час очікування: 5–1800 секунд.', 'Port: 1024–65535. Startup timeout: 5–1800 seconds.'))
        if self.s['address'].strip() not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError(tr('Тестовий клієнт має підключатися до локального сервера.', 'The test client must connect to a local server.'))
        shared = self.dependencies('base')
        only = self.dependencies('server_only')
        if set(shared) & set(only):
            raise ValueError(tr('Є дублікати у списках -mod та -serverMod.', 'Duplicate entries in -mod and -serverMod.'))
        client_mods = list(shared)
        if self.s['shared']:
            shared.append(self.targets[0])
            client_mods.append(self.targets[-1])
        else:
            only.append(self.targets[0])
        server_args = [f'-config={config}', f'-profiles={self.profiles}', f'-port={port}']
        config_text = config.read_text(errors='replace')
        password = re.search(r'(?m)^\s*password\s*=\s*"([^"]*)"\s*;', config_text)
        client_args = [f'-connect={self.s["address"].strip()}', f'-port={port}']
        if password and password.group(1):
            client_args.append('-password=' + password.group(1))
        if self.s.get('client_profiles', '').strip():
            client_args.append(f'-profiles={self.path("client_profiles", self.client)}')
        for args, flag, mods in ((server_args, '-mod', shared), (server_args, '-serverMod', only),
                                 (client_args, '-mod', client_mods)):
            if mods:
                args.append(flag + '=' + ';'.join(map(str, mods)))
        for args, key in ((server_args, 'server_args'), (client_args, 'client_args')):
            for argument in lines(self.s[key]):
                if not argument.startswith('-') or re.match(r'(?i)^-(config|profiles|port|connect|mod|servermod)(=|\s|$)', argument):
                    raise ValueError(tr('Некоректний додатковий аргумент: {}', 'Invalid extra argument: {}').format(argument))
                args.append(argument)
        checks_signatures = bool(re.search(r'(?im)^\s*verifySignatures\s*=\s*[12]\s*;', config.read_text(errors='replace')))
        return server, client, server_args, client_args, port, timeout, checks_signatures

    def dependencies(self, key):
        result = []
        for entry in lines(self.s[key]):
            path = (self.server / entry).resolve()
            if ';' in str(path) or not path.is_dir():
                raise ValueError(tr('Некоректний шлях залежності: {}', 'Invalid dependency path: {}').format(path))
            if path in result or path in self.targets:
                raise ValueError(tr('Повторна залежність або папка цього мода: {}', 'Duplicate dependency or this project’s own mod folder: {}').format(path))
            result.append(path)
        return result

    def ps(self, script):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, encoding='utf-8', errors='replace', timeout=45,
                                creationflags=HIDDEN)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or tr('Помилка опитування процесів Windows.', 'Could not query Windows processes.'))
        return result.stdout.strip()

    def stop(self, server, client, require_idle_port=None, clients_only=False):
        script = """[Console]::OutputEncoding=[Text.Encoding]::UTF8
        @(Get-CimInstance Win32_Process -Filter "Name LIKE 'DayZ%.exe'") |
        Select-Object ProcessId,ExecutablePath,CommandLine,Name | ConvertTo-Json -Compress"""
        current = json.loads(self.ps(script) or '[]')
        current = current if isinstance(current, list) else [current]
        matched = []
        for process in current:
            raw_path = process['ExecutablePath']
            command = windows_args(process['CommandLine']) if process['CommandLine'] else []
            if not raw_path:
                if process['Name'].lower() in {server.name.lower(), client.name.lower(), 'dayz_x64.exe'}:
                    raise RuntimeError(tr('Windows не відкрила дані процесу {}. Запусти програму з тим самим рівнем прав.', 'Windows denied access to process {}. Run Studio with the same privilege level.').format(process['Name']))
                continue
            executable = Path(raw_path)
            options = dict(argument.split('=', 1) for argument in command[1:] if '=' in argument)
            options = {key.casefold(): value for key, value in options.items()}
            process_profiles = executable.parent / options.get('-profiles', '')
            process_mods = {executable.parent / item for item in options.get('-mod', '').split(';') if item}
            is_server = executable == server and process_profiles == self.profiles
            local_address = options.get('-connect', '').lower() in ('127.0.0.1', 'localhost', '::1')
            is_client = (executable.parent == client.parent and local_address
                         and options.get('-port') == self.s['port']
                         and (not self.s['shared'] or bool(process_mods.intersection(self.targets))))
            if is_server and clients_only:
                continue
            if is_server or is_client:
                matched.append((process['ProcessId'], is_server))
            elif executable == server or (executable.parent == client.parent and executable.name.lower() in {client.name.lower(), 'dayz_x64.exe'}):
                raise RuntimeError(tr('Працює інший сеанс DayZ (PID {}): {}. Закрий його або вибери відповідний тестовий профіль.', 'Another DayZ session is running (PID {}): {}. Close it or choose its test profile.').format(process['ProcessId'], executable))
        for pid, is_server in sorted(matched, key=lambda pair: pair[1]):
            self.log(tr('Зупинка тестового процесу PID {}', 'Stopping test process PID {}').format(pid))
            if is_server:
                command = [sys.executable]
                if not getattr(sys, 'frozen', False):
                    command.append(str(Path(__file__).with_name('sidecar.py')))
                command.extend(['--stop-server', str(pid)])
                result = subprocess.run(command, creationflags=HIDDEN, timeout=20)
                if result.returncode:
                    raise RuntimeError(tr('Не вдалося коректно зупинити сервер PID {}. Перевір його консоль.', 'Could not shut down server PID {} gracefully. Check its console.').format(pid))
            else:
                subprocess.run(['taskkill.exe', '/PID', str(pid)], creationflags=HIDDEN, capture_output=True)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and self.ps(f'(Get-Process -Id {pid} -ErrorAction SilentlyContinue).Id'):
                time.sleep(1)
            if self.ps(f'(Get-Process -Id {pid} -ErrorAction SilentlyContinue).Id'):
                raise RuntimeError(tr('Не вдалося завершити PID {}.', 'Could not stop PID {}.').format(pid))
        if require_idle_port and self.ps(f'(Get-NetUDPEndpoint -LocalPort {require_idle_port} -ErrorAction SilentlyContinue).OwningProcess'):
            raise RuntimeError(tr('UDP-порт {} вже зайнятий.', 'UDP port {} is already in use.').format(require_idle_port))

    def verify(self, manifest):
        directory = Path(manifest['package'])
        if directory.name != self.mod or not directory.resolve().is_relative_to((self.state / 'builds').resolve()):
            raise ValueError(tr('Пакет належить іншому проєкту або змінено @папку.', 'The package belongs to another project or the @Mod folder was renamed.'))
        if tree(directory) != manifest['files']:
            raise ValueError(tr('Файли збірки змінилися. Збери мод знову.', 'Build files have changed. Build the mod again.'))
        return directory

    def install(self, manifest, dependency_keys=()):
        self.progress(3, ('Резервна копія та встановлення', 'Backing up and installing'))
        package = self.verify(manifest)
        backup = self.state / 'backups' / uuid.uuid4().hex
        changes = [(target, package, backup / f'mod-{index}') for index, target in enumerate(self.targets)]
        keys = list((package / 'Keys').glob('*.bikey'))
        keys.extend(dependency_keys)
        known = {}
        for key in keys:
            target = self.server / 'keys' / key.name
            if target.exists() and linked(target):
                raise ValueError(tr('Серверний ключ є посиланням: {}', 'Server key is a link: {}').format(target))
            if target in known and digest(known[target]) != digest(key):
                raise ValueError(tr('Конфлікт ключів: {}', 'Conflicting keys: {}').format(key.name))
            known[target] = key
        for target, key in known.items():
            if target.is_file() and digest(target) == digest(key):
                continue
            if target.exists():
                raise ValueError(tr('На сервері вже є інший ключ {}. Вибери пару ключів з унікальною назвою.',
                                    'The server already has a different key named {}. Choose a uniquely named key pair.').format(key.name))
            changes.append((target, key, backup / 'keys' / key.name))
        # Save recovery data before replacing files. The committed pointer moves only after success.
        if (self.server / 'keys').exists() and linked(self.server / 'keys'):
            raise ValueError(tr('Папка keys сервера є посиланням або junction.', 'The server keys folder is a symbolic link or junction.'))
        backup.mkdir(parents=True)
        records = [dict(target=str(target), backup=str(copy), existed=target.exists())
                   for target, _, copy in changes]
        save(backup / 'recovery.json', records)
        transact(changes)
        save(self.state / 'previous.json', dict(records=records))
        self.log(tr('Резервна копія: {}', 'Backup: {}').format(backup))

    def rollback(self):
        self.progress(3, ('Відкат', 'Rolling back'))
        server, client, *_ = self.game_settings()
        record_file = require(self.state / 'previous.json')
        records = load(record_file)['records']
        stamp = self.state / 'backups' / uuid.uuid4().hex
        changes = []
        for index, record in enumerate(records):
            target, backup = Path(record['target']), Path(record['backup'])
            if target not in self.targets and not (target.parent == self.server / 'keys' and target.suffix == '.bikey'):
                raise ValueError(tr('Налаштування шляхів змінилися з моменту встановлення.', 'Installation paths have changed since deployment.'))
            if not backup.resolve().is_relative_to((self.state / 'backups').resolve()):
                raise ValueError(tr('Некоректний шлях резервної копії.', 'Invalid backup path.'))
            if record['existed'] and not backup.exists():
                raise FileNotFoundError(tr('Втрачено резервну копію: {}', 'Backup is missing: {}').format(backup))
            changes.append((target, backup if record['existed'] else None, stamp / str(index)))
        self.stop(server, client)
        transact(changes)
        record_file.unlink()
        self.log(tr('Попередню версію відновлено. Налаштування та сховище місії залишились у профілі сервера.', 'Previous mod files restored. Server profile and mission data remain in place.'))

    def test(self):
        server, client, server_args, client_args, port, timeout, check = self.game_settings()
        if check and self.s['shared'] and not self.s['sign']:
            raise ValueError(tr('Сервер перевіряє підписи. Вибери ключі й увімкни підписування.', 'The server requires signatures. Choose signing keys and enable signing.'))
        manifest = self.build()
        self.stop(server, client, port)
        self.install(manifest)
        self.progress(4, ('Стартап сервера й компіляція Enforce', 'Starting server and compiling Enforce'))
        self.profiles.mkdir(parents=True, exist_ok=True)
        baseline = {p: p.stat().st_size for p in self.profiles.iterdir()
                    if p.is_file() and self.is_game_log(p)}
        with (self.state / 'server-console.log').open('wb') as console:
            process = subprocess.Popen([str(server), *server_args], cwd=self.server, stdout=console,
                                       stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_CONSOLE,
                                       startupinfo=self.hidden_startup())
        self.log(tr('Сервер PID {}; логи: {}', 'Server PID {}; logs: {}').format(process.pid, self.profiles))
        self.wait_ready(process, port, timeout, baseline)
        self.progress(5, ('Запуск клієнта', 'Launching client'))
        subprocess.Popen([str(client), *client_args], cwd=self.client)
        save(self.state / 'tested.json', manifest)
        self.log(tr('Клієнт запущено для {}:{}. Підключення перевіряється у грі.', 'Client launched for {}:{}. Verify the connection in-game.').format(self.s['address'], port))

    @staticmethod
    def hidden_startup():
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        return info

    @staticmethod
    def is_game_log(path):
        return path.suffix.lower() == '.rpt' or (path.name.lower().startswith(('script', 'error')) and path.suffix.lower() == '.log')

    def wait_ready(self, process, port, timeout, offsets):
        deadline = time.monotonic() + timeout
        recent = {}
        while time.monotonic() < deadline:
            for path in self.profiles.iterdir():
                if not path.is_file() or not self.is_game_log(path):
                    continue
                offset = offsets.get(path, 0)
                text = recent.get(path, '')
                with path.open('rb') as stream:
                    stream.seek(0, 2)
                    if stream.tell() < offset:
                        offset, text = 0, ''
                    stream.seek(offset)
                    new = stream.read().decode('utf-8', errors='replace')
                    offsets[path] = stream.tell()
                if new:
                    for line in new.splitlines():
                        if path.suffix.lower() == '.log' or re.search('error|mission|warning', line, re.I):
                            self.log(line)
                recent[path] = (text + new)[-500000:]
            logs = '\n'.join(recent.values())
            if re.search(r"(?i)can't compile|cannot compile|compilation failed|error compiling|missing addons|requires addon|cannot load mission", logs):
                raise RuntimeError(tr('Помилка старту або компіляції. Логи: {}. Доступний відкат.', 'Startup or compilation failed. Logs: {}. Rollback is available.').format(self.profiles))
            if re.search(r'(?i)\[Server\]\s*::\s*termination in:', logs):
                raise RuntimeError(tr('Сервер сам почав завершення під час старту. Перевір конфіг, місію та RPT: {}.', 'The server began shutting down during startup. Check its configuration, mission and RPT: {}.').format(self.profiles))
            if process.poll() is not None:
                raise RuntimeError(tr('Сервер завершився з кодом {}. Логи: {}.', 'The server exited with code {}. Logs: {}.').format(process.returncode, self.profiles))
            if re.search(r'(?i)Module:\s*Mission\s*;', logs):
                listener = self.ps(f"@(Get-NetUDPEndpoint -LocalPort {port} -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq {process.pid}).Count")
                if listener.isdecimal() and int(listener) > 0:
                    return
            time.sleep(2)
        raise TimeoutError(tr('Сервер не підтвердив готовність за {} с. Логи: {}.', 'The server did not report readiness within {} seconds. Logs: {}.').format(timeout, self.profiles))

    def publish(self):
        from workshop import upload
        manifest = load(require(self.state / 'tested.json'))
        package = self.verify(manifest)
        self.progress(5, 'Steam Workshop')
        upload(self.client, int(self.s['workshop']), int(self.s['steam_owner']), package, self.s['notes'], self.log)
        self.log(f'https://steamcommunity.com/sharedfiles/filedetails/?id={self.s["workshop"]}')

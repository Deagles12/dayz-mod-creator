"""Line-delimited JSON adapter for the existing DayZ pipeline."""
import ctypes
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from test_workflow import MACHINE, TestPipeline

from locale_studio import set_language, tr
from pipeline import STORE, Pipeline, defaults, detect_installs, lines, load, operation_lock, required_addons, save


def stop_server(pid):
    kernel = ctypes.windll.kernel32
    kernel.FreeConsole()
    if not kernel.AttachConsole(pid):
        return 1
    try:
        pids = (ctypes.c_uint32 * 64)()
        count = kernel.GetConsoleProcessList(pids, len(pids))
        if not count or count > len(pids) or set(pids[:count]) != {pid, os.getpid()}:
            return 2
        kernel.SetConsoleCtrlHandler(None, True)
        if not kernel.GenerateConsoleCtrlEvent(0, 0):
            return 3
        time.sleep(.6)
        return 0
    finally:
        kernel.FreeConsole()


def state(root):
    key = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:20]
    return STORE / 'projects' / key


def optional(path, fallback):
    try:
        return load(path)
    except (OSError, ValueError):
        return fallback


def project(root):
    if not root.is_dir():
        raise FileNotFoundError(root)
    configured = state(root) / 'project.json'
    values = defaults(root)
    shared = optional(STORE / 'environment.json', {})
    saved = optional(configured, {})
    values.update(saved)
    if shared and not saved.get('environment_override'):
        if saved and any(saved.get(key, value) != value for key, value in shared.items()) and 'environment_override' not in saved:
            values['environment_override'] = True
        else:
            values.update(shared)
    values.setdefault('client_mods_root', '')
    values.setdefault('connection_timeout', '120')
    values.setdefault('environment_override', False)
    validate_project(root, values)
    return {'root': str(root), 'configured': configured.is_file(), 'settings': values}


def validate_project(root, settings):
    for entry in lines(settings.get('addons', '')):
        folder = (root / entry).resolve()
        config = folder / 'config.cpp'
        if folder.is_relative_to(root) and config.is_file():
            source = config.read_text(encoding='utf-8-sig', errors='replace')
            if re.search(r"\bclass\s+CfgPatches\b|(?m:^\s*#include\s+)", source, re.I):
                return
    raise ValueError(tr('У цій папці немає вихідного аддона DayZ. Вибери корінь проєкту з config.cpp.',
                        'This folder has no DayZ source addon. Choose a project folder containing config.cpp.'))


def readiness(root, settings):
    checks = []
    try:
        pipeline = TestPipeline(root, settings, print, lambda *args: None, {})
    except Exception as error:
        return [{'key': 'project', 'ok': False, 'detail': str(error)}]

    def record(key, check):
        try:
            checks.append({'key': key, 'ok': True, 'detail': str(check() or '')})
        except Exception as error:
            checks.append({'key': key, 'ok': False, 'detail': str(error)})

    def sources():
        addons = lines(settings['addons'])
        if not addons:
            raise ValueError(tr('Вкажи папку з config.cpp.', 'Choose a folder containing config.cpp.'))
        for addon in addons:
            source = (root / addon).resolve()
            if not source.is_relative_to(root) or not (source / 'config.cpp').is_file():
                raise FileNotFoundError(source / 'config.cpp')
        return ', '.join(addons)

    def tools():
        tool = pipeline.tools / 'Bin/AddonBuilder/AddonBuilder.exe'
        if not tool.is_file():
            raise FileNotFoundError(tool)
        return pipeline.tools

    def game():
        server, client, _, _, port, _, _ = pipeline.game_settings()
        pipeline.dependency_keys()
        for profile in [pipeline.profiles, *( [pipeline.path('client_profiles', pipeline.client)]
                         if settings.get('client_profiles', '').strip() else [])]:
            if profile.exists() and not profile.is_dir():
                raise ValueError(tr('Профіль має бути папкою: {}', 'Profile must be a folder: {}').format(profile))
        return f'{server.name} / {client.name} · {port}'

    def signing():
        if settings['sign']:
            pipeline.check_tools()
            return pipeline.path('public').name
        try:
            required = pipeline.game_settings()[-1]
        except (OSError, ValueError):
            required = False
        if required and settings['shared']:
            raise ValueError(tr('Сервер вимагає підпису.', 'The server requires signatures.'))
        return tr('Вимкнено', 'Disabled')

    for key, check in [('sources', sources), ('tools', tools), ('environment', game), ('signing', signing)]:
        record(key, check)
    return checks


def details(root, settings):
    directory = state(root)
    tested = optional(directory / 'tested.json', {})
    builds = []
    for path in sorted((directory / 'builds').glob('*/manifest.json'), reverse=True)[:100]:
        info = optional(path, {})
        if 'package' in info:
            builds.append({'name': path.parent.name, 'path': info['package'], 'signed': info['signed'],
                           'tested': info['package'] == tested.get('package'),
                           'count': sum(name.lower().endswith('.pbo') for name in info['files'])})
    dependencies = set()
    for addon in lines(settings['addons']):
        config = (root / addon / 'config.cpp').resolve()
        if config.is_relative_to(root) and config.is_file():
            dependencies.update(required_addons(config))
    history = []
    for path in sorted((directory / 'operations').glob('*.json'), reverse=True)[:20]:
        item = optional(path, None)
        if item:
            history.append(item)
    return {
        'operations': history, 'packageReady': (directory / 'package-checkpoint.json').is_file(), 'deployment': (directory / 'deployment.json').is_file(), 'retry': (directory / 'retry.json').is_file(),
        'checks': readiness(root, settings), 'dependencies': sorted(dependencies),
        'builds': builds, 'backups': [str(path.parent) for path in sorted(
            (directory / 'backups').glob('*/recovery.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:50]],
        'rollback': (directory / 'previous.json').is_file(),
        'tested': bool(tested),
        'logs': [str(path) for path in sorted((directory / 'logs').glob('*.log'), reverse=True)[:50]],
    }


def save_settings(root, settings):
    save(state(root) / 'project.json', settings)
    if not settings.get('environment_override'):
        save(STORE / 'environment.json', {key: settings[key] for key in MACHINE if key in settings})


def operate(root, request, emit):
    action = request['action']
    if action not in ('build', 'test', 'deploy', 'launch', 'retry', 'rollback', 'publish'):
        raise ValueError(action)
    settings = request['settings']
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    file = state(root) / 'logs' / (stamp + '.log')
    file.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = dict(action=action, date=datetime.now().isoformat(), phase=0, status='failed',
                  warnings=0, built=False, signed=False, installed=False, serverReady=False,
                  clientLaunched=False, connected=False, updated=[], files=[], log=str(file))

    def log(message):
        text = str(message)
        if re.search(r'(?i)\[WARN(?:ING)?\s*\]|\(W\):|\bwarning\b', text):
            report['warnings'] += 1
        with file.open('a', encoding='utf-8') as stream:
            stream.write(text + '\n')
        emit('log', text=text)

    def progress(stage, label):
        report['phase'] = stage
        emit('progress', stage=stage, label=label)

    with operation_lock():
        try:
            validate_project(root, settings)
            save_settings(root, settings)
            pipeline = TestPipeline(root, settings, log, progress, report)
            if action == 'test':
                (pipeline.state / 'retry.json').unlink(missing_ok=True)
                pipeline.test()
            elif action == 'deploy':
                checkpoint = load(pipeline.state / 'package-checkpoint.json')
                pipeline.test(checkpoint, deploy_only=True)
            elif action == 'launch':
                checkpoint = load(pipeline.state / 'deployment.json')
                if not checkpoint['installed']:
                    raise ValueError(tr('Спочатку встанови збірку.', 'Install the build first.'))
                pipeline.test(checkpoint)
            elif action == 'retry':
                pipeline.test(load(pipeline.state / 'retry.json'))
            elif action == 'build':
                manifest = pipeline.build()
                pipeline.verify(manifest)
                save(pipeline.state / 'package-checkpoint.json', pipeline.package_checkpoint(manifest))
                report.update(built=True, signed=manifest['signed'], files=list(manifest['files']))
            else:
                getattr(pipeline, action)()
                if action == 'rollback':
                    (pipeline.state / 'retry.json').unlink(missing_ok=True)
                    (pipeline.state / 'deployment.json').unlink(missing_ok=True)
            report['status'] = 'complete'
        except Exception as error:
            report['attention'] = isinstance(error, TimeoutError) and report['clientLaunched']
            report['error'] = str(error)
            log(error)
        finally:
            report['seconds'] = round(time.monotonic() - started, 1)
            save(state(root) / 'operations' / (stamp + '.json'), report)
    return details(root, settings)


def dispatch(request, emit):
    command = request['command']
    if command == 'hello':
        return {'hasEnvironment': (STORE / 'environment.json').is_file(), 'interface': optional(STORE / 'interface.json', {}), 'recent': optional(STORE / 'recent.json', {})}
    if command == 'preferences':
        save(STORE / 'interface.json', request['value'])
        return None
    if command == 'detect':
        return detect_installs(request['settings'])
    root = Path(request['root']).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    if command == 'open':
        result = project(root)
        save(STORE / 'recent.json', {'project': str(root)})
        result['details'] = details(root, result['settings'])
        return result
    if command == 'serverStatus':
        from pipeline import windows_args
        settings = request['settings']
        pipeline = TestPipeline(root, settings, print, lambda *args: None, {})
        executable = pipeline.path('server_exe', pipeline.server)
        port = int(settings['port'])
        if not executable.is_file() or not 1024 <= port <= 65535:
            return 'unknown'
        raw = pipeline.ps(f"""
            $ErrorActionPreference='Stop'
            [Console]::OutputEncoding=[Text.Encoding]::UTF8
            $udp = @(Get-NetUDPEndpoint -ErrorAction Stop | Where-Object LocalPort -eq {port})
            $rows = foreach ($item in $udp) {{
                Get-CimInstance Win32_Process -Filter ('ProcessId='+$item.OwningProcess)
            }}
            @($rows | Select-Object ExecutablePath,CommandLine) | ConvertTo-Json -Compress
        """)
        if not raw:
            return 'offline'
        found = json.loads(raw)
        for row in found if isinstance(found, list) else [found]:
            if row.get('ExecutablePath') and Path(row['ExecutablePath']) == executable and row.get('CommandLine'):
                for argument in windows_args(row['CommandLine']):
                    if argument.lower().startswith('-profiles=') and executable.parent / argument[10:] == pipeline.profiles:
                        return 'ready'
        return 'unknown'
    if command == 'details':
        return details(root, request['settings'])
    if command == 'save':
        save_settings(root, request['settings'])
        return details(root, request['settings'])
    if command == 'run':
        return operate(root, request, emit)
    if command in ('readLog', 'reveal'):
        path = Path(request['path']).resolve()
        if not path.is_relative_to(state(root).resolve()):
            raise ValueError(tr('Шлях поза історією проєкту.', 'Path is outside the project history.'))
        if command == 'reveal':
            if not path.is_dir():
                raise NotADirectoryError(path)
            os.startfile(path)
            return None
        if path.parent != state(root).resolve() / 'logs' or path.suffix != '.log':
            raise ValueError(tr('Вибери журнал операції.', 'Choose an operation log.'))
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 500000))
            return stream.read().decode('utf-8', errors='replace')
    raise ValueError(command)


def main():
    if getattr(sys, 'frozen', False):
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    if len(sys.argv) == 3 and sys.argv[1] == '--stop-server':
        return stop_server(int(sys.argv[2]))
    for line in sys.stdin.buffer:
        request_id = None

        def emit(kind, **data):
            print(json.dumps(dict(id=request_id, event=kind, **data), ensure_ascii=True), flush=True)

        try:
            request = json.loads(line)
            request_id = request['id']
            set_language(request.get('language', 'uk'))
            emit('result', value=dispatch(request, emit))
        except Exception as error:
            emit('error', text=str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

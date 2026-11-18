"""Line-delimited JSON adapter for the existing DayZ pipeline."""
import base64
import ctypes
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from console import ACTIONS, command as shell_command
from test_workflow import MACHINE, TestPipeline

from model_export import export_model, read_glb
from texture_export import convert_textures
from export_folders import can_reveal, install_directory, output_folder
from locale_studio import set_language, tr
from pipeline import STORE, defaults, detect_installs, lines, load, operation_lock, require, required_addons, save
from remote import LinuxDayZ, select_build


def stop_server(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    def failed(operation):
        code = ctypes.get_last_error()
        print(f'{operation}: WinError {code}: {ctypes.FormatError(code).strip()}', file=sys.stderr)
        return 1
    kernel.FreeConsole()
    if not kernel.AttachConsole(pid):
        return failed('AttachConsole')
    try:
        pids = (ctypes.c_uint32 * 64)()
        count = kernel.GetConsoleProcessList(pids, len(pids))
        if not count:
            return failed('GetConsoleProcessList')
        if count > len(pids) or set(pids[:count]) != {pid, os.getpid()}:
            print(f'Unsafe console membership: PID {pid}, members {list(pids[:min(count, len(pids))])}', file=sys.stderr)
            return 2
        if not kernel.SetConsoleCtrlHandler(None, True):
            return failed('SetConsoleCtrlHandler')
        if not kernel.GenerateConsoleCtrlEvent(0, 0):
            return failed('GenerateConsoleCtrlEvent')
        time.sleep(.6)
        return 0
    finally:
        kernel.FreeConsole()


def state(root):
    key = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:20]
    return STORE / 'projects' / key


def recent_file():
    return state(install_directory()) / 'recent.json'


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
    values.setdefault('publish_workshop', False)
    values.setdefault('open_dayz', False)
    for key in ('remote_host', 'remote_user', 'remote_root', 'remote_mod', 'remote_keys',
                'remote_service', 'remote_readiness', 'workshop_title', 'workshop_description', 'workshop_preview'):
        values.setdefault(key, '')
    values.setdefault('remote_port', '22')
    values.setdefault('remote_files_only', False)
    values.setdefault('workshop_visibility', 'private')
    return {'root': str(root), 'configured': configured.is_file(), 'settings': values}


def validate_project(root, settings):
    for entry in lines(settings.get('addons', '')):
        folder = (root / entry).resolve()
        config = folder / 'config.cpp'
        if folder.is_relative_to(root) and config.is_file():
            source = config.read_text(encoding='utf-8-sig', errors='replace')
            if re.search(r"\bclass\s+CfgPatches\b|(?m:^\s*#include\s+)", source, re.I):
                return
    raise ValueError(tr('Вибери папку мода, що містить аддон із config.cpp.',
                        'Choose a mod folder containing an addon with config.cpp.'))


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
        validate_project(root, settings)
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


def recent_operations(directory):
    return [item for path in sorted((directory / 'operations').glob('*.json'), reverse=True)[:20]
            if (item := optional(path, None))]


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
    publication = optional(directory / 'workshop-attempt.json', {})
    published = optional(directory / 'workshop-confirmed.json', {})
    if settings.get('workshop'):
        try:
            item = workshop_item(settings['workshop'])
        except ValueError:
            item = None
        if published.get('item') != str(item):
            published = optional(directory / 'workshop-items' / f'{item}.json', {}) if item else {}
        if publication.get('item') != str(item):
            publication = {}
    local = optional(directory / 'local-ready.json', {})
    sources_changed = None
    remote_choice = {}
    dependencies_state = []
    try:
        pipeline = TestPipeline(root, settings, lambda *args: None, lambda *args: None, {})
    except (OSError, ValueError):
        pipeline = None
    inputs = None
    if pipeline:
        for kind in ('base', 'server_only'):
            for index, entry in enumerate(lines(settings[kind]), 1):
                row = dict(entry=entry, kind=kind, order=index)
                try:
                    resolved = pipeline.resolve_dependency(entry)
                    row.update(path=str(resolved), available=True)
                except (OSError, ValueError) as error:
                    row.update(available=False, error=str(error))
                dependencies_state.append(row)
        if tested or published or local:
            try:
                inputs = pipeline.build_inputs()
            except (OSError, ValueError):
                pass
        if tested.get('inputs') and inputs:
            sources_changed = tested['inputs'] != inputs
    try:
        manifest = remote_manifest(directory, settings)
        remote_choice['buildId'] = manifest['id']
        if inputs:
            remote_choice['changed'] = manifest.get('inputs') != inputs
    except (OSError, ValueError, KeyError):
        pass
    remote_build = optional(directory / 'remote-ready.json', {})
    if remote_build.get('profile') != remote_profile(settings):
        remote_build = {}
    for record in (published, remote_build):
        if inputs and re.fullmatch(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{8}', str(record.get('buildId', ''))):
            manifest = optional(directory / 'builds' / record['buildId'] / 'manifest.json', {})
            if manifest.get('inputs'):
                record['changed'] = manifest['inputs'] != inputs
    return {
        'commands': {action: shell_command(root, action, remote_choice.get('buildId'))
                     for action in ACTIONS if action != 'keys' and (action != 'remote' or remote_choice.get('buildId'))},
        'publication': publication, 'published': published, 'localBuild': local, 'sourcesChanged': sources_changed,
        'workshopDraft': optional(directory / 'workshop-draft.json', {}), 'workshopItem': settings.get('workshop', ''),
        'remoteChoice': remote_choice, 'remoteBuild': remote_build,
        'dependencyState': dependencies_state,
        'operations': recent_operations(directory), 'packageReady': (directory / 'package-checkpoint.json').is_file(), 'deployment': (directory / 'deployment.json').is_file(), 'retry': (directory / 'retry.json').is_file(),
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


def workshop_item(value):
    from urllib.parse import parse_qs, urlsplit
    value = str(value).strip()
    if value.startswith('https://'):
        url = urlsplit(value)
        if url.netloc.lower() == 'steamcommunity.com' and url.path.rstrip('/') in (
                '/sharedfiles/filedetails', '/workshop/filedetails'):
            value, = parse_qs(url.query).get('id', [''])
    if not re.fullmatch(r'[0-9]{1,20}', value) or not 0 < int(value) < 2**64:
        raise ValueError(tr('Вкажи ID або посилання на Steam Workshop.', 'Enter a Steam Workshop item ID or URL.'))
    return int(value)


def remote_manifest(directory, settings):
    item = workshop_item(settings.get('workshop', '')) if settings.get('publish_workshop') else None
    try:
        return select_build(directory, settings, load, item)
    except FileNotFoundError:
        raise ValueError(tr('Спочатку створи й перевір збірку через F5.', 'Create and verify a build with F5 first.')) from None


def remote_profile(settings):
    values = {key: value for key, value in settings.items() if key.startswith('remote_')}
    values['remote_mod'] = settings.get('remote_mod') or settings['mod']
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def publish(pipeline, manifest, retry=False):
    settings = pipeline.s
    directory = pipeline.state
    attempt = directory / 'workshop-attempt.json'
    item = workshop_item(settings['workshop'])
    pipeline.current_package(manifest)
    owner = str(settings['steam_owner'])
    if not re.fullmatch(r'[0-9]{17}', owner):
        raise ValueError(tr('Вкажи SteamID64 власника.', 'Enter the owner SteamID64.'))
    build_id = manifest['id']
    item_attempt = directory / 'workshop' / build_id / f'item-{item}.json'
    previous = optional(item_attempt, {})
    if retry and previous.get('status') != 'failed':
        raise ValueError(tr('Для цієї збірки немає відхиленої публікації, яку можна повторити.',
                            'No failed publication can be retried for this build.'))
    if previous.get('status') in ('pending', 'uncertain'):
        raise ValueError(tr('Результат попередньої публікації невідомий. Перевір item у Steam.',
                            'The previous publication result is unknown. Check the item in Steam.'))
    record = dict(buildId=build_id, item=str(item), date=datetime.now().astimezone().isoformat(), status='pending')
    history = directory / 'workshop' / build_id / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')

    def persist(status):
        record.update(status=status, date=datetime.now().astimezone().isoformat())
        save(attempt, record)
        save(item_attempt, record)
        save(history, record)
        pipeline.report['workshopStatus'] = status

    pipeline.report['buildId'] = build_id
    draft_path = directory / 'workshop-draft.json'
    draft = optional(draft_path, {})
    metadata = first_item_metadata(pipeline) if draft.get('item') == str(item) else None
    persist('pending')
    try:
        if metadata is None:
            pipeline.publish(manifest, item)
        else:
            pipeline.publish(manifest, item, metadata)
    except TimeoutError:
        persist('uncertain')
        raise
    except Exception:
        persist('failed')
        raise
    persist('confirmed')
    save(directory / 'workshop-confirmed.json', record)
    save(directory / 'workshop-items' / f'{item}.json', record)
    if metadata is not None:
        draft_path.unlink(missing_ok=True)


def first_item_metadata(pipeline):
    settings = pipeline.s
    title = str(settings.get('workshop_title', '')).strip()
    description = str(settings.get('workshop_description', '')).strip()
    if not title or not description:
        raise ValueError(tr('Введи назву й опис item.', 'Enter the Workshop title and description.'))
    if not settings.get('workshop_preview'):
        raise ValueError(tr('Вибери файл обкладинки.', 'Choose a preview image file.'))
    preview = require(pipeline.path('workshop_preview'))
    if preview.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise ValueError(tr('Вибери обкладинку PNG або JPEG.', 'Choose a PNG or JPEG preview.'))
    visibility = {'public': 0, 'friends': 1, 'private': 2, 'unlisted': 3}
    selected = str(settings.get('workshop_visibility', 'private') or 'private').strip().lower()
    if selected not in visibility:
        raise ValueError('Workshop visibility: public, friends, private, unlisted.')
    return dict(title=title, description=description, preview=str(preview), visibility=visibility[selected])


def create_workshop(pipeline, manifest):
    from workshop import agreement, create

    pipeline.current_package(manifest)
    first_item_metadata(pipeline)
    settings = pipeline.s
    owner = str(settings.get('steam_owner', ''))
    if not re.fullmatch(r'[0-9]{17}', owner):
        raise ValueError(tr('Вкажи SteamID64 власника.', 'Enter the owner SteamID64.'))
    path = pipeline.state / 'workshop-draft.json'
    draft = optional(path, {})
    if draft.get('status') in ('pending', 'uncertain') and settings.get('workshop'):
        recovered = str(workshop_item(settings['workshop']))
        draft = dict(item=recovered, status='created', buildId=manifest['id'])
        save(path, draft)
    if draft.get('item'):
        item = workshop_item(draft['item'])
        if settings.get('workshop') and workshop_item(settings['workshop']) != item:
            raise ValueError(tr('Вибране посилання відрізняється від чернетки Steam.',
                                'The selected item differs from the Steam draft.'))
        settings['workshop'] = str(item)
        save_settings(pipeline.root, settings)
        publish(pipeline, manifest)
        return
    if draft or settings.get('workshop'):
        raise ValueError(tr('Перевір свої item у Steam і збережи отриманий Workshop ID.',
                            'Check your Steam items and save the resulting Workshop ID.'))
    save(path, dict(status='pending', buildId=manifest['id']))
    try:
        item, needs_agreement = create(pipeline.client, int(owner))
    except TimeoutError:
        save(path, dict(status='uncertain', buildId=manifest['id']))
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise
    save(path, dict(item=str(item), status='created', buildId=manifest['id']))
    settings['workshop'] = str(item)
    save_settings(pipeline.root, settings)
    pipeline.report['buildId'] = manifest['id']
    if needs_agreement:
        raise agreement(item)
    publish(pipeline, manifest)


def generate_keys(root, settings, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', name):
        raise ValueError(tr('Допустимі латинські літери, цифри, дефіс і підкреслення.',
                            'Use letters, numbers, hyphens or underscores for the key name.'))
    with operation_lock():
        pipeline = TestPipeline(root, settings, lambda *args: None, lambda *args: None, {})
        directory = pipeline.state / 'signing'
        directory.mkdir(exist_ok=True)
        target = directory / name
        if target.exists():
            raise FileExistsError(tr('Така пара ключів уже існує.', 'A key pair with this name already exists.'))
        tool = require(pipeline.tools / 'Bin/DsUtils/DSCreateKey.exe')
        with tempfile.TemporaryDirectory(dir=directory) as workspace:
            key_pair = Path(workspace) / 'pair'
            key_pair.mkdir()
            pipeline.run([tool, name], key_pair, timeout=30)
            require(key_pair / f'{name}.bikey')
            require(key_pair / f'{name}.biprivatekey')
            key_pair.rename(target)
        return dict(sign=True, public=str(target / f'{name}.bikey'), private=str(target / f'{name}.biprivatekey'))


def next_step(report, directory, settings):
    action = report['action']
    if report['status'] == 'complete':
        if action in ('test', 'retry', 'publish', 'retry-publish', 'create-workshop') and report.get('buildId'):
            if settings.get('remote_host') and (not settings.get('publish_workshop') or
                                                 report.get('workshopStatus') == 'confirmed'):
                return dict(action='remote', buildId=report['buildId'])
        return dict(action={'build': 'deploy', 'deploy': 'launch'}.get(action, 'status'))
    if report.get('workshopStatus') == 'failed':
        return dict(action='retry-publish')
    if report.get('workshopStatus') in ('uncertain', 'pending') or report.get('remote', {}).get('status') in ('unknown', 'rollback_failed'):
        return dict(action='status')
    if action in ('test', 'retry') and report.get('built') and (directory / 'retry.json').is_file():
        return dict(action='retry')
    if action == 'remote' and not report.get('buildId'):
        return dict(action='status')
    return dict(action='logs')


def load_checkpoint(directory, filename, hint):
    try:
        return load(directory / filename)
    except FileNotFoundError:
        raise ValueError(tr(*hint)) from None


def operate(root, request, emit, report_only=False):
    action = request['action']
    if action not in ('build', 'test', 'deploy', 'launch', 'retry', 'rollback', 'publish', 'retry-publish',
                      'remote', 'remote-check', 'create-workshop'):
        raise ValueError(action)
    settings = request.get('settings')
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
        if settings is None:
            selected = project(root)
            if not selected['configured']:
                raise ValueError(tr('Налаштуй проєкт у GUI або через config --set KEY VALUE.',
                                    'Configure the project in the GUI or with config --set KEY VALUE.'))
            settings = selected['settings']
        try:
            progress(0, ('Перевіряю налаштування', 'Checking project settings'))
            validate_project(root, settings)
            if 'settings' in request:
                save_settings(root, settings)
            pipeline = TestPipeline(root, settings, log, progress, report)
            manifest = None
            retry = load_checkpoint(pipeline.state, 'retry.json', (
                'Немає перерваного оновлення. Запусти update.', 'There is no interrupted update. Run update.')) if action == 'retry' else None
            publish_automatically = bool(settings.get('publish_workshop') and (
                action == 'test' or (retry and retry.get('publishAfter'))))
            if publish_automatically:
                workshop_item(settings['workshop'])
                if not re.fullmatch(r'[0-9]{17}', str(settings['steam_owner'])):
                    raise ValueError(tr('Вкажи SteamID64 власника.', 'Enter the owner SteamID64.'))
            if action == 'test':
                (pipeline.state / 'retry.json').unlink(missing_ok=True)
                manifest = pipeline.test(publish_after=publish_automatically)
            elif action == 'deploy':
                checkpoint = load_checkpoint(pipeline.state, 'package-checkpoint.json', (
                    'Спочатку створи пакет командою build.', 'Create a package with build first.'))
                pipeline.test(checkpoint, deploy_only=True)
            elif action == 'launch':
                checkpoint = load_checkpoint(pipeline.state, 'deployment.json', (
                    'Спочатку встанови пакет командою deploy або update.', 'Install a package with deploy or update first.'))
                if not checkpoint['installed']:
                    raise ValueError(tr('Спочатку встанови збірку.', 'Install the build first.'))
                manifest = pipeline.test(checkpoint, start_client=True)
            elif action == 'retry':
                manifest = pipeline.test(retry, publish_after=publish_automatically)
            elif action == 'build':
                manifest = pipeline.build()
                pipeline.verify(manifest)
                save(pipeline.state / 'package-checkpoint.json', pipeline.package_checkpoint(manifest))
                report.update(built=True, signed=manifest['signed'], files=list(manifest['files']), buildId=manifest['id'])
            elif action == 'rollback':
                deployment = optional(pipeline.state / 'deployment.json', {})
                report['buildId'] = deployment.get('manifest', {}).get('id')
                pipeline.rollback()
                for name in ('retry.json', 'deployment.json', 'tested.json', 'local-ready.json'):
                    (pipeline.state / name).unlink(missing_ok=True)
            elif action in ('publish', 'retry-publish'):
                publish(pipeline, load_checkpoint(pipeline.state, 'tested.json', (
                    'Потрібна локально перевірена збірка. Запусти update.', 'Run update to create a locally verified build.')),
                    retry=action == 'retry-publish')
            elif action == 'create-workshop':
                create_workshop(pipeline, load_checkpoint(pipeline.state, 'tested.json', (
                    'Спочатку запусти update з вимкненою публікацією.', 'Run update with Workshop publishing disabled first.')))
            elif action == 'remote-check':
                progress(0, ('Перевіряю віддалене підключення', 'Checking the remote connection'))
                LinuxDayZ(settings).check()
            elif action == 'remote':
                manifest = remote_manifest(pipeline.state, settings)
                requested_id = request.get('buildId')
                if requested_id and manifest['id'] != requested_id:
                    raise ValueError(tr('Вибрана збірка змінилася. Онови статус перед F6.',
                                        'The selected build changed. Refresh the status before F6.'))
                package = pipeline.verify(manifest)
                report['buildId'] = manifest['id']
                log(tr('Віддалена збірка: {}', 'Remote build: {}').format(manifest['id']))
                try:
                    unchanged = manifest['inputs'] == pipeline.build_inputs()
                except (OSError, ValueError):
                    unchanged = False
                if not unchanged:
                    report['olderBuild'] = True
                    log(tr('Встановлюю попередню перевірену збірку. Для нових змін натисни F5.',
                           'Installing the previous verified build. Use F5 to include new changes.'))
                result = LinuxDayZ(settings).install(package, manifest, progress)
                report['remote'] = result
                if result['status'] == 'uploaded':
                    log(tr('Файли завантажено у проміжну папку. Потрібне ручне встановлення й перезапуск.',
                           'Files uploaded to staging. Manual installation and restart required.'))
                elif result['status'] != 'ready':
                    raise RuntimeError(dict(
                        rolled_back=tr('Нова версія не запустилася. Попередній стан відновлено.',
                                       'The new version failed to start. The previous state was restored.'),
                        rollback_failed=tr('Відкат не завершився. Перевір віддалений сервер.',
                                           'Rollback did not complete. Check the remote server.'),
                        rejected=tr('Віддалений сервер відхилив пакет до встановлення.',
                                    'The remote server rejected the package before installation.'),
                        unknown=tr('Результат невідомий. Перевір віддалений сервер перед повторенням.',
                                   'The result is unknown. Inspect the remote server before retrying.')
                    )[result['status']])
                else:
                    save(pipeline.state / 'remote-ready.json', dict(buildId=manifest['id'], profile=remote_profile(settings),
                                                                     date=datetime.now().astimezone().isoformat()))
            if report['serverReady']:
                save(pipeline.state / 'local-ready.json', dict(buildId=manifest.get('id'), date=datetime.now().astimezone().isoformat()))
                if publish_automatically:
                    publish(pipeline, manifest)
            report['status'] = 'complete'
        except Exception as error:
            report['attention'] = isinstance(error, TimeoutError) and report['clientLaunched']
            report['error'] = str(error)
            log(error)
        finally:
            report['seconds'] = round(time.monotonic() - started, 1)
            report['next'] = next_step(report, state(root), settings)
            save(state(root) / 'operations' / (stamp + '.json'), report)
    if report_only:
        return report
    result = details(root, settings)
    result['currentOperation'] = report
    return result


def dispatch(request, emit):
    command = request['command']
    if command == 'exportFolder':
        return str(output_folder(request['kind'], request.get('path')))
    if command == 'convertTextures':
        return convert_textures(request['paths'], request.get('settings', {}),
                                lambda stage, text: emit('progress', stage=stage, text=text),
                                request.get('output'))
    if command == 'previewModel':
        _, data = read_glb(request['path'])
        return base64.b64encode(data).decode('ascii')
    if command == 'exportModel':
        return export_model(request, lambda stage: emit('progress', stage=stage))
    if command in ('revealModel', 'revealTextures'):
        path = Path(request['path']).resolve()
        if not can_reveal('models' if command == 'revealModel' else 'textures', path):
            raise ValueError('Invalid export folder')
        os.startfile(path)
        return None
    if command == 'hello':
        from archive_workspace import ensure_workspace
        ensure_workspace(install_directory())
        workspace = install_directory() / 'projekt'
        workspace.mkdir(exist_ok=True)
        recent = optional(recent_file(), {}).get('project')
        return {'hasEnvironment': (STORE / 'environment.json').is_file(),
                'interface': optional(STORE / 'interface.json', {}),
                'workspace': str(workspace.resolve()),
                'recent': recent if recent and Path(recent).is_dir() else None}
    if command == 'preferences':
        save(STORE / 'interface.json', request['value'])
        return None
    if command == 'detect':
        return detect_installs(request['settings'])
    root = Path(request['root']).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    if command in ('open', 'snapshot'):
        result = project(root)
        result['details'] = details(root, result['settings'])
        if command == 'open':
            save(recent_file(), {'project': str(root)})
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
            @($rows | Select-Object ProcessId,@{{Name='CreationDate';Expression={{$_.CreationDate.ToUniversalTime().ToString('o')}}}},ExecutablePath,CommandLine) | ConvertTo-Json -Compress
        """)
        if not raw:
            return 'offline'
        found = json.loads(raw)
        for row in found if isinstance(found, list) else [found]:
            if row.get('ExecutablePath') and Path(row['ExecutablePath']) == executable and row.get('CommandLine'):
                for argument in windows_args(row['CommandLine']):
                    if argument.lower().startswith('-profiles=') and executable.parent / argument[10:] == pipeline.profiles:
                        readiness = optional(pipeline.state / 'server-readiness.json', {})
                        if readiness.get('pid') != row.get('ProcessId') or readiness.get('created') != row.get('CreationDate') or not readiness.get('ready'):
                            return 'unknown'
                        for path in pipeline.profiles.iterdir():
                            if path.is_file() and pipeline.is_game_log(path):
                                with path.open('rb') as stream:
                                    stream.seek(min(path.stat().st_size, readiness.get('offsets', {}).get(str(path), 0)))
                                    text = stream.read().decode('utf-8', errors='replace')
                                if re.search(r'(?i)Virtual Machine Exception|(?:storage|persistence|save).*(?:corrupt|damaged|failed)', text):
                                    return 'unknown'
                        return 'ready'
        return 'unknown'
    if command == 'details':
        return details(root, request['settings'])
    if command in ('stopServer', 'forceStopServer'):
        with operation_lock():
            pipeline = TestPipeline(root, request['settings'], print, lambda *args: None, {})
            server, client, *_ = pipeline.game_settings()
            if command == 'stopServer':
                pipeline.stop(server, client)
            else:
                session = optional(pipeline.state / 'session.json', {})
                if not session.get('servers'):
                    raise ValueError(tr('Немає збереженої сесії сервера цієї Studio.',
                                        'No recorded server session for this Studio.'))
                for record in session.get('servers', []):
                    pid = int(record['pid'])
                    created = str(record['created']).replace("'", "''")
                    pipeline.ps(f"""$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'
                        if ($p -and $p.CreationDate.ToUniversalTime().ToString('o') -eq '{created}') {{
                            Stop-Process -Id {pid} -Force -ErrorAction Stop
                            if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{
                                Wait-Process -Id {pid} -Timeout 20 -ErrorAction Stop
                            }}
                        }}""")
            return None
    if command in ('steamOwner', 'workshopCheck'):
        from workshop import active_user, item_details
        with operation_lock():
            pipeline = TestPipeline(root, request['settings'], print, lambda *args: None, {})
            owner = active_user(pipeline.client)
            if command == 'steamOwner':
                return owner
            item = workshop_item(pipeline.s['workshop'])
            info = item_details(item)
            if info is None:
                return dict(id=str(item), owner=owner, status='unknown')
            return dict(id=str(item), owner=owner, title=info['title'],
                        status='owner' if info['dayz'] and info['owner'] == owner else 'mismatch')
    if command == 'generateKeys':
        return generate_keys(root, request['settings'], request['name'])
    if command == 'save':
        with operation_lock():
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
    if len(sys.argv) > 1:
        return terminal(sys.argv[1:])
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


def cli_status(selected, result):
    empty = tr('ще немає', 'none yet')
    output = [selected['root']]
    if not selected['configured']:
        output.append(tr('Збережи налаштування у GUI або через config.', 'Save project settings in the GUI or with config.'))
    for check in result['checks']:
        state_name = tr('Готово', 'Ready') if check['ok'] else tr('Виправ', 'Fix')
        output.append(f"[{state_name}] {check['key']} · {check['detail']}")
    for label, record in (
        (tr('Локальна збірка', 'Local build'), result['localBuild']),
        ('Workshop', result['published']),
        (tr('Віддалена збірка', 'Remote build'), result['remoteBuild']),
        (tr('Пакет для F6', 'Package for F6'), result['remoteChoice']),
    ):
        changed = tr(' · є нові зміни', ' · newer source changes') if record.get('changed') else ''
        output.append(f"{label} · {record.get('buildId') or empty}{changed}")
    if result['operations']:
        output.append(tr('Остання операція', 'Latest operation') + ' · ' + cli_history_line(result['operations'][0]))
    return '\n'.join(output)


def cli_history_line(report):
    action = 'update' if report['action'] == 'test' else report['action']
    result = tr('завершено', 'complete') if report['status'] == 'complete' else tr('помилка', 'failed')
    return ' · '.join(filter(None, (report['date'], action, result, report.get('buildId'))))


def cli_report(report):
    parts = [tr('Готово', 'Complete') if report['status'] == 'complete' else tr('Помилка', 'Failed')]
    if report.get('buildId'):
        parts.append(report['buildId'])
    for key, label in (
        ('built', tr('пакет перевірено', 'package verified')),
        ('installed', tr('локальні копії встановлено', 'local copies installed')),
        ('serverReady', tr('локальний сервер готовий', 'local server ready')),
        ('clientLaunched', tr('DayZ відкрито', 'DayZ launched')),
    ):
        if report.get(key):
            parts.append(label)
    if report.get('workshopStatus') == 'confirmed':
        parts.append(tr('Steam підтвердив публікацію', 'Steam confirmed publication'))
    elif report.get('workshopStatus') in ('pending', 'uncertain'):
        parts.append(tr('результат Steam невідомий', 'Steam result unknown'))
    remote = report.get('remote', {})
    if remote.get('status') == 'ready':
        parts.append(tr('віддалений сервер готовий', 'remote server ready'))
    elif remote.get('status') == 'uploaded':
        parts.append(tr('файли завантажено · потрібне ручне встановлення й перезапуск',
                        'files uploaded · manual installation and restart required'))
    elif report['action'] == 'remote-check' and report['status'] == 'complete':
        parts.append(tr('віддалене підключення перевірено', 'remote connection verified'))
    if report.get('olderBuild'):
        parts.append(tr('вибрано попередню збірку · нові зміни потребують update',
                        'previous build selected · new changes require update'))
    parts.append(f"{report['seconds']}s")
    lines_out = [' · '.join(parts)]
    if remote.get('staging'):
        lines_out.append(tr('Проміжна папка', 'Staging directory') + ' · ' + remote['staging'])
    if report.get('clientError'):
        lines_out.append(tr('Не вдалося відкрити DayZ', 'Could not launch DayZ') + ' · ' + report['clientError'])
    if report.get('error'):
        lines_out.append(report['error'])
    return '\n'.join(lines_out)


def cli_config(root, args):
    with operation_lock():
        settings = project(root)['settings']
        if args.get:
            if args.get not in settings:
                raise ValueError(tr('Невідомий ключ налаштувань', 'Unknown setting') + ' · ' + args.get)
            return {args.get: settings[args.get]}
        if not args.set:
            return dict(keys=sorted(settings))
        changed = {}
        for key, raw in args.set:
            if key not in settings:
                raise ValueError(tr('Невідомий ключ налаштувань', 'Unknown setting') + ' · ' + key)
            if isinstance(settings[key], bool):
                if raw.lower() not in ('true', 'false'):
                    raise ValueError(f'{key} · true / false')
                changed[key] = raw.lower() == 'true'
            else:
                changed[key] = raw
        settings.update(changed)
        validate_project(root, settings)
        save_settings(root, settings)
        return dict(saved=list(changed))


def terminal(arguments):
    locale_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    locale_parser.add_argument('--language', choices=('en', 'uk'))
    language, _ = locale_parser.parse_known_args(arguments)
    set_language(language.language or optional(STORE / 'interface.json', {}).get('language', 'en'))
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    cli = '.\\dayz-backend.exe'
    examples = tr('Приклади', 'Examples') + '\n' + '\n'.join((
        f'  {cli} --project "D:\\Mods\\My Mod" update',
        f'  {cli} --project "D:\\Mods\\My Mod" remote --build-id 20261115-112233-aaaabbbb',
        f'  {cli} --recent --json status',
        f'  {cli} --recent config --set publish_workshop true',
    ))
    parser = argparse.ArgumentParser(
        prog='dayz-backend.exe', allow_abbrev=False,
        description=tr('Збірка й розгортання DayZ із тими самими налаштуваннями, що в GUI.',
                       'Build and deploy DayZ mods with the same settings as the desktop app.'),
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=examples)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--project', type=Path, help=tr('Папка джерел (типово поточна папка)',
                                                       'Source directory (defaults to current directory)'))
    scope.add_argument('--recent', action='store_true', help=tr('Останній проєкт, відкритий у GUI',
                                                               'Last project opened in the GUI'))
    parser.add_argument('--language', choices=('en', 'uk'), help=tr('Мова виводу', 'Output language'))
    parser.add_argument('--json', action='store_true', help=tr('JSON по одному запису на рядок', 'Newline-delimited JSON'))
    parser.add_argument('--verbose', action='store_true', help=tr('Показувати повний журнал під час дії',
                                                                 'Stream the full operation log'))
    commands = parser.add_subparsers(dest='action', required=True, metavar='COMMAND')
    textures = commands.add_parser('textures', allow_abbrev=False,
                                   help=tr('Конвертувати PNG/JPG/TGA у PAA та PAA у PNG',
                                           'Convert PNG/JPG/TGA to PAA and PAA to PNG'))
    textures.add_argument('files', nargs='*', help=tr('Від 1 до 100 файлів', '1 to 100 files'))
    textures.add_argument('--output', help=tr('Наявна папка результатів', 'Existing output directory'))
    textures.add_argument('--tools', help=tr('Папка DayZ Tools', 'DayZ Tools directory'))
    textures.add_argument('--show-output', action='store_true',
                          help=tr('Показати папку результатів', 'Show the output directory'))
    textures.add_argument('--open', action='store_true',
                          help=tr('Відкрити папку результатів', 'Open the output directory'))
    for action, description in ACTIONS.items():
        options = dict(help=tr(*description), description=tr(*description), allow_abbrev=False)
        if action == 'update':
            options['aliases'] = ['test']
        command = commands.add_parser(action, **options)
        if action == 'remote':
            command.add_argument('--build-id', help=tr('Вимагати саме цей ID збірки', 'Require this exact build ID'))
        elif action == 'config':
            mode = command.add_mutually_exclusive_group()
            mode.add_argument('--get', metavar='KEY')
            mode.add_argument('--set', nargs=2, action='append', metavar=('KEY', 'VALUE'))
        elif action == 'keys':
            command.add_argument('name')
    args = parser.parse_args(arguments)
    action = args.action
    last_progress = None

    def emit(event, **data):
        nonlocal last_progress
        if args.json:
            print(json.dumps(dict(event=event, **data)), flush=True)
        elif event == 'log' and args.verbose:
            print(data['text'], flush=True)
        elif event == 'progress':
            label = data['label']
            label = tr(*label) if isinstance(label, (tuple, list)) else label
            if label != last_progress:
                print(f'→ {label}', flush=True)
                last_progress = label

    root = None
    try:
        if action == 'textures':
            if args.show_output and args.files:
                raise ValueError(tr('--show-output використовуй без файлів.', 'Use --show-output without files.'))
            if args.show_output:
                result = {'folder': str(output_folder('textures', args.output)), 'files': [], 'errors': []}
            else:
                if not 1 <= len(args.files) <= 100:
                    raise ValueError(tr('Вибери від 1 до 100 файлів.', 'Choose 1 to 100 files.'))
                settings = optional(STORE / 'environment.json', {})
                if args.project or args.recent:
                    recent = optional(recent_file(), {}).get('project') if args.recent else None
                    if args.recent and not recent:
                        raise ValueError(tr('Немає останнього проєкту.', 'No recent project.'))
                    root = (args.project or Path(recent)).resolve()
                    settings = project(root)['settings']
                if args.tools:
                    settings = {**settings, 'tools': args.tools}
                result = convert_textures(args.files, settings,
                                          lambda stage, text: emit('progress', stage=stage,
                                                                   label=f'{stage}/{len(args.files)} · {text}'),
                                          args.output)
            if args.json:
                emit('result', value=result)
            else:
                print(result['folder'])
                for converted in result['files']:
                    print(f"{converted['source']} → {converted['output']}")
                for failure in result['errors']:
                    print(f"{failure['source']} · {failure['error']}", file=sys.stderr)
            if args.open:
                os.startfile(result['folder'])
            return 1 if result['errors'] else 0
        recent = optional(recent_file(), {}).get('project') if args.recent else None
        if args.recent and not recent:
            raise ValueError(tr('Немає останнього проєкту. Вкажи --project PATH.',
                                'No recent project. Specify --project PATH.'))
        root = (args.project or (Path(recent) if recent else Path.cwd())).resolve()
        if not root.is_dir():
            raise ValueError(tr('Папку проєкту не знайдено', 'Project directory not found') + ' · ' + str(root))
        if action in ('status', 'history', 'logs', 'config', 'steam-owner', 'workshop-check', 'keys'):
            if action == 'status':
                selected = project(root)
                result = details(root, selected['settings'])
                output = cli_status(selected, result)
            elif action == 'history':
                result = recent_operations(state(root))
                output = '\n'.join(map(cli_history_line, result)) or tr('Операцій ще немає.', 'No operations yet.')
            elif action == 'logs':
                files = sorted((state(root) / 'logs').glob('*.log'), reverse=True)
                if not files:
                    raise ValueError(tr('Журналів ще немає.', 'No operation logs yet.'))
                result = dispatch(dict(command='readLog', root=str(root), path=str(files[0])), emit)
                output = result.rstrip()
            elif action == 'config':
                result = cli_config(root, args)
                if args.set:
                    output = tr('Збережено', 'Saved') + ' · ' + ', '.join(result['saved'])
                elif args.get:
                    output = str(result[args.get])
                else:
                    output = '\n'.join(result['keys'])
            else:
                settings = project(root)['settings']
                if action == 'keys':
                    result = generate_keys(root, settings, args.name)
                    output = tr('Ключ створено. Вибери пару в GUI або через config.',
                                'Key generated. Select the pair in the GUI or with config.') + '\n' + result['public']
                else:
                    result = dispatch(dict(command={'steam-owner': 'steamOwner', 'workshop-check': 'workshopCheck'}[action],
                                           root=str(root), settings=settings), emit)
                    output = result if isinstance(result, str) else ' · '.join(
                        str(result[key]) for key in ('id', 'title', 'owner', 'status') if result.get(key))
            if args.json:
                emit('result', value=result)
            else:
                print(output)
                if action == 'status':
                    choice = result['remoteChoice'].get('buildId')
                    print(tr('Оновити локально', 'Update locally') + ' · ' + shell_command(root, 'update'))
                    if choice and selected['settings'].get('remote_host'):
                        print(tr('Розгорнути вибраний пакет', 'Deploy selected package') + ' · ' + shell_command(root, 'remote', choice))
            return 0
        operation = 'test' if action in ('test', 'update') else action
        report = operate(root, dict(action=operation, buildId=getattr(args, 'build_id', None)), emit, report_only=True)
        if args.json:
            emit('result', value=report)
        else:
            failed = report['status'] != 'complete'
            stream = sys.stderr if failed else sys.stdout
            print(cli_report(report), file=stream)
            if failed:
                print(tr('Журнал', 'Log') + ' · ' + report['log'], file=stream)
            next_action = report['next']
            print(tr('Далі', 'Next') + ' · ' + shell_command(root, next_action['action'], next_action.get('buildId')),
                  file=stream)
        return 0 if report['status'] == 'complete' else 1
    except Exception as error:
        if args.json:
            emit('error', text=str(error))
        else:
            print(str(error), file=sys.stderr)
            if root and root.is_dir() and action not in ('status', 'textures'):
                print(tr('Далі', 'Next') + ' · ' + shell_command(root, 'status'), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

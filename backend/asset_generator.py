"""Local asynchronous Blender jobs, parameter validation and atomic delivery."""
import base64
import atexit
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

from export_folders import output_folder
from locale_studio import tr
from model_export import blender_path, read_glb
from pipeline import linked

TEMPLATES = [
    {'id': 'bottle', 'uk': 'Лабораторна пляшечка', 'en': 'Laboratory Bottle',
     'dimensions': [48, 110, 48], 'material': 'amber', 'capDimensions': [24, 14],
     'bodyColor': '#8a4319', 'materials': [
         {'id': 'amber', 'uk': 'Янтарне скло', 'en': 'Amber glass'},
         {'id': 'clear', 'uk': 'Прозоре скло', 'en': 'Clear glass'},
         {'id': 'opaque', 'uk': 'Непрозоре скло', 'en': 'Opaque glass'}]},
    {'id': 'canister', 'uk': 'Хімічна каністра', 'en': 'Chemical Canister',
     'dimensions': [180, 270, 100], 'material': 'plastic', 'capDimensions': [40, 24],
     'bodyColor': '#547b46', 'materials': [{'id': 'plastic', 'uk': 'Пластик', 'en': 'Plastic'}]},
]
jobs = {}
lock = threading.Lock()


def shutdown():
    with lock:
        for job in jobs.values():
            job['cancel'].set()
            process = job.get('process')
            if process is not None and process.poll() is None:
                process.terminate()


atexit.register(shutdown)


def executable(value=None):
    path = Path(value).resolve() if value else blender_path()
    if not path.is_file() or path.name.lower() != 'blender.exe':
        raise ValueError(tr('Вибери blender.exe.', 'Choose blender.exe.'))
    return path


def reference(value):
    path = Path(value).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in ('.png', '.jpg', '.jpeg') or path.stat().st_size > 16 * 1024**2:
        raise ValueError(tr('Вибери PNG або JPG до 16 МБ.', 'Choose a PNG or JPG up to 16 MB.'))
    mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
    return {'path': str(path), 'data': f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')}


def parameters(request):
    values = {key: request.get(key) for key in ('name', 'template', 'width', 'height', 'depth',
               'capWidth', 'capHeight', 'material', 'bodyColor', 'capColor', 'resolution')}
    values['references'] = request.get('references', [])
    values['referenceConfirmed'] = bool(request.get('referenceConfirmed'))
    if values.get('template') not in {item['id'] for item in TEMPLATES}:
        raise ValueError(tr('Вибери доступний шаблон.', 'Choose an available template.'))
    name = str(values.get('name', '')).strip()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,59}', name) or name.upper() in {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{number}' for prefix in ('COM', 'LPT') for number in range(1, 10)}:
        raise ValueError(tr('Назва: латинські літери, цифри, _ або -, до 60 символів.',
                            'Name: Latin letters, digits, _ or -, up to 60 characters.'))
    values['name'] = name
    for key in ('width', 'height', 'depth', 'capWidth', 'capHeight'):
        try:
            number = float(values[key])
        except (KeyError, TypeError, ValueError):
            raise ValueError(tr('Вкажи розміри у міліметрах.', 'Enter dimensions in millimetres.')) from None
        if not math.isfinite(number) or not 1 <= number <= 3000:
            raise ValueError(tr('Розміри мають бути від 1 до 3000 мм.', 'Dimensions must be between 1 and 3000 mm.'))
        values[key] = number
    if values['capWidth'] >= min(values['width'], values['depth']) or values['capHeight'] >= values['height'] * .3:
        raise ValueError(tr('Кришка має бути вужчою за корпус і нижчою за 30% висоти.',
                            'The cap must be narrower than the body and shorter than 30% of the total height.'))
    if max(values['width'], values['depth']) / min(values['width'], values['depth']) > 4 or values['height'] < values['capHeight'] * 4:
        raise ValueError(tr('Пропорції не підходять до шаблону.', 'These proportions do not fit the template.'))
    if values.get('resolution') not in (512, 1024, 2048):
        raise ValueError(tr('Роздільність: 512, 1024 або 2048.', 'Resolution must be 512, 1024 or 2048.'))
    template = next(item for item in TEMPLATES if item['id'] == values['template'])
    if values.get('material') not in {item['id'] for item in template['materials']}:
        raise ValueError(tr('Матеріал не підходить до шаблону.', 'The material does not fit the template.'))
    for key in ('bodyColor', 'capColor'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(values.get(key, ''))):
            raise ValueError(tr('Вибери колір корпусу та кришки.', 'Choose body and cap colours.'))
    references = values.get('references', [])
    if not isinstance(references, list) or len(references) > 5:
        raise ValueError(tr('Додай до п’яти ракурсів.', 'Add up to five reference views.'))
    if references and not values.get('referenceConfirmed'):
        raise ValueError(tr('Перевір відповідність фото шаблону та вручну задай пропорції й кольори.',
                            'Check that the photo matches the template and set proportions and colours manually.'))
    values['references'] = [reference(path)['path'] for path in references]
    return values


def snapshot(identifier):
    with lock:
        job = jobs[identifier]
        return {key: job[key] for key in ('id', 'state', 'stage', 'result', 'error')}


def cancel(identifier):
    with lock:
        job = jobs[identifier]
        if job['state'] == 'running':
            job['cancel'].set()
    return snapshot(identifier)


def check_cancel(event):
    if event.is_set():
        raise InterruptedError('cancelled')


def start(request):
    values = parameters(request)
    blender = executable(request.get('blender'))
    root = output_folder('generator', request.get('output'))
    destination = root / values['name']
    if destination.exists() and not request.get('overwrite'):
        raise FileExistsError(tr('Папка предмета вже існує. Підтверди заміну файлів.',
                                'The item directory already exists. Confirm replacement.'))
    identifier = uuid.uuid4().hex
    with lock:
        if any(job['state'] == 'running' for job in jobs.values()):
            raise RuntimeError(tr('Генерація вже виконується.', 'A generation job is already running.'))
        for key in list(jobs):
            if len(jobs) < 20:
                break
            del jobs[key]
        jobs[identifier] = dict(id=identifier, state='running', stage=0, result=None, error='',
                                cancel=threading.Event(), process=None)
    threading.Thread(target=generate, args=(identifier, values, blender, destination, bool(request.get('overwrite'))),
                     daemon=True).start()
    return snapshot(identifier)


def target(request):
    values = parameters(request)
    folder = output_folder('generator', request.get('output')) / values['name']
    return dict(folder=str(folder), exists=folder.exists())


def generate(identifier, values, blender, destination, overwrite):
    job = jobs[identifier]
    event = job['cancel']
    try:
        # Staging on the destination volume keeps the final rename atomic.
        with tempfile.TemporaryDirectory(prefix='.studio-generator-', dir=destination.parent) as directory:
            stage = Path(directory)
            output = stage / values['name']
            output.mkdir()
            config = stage / 'request.json'
            config.write_text(json.dumps(dict(values, output=str(output))), encoding='utf-8')
            progress = stage / 'progress'
            diagnostic = stage / 'blender.log'
            with diagnostic.open('wb') as log:
                process = subprocess.Popen(
                    [str(blender), '--background', '-t', '2', '--python-exit-code', '1', '--python',
                     str(Path(__file__).with_name('generator_blender') / 'run.py'), '--', str(config)],
                    stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                with lock:
                    job['process'] = process
                deadline = time.monotonic() + 600
                try:
                    while process.poll() is None:
                        check_cancel(event)
                        if time.monotonic() > deadline:
                            raise TimeoutError('Blender timeout (600 s)')
                        if progress.is_file():
                            lines = progress.read_text(encoding='ascii').splitlines()
                            if lines and lines[-1].isdigit():
                                with lock:
                                    job['stage'] = min(int(lines[-1]), 5)
                        time.sleep(.15)
                    check_cancel(event)
                    if process.returncode:
                        raise RuntimeError(diagnostic.read_text(encoding='utf-8', errors='replace')[-4000:] or 'Blender export failed')
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            report = json.loads((output / 'validation.json').read_text(encoding='utf-8'))
            if not report.get('valid'):
                raise ValueError('Model validation failed')
            for relative in (f'{values["name"]}.blend', f'{values["name"]}.glb', f'{values["name"]}.obj',
                             f'{values["name"]}.mtl', f'textures/{values["name"]}_co.png', 'preview.png'):
                if not (output / relative).is_file() or not (output / relative).stat().st_size:
                    raise ValueError(f'Missing output: {relative}')
            _, glb = read_glb(output / f'{values["name"]}.glb')
            result = dict(folder=str(destination), name=values['name'], validation=report,
                          preview=base64.b64encode(glb).decode('ascii'),
                          texture='data:image/png;base64,' + base64.b64encode(
                              (output / 'textures' / f'{values["name"]}_co.png').read_bytes()).decode('ascii'))
            # Cancellation and commit share the lock, so a cancelled job cannot publish files.
            with lock:
                check_cancel(event)
                backup = stage / 'previous'
                if destination.exists():
                    if not overwrite or linked(destination):
                        raise FileExistsError(str(destination))
                    destination.rename(backup)
                try:
                    output.rename(destination)
                except BaseException:
                    if backup.exists():
                        backup.rename(destination)
                    raise
                job.update(state='done', stage=6, result=result)
    except InterruptedError:
        with lock:
            job.update(state='cancelled', error='')
    except Exception as error:
        with lock:
            job.update(state='error', error=str(error))
    finally:
        with lock:
            job['process'] = None


def reveal(identifier, blender=False):
    with lock:
        job = jobs[identifier]
        if job['state'] != 'done':
            raise ValueError('Generation is not complete')
        result = job['result']
    folder = Path(result['folder'])
    if blender:
        config = json.loads((folder / 'validation.json').read_text(encoding='utf-8'))
        binary = executable(config['blender'])
        subprocess.Popen([str(binary), str(folder / (result['name'] + '.blend'))])
    else:
        os.startfile(folder)

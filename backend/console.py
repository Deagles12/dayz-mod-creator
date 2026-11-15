"""PowerShell commands and shared descriptions for the desktop and terminal."""
import sys
from pathlib import Path


ACTIONS = {
    'update': ('Оновити локально й, за налаштуванням, у Workshop (F5)',
               'Update locally and optionally publish to Workshop (F5)'),
    'remote': ('Встановити вибрану перевірену збірку (F6)',
               'Deploy the selected verified build (F6)'),
    'status': ('Показати готовність, вибраний пакет і останній результат',
               'Show readiness, the selected package and the latest result'),
    'history': ('Показати останні операції GUI та CLI', 'Show recent GUI and CLI operations'),
    'logs': ('Показати журнал останньої операції', 'Show the latest operation log'),
    'config': ('Переглянути або змінити спільні з GUI налаштування',
               'Read or change the same project settings used by the GUI'),
    'steam-owner': ('Визначити SteamID64 активного акаунта', 'Find the active account’s SteamID64'),
    'workshop-check': ('Перевірити вибраний item', 'Check the selected Workshop item'),
    'keys': ('Створити нову пару ключів підпису', 'Generate a new signing key pair'),
    'build': ('Лише зібрати й перевірити пакет', 'Build and verify a package'),
    'deploy': ('Встановити останній зібраний пакет локально', 'Install the last built package locally'),
    'launch': ('Запустити локально встановлений пакет', 'Start the locally installed package'),
    'retry': ('Продовжити перерване локальне оновлення', 'Resume an incomplete local update'),
    'publish': ('Опублікувати перевірений пакет поточних джерел',
                'Publish the verified package for the current sources'),
    'create-workshop': ('Створити або завершити першу публікацію',
                        'Create or finish the first Workshop publication'),
    'retry-publish': ('Повторити публікацію того самого пакета', 'Retry publishing the same package'),
    'rollback': ('Відновити попереднє локальне встановлення', 'Restore the previous local installation'),
    'remote-check': ('Перевірити віддалене підключення', 'Check the configured remote connection'),
}


def quote(value):
    # PowerShell treats typographic single quotes as quotation marks too.
    escaped = str(value)
    for mark in ("'", '‘', '’', '‚', '‛'):
        escaped = escaped.replace(mark, mark * 2)
    return "'" + escaped + "'"


def command(root, action, build_id=None):
    if action == 'test':
        action = 'update'
    if action not in ACTIONS:
        raise ValueError(action)
    executable = '& ' + quote(sys.executable)
    if not getattr(sys, 'frozen', False):
        executable += ' ' + quote(Path(__file__).with_name('sidecar.py').resolve())
    result = f'{executable} --project {quote(root)} {action}'
    if action == 'remote' and build_id:
        result += ' --build-id ' + quote(build_id)
    return result

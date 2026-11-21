"""Local PBO build and deployment without the game session workflow."""
from pathlib import Path

from locale_studio import tr
from pipeline import Pipeline, digest, linked, require, tree


class QuickPipeline(Pipeline):
    def __init__(self, root, settings, log=print, progress=lambda *args: None, *, rollback=False):
        if rollback:
            settings = {**settings, 'tools': settings.get('tools') or '.',
                        'copy_server': bool(settings.get('server', '').strip()),
                        'copy_client': bool(settings.get('client', '').strip())}
        for key, message in (
            ('tools', ('Не знайдено AddonBuilder. Вкажи папку DayZ Tools.',
                       'AddonBuilder not found. Choose the DayZ Tools folder.')),
            ('server', ('Вкажи папку локального сервера.', 'Choose the local server folder.')),
            ('client', ('Вкажи папку встановленого DayZ.', 'Choose the installed DayZ folder.')),
        ):
            if (key == 'tools' or settings.get(f'copy_{key}', True)) and not settings.get(key, '').strip():
                raise ValueError(tr(*message))
        super().__init__(root, settings, log, progress, quick=True)
        mounts = [path.resolve() for path in self.targets]
        if len(set(mounts)) != len(mounts) or any(
                parent in child.parents for child in mounts for parent in mounts):
            raise ValueError(tr('Папки встановлення перетинаються.', 'Deployment folders overlap.'))

    def check(self):
        list(self.addon_specs())
        self.check_tools()
        for path, message in (
            (self.server, ('Папка сервера недоступна: {}', 'Server folder is unavailable: {}')),
            (self.client, ('Папка клієнта недоступна: {}', 'Client folder is unavailable: {}')),
        ):
            if path and not path.is_dir():
                raise FileNotFoundError(tr(*message).format(path))
        for target in self.targets:
            path = target.resolve()
            if (path.is_relative_to(self.root) or self.root.is_relative_to(path)
                    or any(part.casefold() in {'workshop', '!workshop'} for part in (*target.parts, *path.parts))):
                raise ValueError(tr('Вибери папку встановлення поза проєктом і Steam Workshop: {}',
                                    'Choose a deployment folder outside the project and Steam Workshop: {}').format(target))
            if (target.exists() or target.is_symlink()) and (linked(target) or not target.is_dir()):
                raise ValueError(tr('Папка мода недоступна: {}', 'The mod folder is unavailable: {}').format(target))
        if self.server:
            keys = self.server / 'Keys'
            if keys.resolve().is_relative_to(self.root) or self.root.is_relative_to(keys.resolve()):
                raise ValueError(tr('Папка Keys перетинається з вихідним проєктом.',
                                    'The Keys folder overlaps the source project.'))

    def install_local(self, manifest):
        if not self.targets:
            return []

        keys = [self.server / filename for filename in manifest['files']
                if self.server and filename.startswith('Keys/') and filename.lower().endswith('.bikey')]
        seen = set()

        def before_copy(target):
            server = self.server and (target == self.server / self.mod or target.parent == self.server / 'Keys')
            if server and 3 not in seen:
                self.progress(3, ('Встановлення на сервер', 'Installing on the server'))
                seen.add(3)
            if target == self.client_target and 4 not in seen:
                self.progress(4, ('Встановлення на клієнт', 'Installing on the client'))
                seen.add(4)

        def verify():
            for target in self.targets:
                if tree(target) != manifest['files']:
                    raise RuntimeError(tr('Файли після встановлення відрізняються: {}',
                                          'Installed files differ from the package: {}').format(target))
            for key in keys:
                if digest(require(key)) != manifest['files']['Keys/' + key.name]:
                    raise RuntimeError(tr('Серверний ключ відрізняється: {}', 'Server key differs: {}').format(key))

        try:
            self.install(manifest, before_copy=before_copy, verify=verify, mode='quick')
        except OSError as error:
            self.log(error)
            if getattr(error, 'winerror', None) in (32, 33):
                raise RuntimeError(tr('Файл використовується іншим процесом: {}',
                                      'A file is in use by another process: {}').format(error.filename or '')) from error
            if isinstance(error, PermissionError):
                raise RuntimeError(tr('Немає дозволу змінити файли встановлення: {}',
                                      'Permission denied while updating installed files: {}').format(error.filename or '')) from error
            raise RuntimeError(tr('Не вдалося скопіювати файли мода: {}',
                                  'Could not copy the mod files: {}').format(error.filename or error)) from error
        return [str(path) for path in (*self.targets, *keys)]

    @property
    def client_target(self):
        return self.client / self.mod if self.client else None

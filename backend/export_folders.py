"""Output folders explicitly selected in the desktop app."""
from pathlib import Path
import sys

from locale_studio import tr

selected = {}


def default_folder(kind):
    if kind not in ('models', 'textures'):
        raise ValueError('Invalid export kind')
    install = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    return (install / 'output' / kind).resolve()


def output_folder(kind, path=None):
    if kind not in ('models', 'textures'):
        raise ValueError('Invalid export kind')
    if path:
        folder = Path(path).resolve(strict=True)
        if not folder.is_dir():
            raise NotADirectoryError(tr('Вибери папку для експорту.', 'Choose an export folder.'))
        selected.setdefault(kind, set()).add(folder)
        return folder
    root = default_folder(kind)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OSError(tr('Не вдалося створити {}. Вибери іншу папку.', 'Cannot create {}. Choose another folder.').format(root)) from error
    return root.resolve()


def can_reveal(kind, path):
    allowed = {default_folder(kind), *selected.get(kind, ())}
    return path.is_dir() and any(path.is_relative_to(root) for root in allowed)

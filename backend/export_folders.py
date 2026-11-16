"""Output folders explicitly selected in the desktop app."""
from pathlib import Path

from locale_studio import tr
from pipeline import STORE

selected = {}


def output_folder(kind, path=None):
    if kind not in ('models', 'textures'):
        raise ValueError('Invalid export kind')
    if path:
        folder = Path(path).resolve(strict=True)
        if not folder.is_dir():
            raise NotADirectoryError(tr('Вибери папку для експорту.', 'Choose an export folder.'))
        selected.setdefault(kind, set()).add(folder)
        return folder
    root = STORE / kind
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def can_reveal(kind, path):
    allowed = {output_folder(kind), *selected.get(kind, ())}
    return path.is_dir() and any(path.is_relative_to(root) for root in allowed)

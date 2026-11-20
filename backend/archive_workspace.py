"""Install bundled archive tools beside the portable Studio executable."""
import hashlib
from pathlib import Path
import shutil
import sys

from export_folders import install_directory
from pipeline import load, save

CATEGORIES = ('Painted Metal', 'Rusted Steel', 'Weathered Wood', 'Dirty Fabric', 'Tin Metal', 'Rubber')


def ensure_workspace(install=None):
    root = (install or install_directory()) / '3D-Generator'
    for relative in ('incoming', 'ready', *(f'materials/{kind}' for kind in CATEGORIES)):
        (root / relative).mkdir(parents=True, exist_ok=True)
    if getattr(sys, 'frozen', False):
        source = Path(__file__).with_name('archive_tools')
    else:
        source = Path(__file__).resolve().parents[1] / 'tools/3D-Generator'
    manifest_path = root / '.studio-tools.json'
    previous = load(manifest_path).get('files', {}) if manifest_path.is_file() else {}
    installed = dict(previous)
    resources = [(path, path.relative_to(source)) for path in source.rglob('*')
                 if path.is_file() and path.suffix in ('.py', '.ps1', '.md', '.json') and '__pycache__' not in path.parts]
    for path, relative in resources:
        destination = root / relative
        new_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        old_hash = hashlib.sha256(destination.read_bytes()).hexdigest() if destination.is_file() else None
        key = relative.as_posix()
        if old_hash == new_hash:
            installed[key] = new_hash
            continue
        if old_hash is not None and previous.get(key) != old_hash:
            # A pre-existing or edited local script belongs to the user.
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if old_hash:
            backup = root / '.studio-backups' / old_hash[:12] / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(destination, backup)
        temporary = destination.with_name(destination.name + '.studio.tmp')
        shutil.copyfile(path, temporary)
        temporary.replace(destination)
        installed[key] = new_hash
    save(manifest_path, dict(version='3.0', files=installed))
    return root

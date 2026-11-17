from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
target = 'x86_64-pc-windows-msvc'
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--console',
    '--name', f'dayz-backend-{target}', '--workpath', str(root / '.build/pyinstaller'),
    '--specpath', str(root / '.build'), '--distpath', str(root / 'src-tauri/binaries'),
    '--add-data', str(root / 'backend/model_blender.py') + ':.',
    *(argument for path in sorted((root / 'backend/generator_blender').glob('*.py'))
      for argument in ('--add-data', str(path) + ':generator_blender')),
    str(root / 'backend/sidecar.py')
], cwd=root, check=True)

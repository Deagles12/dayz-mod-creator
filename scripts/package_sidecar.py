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
    *(argument for path in sorted((root / 'tools/3D-Generator').rglob('*'))
      if path.is_file() and path.suffix in ('.py', '.ps1', '.md', '.json') and '__pycache__' not in path.parts
      for argument in ('--add-data', str(path) + ':archive_tools/' + path.relative_to(root / 'tools/3D-Generator').parent.as_posix())),
    str(root / 'backend/sidecar.py')
], cwd=root, check=True)

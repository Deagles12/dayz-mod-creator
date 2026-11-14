from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
target = 'x86_64-pc-windows-msvc'
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--console',
    '--name', f'dayz-backend-{target}', '--workpath', str(root / '.build/pyinstaller'),
    '--specpath', str(root / '.build'), '--distpath', str(root / 'src-tauri/binaries'),
    str(root / 'backend/sidecar.py')
], cwd=root, check=True)

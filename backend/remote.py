"""Linux DayZ hosting adapter using Windows OpenSSH, SFTP and systemd."""
import re
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from pipeline import HIDDEN


def select_build(state, settings, read, item=None):
    if settings.get('publish_workshop'):
        try:
            record = read(state / 'workshop-items' / f'{item}.json')
        except FileNotFoundError:
            record = read(state / 'workshop-confirmed.json')
        if record['status'] != 'confirmed' or record['item'] != str(item):
            raise ValueError('Run F5 to confirm a build for the selected Workshop item.')
    else:
        record = read(state / 'local-ready.json')
    build_id = record.get('buildId', '')
    if not isinstance(build_id, str) or not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{8}', build_id):
        raise ValueError('Run F5 to create a verified build.')
    manifest = read(state / 'builds' / build_id / 'manifest.json')
    if manifest.get('id') != build_id:
        raise ValueError('Build ID does not match its manifest.')
    return manifest


class OpenSSH:
    def __init__(self, settings):
        host = str(settings.get('remote_host', ''))
        user = str(settings.get('remote_user', ''))
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]*', user):
            raise ValueError('Enter an SSH hostname and username.')
        self.port = int(settings.get('remote_port') or 22)
        if not 1 <= self.port <= 65535:
            raise ValueError('SSH port must be 1–65535.')
        self.destination = f'{user}@{host}'
        self.options = ['-oBatchMode=yes', '-oStrictHostKeyChecking=yes', '-oConnectTimeout=10',
                        '-oServerAliveInterval=10', '-oServerAliveCountMax=3']

    def run(self, args, payload, timeout):
        return subprocess.run(args, input=payload.encode('utf-8'), capture_output=True, timeout=timeout,
                              creationflags=HIDDEN)

    def shell(self, script, *args, timeout=45):
        command = shlex.join(['sh', '-s', '--', *args])
        return self.run(['ssh', '-T', *self.options, '-p', str(self.port), self.destination, command], script, timeout)

    def sftp(self, batch):
        return self.run(['sftp', *self.options, '-P', str(self.port), '-b', '-', self.destination], batch, 1800)


CHECK = """
set -eu
root=$1 keys=$2 unit=$3 health=$4
test "$(cd "$root" && pwd -P)" = "$root"
test -w "$root"
test "$(cd "$keys" && pwd -P)" = "$keys"
test -w "$keys"
for tool in flock sha256sum timeout systemctl sudo; do command -v "$tool" >/dev/null; done
test "$(systemctl show -p LoadState --value "$unit")" = loaded
sudo -n -l -- systemctl stop "$unit" >/dev/null
sudo -n -l -- systemctl start "$unit" >/dev/null
sh -n -c "$health"
"""

ACTIVATE = """
set -eu
root=$1 keys=$2 unit=$3 stage=$4 mod=$5 health=$6
target=$root/$mod
cd "$root"
exec 9<"$root"
flock -n 9
test ! -L "$target" && { test ! -e "$target" || test -d "$target"; }
(
    cd "$stage/$mod"
    sha256sum --strict --check ../checksums
)
mkdir "$stage/new-keys" "$stage/installed-keys"
for key in "$stage/$mod"/Keys/*.bikey; do
    test -f "$key" || continue
    file=$keys/${key##*/}
    test ! -L "$file"
    if test -e "$file"; then
        cmp -s "$key" "$file" || { echo DMC_KEY_CONFLICT; exit 1; }
    else
        cp -- "$key" "$stage/new-keys/${key##*/}"
    fi
done

ready() {
    for attempt in $(seq 1 30); do
        if systemctl is-active --quiet "$unit" && timeout 5 sh -c "$health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

stop() {
    sudo -n systemctl stop "$unit" &&
        case "$(systemctl show -p ActiveState --value "$unit")" in
            inactive|failed) return 0 ;;
            *) return 1 ;;
        esac
}

was_running=0
systemctl is-active --quiet "$unit" && was_running=1
restorable=0
installed=0
rollback() {
    trap - EXIT HUP INT TERM
    set +e
    if stop; then
        good=1
        if test "$installed" = 1; then mv -T -- "$target" "$stage/rejected" || good=0; fi
        if test "$restorable" = 1; then mv -T -- "$stage/previous" "$target" || good=0; fi
        for marker in "$stage"/installed-keys/*; do
            file=$keys/${marker##*/}
            if test -f "$marker" && test -f "$file" && cmp -s "$marker" "$file"; then
                rm -- "$file" || good=0
            fi
        done
        if test "$good" = 1; then
            if test "$was_running" = 0 || { sudo -n systemctl start "$unit" && ready; }; then
                echo DMC_ROLLBACK_OK
                exit 2
            fi
        fi
    fi
    echo DMC_ROLLBACK_FAILED
    exit 3
}

stop || { echo DMC_STOP_FAILED; exit 1; }
trap rollback EXIT
trap 'exit 1' HUP INT TERM
if test -d "$target"; then
    mv -T -- "$target" "$stage/previous"
    restorable=1
fi
mv -T -- "$stage/$mod" "$target"
installed=1
for marker in "$stage"/new-keys/*; do
    test -f "$marker" || continue
    name=${marker##*/}
    temporary=$(mktemp "$keys/.dmc-key.XXXXXXXX")
    if ! cp -- "$marker" "$temporary" || ! chmod 644 "$temporary"; then
        rm -f -- "$temporary"
        exit 1
    fi
    cp -- "$marker" "$stage/installed-keys/$name"
    if ! ln -T -- "$temporary" "$keys/$name"; then
        rm -f -- "$temporary" "$stage/installed-keys/$name"
        exit 1
    fi
    rm -- "$temporary"
done
sudo -n systemctl start "$unit"
ready
trap - EXIT HUP INT TERM
echo DMC_READY
"""


class LinuxDayZ:
    def __init__(self, settings, transport=None):
        self.transport = transport or OpenSSH(settings)
        self.files_only = bool(settings.get('remote_files_only'))
        self.root = self.absolute_path(settings.get('remote_root', ''))
        self.mod = str(settings.get('remote_mod') or settings['mod'])
        if not re.fullmatch(r'@[A-Za-z0-9_-]+', self.mod):
            raise ValueError('The remote mod must be a dedicated @Mod directory.')
        if self.files_only:
            return
        self.keys = self.absolute_path(settings.get('remote_keys', ''))
        self.unit = str(settings.get('remote_service', ''))
        self.health = str(settings.get('remote_readiness', '')).strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*\.service', self.unit) or not self.health:
            raise ValueError('Enter the remote systemd service and readiness command.')
        if PurePosixPath(self.keys).is_relative_to(PurePosixPath(self.root) / self.mod):
            raise ValueError('Use a keys directory outside the mod directory.')

    @staticmethod
    def absolute_path(value):
        path = str(value)
        if not re.fullmatch(r'(?:/[A-Za-z0-9_.@-]+)+', path) or any(part in ('.', '..') for part in path.split('/')):
            raise ValueError('Enter a canonical absolute Linux directory using letters, numbers, dots, @, underscores or hyphens.')
        return path

    def check(self):
        if self.files_only:
            stage = f'{self.root}/.dmc-check.{uuid.uuid4().hex}'
            if self.transport.sftp(f'mkdir {stage}\nrmdir {stage}\n').returncode:
                raise RuntimeError('SFTP could not create and remove a staging directory.')
            return
        result = self.transport.shell(CHECK, self.root, self.keys, self.unit, self.health)
        if result.returncode:
            raise RuntimeError('SSH checks failed. Verify the host key, SSH agent, directory permissions, systemd unit and sudo access.')
        result = self.transport.sftp(f'ls {self.root}\nls {self.keys}\n')
        if result.returncode:
            raise RuntimeError('SFTP could not access the remote DayZ and keys directories.')

    def install(self, package, manifest, progress):
        self.check()
        name = package.name
        if not re.fullmatch(r'@[A-Za-z0-9_-]+', name):
            raise ValueError('Unsupported package directory name for SFTP.')
        for file in manifest['files']:
            if not re.fullmatch(r'[A-Za-z0-9_.@ /-]+', file):
                raise ValueError('A package filename is unsupported for remote transfer.')
        progress(3, ('Передаю пакет через SFTP', 'Staging package over SFTP'))
        local = self.local_path(package)
        checksums = ''.join(f'{checksum}  {file}\n' for file, checksum in manifest['files'].items())
        if self.files_only:
            stage = f'{self.root}/.dmc-stage.{uuid.uuid4().hex}'
            with tempfile.TemporaryDirectory() as temp:
                checksum_file = Path(temp) / 'checksums'
                checksum_file.write_bytes(checksums.encode('ascii'))
                result = self.transport.sftp(
                    f'mkdir {stage}\nput -r "{local}" {stage}/{self.mod}\n'
                    f'put "{self.local_path(checksum_file)}" {stage}/checksums\n')
            if result.returncode:
                raise RuntimeError(f'SFTP transfer failed. The live mod was untouched. Staging: {stage}')
            return dict(status='uploaded', staging=stage)
        result = self.transport.shell('set -eu; mktemp -d "$1/.dmc-stage.XXXXXXXX"', self.root)
        stage = result.stdout.decode('utf-8', errors='replace').strip()
        if result.returncode or not re.fullmatch(re.escape(self.root) + r'/\.dmc-stage\.[A-Za-z0-9]{8}', stage):
            raise RuntimeError('Could not create the remote staging directory.')
        result = self.transport.sftp(f'put -r "{local}" {stage}/{self.mod}\n')
        if result.returncode:
            raise RuntimeError(f'SFTP transfer failed. The live mod was untouched. Staging: {stage}')
        result = self.transport.shell('set -eu\ncat > "$1/checksums" <<\'DMC_CHECKSUMS\'\n'
                                      + checksums + 'DMC_CHECKSUMS\n', stage)
        if result.returncode:
            raise RuntimeError(f'Could not stage checksums. The live mod was untouched. Staging: {stage}')
        progress(4, ('Перевіряю пакет і перезапускаю віддалений сервер', 'Verifying the package and restarting the remote server'))
        try:
            result = self.transport.shell(ACTIVATE, self.root, self.keys, self.unit, stage, self.mod, self.health, timeout=900)
        except subprocess.TimeoutExpired:
            return dict(status='unknown', staging=stage)
        lines = result.stdout.decode('utf-8', errors='replace').splitlines()
        if 'DMC_READY' in lines and result.returncode == 0:
            return dict(status='ready', staging=stage)
        if 'DMC_ROLLBACK_OK' in lines:
            return dict(status='rolled_back', staging=stage)
        if 'DMC_ROLLBACK_FAILED' in lines:
            return dict(status='rollback_failed', staging=stage)
        if 'DMC_KEY_CONFLICT' in lines:
            raise RuntimeError('A public key with the same filename and different content already exists on the remote server.')
        if 'DMC_STOP_FAILED' in lines:
            raise RuntimeError('The remote service did not stop. The live mod was untouched.')
        return dict(status='unknown' if result.returncode == 255 else 'rejected', staging=stage)

    @staticmethod
    def local_path(path):
        value = path.as_posix()
        if any(character in value for character in '"\n\r[]*?'):
            raise ValueError('Unsupported local package path for SFTP.')
        return value

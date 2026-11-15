# DayZ Mod Creator

[![Завантажити для Windows x64](https://img.shields.io/badge/%D0%97%D0%B0%D0%B2%D0%B0%D0%BD%D1%82%D0%B0%D0%B6%D0%B8%D1%82%D0%B8-Windows%20x64-2563EB?style=for-the-badge)](https://github.com/Deagles12/dayz-mod-creator/releases/latest/download/DayZ-Mod-Creator-Windows-x64-portable.zip)

[Release notes and downloads](https://github.com/Deagles12/dayz-mod-creator/releases/latest)

<p align="center"><img src="assets/DMZ.png" alt="DayZ Mod Creator logo" width="180"></p>

DayZ Mod Creator is a Windows desktop and command-line tool for building, signing and deploying DayZ mods.

## Set up a project

1. Keep `dayz-mod-creator.exe` (or `dayz-mod-studio.exe`) and `dayz-backend.exe` together. The portable build needs the Microsoft Edge WebView2 Runtime for its interface.
2. Open the folder containing your source addon. Verify the detected DayZ, DayZ Server and DayZ Tools paths, select your local server config, and save.
3. Enter shared and server-only dependencies in load order as local directories or Workshop IDs. Check the reported files and compare your `requiredAddons` classes with the configured mods. A PBO filename alone cannot identify a configuration class.
4. For signing, select an existing key pair or generate a named pair from the Signing settings. DMC keeps generated keys in its local data folder. Only the public key is included in the build.
5. Turn on **Open DayZ after updating** to open the local client after server readiness.

## Build and release

- **F5 · Update locally** builds and verifies a PBO package, signs it when enabled, stops the recognized local test, backs up the files, installs the package and checks DayZ server readiness. Shared mods use a dedicated test-client folder outside Steam-managed downloads. Server readiness, client launch and manual gameplay checks are separate outcomes.
- **F5 · Update locally + Workshop** additionally uploads the same verified package when **Publish to Workshop** is enabled. Configure a Workshop link or ID and the owner's SteamID64. Use **Check item** to look up public item details and match the active Steam user to the owner. Private items can require direct confirmation from Steam during submission. Workshop confirmation refers to publication by Steam.
- **F6 · Update remote server** deploys the build shown by ID. With automatic Workshop publishing enabled, F6 selects a Steam-confirmed build for the configured item. Otherwise it selects the last locally verified build. Edits after F5 require a fresh F5 to enter the package. F6 validates the saved package and uses that package as-is.
- **Additional actions** provides build-only, install-only, launch-only, manual publication and local rollback. **Details** opens logs. Build manifests contain their ID, creation time, source and build-setting fingerprints, package checksums and signing information. Operation results are stored separately under `%LOCALAPPDATA%\DayZ Mod Studio`.
- A failed Workshop upload can be retried against the same verified build if its inputs are current. The application preserves an uncertain result when Steam does not confirm the request. Check the item in Steam before starting another publication.

For a first publication, run F5 with Workshop publishing off. Supply a title, description, PNG or JPEG preview, and visibility in the Workshop screen. DMC saves the created ID as soon as Steam returns it, so a failed upload or legal-agreement prompt can be resumed against that item. If Steam does not return the creation result, check your Steam items and enter the recovered ID before uploading again. [Steamworks Workshop documentation](https://partner.steamgames.com/doc/features/workshop/implementation)

## Connect a remote server

Configure the host, SSH port, SSH username and DayZ directory under Remote Server. DMC uses Windows OpenSSH with host-key verification and key authentication. Add the verified host key using OpenSSH and unlock your key via `ssh-agent` when required. Keep passwords, tokens and private keys out of DMC settings and readiness commands.

The managed adapter supports Linux with SFTP, SSH, systemd, `flock`, GNU coreutils and non-interactive sudo permission for the configured unit's `systemctl start` and `systemctl stop`. Supply a dedicated `@Mod` directory, the public key directory and a readiness command that returns 0 when DayZ is ready. The command runs as the SSH user. Configure the unit to load the mod and use the matching filesystem paths. Use **Check connection** before deploying.

SFTP uploads to a new staging directory. SSH verifies the SHA-256 checksums before stopping the service. DMC replaces the selected mod directory and adds any missing public keys. A conflicting public key with the same filename stops the deployment. A failed activation attempts to restore the previous mod, remove keys added by this operation and restore the previous service state. The staging path remains in the report for inspection and contains the previous mod on successful upgrade. Review and clean up old staging directories according to your backup policy.

For a host with SFTP access only, enable **SFTP upload only**. DMC stages the files and checksums. Verify and install the package through your host's tools, then restart the server there. The report remains an upload result.

## Run from a Windows terminal

Use the console executable for interactive work, Codex, scripts and CI. It shares project settings, package selection and history with the desktop app. In **PowerShell commands** on the project overview, copy a command with the full executable and project paths. The F6 command also contains its displayed build ID. Copying saves any pending project settings so the terminal can use them immediately.

Put global options before the command. `--project` selects a specific source directory and defaults to the current directory. Use `--recent` to select the last project opened in the desktop app.

```powershell
.\dayz-backend.exe --help
.\dayz-backend.exe --project 'D:\Mods\MyMod' status
.\dayz-backend.exe --project 'D:\Mods\MyMod' update
.\dayz-backend.exe --project 'D:\Mods\MyMod' remote --build-id 20261115-112233-aaaabbbb
.\dayz-backend.exe --recent --json status
.\dayz-backend.exe --recent history
.\dayz-backend.exe --recent logs
```

`update` runs the desktop F5 workflow. The original `test` spelling remains an alias. `remote` runs F6. Read the build ID from `status` or the successful update output when you need to pin an automation to that build. For a failed Workshop upload, use `retry-publish`. Use `remote-check` to validate the saved remote connection.

Use `config` to list setting keys, `config --get KEY` to read a value, and one or more `--set KEY VALUE` pairs to save changes. The GUI reloads saved settings and operation history when you return to the overview with no pending edits.

```powershell
.\dayz-backend.exe --recent config --get publish_workshop
.\dayz-backend.exe --recent config --set publish_workshop true --set open_dayz false
.\dayz-backend.exe --recent --verbose update
```

The desktop executable accepts the same arguments after `--cli`. Use `Start-Process -Wait -PassThru` for its exit code in interactive PowerShell.

```powershell
$process = Start-Process -FilePath .\dayz-mod-creator.exe -ArgumentList '--cli --help' -Wait -PassThru -NoNewWindow
$process.ExitCode
```

Human-readable output shows stages, confirmed destinations, the failure reason if applicable and a next command. Use `--verbose` to stream the full log. `--json` emits newline-delimited progress, log and result records. Exit codes are 0 for success, 1 for operation failure and 2 for invalid arguments. The `remote --build-id` option aborts if the requested ID differs from the selected verified build.

## Build and verify

```powershell
npm ci
python -m pip install pyinstaller
npm run desktop
python -m unittest discover -s backend -p 'test_release.py' -v
```

The automated suite exercises package selection, changed source inputs, Workshop retries and SFTP activation outcomes using mock adapters. For an integration test, use a disposable local DayZ project, a test Workshop item you own and a staging server on your hosting platform. Confirm a real signed package, compare the build ID on F5 and F6, then test staging failure and service rollback on that staging server. Confirm that the readiness command detects actual DayZ availability and test gameplay in the client.

DayZ Mod Creator is an independent community tool.

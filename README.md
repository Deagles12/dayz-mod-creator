# DMC | DayZ Mod Creator

<p align="center">
  <img src="assets/DMZ.png" alt="DayZ Mod Creator logo" width="240">
</p>

<p align="center">
  <a href="https://github.com/Deagles12/dayz-mod-creator/releases/latest"><img src="https://img.shields.io/badge/Version-v2.1.0-25864D" alt="Version v2.1.0"></a>
</p>
<p align="center"><strong><a href="https://github.com/Deagles12/dayz-mod-creator/releases/latest">Download latest release</a></strong></p>

<p align="center">
  <strong>Build, sign, deploy, and test DayZ mods with one keypress.</strong>
</p>

<p align="center">
  <img alt="Windows" src="https://img.shields.io/badge/Platform-Windows-20242A">
  <img alt="Languages" src="https://img.shields.io/badge/Languages-EN%20%7C%20UA-20242A">
  <img alt="Local testing" src="https://img.shields.io/badge/Local%20testing-F5-25864D">
</p>

**DayZ Mod Creator (DMC)** is a Windows desktop application designed to remove repetitive steps from DayZ mod development. Configure your test environment once, select a mod project, save your changes, and press **F5**.

**DMC handles the technical workflow. You focus on writing and testing the mod.**

> [!IMPORTANT]
> **F5 is for local testing only.** Steam Workshop uploads are always a separate action.

## ❌ Without DMC vs. ✅ With DMC

| ❌ Normally done manually | ✅ Automated by DMC |
| --- | --- |
| Open DayZ Tools and configure AddonBuilder | Uses the saved DayZ Tools configuration |
| Package source folders into `.pbo` files | Builds one or more addons from saved source files |
| Sign PBOs and check signatures | Signs and verifies them **when signing is enabled** |
| Copy the mod to the local server | Backs up and installs the new server copy |
| Copy the mod to the test client | Updates the dedicated local client mod copy |
| Place public signing keys on the server | Installs the required `.bikey` files when applicable |
| Close the previous test session | Stops **recognized** test processes when safe |
| Configure and start the DayZ server | Launches the server with saved profiles and dependencies |
| Check whether the server is ready | Monitors mission startup and the game port |
| Start DayZ with the right parameters | Launches the client with the test mods and server address |
| Open logs to investigate failures | Displays step status, warnings, errors, and suggested actions |
| Restore files after a bad deployment | Provides backups and rollback for affected local files and keys |

## How it works

| Step | DMC action | What you see |
| :---: | --- | --- |
| **01** | **Project check** | Source files, tools, server, and client configuration |
| **02** | **PBO build** | Build progress and the resulting packages |
| **03** | **Signing** | Signature verification, or **Skipped** if disabled |
| **04** | **Local deployment** | Server and client copies updated and verified; backups created |
| **05** | **Server startup** | Mission and game-port readiness status |
| **06** | **Client launch** | DayZ started with the configured test mods |
| **07** | **Test result** | What succeeded, what needs attention, and what to do next |

**Your part:** edit the mod, save the files, press **F5**, and test its behavior in DayZ. DMC does not verify gameplay correctness on its own.

## Getting started

| Step | What you do |
| :---: | --- |
| **1** | Keep `dayz-mod-creator.exe` and `dayz-backend.exe` in the **same folder**. Start `dayz-mod-creator.exe` (or `dayz-mod-studio.exe` in older builds). |
| **2** | Select your mod project. DMC checks for DayZ addon structure, including `config.cpp`. |
| **3** | Complete the one-time setup for DayZ Tools, the test server, client, profiles, ports, dependencies, and optional signing keys. |
| **4** | Edit your mod in your preferred editor and **save the changes**. |
| **5** | Press **F5 · Build & Test**. Watch the live progress and result. |
| **6** | Enter the local server if needed and test the changes in-game. Repeat steps 4–6 whenever you edit the mod. |

> [!NOTE]
> DMC does not install DayZ, DayZ Tools, the dedicated server, or missing third-party dependencies. These must already be available and configured.

## Main features

| Feature | Description |
| --- | --- |
| **Project management** | Recent projects, addon folder detection, and rejection of unrelated directories |
| **Environment setup** | Detection of DayZ Tools, server, and client paths; shared and per-project settings |
| **Dependencies** | Reads mod configuration; supports local mod folders and Workshop IDs, with shared and server-side dependency lists |
| **PBO builds** | AddonBuilder integration, multi-addon builds, build history, and build-only mode |
| **Optional signing** | `.biprivatekey`, `.bisign` creation, signature verification, and public `.bikey` deployment |
| **Local test deployment** | Backups, file verification, and installation into separate server and client test locations |
| **Server & client launch** | Stored profiles and launch options, mission/port readiness checks, and client startup |
| **Resume and retry** | Redeploy an already verified build or resume eligible stages without unnecessary rebuilding |
| **Rollback** | Restore previously backed-up local mod files and affected keys |
| **Live feedback** | Stage-by-stage progress, searchable logs, warnings, history, and actionable errors |
| **Workshop updates** | Separate update action for an existing Workshop item with a saved ID |
| **Desktop experience** | Ukrainian/English UI, dark/light themes, and persistent settings |

## Signing: automatic when enabled

| Signing setting | Result |
| --- | --- |
| ✅ **Enabled and configured** | DMC signs new PBOs, creates `.bisign` files, and verifies signatures |
| ⏭️ **Disabled** | The signing stage is shown as **Skipped**, not as a successful signature check |
| ⚠️ **Required by the test server** | DMC requests the necessary signing configuration before continuing |
| ❌ **Verification fails** | DMC reports the failed stage instead of claiming success |

Your private `.biprivatekey` remains local. Only the relevant **public** `.bikey` files are installed on the test server. **Never upload or share your private key.**

## Local testing and Steam Workshop are different

| Action | Local server/client | Steam Workshop |
| --- | :---: | :---: |
| **F5 · Build & Test** | ✅ | ❌ |
| **Build PBO only** | ❌ | ❌ |
| **Update Workshop** | Not the purpose of this action | ✅ Existing item only |
| **First Workshop publication** | Not required | ✋ Manual |

DMC does **not** silently overwrite Steam-managed Workshop download directories. It uses separate local test locations. Updating an existing Workshop item requires a saved **Workshop ID** and appropriate Steam access.

## Resume, backups, and safety

- **No unnecessary rebuilds:** a verified build can be redeployed or launched again when its sources and build-relevant settings have not changed.
- **Backups before replacement:** DMC preserves affected local files and supports rollback.
- **Safe process handling:** if DMC cannot identify an open game/test process reliably, it stops before changing files and asks for manual intervention.
- **Clear outcomes:** a launched game is not automatically treated as a confirmed player connection.

## Portable Windows version

| File | Purpose |
| --- | --- |
| **`dayz-mod-creator.exe`** | The desktop interface you open |
| **`dayz-backend.exe`** | Bundled Python process that performs the build and test operations |

The interface starts the backend automatically. Users of the packaged portable version do not need to install Python separately. Keep both executables together. Some older builds may still name the interface `dayz-mod-studio.exe`.

## What still requires you

| You handle | DMC handles |
| --- | --- |
| ✍️ Write and save mod code | ✅ Build and deploy saved files |
| 🎮 Test gameplay behavior | ✅ Start the local test environment |
| 🔑 Choose signing keys during initial setup | ✅ Reuse them for subsequent signed builds |
| 📦 Install missing third-party mods | ✅ Apply configured dependencies at launch |
| ✋ Publish the first Workshop item | ✅ Update an existing configured item as a separate action |
| ⚠️ Close an unrecognized running client if prompted | ✅ Resume eligible steps afterward |

## Verified testing and current limitations

The reported **`MyMod`** test confirmed:

- ✅ PBO building
- ✅ Signature creation and verification
- ✅ Deployment to both local test copies
- ✅ Rollback of affected files
- ✅ Server readiness checks
- ✅ Client launch
- ⚠️ **Player login was not confirmed by server logs.** DMC correctly reported **Needs attention**, not full end-to-end success.

These results describe the reported `MyMod` test only. They do **not** establish that every mod, server setup, or Steam Workshop update has been tested successfully.

## The goal

| ❌ Without automation | ✅ With DMC |
| --- | --- |
| Repeated manual packing, signing, copying, launching, and log checking | **Save your changes, press F5, and test in DayZ** |

**DMC is an independent community tool and is not an official Bohemia Interactive product.**

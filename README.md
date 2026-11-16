# DayZ Mod Creator

Windows-застосунок для збірки й тестування модів DayZ, підготовки 3D-моделей та конвертації текстур. [Релізи на GitHub](https://github.com/Deagles12/dayz-mod-creator/releases)

## Запуск

1. Розпакуй ZIP. Залиш `dayz-mod-studio.exe` і `dayz-backend.exe` в одній папці та відкрий `dayz-mod-studio.exe`. Для вікна потрібен Microsoft Edge WebView2 Runtime.
2. При першому запуску Studio створить і відкриє папку `projekt` поруч із EXE. Поклади туди вихідні файли мода з `config.cpp` або відкрий іншу папку через **Відкрити папку**. Studio запам’ятає вибір для цієї копії програми. У **Налаштуваннях** перевір шляхи до DayZ Tools, клієнта й сервера, додай залежності та за потреби налаштуй підпис.
3. **F5** збирає, перевіряє, встановлює й запускає локальний тест. **F6** розгортає вибрану перевірену збірку на налаштованому віддаленому сервері. Публікація у Workshop входить у F5, якщо її ввімкнено.

## Моделі й текстури

| Розділ | Що вибрати | Результат |
| --- | --- | --- |
| **3D-моделі** | Кольоровий GLB з UV і вбудованою PNG-текстурою, до 64 МБ | 3D-прев’ю та P3D із трьома візуальними LOD і PAA в `output\models` |
| **Текстури** | Один або кілька PNG, JPG/JPEG, TGA чи PAA | Зображення → PAA, PAA → PNG у `output\textures` |

Обидві папки створюються поруч із EXE. Кнопка **Вибрати папку** змінює шлях, а **Відкрити папку** показує результат. Ці розділи працюють без відкритого проєкту. Для текстур потрібні DayZ Tools, для моделей — також Blender. Якщо Blender не знайдено, задай шлях до `blender.exe` у змінній `DAYZ_BLENDER`. P3D містить візуальну модель. Колізію та ігровий конфіг додають окремо.

## PowerShell

Запускай із папки EXE. На **Огляді → Команди PowerShell** можна скопіювати команди з фактичним шляхом до проєкту та ID збірки.

```powershell
.\dayz-backend.exe --help
.\dayz-backend.exe --project 'D:\Mods\MyMod' status
.\dayz-backend.exe --project 'D:\Mods\MyMod' update
.\dayz-backend.exe --project 'D:\Mods\MyMod' remote --build-id 20261115-112233-aaaabbbb
.\dayz-backend.exe --recent --json status
.\dayz-backend.exe --recent history
.\dayz-backend.exe --recent logs
.\dayz-backend.exe --recent config --get publish_workshop
.\dayz-backend.exe --recent config --set publish_workshop true --set open_dayz false
.\dayz-backend.exe --recent --verbose update
```

| Команда | Дія |
| --- | --- |
| `update` або `test` | Повний локальний цикл F5 |
| `build`, `deploy`, `launch`, `rollback` | Зібрати, встановити, запустити або відкотити локально |
| `workshop-check`, `publish`, `retry-publish` | Перевірити item, опублікувати або повторити публікацію |
| `remote-check`, `remote --build-id ID` | Перевірити підключення або розгорнути збірку через F6 |
| `status`, `history`, `logs`, `config` | Переглянути стан, історію, журнал або налаштування |

`--recent` використовує останній відкритий проєкт. Глобальні параметри вказуй перед командою. `--json` дає машинозчитуваний вивід, `--verbose` — повний журнал. У прикладі F6 заміни ID на перевірений ID зі `status`.

Ті самі команди підтримує основний EXE через `--cli`:

```powershell
$process = Start-Process -FilePath .\dayz-mod-studio.exe -ArgumentList '--cli --help' -Wait -PassThru -NoNewWindow
$process.ExitCode
```

## Збірка з вихідного коду

```powershell
npm ci
python -m pip install pyinstaller
npm run desktop
python -m unittest discover -s backend -p 'test_release.py' -v
```

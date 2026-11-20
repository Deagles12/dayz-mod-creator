# DayZ Mod Studio

Windows-застосунок для збірки й тестування модів DayZ та конвертації 3D-моделей і текстур. [Релізи на GitHub](https://github.com/Deagles12/dayz-mod-studio/releases)

## Запуск

1. Розпакуй ZIP. Залиш `dayz-mod-studio.exe` і `dayz-backend.exe` в одній папці та відкрий `dayz-mod-studio.exe`. Для вікна потрібен Microsoft Edge WebView2 Runtime.
2. При першому запуску Studio створить і відкриє папку `projekt` поруч із EXE. Поклади туди вихідні файли мода з `config.cpp` або відкрий іншу папку через **Відкрити папку**. Studio запам’ятає вибір для цієї копії програми. У **Налаштуваннях** перевір шляхи до DayZ Tools, клієнта й сервера, додай залежності та за потреби налаштуй підпис.
3. **F5** збирає, перевіряє, встановлює й запускає локальний тест. **F6** розгортає вибрану перевірену збірку на налаштованому віддаленому сервері. Публікація у Workshop входить у F5, якщо її ввімкнено.

## Моделі й текстури

У **Моделі й текстури → 3D-моделі** натисни **Відкрити P3D** або **Оглянути P3D** після експорту. Оглядач показує геометрію файлів MLOD (P3DM) до 64 МБ без текстур і матеріалів. Камеру можна обертати, наближати й перетягувати, а LOD перемикати у списку. Для огляду не потрібні Blender або DayZ Tools. Якщо файл бінаризовано у формат ODOL, відкрий вихідний MLOD.

Папка **3D-Generator** поруч із EXE містить окремі інструменти пакетного текстурування готових моделей. Інструкції наведено в **3D-Generator/README_UA.md**.

Перед видачею P3D Studio вилучає невикористані вершини й нормалі, перевіряє індекси граней, скінченність координат та UV і ліміти кожного з трьох візуальних LOD. Поруч із моделлю зберігається `validation.json` із кількістю вершин, трикутників, матеріалів і станом колізії. Geometry та Fire Geometry LOD потрібно підготувати для використання у грі.

Під час локального тесту Studio чекає маркера завершення CE та UDP-порту свого сервера, потім ще 15 секунд перевіряє журнал. Помилки VM і пошкоджених збережень переривають перевірку. На сторінці **Тестовий сервер** доступні повторна спроба коректної зупинки та окрема дія примусового завершення сервера, запущеного цією Studio. Клієнту надсилається запит закриття вікна з очікуванням до 20 секунд. Дані PID і часу створення запущених процесів зберігаються в профілі проєкту.

| Розділ | Що вибрати | Результат |
| --- | --- | --- |
| **3D-моделі** | Кольоровий GLB з UV і вбудованою PNG-текстурою, до 64 МБ | 3D-прев’ю та P3D із трьома візуальними LOD і PAA в `output\models` |
| **Текстури** | Один або кілька PNG, JPG/JPEG, TGA чи PAA | Зображення → PAA, PAA → PNG у `output\textures` |

Обидві папки створюються поруч із EXE. Кнопка **Вибрати папку** змінює шлях, а **Відкрити папку** показує результат. Ці розділи працюють без відкритого проєкту. Для конвертації текстур потрібні DayZ Tools, для експорту GLB — також Blender. Якщо Blender не знайдено, задай шлях до `blender.exe` у змінній `DAYZ_BLENDER`. Експортований P3D містить візуальну модель. Колізію та ігровий конфіг додають окремо.

## PowerShell

### Текстури через CLI

Команда `textures` підтримує той самий пакетний конвертер, що й розділ **Моделі й текстури → Конвертація текстур**. Напрямок визначається розширенням кожного файла. Можна передати разом PNG, JPG/JPEG, TGA та PAA, від 1 до 100 файлів.

```powershell
.\dayz-backend.exe textures 'D:\Textures\wall_co.png' 'D:\Textures\wood_co.paa'
.\dayz-backend.exe textures 'D:\Textures\wall_co.png' --output 'D:\Textures\Converted' --tools 'F:\Steam\steamapps\common\DayZ Tools' --open
.\dayz-backend.exe textures --show-output
.\dayz-backend.exe textures --show-output --output 'D:\Textures\Converted' --open
.\dayz-backend.exe --json textures 'D:\Textures\wall_co.png'
.\dayz-backend.exe --recent textures 'D:\Textures\wall_co.png'
.\dayz-backend.exe --project 'D:\Mods\MyMod' textures 'D:\Textures\wall_co.png'
.\dayz-mod-studio.exe --cli textures 'D:\Textures\wall_co.png'
.\dayz-backend.exe textures --help
```

Типова папка результатів — `output\textures` поруч із EXE. `--output` вибирає наявну папку, а кожна конвертація створює всередині окрему `export-…`. `--show-output` показує папку без конвертації, `--open` відкриває її у Провіднику. Для обробки потрібен ImageToPAA із DayZ Tools. Без вибраного проєкту використовуються спільні налаштування середовища та автоматичний пошук інсталяції. `--project` або `--recent` підхоплює налаштування проєкту, `--tools` задає шлях для поточного виклику.

Звичайний вивід містить прогрес, папку результатів і список файлів. Помилки окремих файлів потрапляють у stderr, обробка решти продовжується. Код завершення — `0` за успіху, `1` за будь-якої помилки конвертації, `2` за помилки аргументів. `--json` повертає JSON-рядки з подіями `progress`, `result` або `error`. Результат містить `folder`, `files` та `errors`.

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

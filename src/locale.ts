export type Lang = 'uk' | 'en'
export type Pair = [string, string]
export const pages = [
  ['overview', 'Огляд', 'Overview'], ['projects', 'Проєкти', 'Projects'], ['build', 'Збірка', 'Build'],
  ['server', 'Тестовий сервер', 'Test server'], ['workshop', 'Workshop', 'Workshop'], ['settings', 'Налаштування', 'Settings'],
] as const
export type Page = typeof pages[number][0]
export const checks: Record<string, Pair> = { project: ['Проєкт', 'Project'], sources: ['Джерела', 'Sources'],
  tools: ['DayZ Tools', 'DayZ Tools'], environment: ['Сервер і клієнт', 'Server and client'], signing: ['Підпис', 'Signing'] }
export const phases: Pair[] = [['Пакування PBO','Package PBO'], ['Перевірка підпису','Verify signatures'],
  ['Копії та встановлення','Back up and deploy'], ['Запуск сервера','Start server'], ['Запуск клієнта','Launch client']]

export const fields: Record<string, [string, string, string]> = {
  "addons": [
    "Папки аддонів",
    "Addon folders",
    "text"
  ],
  "mod": [
    "Папка @мода",
    "@Mod folder",
    ""
  ],
  "addon_name": [
    "Назва PBO",
    "PBO name",
    ""
  ],
  "prefix": [
    "Префікс PBO",
    "PBO prefix",
    ""
  ],
  "metadata": [
    "Файл mod.cpp",
    "mod.cpp file",
    "file"
  ],
  "extra": [
    "Додаткові файли пакета",
    "Extra package files",
    "text"
  ],
  "pack": [
    "Лише пакування",
    "Pack only",
    "bool"
  ],
  "prep_exe": [
    "Підготовка ресурсів",
    "Asset preparation tool",
    "file"
  ],
  "prep_args": [
    "Аргументи підготовки",
    "Asset preparation arguments",
    "text"
  ],
  "tools": [
    "DayZ Tools",
    "DayZ Tools",
    "folder"
  ],
  "server": [
    "Папка DayZ Server",
    "DayZ Server directory",
    "folder"
  ],
  "client": [
    "Папка DayZ",
    "DayZ directory",
    "folder"
  ],
  "server_exe": [
    "Файл запуску сервера",
    "Server executable",
    "file"
  ],
  "client_exe": [
    "Файл запуску клієнта",
    "Client executable",
    "file"
  ],
  "config": [
    "Конфіг сервера",
    "Server configuration",
    "file"
  ],
  "profiles": [
    "Профіль сервера",
    "Server profile directory",
    "folder"
  ],
  "client_profiles": [
    "Профіль клієнта",
    "Client profile directory",
    "folder"
  ],
  "port": [
    "Ігровий порт",
    "Game port",
    ""
  ],
  "address": [
    "Локальна адреса",
    "Local address",
    ""
  ],
  "timeout": [
    "Таймаут запуску, с",
    "Startup timeout, seconds",
    ""
  ],
  "shared": [
    "Завантажувати мод на клієнті",
    "Load the mod on the client",
    "bool"
  ],
  "separate": [
    "Окрема клієнтська копія",
    "Separate client installation",
    "bool"
  ],
  "base": [
    "Спільні залежності",
    "Shared dependencies",
    "text"
  ],
  "server_only": [
    "Серверні залежності",
    "Server-only dependencies",
    "text"
  ],
  "server_args": [
    "Аргументи сервера",
    "Server arguments",
    "text"
  ],
  "client_args": [
    "Аргументи клієнта",
    "Client arguments",
    "text"
  ],
  "sign": [
    "Підписувати й перевіряти PBO",
    "Sign and verify PBO files",
    "bool"
  ],
  "private": [
    "Приватний ключ",
    "Private signing key",
    "file"
  ],
  "public": [
    "Публічний ключ",
    "Public signing key",
    "file"
  ],
  "workshop": [
    "Workshop ID",
    "Workshop ID",
    ""
  ],
  "steam_owner": [
    "SteamID64 власника",
    "Owner SteamID64",
    ""
  ],
  "notes": [
    "Нотатки оновлення",
    "Update notes",
    "text"
  ]
}
export const hints: Record<string, Pair> = {
  "addons": [
    "Відносні шляхи до папок із config.cpp, по одному на рядок.",
    "Paths relative to the project, one config.cpp directory per line."
  ],
  "base": [
    "Один шлях на рядок. Відносні шляхи рахуються від папки сервера.",
    "One path per line. Relative paths start at the server directory."
  ],
  "server_only": [
    "Список -serverMod. Один шлях на рядок.",
    "-serverMod list. Enter one path per line."
  ],
  "server_args": [
    "Один повний аргумент на рядок, без зовнішніх лапок.",
    "One complete argument per line, without surrounding quotes."
  ],
  "client_args": [
    "Наприклад -window або -name=Tester. Один аргумент на рядок.",
    "For example -window or -name=Tester. One argument per line."
  ],
  "profiles": [
    "Відносний до сервера або абсолютний шлях. Тут зберігаються журнали тесту.",
    "An absolute or server-relative path. Test logs are stored here."
  ],
  "private": [
    "Вибери .biprivatekey. Зберігається тільки шлях до файла.",
    "Choose a .biprivatekey file. Studio stores only its path."
  ],
  "public": [
    "Вибери відповідний однойменний .bikey.",
    "Choose the matching .bikey file."
  ],
  "workshop": [
    "ID зі сторінки мода після першої ручної публікації.",
    "The item ID from its Workshop page after the first manual publication."
  ]
}

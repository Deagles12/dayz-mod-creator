# DayZ 3D Generator - текстурування 3.0

Папка 3D-Generator створюється поруч із EXE Studio. Тут розміщені пакетний обробник, finisher, incoming для архівів, ready для результатів та materials для локальної бібліотеки.

Запускай PowerShell 7 із цієї папки. Обробляй архіви з генераторами Python, джерелу яких довіряєш.

    .\Process_DayZ_Archives.ps1 -InputDir .\incoming -OutputDir .\ready -Force -TextureResolution 2048 -Seed 17 -Wear 0.7

Blender працює приховано. PowerShell показує час виконання. Усі матеріальні поверхні запікаються перед об’єднанням мешів. На виході створюються BLEND, GLB, OBJ/MTL, Base Color, tangent normal, roughness, metallic, AO, ORM, validation.json та чотири контрольні рендери.

Force потрібен для заміни результату. Попередня папка переноситься в резервну копію лише після успішного створення й перевірки нової. За помилок залишається робоча папка з generate.log та finish.log, а старий результат зберігається. Batch.json містить статус кожного архіву.

Додаткові параметри включають BlenderPath, MaterialLibrary, SkipRenders і TimeoutSeconds. Seed забезпечує відтворювані варіації, Wear задає інтенсивність від 0 до 1. Джерела локальних фотографічних матеріалів і ліцензії записуються у звіт. Докладний формат описано в materials/README.md.

## Підготовка карт DayZ

    .\Process_DayZ_Archives.ps1 -InputDir .\incoming -OutputDir .\ready -Force -PrepareDayZMaps -NormalGreen keep -DayZPrefix dayz_models

Це окремий наближений профіль для Super shader. Він створює PNG, PAA, RVMAT і dayz-validation.json у підпапці dayz. Префікс шляхів потрібно узгодити зі структурою власного аддона.

Для NOHQ застосовуються штатні swizzle і DXT5 з TexConvert.cfg ImageToPAA. SMDI містить R=1, G як оцінку specular F0, B як нормований specular power, обчислений із roughness. AS містить AO в G. CO є sRGB, решта карт - дані Non-Color.

Цей профіль не є просто перейменуванням карт PBR. Перетворення roughness і metallic у SMDI є наближенням, а єдиний Fresnel для різних матеріалів потребує налаштування у грі. Параметр NormalGreen дозволяє явний вибір орієнтації Y. У звіті готовність до DayZ залишається false до перевірки в цільовому шейдері.

Правила перевірено за документацією BI та локальним TexConvert.cfg. Основні джерела наведено в MATERIAL_RULES.md.

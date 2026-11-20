# PBR та DayZ

GLB використовує стандартний metallic/roughness PBR. CO - sRGB. Tangent normal, roughness, metallic та AO - лінійні дані. ORM зберігає AO у R, roughness у G та metallic у B. У Blender застосовано вузол glTF Material Output для експорту occlusion. [Blender glTF manual](https://docs.blender.org/manual/en/4.4/addons/import_export/scene_gltf2.html)

Super shader використовує NOHQ, AS і SMDI. У SMDI R дорівнює 1, G керує specular, B - specular power. AS використовує G як доступність навколишнього світла. RVMAT описує етапи й параметри конкретного шейдера. Ці канали відрізняються від ORM. [BI Super shader](https://community.bistudio.com/wiki/Super_shader), [BI RVMAT](https://community.bistudio.com/wiki/RVMAT)

Суфікси визначають перетворення під час конвертації в PAA. У локальному DayZ Tools TexConvert.cfg для CO, SMDI й AS задано DXT1, для NOHQ - DXT5. NOHQ виконує swizzle A=1−R та R=1−A, зберігаючи G і B. SMDI фіксує R=1, AS фіксує R=B=1. Тому додаткове ручне пакування цих каналів у фізичний PAA перед ImageToPAA не виконується. Конвертер застосовує належні правила до логічних PNG. [BI Texture Naming Rules](https://community.bistudio.com/wiki/Arma%3A_Texture_Naming_Rules), [BI Texture Map Types](https://community.bistudio.com/wiki/Texture_Map_Types)

У підготовчому профілі specular оцінено як F0 діелектрика 0.04 або яскравість base color металу. Specular power оцінено формулою 2/roughness^4−2 і нормовано на 180. Це інженерне наближення, яке потребує калібрування. Однозначного фізичного перетворення ORM у Super для всіх поверхонь немає.

PAA перевіряються за реальними заголовками формату, а хеш використаного TexConvert.cfg записується у звіт. Візуальну сумісність у DayZ цей офлайн-тест не доводить. EngineValidated і readyForDayZ залишаються false.

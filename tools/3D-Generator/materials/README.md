# Локальна PBR-бібліотека

Категорії Painted Metal, Rusted Steel, Weathered Wood, Dirty Fabric, Tin Metal і Rubber створюються Studio автоматично. Без локальних матеріалів використовуються процедурні поверхні.

Розпакуй власноруч завантажений матеріал у підпапку відповідної категорії. Поруч із зображеннями створи material.json за наведеним прикладом. Шляхи відносні до цього файла.

    {
      "name": "My material",
      "license": "CC0",
      "source": "https://example.org/material-page",
      "scale": 1,
      "maps": {
        "baseColor": "basecolor.png",
        "normal": "normal_opengl.png",
        "roughness": "roughness.png",
        "metallic": "metallic.png",
        "ao": "ao.png"
      }
    }

Base Color є обов’язковим, решта карт додаткові. Base Color читається як sRGB, карти даних - Non-Color. Normal використовує tangent-space OpenGL. Для DirectX normal спочатку інвертуй зелений канал. Roughness має бути roughness, а не glossiness.

Вибирається перший material.json за алфавітом у категорії. Для іншого набору передай окремий корінь через параметр MaterialLibrary. Ліцензія й джерело записуються в validation.json.

Poly Haven та ambientCG можуть бути джерелами матеріалів із придатною ліцензією. Завантаження й перевірка умов конкретного набору виконуються користувачем. Мережевих запитів цей конвеєр не робить.

"""Explicit Super-shader conversion profile, kept separate from standard PBR."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import bpy
import numpy as np


def prepare(destination, name, converter, prefix, green):
    binary = Path(converter).resolve(strict=True)
    config = binary.with_name('TexConvert.cfg')
    if not config.is_file():
        raise ValueError('ImageToPAA requires its TexConvert.cfg')
    folder = destination / 'dayz'
    folder.mkdir()
    arrays = {}
    size = None
    for key in ('co', 'normal', 'roughness', 'metallic', 'ao'):
        image = bpy.data.images.load(str(destination / (name + '_' + key + '.png')), check_existing=False)
        image.colorspace_settings.name = 'sRGB' if key == 'co' else 'Non-Color'
        arrays[key] = np.array(image.pixels[:], dtype=np.float32).reshape((-1, 4))
        size = tuple(image.size)
    normal = arrays['normal'].copy()
    if green == 'flip':
        normal[:, 1] = 1 - normal[:, 1]
    normal[:, 3] = 1
    rough = np.clip(arrays['roughness'][:, 0], .12, 1)
    metal = np.clip(arrays['metallic'][:, 0], 0, 1)
    color = arrays['co'][:, :3]
    linear = np.where(color <= .04045, color / 12.92, ((color + .055) / 1.055) ** 2.4)
    luminance = linear @ np.array([.2126, .7152, .0722])
    smdi = np.ones_like(normal)
    smdi[:, 1] = np.clip(.04 * (1 - metal) + luminance * metal, 0, 1)
    smdi[:, 2] = np.clip((2 / rough**4 - 2) / 180, 0, 1)
    ambient = np.ones_like(normal)
    ambient[:, 1] = arrays['ao'][:, 0]
    shutil.copyfile(destination / (name + '_co.png'), folder / (name + '_co.png'))
    for key, values in (('nohq', normal), ('smdi', smdi), ('as', ambient)):
        image = bpy.data.images.new(name + '_' + key, width=size[0], height=size[1], alpha=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels.foreach_set(values.ravel())
        image.filepath_raw = str(folder / (name + '_' + key + '.png'))
        image.file_format = 'PNG'
        image.save()
    formats = {}
    for key, expected in (('co', 0xff01), ('nohq', 0xff05), ('smdi', 0xff01), ('as', 0xff01)):
        source = folder / (name + '_' + key + '.png')
        target = source.with_suffix('.paa')
        process = subprocess.run([str(binary), source.name, target.name], cwd=folder,
                                 capture_output=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if process.returncode or not target.is_file():
            raise RuntimeError(process.stderr.decode(errors='replace') or 'ImageToPAA failed')
        actual = struct.unpack('<H', target.read_bytes()[:2])[0]
        if actual != expected:
            raise ValueError(f'Unexpected PAA format for {key}: {actual:#x}')
        formats[key] = dict(type=hex(actual), bytes=target.stat().st_size)
    path = prefix.rstrip('\\/') + '\\'
    stages = [
        path + name + '_nohq.paa', '#(argb,8,8,3)color(0.5,0.5,0.5,0)',
        '#(argb,8,8,3)color(0,0,0,0)', path + name + '_as.paa',
        path + name + '_smdi.paa', '#(ai,64,1,1)fresnel(1.5,0)',
        '#(argb,8,8,3)color(0,0,0,0)',
    ]
    material = 'ambient[]={1,1,1,1};\ndiffuse[]={1,1,1,1};\nforcedDiffuse[]={0,0,0,0};\nemmisive[]={0,0,0,0};\nspecular[]={1,1,1,1};\nspecularPower=180;\nPixelShaderID="Super";\nVertexShaderID="Super";\n'
    for index, texture in enumerate(stages, 1):
        material += f'class Stage{index} {{ texture="{texture}"; uvSource="' + ('none' if index > 5 else 'tex') + '"; };\n'
    (folder / (name + '.rvmat')).write_text(material, encoding='ascii')
    report = dict(profile='Super-explicit-approximation-v1', formatValidated=True, engineValidated=False,
                  normalGreen=green, formats=formats, shader='Super', specularPower=180,
                  mappings=dict(smdiR=1, smdiG='dielectric F0 / metal base-color luminance',
                                smdiB='clamp((2/roughness^4-2)/180)', asG='AO'),
                  texConvertSHA256=hashlib.sha256(config.read_bytes()).hexdigest(),
                  limitations='Tangent handedness, mixed-surface Fresnel and response require DayZ validation. No in-game readiness claim.')
    (folder / 'dayz-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report

"""Blender entry point. All executable logic is shipped with Studio."""
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from geometry import create
from uv import unwrap
from textures import materials, atlas, verify_atlas
from validation import inspect, handle_open, uv_overlap
from export import models, preview, verify_glb, verify_obj

config = Path(sys.argv[sys.argv.index('--') + 1])
values = json.loads(config.read_text(encoding='utf-8'))
output = Path(values['output'])


def progress(stage):
    with (config.parent / 'progress').open('a', encoding='ascii') as file:
        file.write(str(stage) + '\n')


bpy.ops.wm.read_factory_settings(use_empty=True)
progress(1)
obj, hole = create(values, materials(values))
progress(2)
unwrap(obj)
uv_report = uv_overlap(obj)
progress(3)
image, texture = atlas(obj, values, output)
texture_report = verify_atlas(image, values)
original = inspect(obj, values)
hole_valid = handle_open(obj, hole)
progress(4)
glb = models(obj, values, output, image)
glb_report = verify_glb(glb)
obj_report = verify_obj(output / (values['name'] + '.obj'))
preview(obj, output)
for index, path in enumerate(values['references']):
    reference_image = bpy.data.images.load(path, check_existing=True)
    reference_image.pack()
    reference = bpy.data.objects.new(f'Reference {index + 1}', None)
    reference.empty_display_type = 'IMAGE'
    reference.data = reference_image
    reference.hide_render = True
    reference.hide_viewport = True
    bpy.context.collection.objects.link(reference)
bpy.ops.wm.save_as_mainfile(filepath=str(output / (values['name'] + '.blend')))
progress(5)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(glb))
imported = [item for item in bpy.context.scene.objects if item.type == 'MESH']
if len(imported) != 1:
    raise ValueError('GLB must reimport as one textured mesh')
# GLB splits points at UV seams. Weld only the validation copy for topology checks.
import bmesh
mesh = imported[0].data
bm = bmesh.new()
bm.from_mesh(mesh)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
bm.to_mesh(mesh)
bm.free()
reimported = inspect(imported[0], values)
handle_open(imported[0], hole)
bpy.ops.wm.open_mainfile(filepath=str(output / (values['name'] + '.blend')))
opened = bpy.data.objects.get(values['name'])
if opened is None:
    raise ValueError('BLEND cannot be reopened')
inspect(opened, values)
if not texture.is_file() or not (output / (values['name'] + '.obj')).read_text(encoding='utf-8').count('\nf '):
    raise ValueError('Missing texture or OBJ faces')
report = dict(valid=True, template=values['template'], mesh=original, uv=uv_report,
              glb=glb_report, reimport=reimported, blendReopened=True,
              handleThroughHole=hole_valid,
              blender=bpy.app.binary_path, parameters={key: value for key, value in values.items() if key != 'output'},
              normalMap=None)
report['texture'] = texture_report
report['obj'] = obj_report
# The old image datablock is invalid after factory reset. Read saved PNG dimensions.
import struct
report['textureResolution'] = list(struct.unpack('>II', texture.read_bytes()[16:24]))
(output / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
progress(6)

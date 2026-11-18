"""DayZ archive finisher 3.0. Trusted, deterministic offline material baking."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import bpy
import bmesh

sys.path.insert(0, str(Path(__file__).parent))
fallback = Path(__file__).resolve().parents[2] / 'backend/generator_blender'
if fallback.is_dir():
    sys.path.append(str(fallback))
from pbr_materials import build, category
from pbr_bake import unwrap, bake, assign
from pbr_export import export, verify_glb, image_statistics, renders
from validation import uv_overlap


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('name')
    parser.add_argument('--resolution', type=int, default=int(os.environ.get('DAYZ_ATLAS_RES', '2048')), choices=(1024, 2048, 4096))
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--wear', type=float, default=.7)
    parser.add_argument('--library', type=Path, default=Path(__file__).parent / 'materials')
    parser.add_argument('--no-renders', action='store_true')
    parser.add_argument('--dayz-converter')
    parser.add_argument('--dayz-prefix', default='dayz_models')
    parser.add_argument('--normal-green', choices=('keep', 'flip'), default='keep')
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def run():
    args = arguments()
    if not math.isfinite(args.wear) or not 0 <= args.wear <= 1:
        raise ValueError('Wear must be between 0 and 1')
    if not args.name or any(not (letter.isascii() and (letter.isalnum() or letter in '_-')) for letter in args.name):
        raise ValueError('Use an ASCII output name')
    dest = args.destination.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()))
    removed = []
    prefixes = ('Table paint wear ', 'Front apron scratches ', 'Cabinet oxidized chips ',
                'Plank scratches', 'Plank chipped edge', 'Rag dirty stain ', 'Can oxidation mark ')
    for obj in list(bpy.data.objects):
        fake_wood = obj.name.startswith('Plank ') and 'wood grain' in obj.name
        if obj.type == 'MESH' and (obj.name.startswith(prefixes) or fake_wood):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    objects = [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.data.polygons]
    if not objects:
        raise ValueError('No mesh surfaces found')
    surfaces = []
    source_count = len(objects)
    for obj in objects:
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for modifier in list(obj.modifiers):
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        loose = [vertex for vertex in mesh.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(mesh, geom=loose, context='VERTS')
        bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
        mesh.to_mesh(obj.data)
        mesh.free()
        points = [vertex.co for vertex in obj.data.vertices]
        low = [min(point[i] for point in points) for i in range(3)]
        high = [max(point[i] for point in points) for i in range(3)]
        attribute = obj.data.attributes.new('SurfaceCoord', 'FLOAT_VECTOR', 'POINT')
        for vertex, value in zip(obj.data.vertices, attribute.data):
            value.vector = tuple((vertex.co[i] - low[i]) / max(high[i] - low[i], 1e-8) for i in range(3))
        if not all(math.isfinite(value) for vertex in obj.data.vertices for value in vertex.co):
            raise ValueError(f'Invalid coordinates in {obj.name}')
        if not obj.data.materials:
            material = bpy.data.materials.new('Unspecified surface')
            obj.data.materials.append(material)
        for index, old in enumerate(list(obj.data.materials)):
            if old is None:
                old = bpy.data.materials.new('Unspecified surface')
            kind = category(obj, old)
            region = build(obj, old, kind, args.seed, args.wear, args.library)
            obj.data.materials[index] = region['material']
            surfaces.append(region)
    unwrap(objects)
    bpy.ops.object.select_all(action='DESELECT')
    for part in objects:
        part.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    objects = [bpy.context.object]
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.seed = args.seed
    images = bake(surfaces, args.resolution, dest, args.name)
    obj = assign(objects, images, args.name)
    uv_report = uv_overlap(obj)
    dimensions = list(obj.dimensions)
    vertices, faces = len(obj.data.vertices), len(obj.data.polygons)
    export(obj, dest, args.name)
    statistics = image_statistics(dest, args.name)
    glb = verify_glb(dest, args.name)
    obj = bpy.data.objects[args.name]
    if any(abs(actual - expected) > max(1e-5, expected * 1e-4) for actual, expected in zip(obj.dimensions, dimensions)):
        raise ValueError('BLEND dimensions changed on reopen')
    dayz = None
    if args.dayz_converter:
        from dayz_maps import prepare
        dayz = prepare(dest, args.name, args.dayz_converter, args.dayz_prefix, args.normal_green)
    render_files = [] if args.no_renders else renders(obj, dest)
    required = [args.name + extension for extension in ('.blend', '.glb', '.obj', '.mtl')]
    required += [args.name + '_' + key + '.png' for key in ('co', 'normal', 'roughness', 'metallic', 'ao', 'orm')]
    for name in required + render_files:
        if not (dest / name).is_file() or not (dest / name).stat().st_size:
            raise ValueError('Missing output: ' + name)
    report = dict(status='ok', version='3.0', seed=args.seed, wear=args.wear,
                  source=str(args.source), mesh_objects_merged=source_count, vertices=vertices, faces=faces,
                  dimensionsMeters=dimensions, removed_fake_wear_meshes=removed, uv=uv_report,
                  textures=statistics, glb=glb, renders=render_files,
                  surface_categories={kind: sum(region['kind'] == kind for region in surfaces) for kind in sorted({region['kind'] for region in surfaces})},
                  local_materials=[dict(manifest=region['library']['manifest'], license=region['library']['license'],
                                        source=region['library']['source']) for region in surfaces if region['library']],
                  dayz=dayz, readyForDayZ=False)
    (dest / 'validation.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('DAYZ_FINISH_OK', json.dumps(dict(status='ok', version='3.0', vertices=vertices, faces=faces)), flush=True)


run()

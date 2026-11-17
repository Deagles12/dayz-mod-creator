import json
import math
import struct
from pathlib import Path
import bpy
from mathutils import Vector


def models(obj, values, output, image):
    name = values['name']
    image.filepath = '//textures/' + name + '_co.png'
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=str(output / (name + '.glb')), export_format='GLB',
                              use_selection=True, export_image_format='AUTO', export_texcoords=True,
                              export_normals=True, export_materials='EXPORT')
    mesh = obj.data
    uv = mesh.uv_layers.active.data
    with (output / (name + '.obj')).open('w', encoding='utf-8') as file:
        file.write(f'mtllib {name}.mtl\no {name}\n')
        for vertex in mesh.vertices:
            file.write('v ' + ' '.join(f'{value:.9g}' for value in vertex.co) + '\n')
        for loop in uv:
            file.write(f'vt {loop.uv.x:.9g} {loop.uv.y:.9g}\n')
        for normal in mesh.corner_normals:
            file.write('vn ' + ' '.join(f'{value:.9g}' for value in normal.vector) + '\n')
        file.write('usemtl UV_atlas\n')
        for polygon in mesh.polygons:
            file.write('f ' + ' '.join(f'{mesh.loops[index].vertex_index + 1}/{index + 1}/{index + 1}'
                                       for index in polygon.loop_indices) + '\n')
    (output / (name + '.mtl')).write_text(
        f'newmtl UV_atlas\nKd 1 1 1\nmap_Kd textures/{name}_co.png\n', encoding='utf-8')
    return output / (name + '.glb')


def preview(obj, output):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 16
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.world = bpy.data.worlds.new('Studio')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value = (.08, .09, .11, 1)
    scene.world.node_tree.nodes.get('Background').inputs[1].default_value = .5
    radius = max(obj.dimensions)
    center = Vector((0, 0, obj.dimensions.z / 2))
    bpy.ops.object.camera_add(location=center + Vector((radius * 2, -radius * 3, radius * 1.7)))
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = radius * 1.5
    scene.camera = camera
    for offset, energy in [((1, -2, 3), 150), ((-2, -1, 1), 75)]:
        bpy.ops.object.light_add(type='AREA', location=center + Vector(offset) * radius)
        light = bpy.context.object
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy = energy * radius * radius
        light.data.shape = 'DISK'
        light.data.size = radius * 2
    scene.render.filepath = str(output / 'preview.png')
    bpy.ops.render.render(write_still=True)


def verify_glb(path):
    data = path.read_bytes()
    magic, version, length, json_size, chunk = struct.unpack_from('<4sIII4s', data)
    if (magic, version, length, chunk) != (b'glTF', 2, len(data), b'JSON'):
        raise ValueError('Invalid GLB')
    document = json.loads(data[20:20 + json_size])
    images = document.get('images', [])
    if len(images) != 1 or images[0].get('mimeType') != 'image/png' or 'bufferView' not in images[0]:
        raise ValueError('GLB must embed one PNG atlas')
    binary_offset = 20 + json_size
    binary_size, binary_type = struct.unpack_from('<I4s', data, binary_offset)
    if binary_type != b'BIN\0':
        raise ValueError('Missing GLB binary chunk')
    view = document['bufferViews'][images[0]['bufferView']]
    image_start = binary_offset + 8 + view.get('byteOffset', 0)
    if data[image_start:image_start + 8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Invalid embedded PNG')
    if any('TEXCOORD_0' not in primitive['attributes'] for mesh in document['meshes'] for primitive in mesh['primitives']):
        raise ValueError('GLB has no UV coordinates')
    for material in document['materials']:
        texture_index = material['pbrMetallicRoughness']['baseColorTexture']['index']
        if document['textures'][texture_index]['source'] != 0:
            raise ValueError('GLB material does not use its embedded atlas')
    return dict(embeddedPNG=True, uv=True, bytes=len(data), embeddedTextureBytes=view['byteLength'])


def verify_obj(path):
    counts = {'v': 0, 'vt': 0, 'vn': 0, 'f': 0}
    for line in path.read_text(encoding='utf-8').splitlines():
        fields = line.split()
        if not fields:
            continue
        kind = fields[0]
        if kind in ('v', 'vt', 'vn'):
            if not all(math.isfinite(float(value)) for value in fields[1:]):
                raise ValueError('Invalid OBJ coordinates')
            counts[kind] += 1
        elif kind == 'f':
            if len(fields) < 4:
                raise ValueError('OBJ face has fewer than three corners')
            for corner in fields[1:]:
                vertex, uv, normal = map(int, corner.split('/'))
                if not (1 <= vertex <= counts['v'] and 1 <= uv <= counts['vt'] and 1 <= normal <= counts['vn']):
                    raise ValueError('Invalid OBJ indices')
            counts['f'] += 1
    material = path.with_suffix('.mtl')
    texture_lines = [line[7:] for line in material.read_text(encoding='utf-8').splitlines() if line.startswith('map_Kd ')]
    if not all(counts.values()) or len(texture_lines) != 1 or not (path.parent / texture_lines[0]).is_file():
        raise ValueError('OBJ material has no valid texture path')
    return dict(vertices=counts['v'], uvCoordinates=counts['vt'], normals=counts['vn'], faces=counts['f'], texturePathsValid=True)

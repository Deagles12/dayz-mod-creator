import json
import math
import struct
import bpy
import numpy as np
from mathutils import Vector


def export(obj, destination, name):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.save_as_mainfile(filepath=str(destination / (name + '.blend')))
    bpy.ops.export_scene.gltf(filepath=str(destination / (name + '.glb')), export_format='GLB',
                              use_selection=True, export_materials='EXPORT')
    mesh = obj.data
    with (destination / (name + '.obj')).open('w', encoding='utf-8') as file:
        file.write(f'mtllib {name}.mtl\no {name}\n')
        for vertex in mesh.vertices:
            file.write('v ' + ' '.join(f'{value:.9g}' for value in vertex.co) + '\n')
        for uv in mesh.uv_layers.active.data:
            file.write(f'vt {uv.uv.x:.9g} {uv.uv.y:.9g}\n')
        for normal in mesh.corner_normals:
            file.write('vn ' + ' '.join(f'{value:.9g}' for value in normal.vector) + '\n')
        file.write('usemtl PBR\n')
        for polygon in mesh.polygons:
            file.write('f ' + ' '.join(f'{mesh.loops[index].vertex_index + 1}/{index + 1}/{index + 1}' for index in polygon.loop_indices) + '\n')
    (destination / (name + '.mtl')).write_text(
        f'newmtl PBR\nKd 1 1 1\nPr 0.6\nPm 0.5\nmap_Kd {name}_co.png\n'
        f'map_Pr {name}_roughness.png\nmap_Pm {name}_metallic.png\nnorm {name}_normal.png\n', encoding='utf-8')


def verify_glb(destination, name):
    path = destination / (name + '.glb')
    binary = path.read_bytes()
    magic, version, size, length, kind = struct.unpack_from('<4sIII4s', binary)
    if (magic, version, size, kind) != (b'glTF', 2, len(binary), b'JSON'):
        raise ValueError('Invalid GLB')
    data = json.loads(binary[20:20 + length])
    material = data['materials'][0]
    for entry in (material['pbrMetallicRoughness']['baseColorTexture'],
                  material['pbrMetallicRoughness']['metallicRoughnessTexture'],
                  material['normalTexture'], material['occlusionTexture']):
        image = data['images'][data['textures'][entry['index']]['source']]
        if image.get('mimeType') != 'image/png' or 'bufferView' not in image:
            raise ValueError('GLB PBR texture is not an embedded PNG')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if len(objects) != 1 or not objects[0].data.uv_layers.active or not objects[0].data.polygons:
        raise ValueError('GLB reimport has no textured geometry')
    shader = next(node for node in objects[0].active_material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    if not all(shader.inputs[key].is_linked for key in ('Base Color', 'Roughness', 'Metallic', 'Normal')):
        raise ValueError('GLB reimport lost a PBR input')
    bpy.ops.wm.open_mainfile(filepath=str(destination / (name + '.blend')))
    return dict(embeddedPBR=True, reimported=True, images=len(data['images']), bytes=len(binary))


def image_statistics(destination, name):
    result = {}
    color = bpy.data.images.load(str(destination / (name + '_co.png')), check_existing=False)
    values = np.array(color.pixels[:], dtype=np.float32).reshape((-1, 4))
    mask = values[:, 3] > .5
    if not np.any(mask):
        raise ValueError('Empty color atlas')
    for key in ('co', 'normal', 'roughness', 'metallic', 'ao'):
        image = bpy.data.images.load(str(destination / (name + '_' + key + '.png')), check_existing=False)
        if key != 'co':
            image.colorspace_settings.name = 'Non-Color'
        pixels = np.array(image.pixels[:], dtype=np.float32).reshape((-1, 4))[mask, :3]
        if not np.isfinite(pixels).all():
            raise ValueError(f'Non-finite texture: {key}')
        result[key] = dict(min=float(pixels.min()), max=float(pixels.max()),
                           std=[float(value) for value in pixels.std(axis=0)],
                           resolution=list(image.size), colorSpace=image.colorspace_settings.name)
        if key in ('co', 'normal', 'roughness') and float(pixels.std(axis=0).max()) < .002:
            raise ValueError(f'No real detail in {key} map')
    return result


def renders(obj, destination):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    scene.world = bpy.data.worlds.new('Inspection world')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value = (.12, .14, .17, 1)
    scene.world.node_tree.nodes.get('Background').inputs[1].default_value = .6
    points = [obj.matrix_world @ Vector(point) for point in obj.bound_box]
    low = Vector(min(point[i] for point in points) for i in range(3))
    high = Vector(max(point[i] for point in points) for i in range(3))
    center = (low + high) / 2
    radius = max(high - low)
    bpy.ops.mesh.primitive_plane_add(size=radius * 10, location=(0, 0, low.z - .008))
    floor = bpy.context.object
    floor_mat = bpy.data.materials.new('Preview floor')
    floor_mat.diffuse_color = (.09, .10, .11, 1)
    floor.data.materials.append(floor_mat)
    for location, energy, size in [((2, -3, 4), 650, 4), ((-2, 0, 2), 350, 3), ((1, 3, 3), 900, 2)]:
        bpy.ops.object.light_add(type='AREA', location=center + Vector(location) * radius / 2)
        light = bpy.context.object
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy = energy
        light.data.size = size
    workbench = 'workbench' in obj.name.lower()
    top_target = Vector((.1, 0, .90)) if workbench else center
    detail_target = Vector((.27, .02, .91)) if workbench else center
    views = [('front', center, Vector((1.6, -2.4, 1.3)) * radius, radius * 1.65),
             ('rear', center, Vector((-1.8, 2.2, 1.2)) * radius, radius * 1.65),
             ('top', top_target, Vector((.1, -.2, 1.4)) * radius, radius * 1.12),
             ('detail', detail_target, Vector((.40, -.72, .82)) * radius / 1.8, radius * .58)]
    for name, target, offset, scale in views:
        bpy.ops.object.camera_add(location=target + offset)
        camera = bpy.context.object
        camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type = 'ORTHO'
        camera.data.ortho_scale = scale
        scene.camera = camera
        scene.render.filepath = str(destination / ('render_' + name + '.png'))
        bpy.ops.render.render(write_still=True)
    return ['render_' + name + '.png' for name, *_ in views]

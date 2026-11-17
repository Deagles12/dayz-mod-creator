"""Bake material regions into a single PNG atlas, including a glass alpha mask."""
from pathlib import Path
import bpy
import numpy as np


def linear(value):
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def rgb(color):
    return tuple(linear(int(color[index:index + 2], 16) / 255) for index in (1, 3, 5))


def materials(values):
    result = []
    for name, color in [('Body', values['bodyColor']), ('Cap', values['capColor'])]:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.diffuse_color = (*rgb(color), 1)
        tree = material.node_tree
        tree.nodes.clear()
        output = tree.nodes.new('ShaderNodeOutputMaterial')
        emission = tree.nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = (*rgb(color), 1)
        tree.links.new(emission.outputs[0], output.inputs['Surface'])
        result.append(material)
    return result


def atlas(obj, values, output):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.render.bake.margin = max(4, values['resolution'] // 128)
    size = values['resolution']
    image = bpy.data.images.new(values['name'] + '_co', width=size, height=size, alpha=True)
    image.generated_color = (0, 0, 0, 0)
    slots = []
    for material in obj.data.materials:
        node = material.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        material.node_tree.nodes.active = node
        slots.append(node)
    bpy.ops.object.bake(type='EMIT')
    pixels = np.empty(size * size * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape((-1, 4))
    # Bake alpha separately so cap and glass retain distinct opacity in one atlas.
    alpha = bpy.data.images.new('Opacity mask', width=size, height=size, alpha=False)
    alpha.colorspace_settings.name = 'Non-Color'
    opacity = .4 if values['material'] == 'clear' else .85 if values['material'] == 'amber' else 1.0
    for index, material in enumerate(obj.data.materials):
        emission = next(node for node in material.node_tree.nodes if node.type == 'EMISSION')
        amount = opacity if index == 0 else 1.0
        emission.inputs['Color'].default_value = (amount, amount, amount, 1)
        slots[index].image = alpha
    bpy.ops.object.bake(type='EMIT')
    mask = np.empty(size * size * 4, dtype=np.float32)
    alpha.pixels.foreach_get(mask)
    pixels[:, 3] = mask.reshape((-1, 4))[:, 0]
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    texture_dir = output / 'textures'
    texture_dir.mkdir()
    path = texture_dir / (values['name'] + '_co.png')
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    image.pack()
    material = bpy.data.materials.new('UV atlas')
    material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Roughness'].default_value = .22 if values['material'] in ('amber', 'clear') else .5
    node = material.node_tree.nodes.new('ShaderNodeTexImage')
    node.image = image
    material.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
    material.node_tree.links.new(node.outputs['Alpha'], shader.inputs['Alpha'])
    if opacity < 1:
        material.surface_render_method = 'DITHERED'
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.material_index = 0
    bpy.data.images.remove(alpha)
    return image, path


def verify_atlas(image, values):
    saved = bpy.data.images.load(image.filepath_raw, check_existing=False)
    pixels = np.empty(len(saved.pixels), dtype=np.float32)
    saved.pixels.foreach_get(pixels)
    bpy.data.images.remove(saved)
    pixels = pixels.reshape((-1, 4))
    counts = {}
    for key in ('bodyColor', 'capColor'):
        encoded = np.array([int(values[key][index:index + 2], 16) / 255 for index in (1, 3, 5)])
        matching = np.max(np.abs(pixels[:, :3] - encoded), axis=1) < .015
        counts[key] = int(np.count_nonzero(matching & (pixels[:, 3] > .1)))
    if not all(counts.values()):
        raise ValueError(f'The UV atlas does not contain both material regions: {counts}')
    return dict(regionPixels=counts, pixels=int(len(pixels)), alphaRange=[float(pixels[:, 3].min()), float(pixels[:, 3].max())])

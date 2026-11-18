"""Bake all source material regions before joining meshes."""
import bpy
import numpy as np


def unwrap(objects):
    for obj in objects:
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for layer in list(obj.data.uv_layers):
            obj.data.uv_layers.remove(layer)
        obj.data.uv_layers.new(name='AtlasUV')
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=.02)
        bpy.ops.object.mode_set(mode='OBJECT')
        source = obj.data.uv_layers.active
        local = obj.data.uv_layers.new(name='LibraryUV')
        for target, old in zip(local.data, source.data):
            target.uv = old.uv
        obj.data.uv_layers.active_index = 0
        obj.data.uv_layers[0].active_render = True
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=True, margin_method='FRACTION', margin=.004)
    bpy.ops.object.mode_set(mode='OBJECT')


def image(name, resolution, color=False):
    result = bpy.data.images.new(name, width=resolution, height=resolution, alpha=True, float_buffer=False)
    result.colorspace_settings.name = 'sRGB' if color else 'Non-Color'
    result.generated_color = (0, 0, 0, 0)
    return result


def pixels(image):
    values = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(values)
    return values.reshape((-1, 4))


def bake(regions, resolution, destination, name):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 8
    scene.render.bake.margin = max(4, resolution // 512)
    scene.render.bake.use_clear = False
    result = {}
    for key in ('co', 'normal', 'roughness', 'metallic', 'ao'):
        print('BAKING', key, flush=True)
        target = image(name + '_' + key, resolution, color=key == 'co')
        emissions = []
        for region in regions:
            material = region['material']
            tree = material.node_tree
            region['target'].image = target
            tree.nodes.active = region['target']
            for link in list(region['output'].inputs['Surface'].links):
                tree.links.remove(link)
            if key == 'normal':
                tree.links.new(region['shader'].outputs[0], region['output'].inputs['Surface'])
            else:
                emission = tree.nodes.new('ShaderNodeEmission')
                emissions.append((tree, emission))
                value = region['color' if key == 'co' else key]
                if key == 'ao':
                    tree.links.new(value, emission.inputs['Color'])
                elif value.is_linked:
                    tree.links.new(value.links[0].from_socket, emission.inputs['Color'])
                else:
                    constant = value.default_value
                    emission.inputs['Color'].default_value = (constant, constant, constant, 1) if isinstance(constant, (int, float)) else constant
                tree.links.new(emission.outputs[0], region['output'].inputs['Surface'])
        if key == 'normal':
            bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT', use_clear=False)
        else:
            bpy.ops.object.bake(type='EMIT', use_clear=False)
        for tree, emission in emissions:
            tree.nodes.remove(emission)
        target.filepath_raw = str(destination / (name + '_' + key + '.png'))
        target.file_format = 'PNG'
        target.save()
        result[key] = target
    orm = image(name + '_orm', resolution)
    values = np.ones((resolution * resolution, 4), dtype=np.float32)
    values[:, 0] = pixels(result['ao'])[:, 0]
    values[:, 1] = pixels(result['roughness'])[:, 0]
    values[:, 2] = pixels(result['metallic'])[:, 0]
    orm.pixels.foreach_set(values.ravel())
    orm.filepath_raw = str(destination / (name + '_orm.png'))
    orm.file_format = 'PNG'
    orm.save()
    result['orm'] = orm
    return result


def assign(objects, images, name):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
        # Only the final atlas UV belongs in the exported model.
        local = obj.data.uv_layers.get('LibraryUV')
        if local:
            obj.data.uv_layers.remove(local)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    material = bpy.data.materials.new(name + '_PBR')
    material.use_nodes = True
    tree = material.node_tree
    shader = tree.nodes.get('Principled BSDF')
    textures = {}
    for key, image in images.items():
        image.pack()
        image.filepath = '//' + name + '_' + key + '.png'
        node = tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        textures[key] = node
    tree.links.new(textures['co'].outputs['Color'], shader.inputs['Base Color'])
    split = tree.nodes.new('ShaderNodeSeparateColor')
    tree.links.new(textures['orm'].outputs['Color'], split.inputs['Color'])
    tree.links.new(split.outputs['Green'], shader.inputs['Roughness'])
    tree.links.new(split.outputs['Blue'], shader.inputs['Metallic'])
    normal = tree.nodes.new('ShaderNodeNormalMap')
    normal.uv_map = 'AtlasUV'
    tree.links.new(textures['normal'].outputs['Color'], normal.inputs['Color'])
    tree.links.new(normal.outputs['Normal'], shader.inputs['Normal'])
    group = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
    group.interface.new_socket(name='Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
    hook = tree.nodes.new('ShaderNodeGroup')
    hook.node_tree = group
    tree.links.new(split.outputs['Red'], hook.inputs['Occlusion'])
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.material_index = 0
    return obj

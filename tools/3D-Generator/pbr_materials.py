"""Geometry-anchored procedural surfaces and optional local photographic maps."""
import hashlib
import json
from pathlib import Path
import bpy

CATEGORIES = ('Painted Metal', 'Rusted Steel', 'Weathered Wood', 'Dirty Fabric', 'Tin Metal', 'Rubber')


def category(obj, material):
    text = (obj.name + ' ' + material.name).lower()
    if any(word in text for word in ('grip', 'rubber')):
        return 'Rubber'
    if any(word in text for word in ('wood', 'plank', 'board')):
        return 'Weathered Wood'
    if any(word in text for word in ('rag', 'cloth', 'fabric', 'paper', 'debris')):
        return 'Dirty Fabric'
    if any(word in text for word in ('tin', 'can open', 'hollow can')):
        return 'Tin Metal'
    if any(word in text for word in ('green', 'tabletop', 'paint', 'cabinet', 'apron')):
        return 'Painted Metal'
    if any(word in text for word in ('steel', 'metal', 'pliers', 'hinge', 'bracket', 'rust', 'leg', 'brace')):
        return 'Rusted Steel'
    return 'Generic'


def linear(color):
    values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    return tuple(value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in values)


class Graph:
    def __init__(self, material):
        self.tree = material.node_tree
        self.tree.nodes.clear()

    def node(self, kind):
        return self.tree.nodes.new(kind)

    def feed(self, value, socket):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, operation, a, b=0):
        node = self.node('ShaderNodeMath')
        node.operation = operation
        self.feed(a, node.inputs[0])
        self.feed(b, node.inputs[1])
        return node.outputs[0]

    def ramp(self, value, low, high):
        node = self.node('ShaderNodeValToRGB')
        node.color_ramp.elements[0].position = low
        node.color_ramp.elements[1].position = high
        self.feed(value, node.inputs[0])
        return node.outputs['Color']

    def mix(self, factor, a, b):
        node = self.node('ShaderNodeMixRGB')
        self.feed(factor, node.inputs[0])
        self.feed(a, node.inputs[1])
        self.feed(b, node.inputs[2])
        return node.outputs[0]

    def vector(self, value, scale):
        node = self.node('ShaderNodeVectorMath')
        node.operation = 'MULTIPLY'
        self.feed(value, node.inputs[0])
        node.inputs[1].default_value = scale
        return node.outputs['Vector']

    def noise(self, coordinate, scale, detail=3):
        node = self.node('ShaderNodeTexNoise')
        node.noise_dimensions = '3D'
        self.feed(coordinate, node.inputs['Vector'])
        node.inputs['Scale'].default_value = scale
        node.inputs['Detail'].default_value = detail
        node.inputs['Roughness'].default_value = .72
        return node.outputs['Fac']


def local_maps(root, kind):
    directory = Path(root) / kind
    manifests = sorted(directory.glob('*/material.json')) + sorted(directory.glob('material.json'))
    if not manifests:
        return None
    manifest = manifests[0]
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if not data.get('license') or not data.get('source'):
        raise ValueError(f'Local material needs license and source: {manifest}')
    maps = {}
    for key, value in data.get('maps', {}).items():
        path = (manifest.parent / value).resolve(strict=True)
        if not path.is_relative_to(manifest.parent.resolve()):
            raise ValueError(f'Material image outside its directory: {path}')
        maps[key] = path
    if 'baseColor' not in maps:
        raise ValueError(f'Local material has no baseColor map: {manifest}')
    return dict(manifest=str(manifest), maps=maps, license=data['license'], source=data['source'],
                scale=float(data.get('scale', 1)))


def build(obj, old, kind, seed, wear, library):
    material = bpy.data.materials.new(obj.name + '_' + kind)
    material.use_nodes = True
    graph = Graph(material)
    coord = graph.node('ShaderNodeAttribute')
    coord.attribute_name = 'SurfaceCoord'
    generated = coord.outputs['Vector']
    geometry = graph.node('ShaderNodeNewGeometry')
    position = geometry.outputs['Position']
    offset = graph.node('ShaderNodeVectorMath')
    offset.operation = 'ADD'
    graph.feed(position, offset.inputs[0])
    hashed = int(hashlib.sha256((str(seed) + obj.name + old.name).encode()).hexdigest()[:8], 16)
    offset.inputs[1].default_value = ((hashed % 113) / 17, (hashed % 97) / 13, (hashed % 61) / 11)
    position = offset.outputs['Vector']
    broad = graph.noise(position, 7)
    medium = graph.noise(position, 65)
    fine = graph.noise(position, 700, 2)
    separate = graph.node('ShaderNodeSeparateXYZ')
    graph.feed(generated, separate.inputs[0])
    distances = []
    for axis, size in zip(('X', 'Y', 'Z'), obj.dimensions):
        value = separate.outputs[axis]
        distance = graph.math('MINIMUM', value, graph.math('SUBTRACT', 1, value))
        distances.append(graph.math('MULTIPLY', distance, max(size, .001)))
    # Median of three face-bound distances isolates edges rather than entire flat faces.
    dx, dy, dz = distances
    median = graph.math('MAXIMUM', graph.math('MINIMUM', dx, dy),
                        graph.math('MAXIMUM', graph.math('MINIMUM', dx, dz), graph.math('MINIMUM', dy, dz)))
    edge = graph.math('SUBTRACT', 1, graph.ramp(median, .001, .012))
    pointiness = graph.ramp(geometry.outputs['Pointiness'], .505, .58)
    edge = graph.math('MAXIMUM', edge, graph.math('MULTIPLY', pointiness, .15))
    ao_node = graph.node('ShaderNodeAmbientOcclusion')
    ao_node.inputs['Distance'].default_value = .09
    ao_node.samples = 8
    ao = ao_node.outputs['AO']
    cavity = graph.math('SUBTRACT', 1, ao)
    gravity = graph.math('SUBTRACT', 1, separate.outputs['Z'])
    dirt = graph.math('MULTIPLY', graph.math('MAXIMUM', cavity, graph.math('MULTIPLY', gravity, .22)),
                      graph.ramp(broad, .35, .75))
    chips = graph.math('MULTIPLY', graph.math('MULTIPLY', edge, graph.ramp(medium, .40, .70)), wear)
    rust = graph.math('MULTIPLY', graph.ramp(graph.math('ADD', graph.math('MULTIPLY', broad, .65),
                                                        graph.math('MULTIPLY', medium, .35)), .52, .73),
                      graph.math('MULTIPLY', graph.math('MAXIMUM', chips, graph.math('MULTIPLY', cavity, .8)), wear))
    color = linear('#3e5545' if 'tabletop' in obj.name.lower() or 'green' in old.name.lower() else '#3b443e')
    roughness = graph.math('ADD', .61, graph.math('MULTIPLY', medium, .14))
    metallic = graph.math('MULTIPLY', chips, .85)
    height = graph.math('MULTIPLY', fine, .25)
    if kind in ('Painted Metal', 'Rusted Steel', 'Tin Metal'):
        base = color if kind == 'Painted Metal' else linear('#343936' if kind == 'Rusted Steel' else '#8b908a')
        if kind != 'Painted Metal':
            rust = graph.math('MAXIMUM', rust, graph.math('MULTIPLY', graph.ramp(broad, .57, .77), wear * .45))
            metallic = graph.math('SUBTRACT', .92, graph.math('MULTIPLY', rust, .88))
            roughness = graph.math('ADD', .28 if kind == 'Tin Metal' else .39, graph.math('MULTIPLY', medium, .18))
        variation = graph.mix(broad, tuple(value * .68 for value in base) + (1,),
                              tuple(value * 1.12 for value in base) + (1,))
        exposed = graph.mix(chips, variation, (*linear('#777b73'), 1))
        oxide = graph.mix(medium, (*linear('#281b13'), 1), (*linear('#795236'), 1))
        color = graph.mix(rust, exposed, oxide)
        color = graph.mix(graph.math('MULTIPLY', dirt, .5), color, (*linear('#25251f'), 1))
        roughness = graph.math('ADD', roughness, graph.math('MULTIPLY', rust, .32))
        height = graph.math('ADD', height, graph.math('MULTIPLY', rust, fine))
        scratch_coord = graph.vector(position, (70, 2, 20))
        scratches = graph.ramp(graph.noise(scratch_coord, 12, 2), .70, .77)
        height = graph.math('SUBTRACT', height, graph.math('MULTIPLY', scratches, .35 * wear))
    elif kind == 'Weathered Wood':
        grain_coordinate = graph.vector(position, (160, 2.5, 130))
        grain = graph.noise(grain_coordinate, 2.5, 4)
        veins = graph.ramp(grain, .28, .70)
        color = graph.mix(veins, (*linear('#34291c'), 1), (*linear('#8b7252'), 1))
        crack = graph.math('SUBTRACT', 1, graph.ramp(grain, .23, .32))
        color = graph.mix(crack, color, (*linear('#171711'), 1))
        color = graph.mix(graph.math('MULTIPLY', dirt, .45), color, (*linear('#29251a'), 1))
        roughness = graph.math('ADD', .68, graph.math('MULTIPLY', grain, .24))
        metallic = 0
        height = graph.math('SUBTRACT', graph.math('MULTIPLY', grain, .5), graph.math('MULTIPLY', crack, .9))
    elif kind == 'Dirty Fabric':
        warp = graph.node('ShaderNodeTexWave')
        warp.bands_direction = 'X'
        graph.feed(position, warp.inputs['Vector'])
        warp.inputs['Scale'].default_value = 850
        weft = graph.node('ShaderNodeTexWave')
        weft.bands_direction = 'Y'
        graph.feed(position, weft.inputs['Vector'])
        weft.inputs['Scale'].default_value = 850
        weave = graph.math('MULTIPLY', warp.outputs['Fac'], weft.outputs['Fac'])
        color = graph.mix(broad, (*linear('#514b39'), 1), (*linear('#8c8265'), 1))
        oil = graph.math('MAXIMUM', dirt, graph.math('MULTIPLY', graph.ramp(medium, .59, .78), wear * .7))
        color = graph.mix(oil, color, (*linear('#2e3027'), 1))
        roughness = graph.math('ADD', .79, graph.math('MULTIPLY', weave, .13))
        metallic = 0
        height = graph.math('ADD', graph.math('MULTIPLY', weave, .3), graph.math('MULTIPLY', medium, .3))
    elif kind == 'Rubber':
        color = graph.mix(medium, (*linear('#32201c'), 1), (*linear('#674136'), 1))
        color = graph.mix(dirt, color, (*linear('#1c201a'), 1))
        roughness = graph.math('ADD', .65, graph.math('MULTIPLY', fine, .2))
        metallic = 0
    elif kind == 'Generic':
        previous = next((node for node in old.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'), None) if old.use_nodes else None
        base = tuple(previous.inputs['Base Color'].default_value) if previous else tuple(old.diffuse_color)
        color = graph.mix(broad, tuple(value * .85 for value in base[:3]) + (1,), base)
        roughness = previous.inputs['Roughness'].default_value if previous else .6
        metallic = previous.inputs['Metallic'].default_value if previous else 0
    local = local_maps(library, kind)
    library_normal = None
    if local:
        library_uv = graph.node('ShaderNodeUVMap')
        library_uv.uv_map = 'LibraryUV'
        mapping = graph.vector(library_uv.outputs['UV'], (local['scale'],) * 3)
        for key, path in local['maps'].items():
            texture = graph.node('ShaderNodeTexImage')
            texture.image = bpy.data.images.load(str(path), check_existing=True)
            texture.image.colorspace_settings.name = 'sRGB' if key == 'baseColor' else 'Non-Color'
            graph.feed(mapping, texture.inputs['Vector'])
            if key == 'baseColor':
                color = graph.mix(graph.math('MULTIPLY', dirt, .5), texture.outputs['Color'], color)
            elif key == 'roughness':
                roughness = texture.outputs['Color']
            elif key == 'metallic':
                metallic = texture.outputs['Color']
            elif key == 'normal':
                normal = graph.node('ShaderNodeNormalMap')
                normal.uv_map = 'LibraryUV'
                graph.feed(texture.outputs['Color'], normal.inputs['Color'])
                library_normal = normal.outputs['Normal']
            elif key == 'ao':
                ao = graph.math('MULTIPLY', ao, texture.outputs['Color'])
    shader = graph.node('ShaderNodeBsdfPrincipled')
    graph.feed(color, shader.inputs['Base Color'])
    graph.feed(roughness, shader.inputs['Roughness'])
    graph.feed(metallic, shader.inputs['Metallic'])
    bump = graph.node('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .45
    bump.inputs['Distance'].default_value = .0015 if kind == 'Weathered Wood' else .0007
    graph.feed(height, bump.inputs['Height'])
    if library_normal is not None:
        graph.feed(library_normal, bump.inputs['Normal'])
    graph.feed(bump.outputs['Normal'], shader.inputs['Normal'])
    output = graph.node('ShaderNodeOutputMaterial')
    graph.feed(shader.outputs[0], output.inputs['Surface'])
    target = graph.node('ShaderNodeTexImage')
    graph.tree.nodes.active = target
    return dict(material=material, shader=shader, output=output, target=target,
                color=shader.inputs['Base Color'], roughness=shader.inputs['Roughness'],
                metallic=shader.inputs['Metallic'], ao=ao, library=local, kind=kind)

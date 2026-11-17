"""Deterministic meshes in metres, with the base on Z=0."""
import math
import bpy


def assign(obj, material):
    obj.data.materials.clear()
    obj.data.materials.append(material)
    return obj


def rounded_box(name, size, location, radius, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = obj.modifiers.new('Rounded corners', 'BEVEL')
    bevel.width = radius
    bevel.segments = 3
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return assign(obj, material)


def lathe(name, profile, depth_ratio, material, ribs=False):
    segments = 96
    vertices = []
    for radius, height in profile:
        for index in range(segments):
            angle = index * math.tau / segments
            adjusted = radius * (1 + (.035 if index % 2 else 0)) if ribs else radius
            vertices.append((adjusted * math.cos(angle), adjusted * math.sin(angle) * depth_ratio, height))
    faces = []
    faces.append(tuple(reversed(range(segments))))
    for ring in range(len(profile) - 1):
        for index in range(segments):
            a = ring * segments + index
            b = ring * segments + (index + 1) % segments
            faces.append((a, b, b + segments, a + segments))
    faces.append(tuple(range((len(profile) - 1) * segments, len(profile) * segments)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth = len(polygon.vertices) == 4
    return assign(obj, material)


def bottle(values, body, cap):
    w, h, d = (values[key] / 1000 for key in ('width', 'height', 'depth'))
    cw, ch = values['capWidth'] / 1000, values['capHeight'] / 1000
    neck = min(cw * .43, w * .24)
    shoulder = h - ch - max(ch * .7, h * .14)
    obj = lathe('Body', [(w * .43, 0), (w * .48, h * .015), (w * .5, h * .045),
                         (w * .5, shoulder * .90), (w * .48, shoulder),
                         (w * .39, shoulder + (h - ch - shoulder) * .45),
                         (neck, h - ch - ch * .18), (neck, h - ch * .8)], d / w, body)
    lid = lathe('Ribbed cap', [(cw * .46, h - ch), (cw * .48, h - ch * .94),
                              (cw * .48, h - ch * .06), (cw * .44, h)], 1, cap, ribs=True)
    return [obj, lid], None


def canister(values, body, cap):
    w, h, d = (values[key] / 1000 for key in ('width', 'height', 'depth'))
    cw, ch = values['capWidth'] / 1000, values['capHeight'] / 1000
    radius = min(w, h, d) * .07
    obj = rounded_box('Canister body', (w, d, h * .77), (0, 0, h * .385), radius, body)
    handle = rounded_box('Handle', (w * .55, d * .35, h * .29),
                         (w * .17, 0, h * .855), radius * .65, body)
    cutter = rounded_box('Handle opening', (w * .34, d * .8, h * .145),
                         (w * .17, 0, h * .865), radius * .4, body)
    bpy.context.view_layer.objects.active = handle
    boolean = handle.modifiers.new('Through hole', 'BOOLEAN')
    boolean.operation = 'DIFFERENCE'
    boolean.solver = 'EXACT'
    boolean.object = cutter
    bpy.ops.object.modifier_apply(modifier=boolean.name)
    bpy.data.objects.remove(cutter, do_unlink=True)
    bpy.context.view_layer.objects.active = obj
    union = obj.modifiers.new('Integrated handle', 'BOOLEAN')
    union.operation = 'UNION'
    union.solver = 'EXACT'
    union.object = handle
    bpy.ops.object.modifier_apply(modifier=union.name)
    bpy.data.objects.remove(handle, do_unlink=True)
    lid = lathe('Cap', [(cw * .46, h * .77), (cw * .48, h * .77 + ch * .1),
                       (cw * .48, h * .77 + ch * .9), (cw * .44, h * .77 + ch)], 1, cap, ribs=True)
    lid.location.x = -w * .30
    # A segment passing through the opening must have no intersection with the body.
    hole = {'x': w * .17, 'z': h * .865, 'depth': d * 2}
    return [obj, lid], hole


BUILDERS = {'bottle': bottle, 'canister': canister}


def create(values, materials):
    parts, hole = BUILDERS[values['template']](values, *materials)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in parts:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = values['name']
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # Enforce the user-facing bounding dimensions after bevels and ribs.
    requested = [values['width'] / 1000, values['depth'] / 1000, values['height'] / 1000]
    factors = [requested[index] / obj.dimensions[index] for index in range(3)]
    for vertex in obj.data.vertices:
        for index in range(3):
            vertex.co[index] *= factors[index]
    obj.data.update()
    if hole:
        hole['x'] *= factors[0]
        hole['z'] *= factors[2]
        hole['depth'] *= factors[1]
    return obj, hole

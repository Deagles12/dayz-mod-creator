import math
import bpy
import bmesh


def unwrap(obj):
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    for edge in bm.edges:
        edge.seam = len(edge.link_faces) != 2 or edge.calc_face_angle(0) > math.radians(55)
    bm.to_mesh(mesh)
    bm.free()
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.025, correct_aspect=True)
    bpy.ops.uv.pack_islands(rotate=True, margin_method='FRACTION', margin=.012)
    bpy.ops.object.mode_set(mode='OBJECT')

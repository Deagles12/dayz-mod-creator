from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import struct

import bpy
from mathutils import Vector


source, stage, converter, prefix, stem = sys.argv[sys.argv.index("--") + 1:]
stage = Path(stage)


def progress(step):
    with (stage.parent / "progress").open("a", encoding="ascii") as file:
        file.write(f"{step}\n")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
parts = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if len(parts) != 1:
    raise ValueError("Expected a single textured mesh from the ComfyUI workflow.")
obj = parts[0]
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if not obj.data.uv_layers.active or len(obj.data.materials) != 1:
    raise ValueError("The GLB needs UVs and one Base Color material.")
material = obj.data.materials[0]
shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
links = shader.inputs["Base Color"].links
img = links[0].from_node.image if links and links[0].from_node.type == "TEX_IMAGE" else None
if img is None or not img.packed_file or not img.packed_file.data.startswith(b"\x89PNG\r\n\x1a\n"):
    raise ValueError("Expected the Base Color to be embedded as PNG in the GLB.")

bounds = list(map(Vector, obj.bound_box))
low = Vector(min(p[i] for p in bounds) for i in range(3))
high = Vector(max(p[i] for p in bounds) for i in range(3))
origin = (high + low) / 2
extent = max(high - low)
if extent <= 0:
    raise ValueError("Model is empty.")

progress(2)
data = stage / "data"
data.mkdir()
texture_name = stem + "_co"
with tempfile.TemporaryDirectory(prefix="dayz-paa-") as temp:
    scratch = Path(temp)
    png = scratch / (texture_name + ".png")
    paa = scratch / (texture_name + ".paa")
    png.write_bytes(img.packed_file.data)
    subprocess.run([converter, png.name, paa.name], cwd=scratch, check=True, timeout=60)
    with paa.open("rb") as file:
        if file.read(2) not in (b"\x01\xff", b"\x03\xff", b"\x05\xff"):
            raise ValueError("ImageToPAA did not return a recognized PAA texture.")
    shutil.copyfile(paa, data / paa.name)

texture = f"{prefix}\\{stem}\\data\\{texture_name}.paa"
progress(3)
lods = []
for level, budget in ((1, 10000), (2, 4500), (3, 1800)):
    obj.data.calc_loop_triangles()
    count = len(obj.data.loop_triangles)
    if count > budget:
        decimate = obj.modifiers.new("DayZ visual LOD", "DECIMATE")
        decimate.ratio = budget / count
        decimate.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=decimate.name)
    mesh = obj.data
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles or len(mesh.loop_triangles) > 10922:
        raise ValueError("The visual LOD exceeds its triangle budget.")
    lods.append((level, mesh.copy()))

with (stage / (stem + ".p3d")).open("wb") as out:
    out.write(struct.pack("<4sII", b"MLOD", 257, len(lods)))
    for level, mesh in lods:
        mesh.calc_loop_triangles()
        uv = mesh.uv_layers.active.data
        out.write(struct.pack("<4s6I", b"P3DM", 28, 256, len(mesh.vertices),
                              len(mesh.corner_normals), len(mesh.loop_triangles), 0))
        for vertex in mesh.vertices:
            x, y, z = vertex.co - origin
            out.write(struct.pack("<3fI", x, z, y, 0))
        for normal in mesh.corner_normals:
            x, y, z = normal.vector
            out.write(struct.pack("<3f", -x, -z, -y))
        for triangle in mesh.loop_triangles:
            out.write(struct.pack("<I", 3))
            for vertex, corner in zip(triangle.vertices, triangle.loops):
                u, v = uv[corner].uv
                out.write(struct.pack("<IIff", vertex, corner, u, 1 - v))
            out.write(bytes(20))
            out.write(texture.encode("ascii") + b"\0\0")
        out.write(b"TAGG\x01#EndOfFile#\0")
        out.write(struct.pack("<If", 0, level))

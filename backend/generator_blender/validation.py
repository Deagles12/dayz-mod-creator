import math
import bpy
import bmesh
from mathutils import Vector


def inspect(obj, expected):
    mesh = obj.data
    mesh.calc_loop_triangles()
    if not mesh.vertices or not mesh.polygons or not mesh.uv_layers.active:
        raise ValueError('Mesh needs faces and UV coordinates')
    if not all(math.isfinite(value) for vertex in mesh.vertices for value in vertex.co):
        raise ValueError('Non-finite vertex coordinates')
    if not all(math.isfinite(value) and -.0001 <= value <= 1.0001
               for loop in mesh.uv_layers.active.data for value in loop.uv):
        raise ValueError('Invalid UV coordinates')
    if any(face.area <= 1e-14 or not all(math.isfinite(value) for value in face.normal) or face.normal.length < .99
           for face in mesh.polygons):
        raise ValueError('Degenerate faces or invalid normals')
    corners = [obj.matrix_world @ Vector(point) for point in obj.bound_box]
    dimensions = [max(point[i] for point in corners) - min(point[i] for point in corners) for i in range(3)]
    target = [expected[key] / 1000 for key in ('width', 'depth', 'height')]
    if any(abs(actual - requested) > max(.00001, requested * .002) for actual, requested in zip(dimensions, target)):
        raise ValueError(f'Dimension mismatch: {dimensions} / {target}')
    bm = bmesh.new()
    bm.from_mesh(mesh)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()
    if non_manifold:
        raise ValueError(f'Non-manifold geometry: {non_manifold} edges')
    materials = list(mesh.materials)
    if len(materials) != 1:
        raise ValueError('Expected a single atlas material')
    images = [node.image for node in materials[0].node_tree.nodes if node.type == 'TEX_IMAGE' and node.image]
    if not images:
        raise ValueError('Material has no Image Texture')
    return dict(vertices=len(mesh.vertices), polygons=len(mesh.polygons), triangles=len(mesh.loop_triangles),
                dimensionsMM=[round(value * 1000, 5) for value in (dimensions[0], dimensions[2], dimensions[1])],
                uv=True, imageTexture=True, materials=len(materials), nonManifoldEdges=non_manifold,
                normalsValid=True)


def handle_open(obj, hole):
    if hole is None:
        return None
    origin = Vector((hole['x'], -hole['depth'], hole['z']))
    end = Vector((hole['x'], hole['depth'], hole['z']))
    inverse = obj.matrix_world.inverted()
    local_origin, local_end = inverse @ origin, inverse @ end
    direction = local_end - local_origin
    hit, *_ = obj.ray_cast(local_origin, direction.normalized(), distance=direction.length)
    if hit:
        raise ValueError('Canister handle opening is obstructed')
    return True


def uv_overlap(obj):
    """Count positive-area UV intersections using a spatial grid and polygon clipping."""
    mesh = obj.data
    mesh.calc_loop_triangles()
    data = mesh.uv_layers.active.data
    triangles = [[tuple(data[index].uv) for index in triangle.loops] for triangle in mesh.loop_triangles]
    cells = {}
    checked = set()
    overlaps = 0

    def cross(a, b, point):
        return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])

    def intersection_area(subject, clip):
        if cross(clip[0], clip[1], clip[2]) < 0:
            clip = clip[::-1]
        polygon = subject[:]
        for a, b in zip(clip, clip[1:] + clip[:1]):
            incoming, polygon = polygon, []
            if not incoming:
                return 0
            previous = incoming[-1]
            distance_previous = cross(a, b, previous)
            for point in incoming:
                distance = cross(a, b, point)
                if (distance >= 0) != (distance_previous >= 0):
                    factor = distance_previous / (distance_previous - distance)
                    polygon.append(tuple(previous[i] + factor * (point[i] - previous[i]) for i in (0, 1)))
                if distance >= 0:
                    polygon.append(point)
                previous, distance_previous = point, distance
        return abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2

    for index, triangle in enumerate(triangles):
        x0, x1 = (int(min(point[0] for point in triangle) * 32), int(max(point[0] for point in triangle) * 32))
        y0, y1 = (int(min(point[1] for point in triangle) * 32), int(max(point[1] for point in triangle) * 32))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                cell = cells.setdefault((x, y), [])
                for other in cell:
                    pair = (other, index)
                    if pair not in checked:
                        checked.add(pair)
                        if intersection_area(triangle, triangles[other]) > 1e-10:
                            overlaps += 1
                cell.append(index)
    if overlaps:
        raise ValueError(f'Overlapping UV triangles: {overlaps}')
    return dict(overlappingTriangles=overlaps, uvTriangles=len(triangles))

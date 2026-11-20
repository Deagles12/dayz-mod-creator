"""Shared UV overlap validation for the archive finisher."""

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

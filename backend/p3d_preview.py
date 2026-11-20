"""Read geometry for the Studio viewer from editable P3DM models."""
from array import array
from base64 import b64encode
from io import BytesIO
import math
from pathlib import Path
import struct
import sys

from locale_studio import tr


def invalid_p3d():
    return ValueError(tr('P3D пошкоджений або неповний.', 'The P3D file is invalid or incomplete.'))


def preview_p3d(value):
    limit = 64 * 1024**2
    path = Path(value)
    if path.suffix.lower() != '.p3d' or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(tr('Вибери P3D розміром до 64 МБ.', 'Choose a P3D file of up to 64 MB.'))
    try:
        with path.open('rb') as file:
            data = file.read(limit + 1)
    except OSError as error:
        raise ValueError(tr('Не вдалося прочитати P3D.', 'Could not read the P3D file.')) from error
    if len(data) > limit:
        raise ValueError(tr('Вибери P3D розміром до 64 МБ.', 'Choose a P3D file of up to 64 MB.'))

    stream = BytesIO(data)

    def read(size):
        result = stream.read(size)
        if len(result) != size:
            raise invalid_p3d()
        return result

    def unpack(layout):
        return struct.unpack(layout, read(struct.calcsize(layout)))

    def skip(size):
        if size > len(data) - stream.tell():
            raise invalid_p3d()
        stream.seek(size, 1)

    def string():
        start = stream.tell()
        end = data.find(b'\0', start, start + 4096)
        if end < 0:
            raise invalid_p3d()
        stream.seek(end + 1)
        return data[start:end]

    signature = read(4)
    if signature == b'ODOL':
        raise ValueError(tr('Цей P3D бінаризований (ODOL). Для огляду потрібен вихідний P3D у форматі MLOD.',
                            'This P3D is binarized (ODOL). Open the editable MLOD source file.'))
    if signature != b'MLOD':
        raise invalid_p3d()
    version, count = unpack('<II')
    if version != 257:
        raise ValueError(tr('Ця версія MLOD не підтримується.', 'This MLOD version is unsupported.'))
    if not 0 < count <= min(1024, (len(data) - stream.tell()) // 28):
        raise invalid_p3d()

    lods = []
    for _ in range(count):
        magic, major, minor, points, normals, faces, _flags = unpack('<4s6I')
        if (magic, major, minor) != (b'P3DM', 28, 256):
            raise ValueError(tr('Для огляду потрібні LOD у форматі P3DM.', 'The viewer requires P3DM LODs.'))
        if points * 16 + normals * 12 + faces * 74 > len(data) - stream.tell():
            raise invalid_p3d()
        positions = bytearray()
        for _ in range(points):
            point = read(16)
            if not all(map(math.isfinite, struct.unpack_from('<3f', point))):
                raise invalid_p3d()
            positions.extend(point[:12])
        skip(normals * 12)

        indices = array('I')
        for _ in range(faces):
            corners, = unpack('<I')
            if corners not in (3, 4):
                raise invalid_p3d()
            vertices = []
            for _ in range(corners):
                vertex, normal, _u, _v = unpack('<IIff')
                if vertex >= points or normal >= normals:
                    raise invalid_p3d()
                vertices.append(vertex)
            skip((4 - corners) * 16 + 4)
            string()  # texture path
            string()  # material path
            # P3D faces are clockwise. Three.js expects counterclockwise triangles.
            indices.extend((vertices[0], vertices[2], vertices[1]))
            if corners == 4:
                indices.extend((vertices[0], vertices[3], vertices[2]))

        if read(4) != b'TAGG':
            raise invalid_p3d()
        while True:
            read(1)  # tag activation flag
            name = string()
            size, = unpack('<I')
            skip(size)
            if name == b'#EndOfFile#':
                break
        resolution, = unpack('<f')
        if not math.isfinite(resolution):
            raise invalid_p3d()
        if sys.byteorder == 'big':
            indices.byteswap()
        lods.append({
            'resolution': resolution, 'vertices': points, 'faces': faces, 'triangles': len(indices) // 3,
            'positions': b64encode(positions).decode('ascii'),
            'indices': b64encode(indices).decode('ascii'),
        })

    if stream.read(1):
        raise invalid_p3d()
    if not any(lod['vertices'] for lod in lods):
        raise ValueError(tr('У файлі немає вершин для огляду.', 'The file contains no vertices to display.'))
    return lods

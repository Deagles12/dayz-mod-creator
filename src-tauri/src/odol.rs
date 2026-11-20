//! Read only the geometry needed to display a DayZ ODOL v53–56 model.
//! Layout reference: https://github.com/bzed/dayzmake/blob/main/docs/superpowers/specs/2026-11-16-odol-v56-layout.md

use base64::{engine::general_purpose::STANDARD, Engine};
use serde::Serialize;
use std::{
    borrow::Cow,
    fs::File,
    io::{Cursor, Read},
    path::Path,
};

const FILE_LIMIT: usize = 64 * 1024 * 1024;
const ARRAY_LIMIT: usize = 8 * 1024 * 1024;
const FORMAT_ERROR: &str = "invalid";
type Result<T> = std::result::Result<T, &'static str>;

#[derive(Serialize)]
pub struct Lod {
    resolution: f32,
    vertices: usize,
    faces: usize,
    triangles: usize,
    positions: String,
    indices: String,
}

struct Reader<'a> {
    bytes: &'a [u8],
    budget: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, size: usize) -> Result<&'a [u8]> {
        let (head, rest) = self.bytes.split_at_checked(size).ok_or(FORMAT_ERROR)?;
        self.bytes = rest;
        Ok(head)
    }

    fn skip(&mut self, size: usize) -> Result<()> {
        self.take(size).map(|_| ())
    }

    fn byte(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn u16(&mut self) -> Result<usize> {
        Ok(u16::from_le_bytes(self.take(2)?.try_into().unwrap()) as usize)
    }

    fn u32(&mut self) -> Result<usize> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()) as usize)
    }

    fn count(&mut self, limit: usize) -> Result<usize> {
        let count = self.u32()?;
        (count <= limit).then_some(count).ok_or(FORMAT_ERROR)
    }

    fn string(&mut self) -> Result<&'a [u8]> {
        let end = self
            .bytes
            .iter()
            .take(65536)
            .position(|&byte| byte == 0)
            .ok_or(FORMAT_ERROR)?;
        let content = self.take(end)?;
        self.skip(1)?;
        Ok(content)
    }

    fn array(&mut self, count: usize, width: usize) -> Result<Cow<'a, [u8]>> {
        let size = count
            .checked_mul(width)
            .filter(|&size| size <= ARRAY_LIMIT)
            .ok_or(FORMAT_ERROR)?;
        if size < 1024 {
            return Ok(Cow::Borrowed(self.take(size)?));
        }
        self.budget = self.budget.checked_sub(size).ok_or(FORMAT_ERROR)?;
        let mut compressed = Cursor::new(self.bytes);
        let bytes =
            lzokay_native::decompress_bounded(&mut compressed, size).map_err(|_| FORMAT_ERROR)?;
        self.skip(compressed.position() as usize)?;
        if bytes.len() != size {
            return Err(FORMAT_ERROR);
        }
        Ok(Cow::Owned(bytes))
    }

    fn skip_array(&mut self, width: usize) -> Result<()> {
        let count = self.u32()?;
        self.array(count, width).map(|_| ())
    }

    fn skip_condensed(&mut self, width: usize) -> Result<()> {
        let count = self.u32()?;
        match self.byte()? {
            0 => self.array(count, width).map(|_| ()),
            1 => self.skip(width),
            _ => Err(FORMAT_ERROR),
        }
    }

    fn skip_strings(&mut self, limit: usize) -> Result<()> {
        for _ in 0..self.count(limit)? {
            self.string()?;
        }
        Ok(())
    }
}

fn skip_model_info(reader: &mut Reader<'_>, version: usize) -> Result<()> {
    // Bounds, centers and inertia, render flags, and the thermal profile.
    reader.skip(if version == 56 { 216 } else { 212 })?;
    if !reader.string()?.is_empty() {
        reader.skip(1)?;
        for _ in 0..reader.count(65536)? {
            reader.string()?;
            reader.string()?;
        }
        reader.string()?;
    }
    reader.skip(1)?;
    reader.skip_array(4)?; // point masses
    reader.skip(if version == 53 { 33 } else { 34 })?;
    reader.string()?;
    reader.string()?;
    reader.skip(if version >= 55 { 2 } else { 1 })?;
    reader.skip_strings(65536)
}

fn skip_animations(reader: &mut Reader<'_>, lods: usize) -> Result<()> {
    let mut kinds = Vec::new();
    for _ in 0..reader.count(10000)? {
        let kind = reader.count(9)?;
        reader.string()?;
        reader.string()?;
        reader.skip(
            20 + match kind {
                8 => 32,
                9 => 4,
                _ => 8,
            },
        )?;
        kinds.push(kind);
    }
    let mappings = reader.count(lods)?;
    if mappings != 0 && mappings != lods {
        return Err(FORMAT_ERROR);
    }
    for _ in 0..mappings {
        for _ in 0..reader.count(65536)? {
            let links = reader.count(kinds.len())?;
            reader.skip(4 * links)?;
        }
    }
    for _ in 0..mappings {
        for &kind in &kinds {
            if reader.u32()? != u32::MAX as usize && kind < 8 {
                reader.skip(24)?;
            }
        }
    }
    Ok(())
}

fn lod_ranges(file: &[u8], reader: &mut Reader<'_>, count: usize) -> Result<Vec<(usize, usize)>> {
    let table_end = file.len() - reader.bytes.len() + 9 * count;
    let starts = (0..count)
        .map(|_| reader.u32())
        .collect::<Result<Vec<_>>>()?;
    let mut ranges = Vec::with_capacity(count);
    for start in starts {
        let end = reader.u32()?;
        if start < table_end || start >= file.len() || start >= end || end > file.len() + 16 {
            return Err(FORMAT_ERROR);
        }
        ranges.push((start, end));
    }
    if reader.take(count)?.iter().any(|&flag| flag > 1) {
        return Err(FORMAT_ERROR);
    }
    let mut sorted = ranges.clone();
    sorted.sort_unstable();
    if sorted.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return Err(FORMAT_ERROR);
    }
    Ok(ranges)
}

fn skip_material(reader: &mut Reader<'_>) -> Result<()> {
    reader.string()?;
    let fields = match reader.u32()? {
        15 => 140,
        16 => 156,
        20 => 204,
        _ => return Err(FORMAT_ERROR),
    };
    reader.skip(fields + 16)?; // lighting and shader fields
    reader.string()?;
    reader.skip(8)?;
    let stages = reader.count(128)?;
    let transforms = reader.count(128)?;
    for _ in 0..stages {
        skip_texture_stage(reader)?;
    }
    reader.skip(52 * transforms)?;
    skip_texture_stage(reader) // final default stage
}

fn skip_texture_stage(reader: &mut Reader<'_>) -> Result<()> {
    reader.skip(4)?;
    reader.string()?;
    reader.skip(5)
}

fn load_lod(
    reader: &mut Reader<'_>,
    resolution: f32,
    declared_size: usize,
    budget: &mut usize,
) -> Result<Lod> {
    let available = reader.bytes.len();
    for _ in 0..reader.count(65536)? {
        reader.string()?;
        reader.skip(64)?; // proxy transform and links
    }
    let links = reader.count(65536)?;
    reader.skip(4 * links)?;
    for _ in 0..reader.count(65536)? {
        let links = reader.count(65536)?;
        reader.skip(4 * links)?;
    }
    let vertex_hint = reader.count(ARRAY_LIMIT / 12)?;
    let width = if vertex_hint > u16::MAX as usize {
        4
    } else {
        2
    };
    reader.skip(52)?; // area, hints and bounds
    reader.skip_strings(65536)?;
    for _ in 0..reader.count(65536)? {
        skip_material(reader)?;
    }
    reader.skip_array(4)?; // point to vertex
    reader.skip_array(4)?; // vertex to point

    let faces = reader.count((reader.bytes.len() / 7).min(*budget / 12))?;
    let face_bytes = reader.u32()?;
    reader.skip(2)?;
    let mut indices = Vec::new();
    let mut size = 0;
    let mut max_index = 0;
    for _ in 0..faces {
        let corners = reader.byte()?;
        if !matches!(corners, 3 | 4) {
            return Err(FORMAT_ERROR);
        }
        *budget = budget
            .checked_sub(if corners == 3 { 12 } else { 24 })
            .ok_or(FORMAT_ERROR)?;
        let mut points = [0; 4];
        for point in &mut points[..corners as usize] {
            *point = if width == 4 {
                reader.u32()?
            } else {
                reader.u16()?
            };
            max_index = max_index.max(*point);
        }
        for point in [points[0], points[1], points[2]] {
            indices.extend_from_slice(&(point as u32).to_le_bytes());
        }
        if corners == 4 {
            for point in [points[0], points[2], points[3]] {
                indices.extend_from_slice(&(point as u32).to_le_bytes());
            }
        }
        // The engine's face table accounts for a two-byte corner count.
        size += 2 + width * corners as usize;
    }
    if size != face_bytes {
        return Err(FORMAT_ERROR);
    }
    for _ in 0..reader.count(65536)? {
        reader.skip(26)?;
        if reader.u32()? == u32::MAX as usize {
            reader.string()?;
        }
        let stages = reader.count(128)?;
        reader.skip(4 * stages)?;
    }
    for _ in 0..reader.count(65536)? {
        reader.string()?;
        reader.skip_array(width)?;
        reader.skip(5)?;
        reader.skip_array(4)?;
        reader.skip_array(width)?;
        reader.skip_array(1)?;
    }
    for _ in 0..reader.count(65536)? {
        reader.string()?;
        reader.string()?;
    }
    for _ in 0..reader.count(65536)? {
        reader.skip(4)?;
        let points = reader.count(ARRAY_LIMIT / 12)?;
        reader.skip(12 * points)?;
    }
    reader.skip(13)?;
    let rest_offset = available - reader.bytes.len();
    let tail = reader.u32()?;
    let tail_end = rest_offset.checked_add(tail).ok_or(FORMAT_ERROR)?;
    if !(declared_size.saturating_sub(16)..=declared_size).contains(&tail_end) || tail < 4 {
        return Err(FORMAT_ERROR);
    }
    reader.bytes = &reader.bytes[..reader.bytes.len().min(tail - 4)];
    reader.skip_condensed(4)?; // vertex clip flags
    reader.skip(16)?; // bounds of the primary UV set
    reader.skip_condensed(4)?;
    for _ in 1..reader.count(32)? {
        reader.skip(16)?;
        reader.skip_condensed(4)?;
    }
    let vertices = reader.count(ARRAY_LIMIT / 12)?;
    *budget = budget.checked_sub(vertices * 12).ok_or(FORMAT_ERROR)?;
    let positions = reader.array(vertices, 12)?;
    if (faces > 0 && max_index >= vertices)
        || positions
            .chunks_exact(4)
            .any(|chunk| !f32::from_le_bytes(chunk.try_into().unwrap()).is_finite())
    {
        return Err(FORMAT_ERROR);
    }
    Ok(Lod {
        resolution,
        vertices,
        faces,
        triangles: indices.len() / 12,
        positions: STANDARD.encode(positions),
        indices: STANDARD.encode(indices),
    })
}

fn parse(file: &[u8], version: usize) -> Result<Vec<Lod>> {
    let mut reader = Reader {
        bytes: file.get(8..).ok_or(FORMAT_ERROR)?,
        budget: FILE_LIMIT * 2,
    };
    let count = reader.count(1024)?;
    if count == 0 {
        return Err(FORMAT_ERROR);
    }
    let resolutions = reader
        .take(4 * count)?
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes(chunk.try_into().unwrap()));
    skip_model_info(&mut reader, version)?;
    let after_info = reader.bytes;
    // Older DayZ tools wrote the animation section both with and without a flag byte.
    let layouts = if version == 56 {
        &[(true, true), (true, false)][..]
    } else {
        &[(true, true), (true, false), (false, true), (false, false)]
    };
    let ranges = layouts
        .iter()
        .find_map(|&(has_flag, animated)| {
            reader.bytes = after_info;
            if has_flag && reader.byte().ok()? != u8::from(animated) {
                return None;
            }
            if animated {
                skip_animations(&mut reader, count).ok()?;
            }
            lod_ranges(file, &mut reader, count).ok()
        })
        .ok_or(FORMAT_ERROR)?;
    let mut budget = FILE_LIMIT;
    let mut lods = Vec::with_capacity(count);
    for ((start, end), resolution) in ranges.into_iter().zip(resolutions) {
        if !resolution.is_finite() {
            return Err(FORMAT_ERROR);
        }
        reader.bytes = &file[start..end.min(file.len())];
        lods.push(load_lod(&mut reader, resolution, end - start, &mut budget)?);
    }
    if !lods.iter().any(|lod| lod.vertices > 0) {
        return Err("empty");
    }
    Ok(lods)
}

fn open_odol(path: &Path) -> std::result::Result<Option<Vec<Lod>>, String> {
    let mut file = File::open(path).map_err(|_| "read")?;
    if !file.metadata().map_err(|_| "read")?.is_file() {
        return Err("read".into());
    }
    let mut signature = [0; 4];
    if file.read_exact(&mut signature).is_err() || &signature != b"ODOL" {
        return Ok(None);
    }
    let mut version = [0; 4];
    file.read_exact(&mut version).map_err(|_| FORMAT_ERROR)?;
    let version = u32::from_le_bytes(version) as usize;
    if !(53..=56).contains(&version) {
        return Err(format!("version:{version}"));
    }
    if file.metadata().map_err(|_| "read")?.len() > FILE_LIMIT as u64 {
        return Err("size".into());
    }
    let mut data = Vec::from([0; 8]);
    file.take((FILE_LIMIT - 7) as u64)
        .read_to_end(&mut data)
        .map_err(|_| "read")?;
    if data.len() > FILE_LIMIT {
        return Err("size".into());
    }
    Ok(Some(parse(&data, version)?))
}

#[tauri::command]
pub async fn preview_odol(path: String) -> std::result::Result<Option<Vec<Lod>>, String> {
    tauri::async_runtime::spawn_blocking(move || open_odol(Path::new(&path)))
        .await
        .map_err(|_| FORMAT_ERROR)?
}

#[cfg(test)]
mod tests {
    use super::*;

    fn quad(version: u32, last_index: u16) -> Vec<u8> {
        let mut lod = Vec::from([0; 12]); // proxies, items and bone links
        lod.extend(4u32.to_le_bytes());
        lod.extend([0; 68]); // bounds and empty texture, material, and reference arrays
        lod.extend(1u32.to_le_bytes());
        lod.extend(10u32.to_le_bytes());
        lod.extend([0, 0, 4]); // reserved word and corner count
        for index in [0u16, 1, 2, last_index] {
            lod.extend(index.to_le_bytes());
        }
        lod.extend([0; 29]); // sections, selections, properties, frames and flags
        let mut rest = Vec::from([0; 26]); // empty clip and primary UV arrays
        rest.extend(1u32.to_le_bytes());
        rest.extend(4u32.to_le_bytes());
        for vertex in [[0f32, 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]] {
            for coord in vertex {
                rest.extend(coord.to_le_bytes());
            }
        }
        lod.extend(((rest.len() + 4) as u32).to_le_bytes());
        lod.extend(rest);

        let mut file = Vec::from(*b"ODOL");
        file.extend(version.to_le_bytes());
        file.extend(1u32.to_le_bytes());
        file.extend(1f32.to_le_bytes());
        file.resize(file.len() + if version == 56 { 216 } else { 212 }, 0);
        file.extend([0; 6]); // empty skeleton, map type and mass array
        file.resize(file.len() + if version == 53 { 33 } else { 34 }, 0);
        file.extend([0; 7]); // class, damage, frequent and property strings
        if version >= 55 {
            file.push(0);
        }
        if version != 53 {
            file.push(0); // no animations flag
        }
        let start = file.len() + 9;
        file.extend((start as u32).to_le_bytes());
        file.extend(((start + lod.len()) as u32).to_le_bytes());
        file.push(1);
        file.extend(lod);
        file
    }

    #[test]
    fn reads_quad_geometry_in_each_supported_version() {
        for version in 53..=56 {
            let lods = parse(&quad(version, 3), version as usize).unwrap();
            let lod = &lods[0];
            assert_eq!((lod.vertices, lod.faces, lod.triangles), (4, 1, 2));
            assert_eq!(STANDARD.decode(&lod.positions).unwrap().len(), 48);
            let indices = [0u32, 1, 2, 0, 2, 3]
                .into_iter()
                .flat_map(u32::to_le_bytes)
                .collect::<Vec<_>>();
            assert_eq!(STANDARD.decode(&lod.indices).unwrap(), indices);
        }
    }

    #[test]
    fn rejects_bad_indices_and_truncated_geometry() {
        assert!(parse(&quad(56, 4), 56).is_err());
        let model = quad(56, 3);
        assert!(parse(&model[..model.len() - 12], 56).is_err());
    }
}

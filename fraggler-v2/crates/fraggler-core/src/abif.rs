use std::collections::BTreeMap;
use std::fs;
use std::io::Read;

use byteorder::{BigEndian, ReadBytesExt};
use camino::{Utf8Path, Utf8PathBuf};

use crate::engine::EngineError;

#[derive(Debug, Clone, PartialEq)]
pub enum AbifValue {
    Bytes(Vec<u8>),
    String(String),
    I16(Vec<i16>),
    I32(Vec<i32>),
    U16(Vec<u16>),
    F32(Vec<f32>),
    F64(Vec<f64>),
    Bool(bool),
    Raw(Vec<u8>),
}

impl AbifValue {
    pub fn as_i16_slice(&self) -> Option<&[i16]> {
        match self {
            Self::I16(values) => Some(values.as_slice()),
            _ => None,
        }
    }

    pub fn as_string(&self) -> Option<&str> {
        match self {
            Self::String(value) => Some(value.as_str()),
            _ => None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct AbifRecord {
    pub path: Utf8PathBuf,
    pub file_name: String,
    pub tags: BTreeMap<String, AbifValue>,
}

impl AbifRecord {
    pub fn from_path(path: &Utf8Path) -> Result<Self, EngineError> {
        let bytes = fs::read(path).map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read abif file",
            source,
        })?;
        let tags = parse_abif_bytes(&bytes, path)?;
        let file_name = path
            .file_name()
            .map(ToOwned::to_owned)
            .unwrap_or_else(|| path.as_str().to_owned());
        Ok(Self {
            path: path.to_owned(),
            file_name,
            tags,
        })
    }

    pub fn data_channels(&self) -> Vec<String> {
        self.tags
            .iter()
            .filter_map(|(key, value)| {
                if key.starts_with("DATA") && value.as_i16_slice().is_some() {
                    Some(key.clone())
                } else {
                    None
                }
            })
            .collect()
    }

    pub fn channel_values(&self, key: &str) -> Option<Vec<f64>> {
        self.tags
            .get(key)
            .and_then(AbifValue::as_i16_slice)
            .map(|values| values.iter().map(|value| *value as f64).collect())
    }

    pub fn string_value(&self, key: &str) -> Option<&str> {
        self.tags.get(key).and_then(AbifValue::as_string)
    }
}

#[derive(Debug, Clone)]
struct DirectoryEntry {
    tag_name: String,
    tag_number: u32,
    element_code: u16,
    element_num: u32,
    data_size: usize,
    data_offset: usize,
}

fn parse_abif_bytes(
    bytes: &[u8],
    path: &Utf8Path,
) -> Result<BTreeMap<String, AbifValue>, EngineError> {
    if bytes.len() < 4 || &bytes[0..4] != b"ABIF" {
        return Err(EngineError::InvalidAbif {
            path: path.to_owned(),
            message: "missing ABIF marker".to_owned(),
        });
    }

    let mut cursor = std::io::Cursor::new(&bytes[4..]);
    let _version = cursor
        .read_u16::<BigEndian>()
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF version",
            source,
        })?;
    let mut _root_tag = [0_u8; 4];
    cursor
        .read_exact(&mut _root_tag)
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF root tag",
            source,
        })?;
    let _root_tag_number = cursor
        .read_u32::<BigEndian>()
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF root tag number",
            source,
        })?;
    let _root_element_code = cursor
        .read_u16::<BigEndian>()
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF root element code",
            source,
        })?;
    let _root_element_size = cursor
        .read_u16::<BigEndian>()
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF root element size",
            source,
        })?;
    let root_element_num = cursor
        .read_u32::<BigEndian>()
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF root element count",
            source,
        })?;
    let _root_data_size = cursor
        .read_u32::<BigEndian>()
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF root data size",
            source,
        })?;
    let root_data_offset = cursor
        .read_u32::<BigEndian>()
        .map_err(|source| EngineError::Io {
            path: path.to_owned(),
            context: "read ABIF root data offset",
            source,
        })?;

    let directory_count = root_element_num as usize;
    // Directory records are always 28 bytes. Per the ABIF specification,
    // readers use the root count and offset and ignore its other fields.
    let directory_size = 28;
    let directory_start = root_data_offset as usize;
    if directory_start > bytes.len()
        || directory_count > (bytes.len() - directory_start) / directory_size
    {
        return Err(EngineError::InvalidAbif {
            path: path.to_owned(),
            message: "directory points outside the file".to_owned(),
        });
    }
    let mut tags = BTreeMap::new();

    for index in 0..directory_count {
        let start = root_data_offset as usize + index * directory_size;
        if start + 28 > bytes.len() {
            return Err(EngineError::InvalidAbif {
                path: path.to_owned(),
                message: format!("directory entry {index} points outside the file"),
            });
        }

        let mut dir_cursor = std::io::Cursor::new(&bytes[start..start + 28]);
        let mut tag_buf = [0_u8; 4];
        dir_cursor
            .read_exact(&mut tag_buf)
            .map_err(|source| EngineError::Io {
                path: path.to_owned(),
                context: "read ABIF directory tag",
                source,
            })?;
        let tag_name = String::from_utf8_lossy(&tag_buf).to_string();
        let tag_number = dir_cursor
            .read_u32::<BigEndian>()
            .map_err(|source| EngineError::Io {
                path: path.to_owned(),
                context: "read ABIF directory tag number",
                source,
            })?;
        let element_code =
            dir_cursor
                .read_u16::<BigEndian>()
                .map_err(|source| EngineError::Io {
                    path: path.to_owned(),
                    context: "read ABIF element code",
                    source,
                })?;
        let _element_size =
            dir_cursor
                .read_u16::<BigEndian>()
                .map_err(|source| EngineError::Io {
                    path: path.to_owned(),
                    context: "read ABIF element size",
                    source,
                })?;
        let element_num = dir_cursor
            .read_u32::<BigEndian>()
            .map_err(|source| EngineError::Io {
                path: path.to_owned(),
                context: "read ABIF element count",
                source,
            })?;
        let data_size = dir_cursor
            .read_u32::<BigEndian>()
            .map_err(|source| EngineError::Io {
                path: path.to_owned(),
                context: "read ABIF data size",
                source,
            })? as usize;
        let mut data_offset =
            dir_cursor
                .read_u32::<BigEndian>()
                .map_err(|source| EngineError::Io {
                    path: path.to_owned(),
                    context: "read ABIF data offset",
                    source,
                })? as usize;

        if data_size <= 4 {
            data_offset = start + 20;
        }

        if data_offset + data_size > bytes.len() {
            return Err(EngineError::InvalidAbif {
                path: path.to_owned(),
                message: format!(
                    "tag {tag_name}{tag_number} points outside the file (offset={data_offset}, size={data_size})"
                ),
            });
        }

        let entry = DirectoryEntry {
            tag_name,
            tag_number,
            element_code,
            element_num,
            data_size,
            data_offset,
        };
        let numeric_element_size = match entry.element_code {
            3 | 4 => Some(2),
            5 | 7 => Some(4),
            8 => Some(8),
            _ => None,
        };
        if let Some(element_size) = numeric_element_size {
            // Validate before allocating from the untrusted element count.
            // ABIF permits padding, so the payload may be larger than needed.
            if entry.element_num as usize > entry.data_size / element_size {
                return Err(EngineError::InvalidAbif {
                    path: path.to_owned(),
                    message: format!(
                        "tag {}{} has too few bytes for {} numeric elements",
                        entry.tag_name, entry.tag_number, entry.element_num
                    ),
                });
            }
        }
        let raw = &bytes[entry.data_offset..entry.data_offset + entry.data_size];
        let key = format!("{}{}", entry.tag_name, entry.tag_number);
        tags.insert(
            key,
            parse_tag_data(entry.element_code, entry.element_num, raw),
        );
    }

    Ok(tags)
}

fn parse_tag_data(element_code: u16, element_num: u32, raw: &[u8]) -> AbifValue {
    let count = element_num as usize;
    match element_code {
        1 => AbifValue::Raw(raw.to_vec()),
        2 => decode_string(raw, count),
        3 => {
            let mut cursor = std::io::Cursor::new(raw);
            let mut values = Vec::with_capacity(count);
            for _ in 0..count {
                if let Ok(value) = cursor.read_u16::<BigEndian>() {
                    values.push(value);
                }
            }
            AbifValue::U16(values)
        }
        4 => {
            let mut cursor = std::io::Cursor::new(raw);
            let mut values = Vec::with_capacity(count);
            for _ in 0..count {
                if let Ok(value) = cursor.read_i16::<BigEndian>() {
                    values.push(value);
                }
            }
            AbifValue::I16(values)
        }
        5 => {
            let mut cursor = std::io::Cursor::new(raw);
            let mut values = Vec::with_capacity(count);
            for _ in 0..count {
                if let Ok(value) = cursor.read_i32::<BigEndian>() {
                    values.push(value);
                }
            }
            AbifValue::I32(values)
        }
        7 => {
            let mut cursor = std::io::Cursor::new(raw);
            let mut values = Vec::with_capacity(count);
            for _ in 0..count {
                if let Ok(value) = cursor.read_f32::<BigEndian>() {
                    values.push(value);
                }
            }
            AbifValue::F32(values)
        }
        8 => {
            let mut cursor = std::io::Cursor::new(raw);
            let mut values = Vec::with_capacity(count);
            for _ in 0..count {
                if let Ok(value) = cursor.read_f64::<BigEndian>() {
                    values.push(value);
                }
            }
            AbifValue::F64(values)
        }
        10 => {
            if raw.len() >= 4 {
                let year = u16::from_be_bytes([raw[0], raw[1]]);
                let month = raw[2];
                let day = raw[3];
                AbifValue::String(format!("{year:04}-{month:02}-{day:02}"))
            } else {
                AbifValue::Raw(raw.to_vec())
            }
        }
        11 => {
            if raw.len() >= 3 {
                AbifValue::String(format!("{:02}:{:02}:{:02}", raw[0], raw[1], raw[2]))
            } else {
                AbifValue::Raw(raw.to_vec())
            }
        }
        13 => AbifValue::Bool(raw.first().copied().unwrap_or_default() != 0),
        18 => {
            let string_bytes = if raw.is_empty() { raw } else { &raw[1..] };
            AbifValue::String(String::from_utf8_lossy(string_bytes).to_string())
        }
        19 => {
            let string_bytes = if raw.is_empty() {
                raw
            } else {
                &raw[..raw.len().saturating_sub(1)]
            };
            AbifValue::String(String::from_utf8_lossy(string_bytes).to_string())
        }
        _ => AbifValue::Raw(raw.to_vec()),
    }
}

fn decode_string(raw: &[u8], count: usize) -> AbifValue {
    if count == 1 {
        AbifValue::Bytes(raw.to_vec())
    } else {
        AbifValue::String(String::from_utf8_lossy(raw).to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::{AbifValue, parse_abif_bytes};
    use camino::Utf8Path;

    fn file_with_short_tags(count: u32, data_size: u32, directory_stride: u16) -> Vec<u8> {
        let mut bytes = b"ABIF".to_vec();
        bytes.extend(101_u16.to_be_bytes());
        bytes.extend(b"tdir");
        bytes.extend(1_u32.to_be_bytes());
        bytes.extend(1023_u16.to_be_bytes());
        bytes.extend(directory_stride.to_be_bytes());
        bytes.extend(2_u32.to_be_bytes());
        bytes.extend(56_u32.to_be_bytes());
        bytes.extend(34_u32.to_be_bytes());
        bytes.extend(0_u32.to_be_bytes());
        for tag_number in [4_u32, 5_u32] {
            bytes.extend(b"DATA");
            bytes.extend(tag_number.to_be_bytes());
            bytes.extend(4_u16.to_be_bytes());
            bytes.extend(2_u16.to_be_bytes());
            bytes.extend(count.to_be_bytes());
            bytes.extend(data_size.to_be_bytes());
            bytes.extend([0_u8, 1, 0, 2]);
            bytes.extend(0_u32.to_be_bytes());
        }
        bytes
    }

    #[test]
    fn truncated_numeric_payload_is_rejected() {
        let bytes = file_with_short_tags(3, 4, 28);
        assert!(parse_abif_bytes(&bytes, Utf8Path::new("truncated.fsa")).is_err());
    }

    #[test]
    fn numeric_payload_padding_is_permitted() {
        let bytes = file_with_short_tags(1, 4, 28);
        let tags = parse_abif_bytes(&bytes, Utf8Path::new("padded.fsa")).unwrap();
        assert_eq!(tags["DATA4"], AbifValue::I16(vec![1]));
    }

    #[test]
    fn directory_records_use_fixed_abif_stride() {
        // ABIF readers use the header's count/offset; its other directory
        // fields are advisory and cannot change the 28-byte record format.
        let bytes = file_with_short_tags(2, 4, 0);
        let tags = parse_abif_bytes(&bytes, Utf8Path::new("directory.fsa")).unwrap();
        assert_eq!(tags["DATA4"], AbifValue::I16(vec![1, 2]));
        assert_eq!(tags["DATA5"], AbifValue::I16(vec![1, 2]));
    }
}

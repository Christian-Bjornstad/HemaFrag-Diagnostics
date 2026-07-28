//! PyO3 wrapper exposing `fraggler-core` primitives to Python.
//!
//! Builds as a Python extension module named `_fraggler_native` (the
//! maturin-built wheel installs it under `fraggler_native`).
use std::path::PathBuf;

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use pyo3::exceptions::{PyFileNotFoundError, PyRuntimeError, PyValueError};
use serde_json::Value;

use fraggler_core::{analyze_fsa_primitives, AnalysisKind, EngineError};

fn engine_error_to_py(err: EngineError) -> PyErr {
    PyRuntimeError::new_err(format!("fraggler-core error: {}", err))
}

fn parse_analysis_kind(s: Option<&str>) -> PyResult<Option<AnalysisKind>> {
    let Some(raw) = s else { return Ok(None) };
    let lower = raw.to_ascii_lowercase();
    let kind = match lower.as_str() {
        "clonality" => AnalysisKind::Clonality,
        "flt3" | "flt3-itd" | "flt3_itd" => AnalysisKind::Flt3,
        "general" => AnalysisKind::General,
        other => {
            return Err(PyValueError::new_err(format!(
                "Unknown analysis_kind '{}' (expected clonality|flt3|general)",
                other
            )))
        }
    };
    Ok(Some(kind))
}

/// Run the Rust primitive analysis on a single FSA file and return a
/// Python dict.
#[pyfunction]
fn analyze_fsa<'py>(
    py: Python<'py>,
    path: &str,
    analysis_kind: Option<&str>,
) -> PyResult<Bound<'py, PyDict>> {
    let path_buf = PathBuf::from(path);
    if !path_buf.exists() {
        return Err(PyFileNotFoundError::new_err(format!(
            "FSA file not found: {}",
            path
        )));
    }

    let kind = parse_analysis_kind(analysis_kind)?;
    let utf8_path = camino::Utf8Path::new(path);

    let result = analyze_fsa_primitives(utf8_path, kind.as_ref()).map_err(engine_error_to_py)?;

    let value = serde_json::to_value(&result).map_err(|e| {
        PyRuntimeError::new_err(format!("convert PrimitiveAnalysisResult: {}", e))
    })?;

    let dict = PyDict::new(py);
    if let Value::Object(map) = value {
        for (k, v) in map.into_iter() {
            dict.set_item(k, json_to_py(py, v)?)?;
        }
    } else {
        return Err(PyRuntimeError::new_err(
            "PrimitiveAnalysisResult did not serialise as a JSON object",
        ));
    }
    Ok(dict)
}

/// Convert a `serde_json::Value` to an equivalent Python object.
fn json_to_py<'py>(py: Python<'py>, v: Value) -> PyResult<Bound<'py, PyAny>> {
    match v {
        Value::Null => Ok(py.None().into_bound(py)),
        Value::Bool(b) => {
            let bound = b.into_pyobject(py)?;
            Ok(bound.to_owned().into_any())
        }
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                let bound = i.into_pyobject(py)?;
                Ok(bound.to_owned().into_any())
            } else if let Some(f) = n.as_f64() {
                let bound = f.into_pyobject(py)?;
                Ok(bound.to_owned().into_any())
            } else {
                let bound = n.to_string().into_pyobject(py)?;
                Ok(bound.to_owned().into_any())
            }
        }
        Value::String(s) => {
            let bound = s.into_pyobject(py)?;
            Ok(bound.to_owned().into_any())
        }
        Value::Array(items) => {
            let list = PyList::empty(py);
            for item in items {
                list.append(json_to_py(py, item)?)?;
            }
            Ok(list.into_any())
        }
        Value::Object(map) => {
            let dict = PyDict::new(py);
            for (k, v) in map.into_iter() {
                dict.set_item(k, json_to_py(py, v)?)?;
            }
            Ok(dict.into_any())
        }
    }
}

/// Best-effort lookup of the standalone `fraggler-cli` binary.
#[pyfunction]
fn fraggler_cli_path() -> Option<String> {
    let candidates: &[&str] = if cfg!(target_os = "windows") {
        &["fraggler-cli.exe", "fraggler-cli"]
    } else {
        &["fraggler-cli"]
    };

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for c in candidates {
                let p = dir.join(c);
                if p.exists() {
                    return Some(p.to_string_lossy().into_owned());
                }
            }
        }
    }

    let here = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let workspace_root = here.parent().and_then(|p| p.parent()).map(|p| p.to_path_buf());
    if let Some(root) = workspace_root {
        for dir in [root.join("target").join("release"), root.join("target").join("debug")] {
            for c in candidates {
                let p = dir.join(c);
                if p.exists() {
                    return Some(p.to_string_lossy().into_owned());
                }
            }
        }
    }

    None
}

#[pyfunction]
fn is_available() -> bool {
    true
}

#[pymodule]
fn fraggler_native(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(analyze_fsa, m)?)?;
    m.add_function(wrap_pyfunction!(fraggler_cli_path, m)?)?;
    m.add_function(wrap_pyfunction!(is_available, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}

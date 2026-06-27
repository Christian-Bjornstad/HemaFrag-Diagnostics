"""HemaFrag — `rust_bridge` split package (code-cleanup Phase 6).

Re-exports the legacy public API of the previously-monolithic
`core/rust_bridge.py` module so existing
`from core.rust_bridge import X` statements keep working unchanged.

Submodules:
- `_constants`: ROX / GS500ROX / LIZ timing-window constants, internal
  Rust worker locks, result-cache size, engine-stats lock.
- `_legacy`:    the imports block plus the two helper classes
  `_RustSizingModel`, `_RustPrimitiveWorker` and 34 top-level helper
  functions for invoking the Rust `fraggler-cli`.
"""
from core.rust_bridge._constants import *  # noqa: F401,F403
from core.rust_bridge._legacy import *      # noqa: F401,F403

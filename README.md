# HemaFrag Diagnostics

Desktopverktøy for HemaFrag-analyse, ladder-QC og rapportflyt.

Repoet inneholder kildekoden for:
- Python/PyQt6 desktop-appen
- analyse- og rapportmotoren i `core/`
- Rust-motoren i `fraggler-v2/`
- packaging-oppsett for desktop-builds
- prosjektminne og arbeidslogg i `ObsidianVault/`

Dette holdes utenfor Git:
- rå `.fsa`-/kliniske data
- store `artifacts/`-mapper
- review bundles og scratch-output
- `build/`, `dist/` og Rust `target/`
- lokale runtime-binærer

## Viktig oppstart

Start alltid med a lese:
1. `memory.md`
2. `AGENTS.md`
3. `ObsidianVault/00_Start_Here.md`

Disse filene beskriver arbeidsregler, prosjektminne og hva som skal loggfores videre.

## Kjore appen fra source

```bash
cd /Users/christian/Desktop/HemaFrag
python3 qt_app.py
```

Rust-motoren bygges slik:

```bash
cd /Users/christian/Desktop/HemaFrag/fraggler-v2
cargo build --release
```

Legacy Panel-app finnes fortsatt og kan startes manuelt ved behov:

```bash
panel serve app.py --port 5078 --allow-websocket-origin=localhost:5078
```

## Bygge desktop-app

```bash
cd /Users/christian/Desktop/HemaFrag
./packaging/build_mac.sh
```

For Linux og Windows brukes skriptene i `packaging/`.

## Struktur

- `assets/`: ikoner, CSS og innebygde frontend-assets
- `bin/`: lokal runtime-binær ved behov, ikke versjonert
- `core/`: analysemotor og pipelines
- `data/`: lokal data-mappe, ikke versjonert
- `fraggler-v2/`: Rust-kildekode
- `gui/`: legacy Panel-GUI
- `gui_qt/`: primar PyQt6-app
- `ObsidianVault/`: prosjektets memory-bank og logg

## Test

```bash
python3 -m unittest tests/test_ladder_review_gate.py tests/test_water_filter.py
python3 -m py_compile qt_app.py gui_qt/main_window.py gui_qt/tabs/tab_batch.py gui_qt/tabs/tab_ladder.py
```

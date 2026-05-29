# HemaFrag Windows Release Runbook

Dette dokumentet beskriver Windows-pakken som fungerte 2026-05-28, og hva som maa huskes neste gang HemaFrag skal bygges for Windows.

## Kort oppsummert

Windows-pakken som fungerte er en PyInstaller `--windowed` bundle bygget paa Mac via Docker/Wine:

```text
dist/releases/HemaFrag_Windows.zip
```

Fungerende SHA256 for siste lokale testede zip:

```text
a06947091753527eebeab9f678541071c3b57695c26446b8151b6c98acbf2d94
```

Byggkommando:

```bash
./packaging/build_windows.sh
```

Etter build skal zip testes:

```bash
python3 -m zipfile -t dist/releases/HemaFrag_Windows.zip
shasum -a 256 dist/releases/HemaFrag_Windows.zip
```

## Det som maatte fikses

### 1. Rust-motoren maa bygges for Windows

Docker-bygget maa cross-compile Rust CLI-en:

```text
fraggler-v2/target/release/fraggler-cli.exe
```

Den maa ligge i Windows-bundlen her:

```text
HemaFrag_Windows/_internal/fraggler-cli.exe
```

Hvis Windows-loggen sier `could not find fraggler-cli`, sjekk at:

- `fraggler-cli.exe` faktisk ligger i `_internal`
- `core/rust_bridge.py` leter etter `.exe` paa Windows
- frozen runtime sjekker `_MEIPASS`, mappen ved `HemaFrag.exe`, og `_internal`

### 2. Windowed app har ikke stdout/stderr

PyInstaller `--windowed` paa Windows kan gi:

```text
"NoneType" object has no attribute "isatty"
```

Dette ble fikset ved at `qt_app.py` og `packaging/hooks/runtime_desktop.py` setter en liten null-stream naar `sys.stdout` eller `sys.stderr` er `None`.

I tillegg maa kode som bruker `sys.stdout.isatty()` guardes mot `None`.

### 3. Ikke bruk persistent Rust worker/prewarm paa Windows

Windows ga:

```text
RUST ERROR: Worker pool batch prewarm failed: [WinError 10038]
An operation was attempted on something that is not a socket
```

Aarsaken var persistent Rust worker/prewarm som bruker `select()` paa subprocess-pipes. Det er ikke portabelt paa Windows.

Fungerende loesning:

- Disable persistent Rust worker/prewarm naar `sys.platform == "win32"`
- Returner `0` fra `prime_rust_worker_results(...)` paa Windows
- La vanlig Rust-analyse fortsatt kjoere per fil med one-shot CLI
- Start Rust CLI skjult med Windows no-console subprocess flags

Dette gjoer at rapporter fortsatt lages, men uten workerpool-feil og uten ekstra popup-vinduer.

### 4. Python multiprocessing skal vaere av i pakket desktop-app

Runtime hooken setter:

```text
FRAGGLER_DISABLE_MULTIPROCESSING=1
HEMAFRAG_ENABLE_LEGACY_PANEL=0
```

Dette hindrer at pakket Windows-app starter ekstra GUI-prosesser eller legacy Panel-server som bivirkning.

## Windows-PC: anbefalt testprosedyre

1. Lukk alle gamle HemaFrag-vinduer.
2. I Task Manager: avslutt gamle `HemaFrag.exe` og `fraggler-cli.exe`.
3. Slett gammel utpakket mappe:

```text
C:\HemaFrag\HemaFrag_Windows\
```

4. Kopier ny `HemaFrag_Windows.zip` til Windows-PC-en.
5. Høyreklikk zip -> `Properties` -> `Unblock` hvis knappen finnes.
6. Pakk ut hele zip-en.
7. Start:

```text
C:\HemaFrag\HemaFrag_Windows\HemaFrag.exe
```

8. Kjoer en liten analyse foerst og bekreft at rapporter blir laget.

## Forventede loggmeldinger

Disse kan normalt ignoreres hvis rapporter lages:

- PyInstaller/Wine build warnings om `api-ms-win-crt-*`
- UPX `NotCompressibleException` under build
- `Still running: ...` heartbeat mens en jobb tar lang tid

Disse skal ikke komme i fungerende Windows-pakke:

- `NoneType object has no attribute isatty`
- `could not find fraggler-cli`
- `Worker pool batch prewarm failed: WinError 10038`
- Mange nye HemaFrag-popupvinduer under analyse

## Kopiering til T7 Shield

Hvis T7 er montert paa Mac:

```bash
mkdir -p "/Volumes/T7 Shield/HemaFrag/Windows"
cp -f dist/releases/HemaFrag_Windows.zip "/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows.zip"
python3 -m zipfile -t "/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows.zip"
shasum -a 256 "/Volumes/T7 Shield/HemaFrag/Windows/HemaFrag_Windows.zip"
```

Hvis `/Volumes/T7 Shield` ikke finnes, er disken ikke montert.

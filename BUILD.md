# Building the afpub Converter

## Prerequisites

### Python 3.11+
- Windows: https://www.python.org/downloads/ — check "Add Python to PATH"
- macOS: `brew install python@3.11`

### zstd library
**Windows:** Download from https://github.com/facebook/zstd/releases
- Grab `zstd-vX.Y.Z-win64.zip`, extract it, copy `zstd.dll` into `afpub-web/`

**macOS:** `brew install zstd`

### Python dependencies
```bash
pip install -r requirements.txt
pip install pyinstaller
```

## Run locally
```bash
python main.py
```
Opens http://127.0.0.1:8080 automatically.

## Build executable

### Windows
```cmd
pyinstaller afpub_converter.spec
```
Output: `dist/afpub_converter.exe` + copy `zstd.dll` alongside it.

### macOS
```bash
pyinstaller afpub_converter.spec
```
Output: `dist/afpub_converter`

## Adding a new template
1. Create `templates/my_new_book/styles.yaml`
2. Use the Calibration section in the app to get style IDs
3. Map IDs in `styles.yaml` (use `homestead` as reference)
4. Redeploy

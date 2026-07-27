# PoGo XP

Local dashboard and pipelines for Pokemon GO XP, medals, and Pokédex tracking. Shared inputs live in `inputs/`; path helpers are in `shared/paths.py` (override with `POGO_INPUT_DIR`).

## Quick start

```powershell
pip install -r requirements-localhost.txt
python run_server.py
```

Open `http://127.0.0.1:8050`.

| Command | Purpose |
| --- | --- |
| `python run_xp.py --no-show` | XP plots |
| `python run_medals.py` | Medal report |
| `python update_all.py` | Both |
| `python tools/update_pokemon_catalog.py` | Refresh Pokemon catalog |

## Layout

```text
inputs/           config, data, reference, templates, private credentials
pogo-xp/          XP plotting
medal-tracker/    medal reporting
webapp/           localhost dashboard (Dash)
tools/            catalog + Google Drive helpers
output/           generated PNG/CSV/HTML
```

## Google Drive export

On successful XP / medal / Pokédex save, configured dashboard HTML is rebuilt and uploaded to Drive (stable share links).

1. Save OAuth Desktop client JSON as `inputs/private/google_drive_credentials.json`  
   (see `inputs/templates/google_drive_credentials.example.json`)
2. `python tools/google_drive_connect.py`
3. `python tools/google_drive_setup_folders.py`

Folder/file IDs and share mode live in `inputs/config/google_drive_exports.json`. Credentials stay under `inputs/private/` (gitignored).

## Tests

```powershell
python -m unittest -v tests/test_metrics.py
python -m unittest -v tests/test_google_drive.py
```

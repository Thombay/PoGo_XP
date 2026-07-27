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

Exports include Global, Personal (with medal charts), and Medal Dashboard pages for `OwnAccounts` / `Ich`.

## GitHub Pages export

The same save flow also publishes rendered HTML to the `gh-pages` branch (Drive preview shows source; Pages renders in the browser).

Config: `inputs/config/github_pages.json`  
One-off publish:

```powershell
python tools/github_pages_publish.py
```

Enable Pages in GitHub: **Settings → Pages → Deploy from a branch → `gh-pages` / root**.  
URLs look like `https://thombay.github.io/PoGo_XP/Dashboard-Global/All/` (public to anyone with the link).

## Tests

```powershell
python -m unittest -v tests/test_metrics.py
python -m unittest -v tests/test_google_drive.py
python -m unittest -v tests/test_github_pages.py
```

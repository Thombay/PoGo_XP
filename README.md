# PoGo XP

Local Streamlit dashboard and pipelines for Pokemon GO XP, medals, and Pokédex. Shared inputs in `inputs/` via `shared/paths.py` (`POGO_INPUT_DIR` optional).

## Quick start

```powershell
pip install -r requirements-localhost.txt
python run_server.py
```

→ `http://127.0.0.1:8050`

| Command | Purpose |
| --- | --- |
| `python run_xp.py --no-show` | XP plots |
| `python run_medals.py` | Medal report |
| `python update_all.py` | Both |
| `python tools/update_pokemon_catalog.py` | Refresh catalog |

## Layout

```text
inputs/         config, data, reference, templates, private credentials
pogo-xp/        XP plotting
medal-tracker/  medal reporting
webapp/         Streamlit dashboard
tools/          catalog, Drive, GitHub Pages helpers
output/         generated PNG/CSV/HTML
```

## Auto export

After a successful XP / medal / Pokédex save, configured HTML dashboards are rebuilt and published to both:

1. **Google Drive** — stable share links (`inputs/config/google_drive_exports.json`)
2. **GitHub Pages** — browser-rendered URLs (`inputs/config/github_pages.json` → `gh-pages` branch)

### Links (GitHub Pages — use these)

| Dashboard | Group | URL |
| --- | --- | --- |
| Global | All | https://thombay.github.io/PoGo_XP/Dashboard-Global/All/ |
| Global | Family | https://thombay.github.io/PoGo_XP/Dashboard-Global/Family/ |
| Global | Work | https://thombay.github.io/PoGo_XP/Dashboard-Global/Work/ |
| Global | Papiermuehlgasse | https://thombay.github.io/PoGo_XP/Dashboard-Global/Papiermuehlgasse/ |
| Global | Bekannte | https://thombay.github.io/PoGo_XP/Dashboard-Global/Bekannte/ |
| Personal | OwnAccounts | https://thombay.github.io/PoGo_XP/Dashboard-Personal/OwnAccounts/ |
| Personal | Ich | https://thombay.github.io/PoGo_XP/Dashboard-Personal/Ich/ |
| Medal | OwnAccounts | https://thombay.github.io/PoGo_XP/Medal-Dashboard/OwnAccounts/ |
| Medal | Ich | https://thombay.github.io/PoGo_XP/Medal-Dashboard/Ich/ |

Drive copies (preview may show source HTML): root [PoGo](https://drive.google.com/drive/folders/1ubwLQHIMalbLrgmMishi4Gc6g8qAACWM) · [All](https://drive.google.com/file/d/1YvgyXh0-tvyC2Il1443lDepHnmcZHC3I/view) · [Family](https://drive.google.com/file/d/1rQ1NyCxxmlC7NGnOoXYF51cEfoxb92-D/view) · [Work](https://drive.google.com/file/d/1OeVDFaTEKjl7WNvcbZf4y3zD9CU9DCif/view) · [Papiermuehlgasse](https://drive.google.com/file/d/1zeunFYyldYy-GpA3hSCIJyX3fBYX6LsQ/view) · [Bekannte](https://drive.google.com/file/d/1hof3_e_yl8f742DcKKjd9gARpjjl55yO/view) · [OwnAccounts](https://drive.google.com/file/d/1A4EUe7jjBnQ8cvyCoHotwvnUSYe65JWG/view) · [Ich](https://drive.google.com/file/d/1wKWmkOOC1ri4nGALJhm1S5vmY_WpBjSu/view)

**Drive setup (once):**

1. Save OAuth Desktop JSON as `inputs/private/google_drive_credentials.json`  
   (template: `inputs/templates/google_drive_credentials.example.json`)
2. `python tools/google_drive_connect.py`
3. `python tools/google_drive_setup_folders.py`

**Pages setup (once):** GitHub → Settings → Pages → Deploy from branch → `gh-pages` / root.

```powershell
python tools/github_pages_publish.py          # one-off publish
python tools/github_pages_publish.py --no-push  # build locally only
```

## Tests

```powershell
python -m unittest -v tests/test_metrics.py tests/test_google_drive.py tests/test_github_pages.py
```

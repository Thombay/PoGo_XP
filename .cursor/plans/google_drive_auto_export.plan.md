# Google Drive Auto Export Plan

## Goal

Automatically renew hosted dashboard exports in Google Drive whenever data is saved in the Streamlit app.

## Plan

1. Finish Google auth.
   - Put `google_drive_credentials.json` into `inputs/private/`.
   - Run `tools/google_drive_connect.py` once to create `google_drive_token.json`.

2. Create the Drive structure.
   - Create/find root folder `PoGo`.
   - Create folders per dashboard and group, for example `Dashboard Global/All` and `Dashboard Global/Family`.
   - Store folder and file IDs in a local config file.

3. Add a Drive upload helper.
   - Create files on first upload.
   - Update existing files by file ID on later uploads so share links stay stable.
   - Support public "anyone with link" or restricted sharing.

4. Connect uploads to save buttons.
   - After XP, Medal, or Pokedex save succeeds, rebuild configured exports.
   - Upload/replace the configured Google Drive files.
   - Show a success message with the updated links.

5. Test the workflow.
   - Save new data in the app.
   - Confirm Google Drive file contents update.
   - Confirm existing links stay unchanged.

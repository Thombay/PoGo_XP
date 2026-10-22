# PoGo Pokedex phone app

This is the Android hunting list. It signs in with Google, then reads and writes the Pokédex files in the private Drive folder named `PoGo Sync`. The phone does not create that folder.

Sign-in uses the Capacitor plugin `@capacitor-community/generic-oauth2`. The flow is the OAuth authorization-code flow with PKCE. Put the Android OAuth client id in `www/google-client.js` as `GOOGLE_CLIENT_ID`. This plugin does not need a separate web client id, and the app does not use a client secret. Google only accepts the reversed Android client id as the redirect, not the app package name.

## One-time setup

1. In Google Cloud, the consent screen for this project must be In production. While the screen is in Testing, refresh tokens die after 7 days.

2. The sync scope is `https://www.googleapis.com/auth/drive`. The first approval shows Google's unverified-app warning. Continue past it once. This personal app is not submitted for verification.

3. On the PC, once, run `python tools/pokedex_sync_connect.py`. That creates the private Drive folder `PoGo Sync` and the three sync files. The phone only looks for that folder. If it is missing, the app says the PC command has not been run yet.

4. Create an Android OAuth client in the same Cloud project. Package name `com.pogo.pokedex`. Debug SHA-1 comes from `cd android && .\gradlew signingReport` after the Android project exists. Put that client id in `www/google-client.js`. No web client id is required. If the client id is `123-abc.apps.googleusercontent.com`, set `custom_url_scheme` in `android/app/src/main/res/values/strings.xml` to `com.googleusercontent.apps.123-abc`. The app then redirects to `com.googleusercontent.apps.123-abc:/oauth2redirect`. A package-name redirect is rejected for this client type.

5. From `phone/pokedex`, run `npm install`, then `npx cap add android` if the `android` folder is not there yet (this copy already has it), then `npx cap sync`, then `cd android && .\gradlew assembleDebug`. The debug APK is `android\app\build\outputs\apk\debug\app-debug.apk`. Copy that file onto the phone and sideload it. There is no Play Store listing. This machine did not have Java on PATH and did not have an Android SDK, so no APK was produced. Install Android Studio (JDK and SDK), then run the gradle command. Do not keep retrying the build until those are installed.

6. On the first phone launch, tap Sign in with Google and use the same account as the PC. Later launches sync with no prompt. If Google revokes the login, the button comes back. No token file is copied onto the phone.

## Tests

From `phone/pokedex`, run `npm test`. That runs `node --test test/model.test.js`.

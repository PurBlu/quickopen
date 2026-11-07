# QuickOpen

A tiny, self-hosted, ad-free client for opening a residential building entrance door.

The official door-access app wraps a single HTTPS request in a splash ad, interstitial ads, forced app-store redirects, a shopping feed and analytics SDKs. Opening the door can take half a minute. QuickOpen keeps only the sign-in and open-door calls, runs them from a small always-on Mac, and gives every device the same one-tap web interface.

This repository contains no third-party endpoints, application ids, secrets or keys. All protocol values live in a local, gitignored configuration file; only a placeholder template is published here. See [Protocol configuration](#protocol-configuration).

Licensed under the [MIT License](LICENSE); see [License](#license) for scope and third-party notices.

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Protocol configuration](#protocol-configuration)
- [Quick start](#quick-start)
- [First-time sign-in](#first-time-sign-in)
- [Installing the web app on a phone](#installing-the-web-app-on-a-phone)
- [The macOS menu bar app](#the-macos-menu-bar-app)
- [Runtime configuration](#runtime-configuration)
- [HTTP API](#http-api)
- [Diagnostics and tests](#diagnostics-and-tests)
- [Icons](#icons)
- [Security model](#security-model)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Credits](#credits)
- [License](#license)

---

## What it does

- Signs in once with your own phone number and an official SMS verification code.
- Fetches every door key authorised for your account.
- Opens any of those doors with a single tap, in roughly one HTTP round trip.
- Keeps the session alive in the background so you rarely need to sign in again.
- Shows service health, session state, resource usage, door statistics and recent events on a status page.
- Provides an optional native macOS menu bar app with a per-door picker.
- Works identically on iOS, Android, macOS and any modern browser.
- Contains no ads, no tracking, no third-party runtime dependencies and no cloud service. Everything runs on your own machine.

Measured on an always-on Mac mini: about 23 MB of resident memory, roughly 0.04 % average CPU while idle, and three to four threads.

---

## How it works

```
iPhone / Android / Mac browser        macOS menu bar app
        |                                    |
        +------------+-----------------------+
                     |
        one PWA, one interface, one tap
                     |
      Mac mini, launchd, Python 3 standard library
      +------------------------------------------+
      | door_service.py                          |
      |   HTTP API, status, statistics, session  |
      |   keepalive, access key, static hosting  |
      +------------------------------------------+
      | door_protocol.py                         |
      |   sign-in, key list, open-door protocol  |
      +------------------------------------------+
                     |
        official servers (HTTPS)
        session and door permission still
        validated on the server side
                     |
              entrance door
```

The browser never speaks the door protocol. It only calls high-level endpoints on the local service. The service forwards a signed request to the official servers, which still verify both the session and whether your account owns that door. Nothing bypasses authentication or authorisation.

---

## Requirements

- A Mac that stays on (developed and tested on a Mac mini M4 with macOS).
- Python 3.9 or newer. The system `/usr/bin/python3` works fine.
- No pip packages, no virtual environment, no database, no Node.js.
- Optional: Xcode Command Line Tools (`swiftc`) for the native menu bar app.
- Any modern browser on iOS, Android or desktop.
- A valid, authorised account with the official door-access app.
- `viewport-fit=cover` plus `env(safe-area-inset-*)` are used for notched iPhones, so the fixed bottom tab bar stays clear of the home indicator.

---

## Protocol configuration

**Nothing in this repository will work out of the box, by design.** The service talks to a third-party API whose endpoints and signing material are not redistributed here. You must supply them locally.

```bash
cp protocol_config.example.py protocol_config.py
# then edit protocol_config.py and fill in every value
```

`protocol_config.py` is listed in `.gitignore` and must never be committed. Every setting can alternatively be supplied through a `QO_*` environment variable, which takes precedence over the file. The launcher reads the file from its working directory, so keep it beside `door_service.py`.

The template contains placeholders only:

| Key | Meaning | Required |
| --- | --- | --- |
| `BASE_URL` | Business API base URL | yes |
| `SMS_URL` | SMS gateway URL | yes |
| `APP_VERSION` | Client version string used in signatures | yes |
| `APP_VERSION_CODE` | Client version code header | yes |
| `APP_CHANNEL` | Channel field in signed requests | yes |
| `SIGNING_SALT` | Salt appended when computing the request signature | yes |
| `HEX_AES_KEY` | 16-byte hex key used to encrypt the phone number at sign-in | yes |
| `SMS_APP_ID` | Application id for the SMS gateway | yes |
| `SMS_APP_SECRET` | Application secret for the SMS gateway | yes |
| `TIMEOUT` | Upstream HTTP timeout in seconds | yes |

If any value is missing, the service still starts but prints a warning, `/api/status` reports it in `config_missing`, and requests fail with a clear message telling you to copy the template. Third-party attribution and the upstream MIT license notice are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

## Quick start

1. Copy `protocol_config.example.py` to `protocol_config.py` and fill in your local values as described above.
2. Double-click `Install.command`, or run `./install.sh` from a terminal.

The installer:

- Runs the offline self-test.
- Creates `~/.quickopen/` and generates a random access key (mode 0600).
- Writes two LaunchAgents to `~/Library/LaunchAgents/`: `cn.quickopen.door.plist` for the service (`RunAtLoad`, `KeepAlive`, `ProcessType=Background`, `LowPriorityIO`, `Nice=5`) and `cn.quickopen.menubar.plist` for the menu bar app.
- Compiles the menu bar app with `swiftc` if available.
- Starts everything and prints the URLs you need.

At the end it prints a **provisioning link** shaped like this:

```
http://192.168.1.10:8787/#k=<random-access-key>
```

Open that link once on your phone. The web app reads the key from the URL fragment, stores it locally and clears the fragment, so the secret is not left in the address bar.

Useful commands:

```bash
./status.sh          # quick terminal status report
./uninstall.sh       # stop and remove both LaunchAgents
python3 diagnose.py  # protocol health check (also available from the status page)
python3 selftest.py  # offline regression suite
```

To restart the service after editing code:

```bash
launchctl kickstart -k gui/$(id -u)/cn.quickopen.door
```

---

## First-time sign-in

The official service has added a WAF in front of its SMS gateway. Requests built with older client constants are rejected with HTTP 403 and a message meaning "signature check failed, required signature field missing". This affects **only the SMS sending endpoint**. Sign-in, key listing and opening a door still accept the existing signature scheme.

The verification code is issued by the server against a phone number, not against a particular client. So the one-time workaround is:

1. Open the **official door-access app** on your phone and request a verification code.
2. Open the QuickOpen console and go to the **Settings** tab.
3. Enter your phone number and the code you just received.
4. Click **Sign in and sync keys**.

That is the only time you need the official app. The service keeps the session alive with a lightweight call every 15 minutes and refreshes it on demand before an open request. If a session eventually expires, repeat the same short flow.

The `POST /api/send-code` button in the console acts as a help hint rather than calling the blocked gateway. Set `QO_SMS_PROVIDER=legacy` if you ever adapt the new gateway signature and want to try the old path again.

---

## Installing the web app on a phone

1. Open the provisioning link from the installer in Safari (iOS) or Chrome (Android).
2. Use **Add to Home Screen**.
3. The installed app launches full-screen, works offline for its shell, and shows the same interface as the desktop browser.

The manifest declares `any`, `maskable` and `monochrome` icons. The SVG favicon adapts to light and dark system themes. The fixed bottom tab bar reserves space for the iPhone home indicator.

> iOS caches both the home-screen icon and the service worker. After an update, pull to refresh once; after changing the icon, delete the home-screen shortcut and add it again.

Remote access from outside your LAN is best done with a private mesh VPN such as Tailscale. Do not expose port 8787 to the public internet.

---

## The macOS menu bar app

`menubar/QuickOpenBar.swift` is a single-file AppKit app with no dependencies. Build it with:

```bash
bash menubar/build.sh
```

The menu shows:

- Service status, version and uptime.
- Session state and time of the last successful request.
- Memory, CPU, thread count and open/close statistics.
- **One-tap open (default door)** for the fastest path.
- **Open a specific door** submenu listing every authorised key; picking one opens that door immediately.
- **Set default door** submenu with radio-button selection.
- Open the web console, restart the background service, or quit the menu bar app (the service keeps running).

The menu polls `/api/status` every 20 seconds and rebuilds the door list only when it changes. The compiled `.app` bundle is intentionally not committed; `build.sh` regenerates it.

---

## Runtime configuration

Runtime settings are plain environment variables. Put overrides in the LaunchAgent plist or pass them when running `door_service.py` in the foreground.

| Variable | Default | Purpose |
| --- | --- | --- |
| `QO_PORT` | `8787` | HTTP port for the console and API |
| `QO_BIND` | `0.0.0.0` | Bind address; use `127.0.0.1` for Mac-only |
| `QO_ACCESS_KEY` | random file | Shared secret required for non-loopback clients |
| `QO_SMS_PROVIDER` | `external` | `external` = get the code from the official app; `legacy` = call the old gateway |
| `QO_TOUCH_INTERVAL` | `900` | Seconds between background session keepalive calls |
| `QO_TOUCH_STALE` | `1200` | Refresh before an open request if the session is older than this |
| `QO_TIMEOUT` | `8` | Upstream HTTP timeout in seconds |
| `QO_PYTHON` | auto | Override the Python binary used by `install.sh` |

All `QO_*` variables matching a key in the table under [Protocol configuration](#protocol-configuration) override that local file value.

Runtime state lives in `~/.quickopen/`:

| File | Contents |
| --- | --- |
| `state.json` | Session, door keys, statistics (mode 0600) |
| `access_key` | Random LAN access key (mode 0600) |
| `events.log` | Redacted event log |
| `logs/service.log` | launchd stdout and stderr |

---

## HTTP API

Requests from `127.0.0.1` are exempt from authentication. All other clients must send the access key either in the `X-Key` header or as a `?k=` query parameter.

| Method | Path | Body | Result |
| --- | --- | --- | --- |
| `GET` | `/api/health` | - | Liveness and version |
| `GET` | `/api/status` | - | Full status, resource usage, keys, statistics, events |
| `GET` | `/api/keys` | - | Authorised door keys and the default key id |
| `GET` | `/api/logs` | - | Recent event lines |
| `GET` | `/api/onboard` | - | Access key and provisioning link |
| `GET` | `/api/diagnose` | - | Protocol probes and a conclusion |
| `POST` | `/api/send-code` | `{ "phone": "..." }` | Guidance or legacy SMS request |
| `POST` | `/api/login` | `{ "phone": "...", "code": "..." }` | Signs in and syncs keys |
| `POST` | `/api/open` | `{ "key_id": "..." }` (optional) | Opens the chosen or default door |
| `POST` | `/api/refresh-keys` | - | Re-fetches door keys |
| `POST` | `/api/set-default` | `{ "key_id": "..." }` | Changes the default door |
| `POST` | `/api/touch` | - | Forces a session keepalive call |
| `POST` | `/api/logout` | - | Clears the local session and keys |

Errors are returned as `{ "ok": false, "message": "..." }`. Upstream responses are recorded in redacted form in `last_upstream` and shown on the status page.

---

## Diagnostics and tests

```bash
python3 selftest.py    # offline checks, no network, no real account
python3 diagnose.py    # live probes using fake data only
```

The self-test covers AES against the FIPS-197 test vector, a byte-exact reimplementation of Java's `URLEncoder`, signature construction, the complete sign-in / key / open flow against a simulated upstream, every HTTP endpoint, access-key enforcement, rate limiting, file permissions, and verification that no protocol secret is present in any file that would be committed.

`diagnose.py` answers the question "which part of the protocol did the vendor change this time?" It probes the SMS gateway, sign-in, key listing and open-door endpoints with a fake phone number, a fake code and a fake session. It never sends an SMS, never signs in and never opens a door. The same report is available from the **Protocol check** card on the status page.

---

## Icons

`make_icons.py` regenerates the complete icon set:

```bash
python3 make_icons.py
```

Rasterisation uses the macOS built-in `sips` tool, so no image libraries are needed. All icons have a transparent background, use only black and white, contain no gradients and no small decorative details, and remain legible at 48 px and in greyscale. Light and dark variants are provided, plus a `monochrome` icon for Android themed icons and an adaptive SVG favicon.

---

## Security model

- No third-party endpoints, application ids, secrets or keys are committed. They live only in the gitignored `protocol_config.py`.
- The local service is the only component holding credentials. They are stored in a file with mode 0600 and never uploaded anywhere.
- Loopback requests need no key; LAN requests require a high-entropy access key. The provisioning link contains that key, so treat it like a password.
- The service refuses to start if its AES self-test fails, and warns at start-up if protocol configuration is incomplete.
- All upstream failures are logged with phone numbers and session ids redacted.
- A short cooldown prevents accidental double-open requests.
- The server-side session check and door permission check are never bypassed.
- No telemetry, analytics, advertising or third-party network calls exist in the client or the service.
- HTTPS is enforced for upstream calls, and redirects are not followed.

If a phone is lost, delete `~/.quickopen/access_key` on the Mac, restart the service to generate a new key, and re-provision the remaining devices.

---

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Protocol configuration is incomplete` | Copy `protocol_config.example.py` to `protocol_config.py` and fill in every value |
| `Signature check failed, required signature field missing` | Expected on the SMS gateway; use the official app to request a code |
| `Verification code expired` | Request a fresh code in the official app and sign in again quickly |
| Console cannot reach the service | Confirm the Mac is awake, run `curl http://127.0.0.1:8787/api/health`, and check the access key |
| `Not logged in` on open | Re-run the short sign-in flow; inspect `last_upstream` on the status page |
| Menu bar icon missing | Run `bash menubar/build.sh`, then `launchctl kickstart -k gui/$(id -u)/cn.quickopen.menubar` |
| Old layout after an update | Pull to refresh so the service worker cache activates; re-add the home-screen shortcut for icon changes |
| Service will not start | `tail -50 ~/.quickopen/logs/service.log` and `python3 selftest.py` |

---

## Project layout

```
.
|-- index.html                     Single-file PWA console (three tabs, offline shell)
|-- sw.js                          Service worker (network-first for HTML)
|-- manifest.webmanifest           PWA manifest and icon declarations
|-- door_protocol.py               Protocol layer: AES, signing, HTTP calls
|-- protocol_config.example.py     Template: placeholders only, safe to publish
|-- protocol_config.py             Local values, gitignored, never committed
|-- door_service.py                Local service: API, state, keepalive, static files
|-- diagnose.py                    Live protocol health check
|-- selftest.py                    Offline regression suite
|-- make_icons.py                  Icon generator using sips
|-- install.sh                     launchd installer
|-- uninstall.sh                   Removes both LaunchAgents
|-- status.sh                      Terminal status report
|-- push.sh                        One-command publish to GitHub
|-- Install.command                Double-click installer (macOS)
|-- Status.command                 Double-click status report
|-- Diagnostics.command            Double-click protocol check
|-- THIRD_PARTY_NOTICES.md         Upstream MIT license notices
|-- LICENSE                        MIT license for the original code in this repository
|-- menubar/
|   |-- QuickOpenBar.swift         Native menu bar app
|   |-- Info.plist                 LSUIElement and local-network ATS settings
|   `-- build.sh                   Compiles the .app bundle
`-- icon*.svg / icon*.png / apple-touch-icon.png
```

---

## Credits

- The protocol layer was adapted from an MIT-licensed open-source Android client. The full attribution and license text are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- The application icon was adapted from Tabler Icons (MIT); see the same notices file.
- `door_protocol.py` implements AES-128-ECB in pure Python and verifies it against the FIPS-197 vector at start-up.

## License

The original code in this repository is released under the MIT License. See [LICENSE](LICENSE).

Third-party derived material remains under its own MIT license, reproduced in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Trademarks, server-side protocols and official client software are not covered by this license.

This project is not affiliated with, endorsed by, or sponsored by any door-access vendor. It is intended only for a person using their own authorised account and a door they are permitted to open. Protocol values may change when the vendor updates its app; use the diagnostics tool and `QO_*` overrides to adapt. Use at your own risk; no warranty is provided.

# Public web demo (static, read-only)

`https://frame.marinachain.io` shows finished MarinaFrame runs in the app's own UI. It is a
folder of static files: no server process, no uploads, no model calls, no code runs on the
server. Nothing a visitor does is saved.

## How it works

| Part | File | What it does |
|---|---|---|
| Static backend | `app/ui/static/backend.js` | Answers the app's read commands (`list_tasks`, `get_task`, `get_events`, `get_live_steps`, `get_hull_sections`, `read_artifact`, `list_sources`, `read_source_page`, `list_exports`, `sounding_table`, settings and status) from files under `data/`. Every other command is refused with "Demo: read-only. Install the desktop app to build your own." |
| Transport choice | `app/ui/js/api.js` | `<meta name="marinaframe-backend" content="static">` selects the static backend. `readOnly` is then true. |
| Demo UI | `app/ui/js/app.js`, `home.js`, `export.js`, `styles.css` | `<html data-demo="read-only">`: no setup screen; Home shows the intro and the vessels; controls that start or change a run are hidden; Export lists download links for files that already exist. |
| Pilot page | `app/ui/static/pilot.html` | "Proposed: GA revision pilot", text and a diagram only. It is clearly marked as a proposal. |
| Exporter | `app/core/examples/web_demo_export.rs` | Calls the desktop app's own `Backend` read methods on each run folder and writes their answers and the files they name. It also stages the UI by the desktop release rules (`--stage-ui`, `release_ui::stage`). |
| Build | `scripts/build_web_demo.py` | Stages the UI, exports the runs in `scripts/web_demo_runs.json`, applies the data gates, scales images down and writes `data/manifest.json` into `build/web-demo/` (git-ignored). |

The release desktop bundle leaves out `app/ui/static`, so the desktop app carries no demo code.

## Build

```sh
.venv/bin/python scripts/build_web_demo.py \
    --runs work/web-demo-runs/runs --config work/web-demo-runs/config
```

`--config` is the app config folder that the runs were reviewed with. A person's part reviews
and sign-off are kept there, not in the run folder. The exporter copies it to a temporary folder
and never writes into it.

The build fails, and deletes its output, when:

- a run in `scripts/web_demo_runs.json` has a licence outside `ALLOWED_LICENCES`;
- a drawing given to a run has a SHA-256 that is not listed for that run;
- a slug, file or source name contains `truth`, `holdout_value` or `sealed`;
- any JSON file still contains a local path (`/Users/`, `/home/`, `/private/`, `/tmp/`, ...);
- the bundle is larger than 300 MB;
- the release UI rules fail (a non-UI file type, a link, a file over 1 MB in the UI folders).

Drawing images larger than 4000 px on the long edge are scaled down. Each run in the manifest
records the original and the shown size (`downscaled_images`). The JSON keeps the page sizes
that the app reported, so overlays and hover-to-source stay aligned.

The same runs, config and commit give the same bytes (`built_from_commit` is in the manifest).

### Licences

| Key | Used for |
|---|---|
| `public-domain-us-government` | HAER drawings from the Library of Congress |
| `mit` | DTMB 5415 surface (mathLab/WaveBEMapp-DTMB-5415) |
| `cc-by-3.0` | Series 60 example hull (FreeCAD Ship workbench); the credit is shown under its card |
| `synthetic` | the built-in sample hull |
| `owner-approved-display` | R/V Gunnerus and MiDShip (development split only, never sealed): licence not confirmed. They stay out of git. |

Approval for `owner-approved-display` (2026-11-11): the PM asked the user "Can we show Gunnerus
(and MiDShip tanker sections) on a public site?" and the user answered "1. Yes".

## Local check

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory build/web-demo
```

Open `http://127.0.0.1:8765/`. The site uses relative paths only and works at `/`.

## Hosting with Caddy (guidance; no server was changed)

Copy `build/web-demo/` to the server (for example `/srv/marinaframe-web-demo/`), then use a
site block like this:

```caddyfile
frame.marinachain.io {
	root * /srv/marinaframe-web-demo
	encode zstd gzip

	# A static site: only GET and HEAD.
	@write not method GET HEAD
	respond @write 405

	header {
		# Same policy as the page's own meta tag (scripts/build_web_demo.py WEB_CSP), plus
		# frame-ancestors, which only works as a header. No inline script, no eval.
		Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; font-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
		Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
		Cross-Origin-Opener-Policy "same-origin"
		Cross-Origin-Resource-Policy "same-origin"
		-Server
	}

	# Revalidate every file (ETag), so a new build shows at once after a redeploy.
	header Cache-Control "no-cache"

	file_server
}
```

Notes:

- The CSP needs no `unsafe-inline` or `unsafe-eval`. Images and models are loaded as
  `data:` URLs (the app's `read_artifact` shape), so `img-src` keeps `data:` and `blob:`.
- The pilot page has a stricter meta CSP of its own (`script-src 'none'`). Both policies apply.
- Do not turn on directory listings (`file_server browse`).
- Caddy serves `.glb`, `.step` and `.pdf` files as downloads; the app reads models with `fetch`,
  so their MIME type does not matter.

## Desktop fallback

`work/web-demo-runs/runs/` is a normal desktop runs folder. You can copy a run folder into
`~/Library/Application Support/io.marinachain.marinaframe/runs/` and open it in the app.

The app compares the SHA-256 of its own executable with `config.binary_sha256` in the run's
`state.json` (`app/core/src/view.rs`). That value is the SHA-256 of the program that ran the
controller. Runs made with the `marinaframe` CLI, or with another app build, therefore show
"A different build of MarinaFrame made this run, so it can be viewed here but not continued or
changed." This is true even when the CLI and the app come from the same commit, because they
are different executables. Only a run made by the identical app binary opens without the
notice. Viewing works in all cases. The check is unchanged.

Part reviews ("accepted", "marked" with a note) are kept in the app config folder, in
`part_reviews.json`, keyed by the absolute path of the run folder (`app/core/src/parts.rs`). A
run folder copied to another Mac therefore shows its parts as not reviewed. The part revisions
themselves (History, before and after) are in the run folder and do come along.

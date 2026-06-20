# NZXT-ESC local source

The served local editor is:

- `nzxt-esc-live/dist`

The local server mounts that folder at:

- `http://127.0.0.1:8000/nzxt-esc/`

The supported local stream path is now Electron:

- `electron-app/`
- visible editor: `http://127.0.0.1:8000/nzxt-esc/`
- hidden device renderer: `http://127.0.0.1:8000/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle&streamRenderer=1`
- frame handoff: Electron captures the hidden 480x480 renderer and posts frames to `/api/v1/designer/frame`

The Python/Playwright renderer and supervisor are legacy fallback/debug paths. They should not be launched for normal NZXT-ESC streaming because they can compete with Electron for preview ownership.

Archived or older experiments are kept under:

- `_unused_esc_copies/`

Do not launch or mount those archived copies for the local device stream. They include older or experimental builds that can look similar but do not match the live `https://nzxt-esc.pages.dev/` UI and can break preset/render synchronization.

The gallery data source remains:

- `nzxt-esc-gallery/`

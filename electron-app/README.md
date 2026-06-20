# Open AIO Electron Shell

This is the Electron route for NZXT-ESC v6.05.11:

- visible editor window: `http://127.0.0.1:8000/nzxt-esc/`
- hidden 480x480 render window: `http://127.0.0.1:8000/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle&streamRenderer=1`
- offscreen capture posts JPEG frames to the existing local server endpoint
- the existing Python agent/USB path can continue sending frames to the ESP32

Install/run:

```powershell
cd electron-app
npm.cmd install
npm.cmd start
```

If Electron's binary did not download during install, run:

```powershell
.\bootstrap-electron.cmd
```

Electron and the renderer use the same persistent Chromium partition:

```text
persist:cooler-display
```

That is the key difference from Firefox plus Playwright: the editor and hidden LCD renderer share one desktop app session.

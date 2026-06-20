from pathlib import Path

Import("env")

project_dir = Path(env["PROJECT_DIR"])
pioenv = env["PIOENV"]
panel_cpp = (
    project_dir
    / ".pio"
    / "libdeps"
    / pioenv
    / "LilyGo-T-RGB"
    / "src"
    / "LilyGo_RGBPanel.cpp"
)

if panel_cpp.exists():
    text = panel_cpp.read_text(encoding="utf-8")
    marker = "tmp->disableAutoSleep();"
    anchor = """#if ARDUHAL_LOG_LEVEL >= ARDUHAL_LOG_LEVEL_INFO
        const char *model = _touchDrv->getModelName();
        log_i("Successfully initialized %s, using %s Driver!\\n", model, model);
#endif
"""
    replacement = anchor + """        TouchDrvCSTXXX *tmp = static_cast<TouchDrvCSTXXX *>(_touchDrv);
        tmp->disableAutoSleep();
"""
    if marker not in text and anchor in text:
        panel_cpp.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")

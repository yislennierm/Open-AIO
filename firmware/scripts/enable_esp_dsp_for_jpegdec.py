from pathlib import Path

Import("env")

framework_dir = Path(env.PioPlatform().get_package_dir("framework-arduinoespressif32"))
sdk_dir = framework_dir / "tools" / "sdk" / "esp32s3"
dsp_include = sdk_dir / "include" / "espressif__esp-dsp" / "modules" / "fft" / "include"
dsp_lib_dir = sdk_dir / "lib"
dsp_lib = dsp_lib_dir / "libespressif__esp-dsp.a"

if dsp_include.exists():
    env.Append(CPPPATH=[str(dsp_include)])

if dsp_lib.exists():
    env.Append(LIBPATH=[str(dsp_lib_dir)])
    env.Append(LIBS=["espressif__esp-dsp"])

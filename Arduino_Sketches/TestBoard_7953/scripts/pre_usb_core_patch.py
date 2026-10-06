"""PlatformIO middleware: substitute the repaired build-local USB core."""

from pathlib import Path
import sys

Import("env")
sys.path.insert(0, str(Path(env.subst("$PROJECT_DIR")) / "scripts"))
from usb_core_patch import patch_usb_serial


def replace_usb_core(build_env, node):
    original = Path(node.srcnode().get_abspath())
    if original.name != "usb_serial.c" or original.parent.name != "teensy4":
        return node
    patched = patch_usb_serial(original.read_text(encoding="utf-8"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched_core" / "usb_serial.c"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8", newline="\n")
    print("TestBoard USB core: ordered TX guards and protected explicit flush")
    return build_env.File(str(destination))


env.AddBuildMiddleware(replace_usb_core, "*usb_serial.c")

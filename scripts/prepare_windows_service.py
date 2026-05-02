import filecmp
import shutil
import site
import sys
from pathlib import Path


def copy_if_needed(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"missing: {src}")
        return
    if dst.exists() and filecmp.cmp(src, dst, shallow=False):
        print(f"ok: {dst}")
        return
    shutil.copy2(src, dst)
    print(f"copied: {src} -> {dst}")


def main() -> int:
    python_root = Path(sys.prefix)
    system_site = python_root / "Lib" / "site-packages"
    user_site = Path(site.getusersitepackages())
    pywin32_system32 = user_site / "pywin32_system32"

    if not system_site.exists():
        print(f"System site-packages not found: {system_site}")
        return 1
    if not user_site.exists():
        print(f"User site-packages not found: {user_site}")
        return 1

    pth_path = system_site / "print_service_pywin32_paths.pth"
    pth_lines = [
        str(user_site),
        str(user_site / "win32"),
        str(user_site / "win32" / "lib"),
        str(user_site / "Pythonwin"),
    ]
    pth_path.write_text("\n".join(pth_lines) + "\n", encoding="utf-8")
    print(f"wrote: {pth_path}")

    version = f"{sys.version_info.major}{sys.version_info.minor}"
    copy_if_needed(pywin32_system32 / f"pywintypes{version}.dll", python_root / f"pywintypes{version}.dll")
    copy_if_needed(pywin32_system32 / f"pythoncom{version}.dll", python_root / f"pythoncom{version}.dll")
    copy_if_needed(user_site / "win32" / "servicemanager.pyd", python_root / "servicemanager.pyd")

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

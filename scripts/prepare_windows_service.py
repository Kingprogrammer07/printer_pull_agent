import filecmp
import os
import shutil
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


def require_module_path(module_name: str) -> Path | None:
    try:
        module = __import__(module_name)
    except ImportError:
        return None
    file_path = getattr(module, "__file__", None)
    return Path(file_path).resolve() if file_path else None


def pywin32_paths() -> tuple[list[Path], Path | None, Path | None, Path | None]:
    servicemanager_path = require_module_path("servicemanager")
    win32serviceutil_path = require_module_path("win32serviceutil")
    pythoncom_path = require_module_path("pythoncom")
    pywintypes_path = require_module_path("pywintypes")

    roots: list[Path] = []
    for path in (servicemanager_path, win32serviceutil_path, pythoncom_path, pywintypes_path):
        if path is None:
            continue
        parent = path.parent
        roots.append(parent)
        if parent.name.lower() in {"win32", "pythonwin", "pywin32_system32"}:
            roots.append(parent.parent)

    unique_roots: list[Path] = []
    for root in roots:
        if root.exists() and root not in unique_roots:
            unique_roots.append(root)
    return unique_roots, servicemanager_path, pythoncom_path, pywintypes_path


def main() -> int:
    python_root = Path(sys.prefix)
    system_site = python_root / "Lib" / "site-packages"

    if "WindowsApps" in str(python_root):
        print("Microsoft Store Python aniqlandi:")
        print(f"  {python_root}")
        print("Bu Python Windows Service uchun mos emas, WindowsApps papkasiga yozib bo'lmaydi.")
        print("python.org dan oddiy Python o'rnating yoki mavjud normal Python'ni full path bilan ishlating.")
        print(r"Masalan: C:\Python314\python.exe scripts\prepare_windows_service.py")
        return 2

    if not system_site.exists():
        print(f"System site-packages not found: {system_site}")
        return 1

    roots, servicemanager_path, pythoncom_path, pywintypes_path = pywin32_paths()
    if servicemanager_path is None:
        print("pywin32 topilmadi: servicemanager import bo'lmadi.")
        print("Avval shu Python bilan dependencylarni o'rnating:")
        print(f'  "{sys.executable}" -m pip install -r requirements.txt')
        print("Yoki kamida:")
        print(f'  "{sys.executable}" -m pip install pywin32')
        return 4

    pth_lines: list[str] = []
    for root in roots:
        pth_lines.append(str(root))
        for child in ("win32", "win32\\lib", "Pythonwin", "pywin32_system32"):
            child_path = root / child
            if child_path.exists():
                pth_lines.append(str(child_path))

    pth_lines = list(dict.fromkeys(pth_lines))
    pth_path = system_site / "print_service_pywin32_paths.pth"
    try:
        pth_path.write_text("\n".join(pth_lines) + "\n", encoding="utf-8")
        print(f"wrote: {pth_path}")
    except PermissionError:
        print(f"Permission denied: {pth_path}")
        print("PowerShell'ni Run as Administrator qilib oching va qayta urinib ko'ring.")
        return 3

    if pywintypes_path is not None:
        copy_if_needed(pywintypes_path, python_root / pywintypes_path.name)
    if pythoncom_path is not None:
        copy_if_needed(pythoncom_path, python_root / pythoncom_path.name)
    if servicemanager_path is not None:
        copy_if_needed(servicemanager_path, python_root / servicemanager_path.name)

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

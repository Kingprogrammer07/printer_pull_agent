import argparse
import sys
from datetime import datetime


PRINTER_NAME = "Xprinter D481B"


STATUS_BITS = {
    0x00000001: "PAUSED",
    0x00000002: "ERROR",
    0x00000008: "PAPER_JAM",
    0x00000010: "PAPER_OUT",
    0x00000040: "PAPER_PROBLEM",
    0x00000080: "OFFLINE",
    0x00000400: "PRINTING",
    0x00004000: "PROCESSING",
    0x00040000: "NO_TONER",
    0x00100000: "USER_INTERVENTION",
    0x00400000: "DOOR_OPEN",
}


def require_pywin32():
    try:
        import win32print
        import win32ui
    except ImportError as exc:
        raise SystemExit("pywin32 kerak: pip install pywin32") from exc
    return win32print, win32ui


def list_printers() -> list[str]:
    win32print, _ = require_pywin32()
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [printer[2] for printer in win32print.EnumPrinters(flags)]


def get_status(printer_name: str) -> dict:
    win32print, _ = require_pywin32()
    handle = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(handle, 2)
        raw_status = int(info.get("Status", 0))
        flags = [name for bit, name in STATUS_BITS.items() if raw_status & bit]
        return {
            "name": info.get("pPrinterName", printer_name),
            "raw_status": raw_status,
            "flags": flags,
            "jobs": int(info.get("cJobs", 0)),
            "ready": raw_status == 0 or raw_status & (0x00000400 | 0x00004000),
        }
    finally:
        win32print.ClosePrinter(handle)


def print_gdi_test_page(printer_name: str) -> None:
    _, win32ui = require_pywin32()
    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)
    try:
        dc.StartDoc("Xprinter D481B test")
        dc.StartPage()
        dc.TextOut(100, 100, "Xprinter D481B printer test")
        dc.TextOut(100, 160, f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        dc.TextOut(100, 220, "If you see this, Windows driver printing works.")
        dc.EndPage()
        dc.EndDoc()
    finally:
        dc.DeleteDC()


def resolve_printer_name(requested: str, printers: list[str]) -> str | None:
    if requested in printers:
        return requested

    lower_requested = requested.lower()
    for printer in printers:
        if lower_requested in printer.lower() or printer.lower() in lower_requested:
            return printer

    xprinter_matches = [printer for printer in printers if "xprinter" in printer.lower()]
    if len(xprinter_matches) == 1:
        print(f"'{requested}' topilmadi, lekin Xprinter nomi topildi: {xprinter_matches[0]}")
        return xprinter_matches[0]

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Xprinter D481B status and print test")
    parser.add_argument("--printer", default=PRINTER_NAME, help="Windows printer name")
    parser.add_argument("--status", action="store_true", help="Only check printer status")
    parser.add_argument("--print", action="store_true", help="Print a small test page")
    parser.add_argument("--list", action="store_true", help="List installed printers")
    args = parser.parse_args()

    if args.list:
        print("Installed printers:")
        for name in list_printers():
            print(f" - {name}")
        return 0

    printers = list_printers()
    resolved_printer = resolve_printer_name(args.printer, printers)
    if resolved_printer is None:
        print(f"Printer topilmadi: {args.printer}")
        print("Mavjud printerlar:")
        for name in printers:
            print(f" - {name}")
        return 2

    status = get_status(resolved_printer)
    print(f"Printer: {status['name']}")
    print(f"Raw status: {status['raw_status']}")
    print(f"Flags: {', '.join(status['flags']) if status['flags'] else 'READY'}")
    print(f"Jobs in queue: {status['jobs']}")

    if args.status and not args.print:
        return 0 if status["ready"] else 1

    if args.print:
        if not status["ready"]:
            print("Printer tayyor emas, test sahifa yuborilmadi.")
            return 1
        print_gdi_test_page(resolved_printer)
        print("Test sahifa Windows print queue ga yuborildi.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

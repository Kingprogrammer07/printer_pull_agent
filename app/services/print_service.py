import asyncio
import os
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.exceptions import PrinterError


class PrinterStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    PAUSED = "PAUSED"
    UNKNOWN = "UNKNOWN"


PRINTER_STATUS_PAUSED = 0x00000001
PRINTER_STATUS_ERROR = 0x00000002
PRINTER_STATUS_PAPER_JAM = 0x00000008
PRINTER_STATUS_PAPER_OUT = 0x00000010
PRINTER_STATUS_MANUAL_FEED = 0x00000020
PRINTER_STATUS_PAPER_PROBLEM = 0x00000040
PRINTER_STATUS_OFFLINE = 0x00000080
PRINTER_STATUS_IO_ACTIVE = 0x00000100
PRINTER_STATUS_BUSY = 0x00000200
PRINTER_STATUS_PRINTING = 0x00000400
PRINTER_STATUS_OUTPUT_BIN_FULL = 0x00000800
PRINTER_STATUS_NOT_AVAILABLE = 0x00001000
PRINTER_STATUS_WAITING = 0x00002000
PRINTER_STATUS_PROCESSING = 0x00004000
PRINTER_STATUS_INITIALIZING = 0x00008000
PRINTER_STATUS_WARMING_UP = 0x00010000
PRINTER_STATUS_TONER_LOW = 0x00020000
PRINTER_STATUS_NO_TONER = 0x00040000
PRINTER_STATUS_PAGE_PUNT = 0x00080000
PRINTER_STATUS_USER_INTERVENTION = 0x00100000
PRINTER_STATUS_OUT_OF_MEMORY = 0x00200000
PRINTER_STATUS_DOOR_OPEN = 0x00400000
PRINTER_STATUS_SERVER_UNKNOWN = 0x00800000
PRINTER_STATUS_POWER_SAVE = 0x01000000


class PrintService:
    def __init__(self, printer_name: str = ""):
        self.printer_name = printer_name or self._default_printer()

    def get_printer_status(self) -> PrinterStatus:
        details = self.get_detailed_status()
        if details.get("is_paused"):
            return PrinterStatus.PAUSED
        if details.get("is_offline"):
            return PrinterStatus.OFFLINE
        if details.get("has_error"):
            return PrinterStatus.ERROR
        if details.get("is_ready"):
            return PrinterStatus.ONLINE
        if details.get("is_processing"):
            return PrinterStatus.ONLINE
        return PrinterStatus.UNKNOWN

    def is_online(self) -> bool:
        return self.get_printer_status() == PrinterStatus.ONLINE

    def get_detailed_status(self) -> dict[str, Any]:
        win32print = self._import_win32print()
        handle = win32print.OpenPrinter(self.printer_name)
        try:
            info = win32print.GetPrinter(handle, 2)
            status_code = int(info.get("Status", 0))
            attributes = int(info.get("Attributes", 0))
            return {
                "name": info.get("pPrinterName", self.printer_name),
                "raw_status": status_code,
                "attributes": attributes,
                "is_ready": status_code == 0,
                "is_offline": bool(status_code & PRINTER_STATUS_OFFLINE),
                "has_error": bool(
                    status_code
                    & (
                        PRINTER_STATUS_ERROR
                        | PRINTER_STATUS_PAPER_JAM
                        | PRINTER_STATUS_PAPER_OUT
                        | PRINTER_STATUS_PAPER_PROBLEM
                        | PRINTER_STATUS_NO_TONER
                        | PRINTER_STATUS_USER_INTERVENTION
                        | PRINTER_STATUS_DOOR_OPEN
                        | PRINTER_STATUS_NOT_AVAILABLE
                    )
                ),
                "is_paused": bool(status_code & PRINTER_STATUS_PAUSED),
                "paper_jam": bool(status_code & PRINTER_STATUS_PAPER_JAM),
                "no_paper": bool(status_code & PRINTER_STATUS_PAPER_OUT),
                "no_toner": bool(status_code & PRINTER_STATUS_NO_TONER),
                "door_open": bool(status_code & PRINTER_STATUS_DOOR_OPEN),
                "is_processing": bool(status_code & (PRINTER_STATUS_PRINTING | PRINTER_STATUS_PROCESSING)),
                "jobs": int(info.get("cJobs", 0)),
            }
        finally:
            win32print.ClosePrinter(handle)

    async def print_pdf(self, file_path: str) -> bool:
        return await asyncio.to_thread(self._print_pdf_sync, file_path)

    def _print_pdf_sync(self, file_path: str) -> bool:
        path = Path(file_path)
        if not path.exists():
            raise PrinterError(f"PDF not found: {file_path}")
        if self.get_printer_status() != PrinterStatus.ONLINE:
            raise PrinterError(f"Printer is not online: {self.printer_name}")

        win32api = self._import_win32api()
        operation = "printto" if self.printer_name else "print"
        params = f'"{self.printer_name}"' if self.printer_name else None
        result = win32api.ShellExecute(0, operation, str(path), params, os.getcwd(), 0)
        if result <= 32:
            raise PrinterError(f"ShellExecute print failed with code {result}")
        return True

    @staticmethod
    def _default_printer() -> str:
        win32print = PrintService._import_win32print()
        try:
            return win32print.GetDefaultPrinter()
        except Exception as exc:
            raise PrinterError("No default printer is configured") from exc

    @staticmethod
    def _import_win32print():
        try:
            import win32print

            return win32print
        except ImportError as exc:
            raise PrinterError("pywin32 is required for printer access on Windows") from exc

    @staticmethod
    def _import_win32api():
        try:
            import win32api

            return win32api
        except ImportError as exc:
            raise PrinterError("pywin32 is required for PDF printing on Windows") from exc


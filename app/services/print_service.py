import asyncio
import os
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.config import settings
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
    def __init__(
        self,
        printer_name: str = "",
        *,
        pdf_print_backend: str | None = None,
        sumatra_path: str | None = None,
        print_timeout_seconds: int | None = None,
        print_copies: int | None = None,
    ):
        self.printer_name = printer_name or self._default_printer()
        self.pdf_print_backend = (pdf_print_backend or settings.pdf_print_backend).lower()
        self.sumatra_path = sumatra_path if sumatra_path is not None else settings.sumatra_path
        self.print_timeout_seconds = print_timeout_seconds or settings.print_timeout_seconds
        self.print_copies = max(1, int(print_copies or settings.print_copies))

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

        if self.pdf_print_backend not in {"auto", "sumatra", "shell"}:
            raise PrinterError(f"Unknown PDF print backend: {self.pdf_print_backend}")

        if self.pdf_print_backend in {"auto", "sumatra"}:
            sumatra = self._resolve_sumatra_path()
            if sumatra:
                return self._print_with_sumatra(sumatra, path)
            if self.pdf_print_backend == "sumatra":
                raise PrinterError("SumatraPDF.exe not found. Set SUMATRA_PATH or install SumatraPDF.")

        return self._print_with_shell_execute(path)

    def _print_with_sumatra(self, sumatra_path: str, pdf_path: Path) -> bool:
        command = [
            sumatra_path,
            "-print-to",
            self.printer_name,
            "-print-settings",
            f"{self.print_copies}x",
            "-silent",
            "-exit-on-print",
            str(pdf_path),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.print_timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            stdout = completed.stdout.strip()
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise PrinterError(f"SumatraPDF print failed: {detail}")
        return True

    def _print_with_shell_execute(self, pdf_path: Path) -> bool:
        win32api = self._import_win32api()
        for copy_number in range(self.print_copies):
            try:
                result = win32api.ShellExecute(
                    0,
                    "printto",
                    str(pdf_path),
                    f'"{self.printer_name}"',
                    os.getcwd(),
                    0,
                )
            except Exception as exc:
                raise PrinterError(
                    "ShellExecute PDF print failed. Install SumatraPDF and set SUMATRA_PATH if this PDF viewer "
                    f"does not support printto. Copy {copy_number + 1}/{self.print_copies}. Original error: {exc}"
                ) from exc
            if result <= 32:
                raise PrinterError(
                    "ShellExecute PDF print failed. Install SumatraPDF and set SUMATRA_PATH if this PDF viewer "
                    f"does not support printto. Copy {copy_number + 1}/{self.print_copies}. ShellExecute code: {result}"
                )
        return True

    def _resolve_sumatra_path(self) -> str | None:
        candidates = []
        if self.sumatra_path:
            candidates.append(self.sumatra_path)
        which_path = shutil.which("SumatraPDF.exe") or shutil.which("SumatraPDF")
        if which_path:
            candidates.append(which_path)
        candidates.extend(
            [
                r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
                r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
                str(Path.home() / "AppData" / "Local" / "SumatraPDF" / "SumatraPDF.exe"),
            ]
        )
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return str(Path(candidate))
        return None

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

import asyncio
import os
import sys
import threading
import traceback


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bootstrap_paths() -> None:
    env_user_site = os.path.join(
        os.environ.get("APPDATA", r"C:\Users\Admin\AppData\Roaming"),
        "Python",
        f"Python{sys.version_info.major}{sys.version_info.minor}",
        "site-packages",
    )
    admin_user_site = os.path.join(
        r"C:\Users\Admin\AppData\Roaming",
        "Python",
        f"Python{sys.version_info.major}{sys.version_info.minor}",
        "site-packages",
    )
    env_local_site = os.path.join(
        os.environ.get("LOCALAPPDATA", r"C:\Users\Admin\AppData\Local"),
        "Programs",
        "Python",
        f"Python{sys.version_info.major}{sys.version_info.minor}",
        "Lib",
        "site-packages",
    )
    admin_local_site = os.path.join(
        r"C:\Users\Admin\AppData\Local",
        "Programs",
        "Python",
        f"Python{sys.version_info.major}{sys.version_info.minor}",
        "Lib",
        "site-packages",
    )
    site_roots = [env_user_site, admin_user_site, env_local_site, admin_local_site]
    paths = [BASE_DIR]
    for root in site_roots:
        paths.extend(
            [
                root,
                os.path.join(root, "win32"),
                os.path.join(root, "win32", "lib"),
                os.path.join(root, "pywin32_system32"),
            ]
        )
    for path in reversed(paths):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    if hasattr(os, "add_dll_directory"):
        for root in site_roots:
            path = os.path.join(root, "pywin32_system32")
            if os.path.isdir(path):
                os.add_dll_directory(path)


_bootstrap_paths()

import servicemanager
import win32event
import win32service
import win32serviceutil

from app.agent.client import LocalPrintAgent
from app.core.config import settings


class PDFPrintAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = f"{settings.service_name}Agent"
    _svc_display_name_ = "PDF Print Queue Local Agent"
    _svc_description_ = "Connects to the cloud print queue and prints jobs on the local Windows printer."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.loop = None
        self.task = None
        self.thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.loop and self.task:
            self.loop.call_soon_threadsafe(self.task.cancel)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        try:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            os.chdir(BASE_DIR)
            self.thread = threading.Thread(target=self.main, name="PDFPrintAgent", daemon=True)
            self.thread.start()
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        except Exception:
            servicemanager.LogErrorMsg(f"SvcDoRun error:\n{traceback.format_exc()}")
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def main(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def main_wrapper():
            self.task = asyncio.current_task()
            await LocalPrintAgent().run_forever()

        try:
            self.loop.run_until_complete(main_wrapper())
        except asyncio.CancelledError:
            servicemanager.LogInfoMsg("PDF print agent stopped.")
        except Exception:
            servicemanager.LogErrorMsg(traceback.format_exc())
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                self.loop.close()


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PDFPrintAgentService)

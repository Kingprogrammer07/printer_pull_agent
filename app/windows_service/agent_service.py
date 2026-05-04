import asyncio
import os
import sys
import threading
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows services have no console; redirect stdout/stderr to a log file
# BEFORE any imports that may configure logging.
_AGENT_OUT_LOG = os.path.join(BASE_DIR, "logs", "agent.out.log")
os.makedirs(os.path.dirname(_AGENT_OUT_LOG), exist_ok=True)
_agent_out_stream = open(_AGENT_OUT_LOG, "a", encoding="utf-8")
sys.stdout = _agent_out_stream
sys.stderr = _agent_out_stream

# Ensure .env is loaded from the project directory, not System32.
os.chdir(BASE_DIR)


def _bootstrap_paths() -> None:
    import site

    # Standard system & user site-packages
    site_roots = []
    try:
        site_roots.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            site_roots.append(user_site)
    except Exception:
        pass

    # Fallback to common Windows paths if site module returns nothing
    if not site_roots:
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

    # Also preserve whatever paths the current interpreter already knows
    for p in sys.path:
        if p not in site_roots:
            site_roots.append(p)

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


_LOG_PATH = os.path.join(BASE_DIR, "logs", "agent_service.log")


def _log_to_file(text: str) -> None:
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(TASHKENT_TZ).isoformat()} {text}\n")
    except Exception:
        pass


class PDFPrintAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = f"{settings.service_name}Agent"
    _svc_display_name_ = "PDF Print Queue Local Agent"
    _svc_description_ = "Connects to the cloud print queue and prints jobs on the local Windows printer."
    _svc_deps_ = []
    # Start automatically on Windows boot
    StartType = win32service.SERVICE_AUTO_START

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
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except Exception as exc:
                _log_to_file(f"SvcStop cancel error: {exc}")
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
            _log_to_file("SvcDoRun started")
            self.thread = threading.Thread(target=self.main, name="PDFPrintAgent", daemon=True)
            self.thread.start()
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        except Exception:
            err = traceback.format_exc()
            _log_to_file(f"SvcDoRun error: {err}")
            servicemanager.LogErrorMsg(f"SvcDoRun error:\n{err}")
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def main(self):
        try:
            _log_to_file("main() started")
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            async def main_wrapper():
                self.task = asyncio.current_task()
                _log_to_file("main_wrapper() entering run_forever")
                await LocalPrintAgent().run_forever()

            self.loop.run_until_complete(main_wrapper())
        except asyncio.CancelledError:
            _log_to_file("main() cancelled")
            servicemanager.LogInfoMsg("PDF print agent stopped.")
        except Exception:
            err = traceback.format_exc()
            _log_to_file(f"main() error: {err}")
            servicemanager.LogErrorMsg(err)
        finally:
            _log_to_file("main() cleaning up")
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                self.loop.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "install":
        win32serviceutil.HandleCommandLine(PDFPrintAgentService)
        # Set startup type to Automatic after installation
        try:
            import win32service
            hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            try:
                hs = win32service.OpenService(
                    hscm, PDFPrintAgentService._svc_name_, win32service.SERVICE_ALL_ACCESS
                )
                try:
                    win32service.ChangeServiceConfig(
                        hs,
                        win32service.SERVICE_NO_CHANGE,
                        win32service.SERVICE_AUTO_START,
                        win32service.SERVICE_NO_CHANGE,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                finally:
                    win32service.CloseServiceHandle(hs)
            finally:
                win32service.CloseServiceHandle(hscm)
        except Exception as exc:
            _log_to_file(f"Failed to set auto-start: {exc}")
    else:
        win32serviceutil.HandleCommandLine(PDFPrintAgentService)

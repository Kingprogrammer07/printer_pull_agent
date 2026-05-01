import os
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

from app.core.config import settings


class PDFPrintQueueService(win32serviceutil.ServiceFramework):
    _svc_name_ = settings.service_name
    _svc_display_name_ = settings.service_display_name
    _svc_description_ = "Downloads PDF files and sends them to a Windows printer sequentially."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.server is not None:
            self.server.should_exit = True

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.main()

    def main(self):
        import uvicorn

        os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        config = uvicorn.Config(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            log_level="info",
        )
        self.server = uvicorn.Server(config)
        self.server.run()


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PDFPrintQueueService)


from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    db_path: str = "./data/print_jobs.db"

    downloads_dir: str = "./downloads"
    pending_dir: str = "./downloads/pending"
    ready_dir: str = "./downloads/ready"
    archive_dir: str = "./downloads/archive"
    archive_retention_days: int = 7

    max_concurrent_downloads: int = 5
    download_timeout_connect: int = 10
    download_timeout_read: int = 30
    max_pdf_size_mb: int = 50

    max_retry_count: int = 3
    retry_delays_seconds: List[int] = [5, 15, 45]

    printer_name: str = ""
    printer_poll_interval: int = 10
    pdf_print_backend: str = "auto"
    sumatra_path: str = ""
    print_timeout_seconds: int = 60
    print_copies: int = 1

    service_name: str = "PDFPrintQueue"
    service_display_name: str = "PDF Print Queue Service"

    agent_id: str = "windows-agent-1"
    server_url: str = "http://127.0.0.1:8000"
    agent_poll_interval: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

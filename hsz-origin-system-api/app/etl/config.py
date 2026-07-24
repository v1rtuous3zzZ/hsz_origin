import os
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class EtlSettings:
    batch_size: int = int(os.getenv("HSZ_ETL_SOURCE_BATCH_SIZE", "2000"))
    max_workers: int = int(os.getenv("HSZ_ETL_MAX_WORKERS", "1"))
    source_retries: int = int(os.getenv("HSZ_ETL_SOURCE_RETRIES", "2"))

    center_retries: int = int(os.getenv("HSZ_ETL_CENTER_RETRIES", "2"))
    center_write_batch_size: int = int(
        os.getenv("HSZ_ETL_CENTER_WRITE_BATCH_SIZE", "10000")
    )

    live_window_minutes: int = int(os.getenv("HSZ_ETL_LIVE_WINDOW_MINUTES", "120"))
    poll_seconds: int = int(os.getenv("HSZ_ETL_POLL_SECONDS", "60"))
    safety_delay: timedelta = timedelta(
        seconds=int(os.getenv("HSZ_ETL_SAFETY_DELAY_SECONDS", "120"))
    )

    history_sleep_seconds: int = int(os.getenv("HSZ_ETL_SLEEP_SECONDS", "5"))

    manual_job_poll_seconds: int = int(os.getenv("HSZ_ETL_MANUAL_JOB_POLL_SECONDS", "5"))

    def __post_init__(self) -> None:
        if self.max_workers != 1:
            raise ValueError("新 ETL 仅支持 HSZ_ETL_MAX_WORKERS=1 的单 worker 串行模式")


def source_credentials(credential_key: str) -> tuple[str, str]:
    prefix = credential_key.upper()
    user, password = os.getenv(f"{prefix}_USER"), os.getenv(f"{prefix}_PASSWORD")
    if not user or not password:
        raise RuntimeError(f"源服务器凭据缺失：请设置 {prefix}_USER 与 {prefix}_PASSWORD")
    return user, password

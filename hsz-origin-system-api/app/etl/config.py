import os
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class EtlSettings:
    batch_size: int = int(os.getenv("HSZ_ETL_BATCH_SIZE", "2000"))
    max_workers: int = int(os.getenv("HSZ_ETL_MAX_WORKERS", "4"))
    poll_seconds: int = int(os.getenv("HSZ_ETL_POLL_SECONDS", "60"))
    safety_delay: timedelta = timedelta(
        seconds=int(os.getenv("HSZ_ETL_SAFETY_DELAY_SECONDS", "120"))
    )
    overlap: timedelta = timedelta(seconds=int(os.getenv("HSZ_ETL_OVERLAP_SECONDS", "7200")))
    initial_lookback: timedelta = timedelta(
        minutes=int(os.getenv("HSZ_ETL_INITIAL_LOOKBACK_MINUTES", "60"))
    )
    history_window_minutes: int = int(os.getenv("HSZ_ETL_HISTORY_WINDOW_MINUTES", "60"))
    history_sleep_seconds: int = int(os.getenv("HSZ_ETL_HISTORY_SLEEP_SECONDS", "1"))


def source_credentials(credential_key: str) -> tuple[str, str]:
    prefix = credential_key.upper()
    user, password = os.getenv(f"{prefix}_USER"), os.getenv(f"{prefix}_PASSWORD")
    if not user or not password:
        raise RuntimeError(f"源服务器凭据缺失：请设置 {prefix}_USER 与 {prefix}_PASSWORD")
    return user, password

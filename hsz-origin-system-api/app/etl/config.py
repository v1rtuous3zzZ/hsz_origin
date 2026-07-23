import os
from dataclasses import dataclass
from datetime import timedelta


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EtlSettings:
    batch_size: int = int(os.getenv("HSZ_ETL_BATCH_SIZE", "2000"))
    max_workers: int = int(os.getenv("HSZ_ETL_MAX_WORKERS", "4"))
    source_retries: int = int(os.getenv("HSZ_ETL_SOURCE_RETRIES", "2"))
    source_lock_timeout_seconds: int = int(
        os.getenv("HSZ_ETL_SOURCE_LOCK_TIMEOUT_SECONDS", "300")
    )
    serialize_source_reads: bool = _env_bool("HSZ_ETL_SERIALIZE_SOURCE_READS", True)

    center_retries: int = int(os.getenv("HSZ_ETL_CENTER_RETRIES", "2"))
    center_write_batch_size: int = int(
        os.getenv("HSZ_ETL_CENTER_WRITE_BATCH_SIZE", "10000")
    )

    live_window_minutes: int = int(os.getenv("HSZ_ETL_LIVE_WINDOW_MINUTES", "120"))
    poll_seconds: int = int(os.getenv("HSZ_ETL_POLL_SECONDS", "60"))
    safety_delay: timedelta = timedelta(
        seconds=int(os.getenv("HSZ_ETL_SAFETY_DELAY_SECONDS", "120"))
    )

    history_window_minutes: int = int(
        os.getenv("HSZ_ETL_HISTORY_WINDOW_MINUTES", "360")
    )
    history_sleep_seconds: int = int(os.getenv("HSZ_ETL_HISTORY_SLEEP_SECONDS", "0"))

    manual_job_poll_seconds: int = int(os.getenv("HSZ_ETL_MANUAL_JOB_POLL_SECONDS", "5"))
    manual_job_stale_minutes: int = int(
        os.getenv("HSZ_ETL_MANUAL_JOB_STALE_MINUTES", "360")
    )

    overlap: timedelta = timedelta(seconds=int(os.getenv("HSZ_ETL_OVERLAP_SECONDS", "600")))
    initial_lookback: timedelta = timedelta(
        minutes=int(os.getenv("HSZ_ETL_INITIAL_LOOKBACK_MINUTES", "60"))
    )


def source_credentials(credential_key: str) -> tuple[str, str]:
    prefix = credential_key.upper()
    user, password = os.getenv(f"{prefix}_USER"), os.getenv(f"{prefix}_PASSWORD")
    if not user or not password:
        raise RuntimeError(f"源服务器凭据缺失：请设置 {prefix}_USER 与 {prefix}_PASSWORD")
    return user, password

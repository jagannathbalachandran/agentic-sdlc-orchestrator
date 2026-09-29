"""Shared ID regex patterns, reused across domain models to keep formats consistent."""

REQ_ID_PATTERN = r"^REQ-\d+$"
FR_ID_PATTERN = r"^FR-\d+$"
AC_ID_PATTERN = r"^FR-\d+\.AC\d+$"
DD_ID_PATTERN = r"^DD-\d+$"
TASK_ID_PATTERN = r"^T-\d+\.\d+$"
RUN_ID_PATTERN = r"^[a-z][a-z0-9-]*-\d{8}-\d+$"

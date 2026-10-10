"""CEF (Common Event Format) egress for SIEM integration (CLAUDE.md, L5:
"syslog/CEF egress"). Format: `CEF:Version|Vendor|Product|Version|
Signature ID|Name|Severity|Extension` (ArcSight CEF spec).

Lives in pulseguard_common (not services/mitigation) because both the
mitigation controller and the detection engine's CEF-export API endpoint
need it, and each service's Docker image only copies its own service
directory plus common/ — a cross-service import would work in local
pytest (whole repo on sys.path) but silently break in the actual
containerized deployment.
"""

from __future__ import annotations

from datetime import datetime

CEF_VERSION = 0
DEVICE_VENDOR = "PulseGuard"
DEVICE_PRODUCT = "MFAFatigueDetector"
DEVICE_VERSION = "1.0"


def _escape_header_field(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|")


def _escape_extension_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("=", "\\=").replace("\n", "\\n")


def format_cef(
    signature_id: str,
    name: str,
    severity: int,
    user_id: str,
    action: str,
    fused_score: float,
    timestamp: datetime,
) -> str:
    if not (0 <= severity <= 10):
        raise ValueError(f"CEF severity must be 0-10, got {severity}")

    header = "|".join(
        [
            f"CEF:{CEF_VERSION}",
            _escape_header_field(DEVICE_VENDOR),
            _escape_header_field(DEVICE_PRODUCT),
            _escape_header_field(DEVICE_VERSION),
            _escape_header_field(signature_id),
            _escape_header_field(name),
            str(severity),
        ]
    )
    extension = (
        f"suser={_escape_extension_value(user_id)} "
        f"act={_escape_extension_value(action)} "
        f"cs1Label=fused_score cs1={fused_score:.4f} "
        f"rt={int(timestamp.timestamp() * 1000)}"
    )
    return f"{header}|{extension}"

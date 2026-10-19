from dataclasses import dataclass
from typing import Any

from middlewared.alert.base import AlertCategory, AlertClassConfig, AlertLevel, OneShotAlertClass


@dataclass(kw_only=True)
class NVMetPortTransferSizeUnsupportedAlert(OneShotAlertClass):
    config = AlertClassConfig(
        category=AlertCategory.SHARING,
        level=AlertLevel.ERROR,
        title="NVMe-oF Ports Not Serving Subsystems",
        text=(
            "The running kernel does not support the maximum data transfer size configured on NVMe-oF port(s) "
            "%(ports)s, so they serve no subsystems. Clear the maximum data transfer size on these ports to serve "
            "them without a limit."
        ),
        keys=[],
    )

    ports: str

    @classmethod
    def key_from_args(cls, args: Any) -> Any:
        return None

"""Per-host request spacing and retry policy for the external sources."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostPolicy:
    """Request spacing and retry count for one host."""

    min_interval_s: float
    max_retries: int


HOST_POLICIES: Mapping[str, HostPolicy] = {
    "api-web.nhle.com": HostPolicy(min_interval_s=0.5, max_retries=3),
    "site.api.espn.com": HostPolicy(min_interval_s=2.0, max_retries=3),
    "www.dailyfaceoff.com": HostPolicy(min_interval_s=5.0, max_retries=3),
    "moneypuck.com": HostPolicy(min_interval_s=5.0, max_retries=3),
    "peter-tanner.com": HostPolicy(min_interval_s=5.0, max_retries=3),
}

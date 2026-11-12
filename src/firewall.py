import asyncio
import ipaddress
import logging
import time
from collections import deque
from typing import Deque, Dict, Optional, Set

logger = logging.getLogger(__name__)


class ActiveDefenseFirewall:
    """
    Asynchronous Kernel Firewall controller (nftables).
    Tracks security violations per source IP and dynamically blackholes
    malicious clients at the Linux kernel level without blocking the Event Loop.
    """

    def __init__(
        self,
        max_strikes: int = 3,
        strike_window: float = 60.0,
        ban_duration: str = "10m",
        wrapper_path: str = "/usr/local/bin/cerberus-ban",
        protected_ips: Optional[Set[str]] = None,
    ) -> None:
        self.max_strikes = max_strikes
        self.strike_window = strike_window
        self.ban_duration = ban_duration
        self.wrapper_path = wrapper_path
        self.protected_ips: Set[str] = protected_ips if protected_ips is not None else set()

        # Tracks timestamps of recent violations per IP: {ip: deque([t1, t2, ...])}
        self._strikes: Dict[str, Deque[float]] = {}
        # Tracks active bans to avoid spawning redundant subprocesses: {ip: expiry_monotonic}
        self._active_bans: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _parse_duration_seconds(self, duration: str) -> float:
        """Converts nftables timeout string (e.g., '30s', '10m', '1h') to seconds."""
        unit = duration[-1]
        value = int(duration[:-1])
        multipliers = {"s": 1.0, "m": 60.0, "h": 3600.0}
        return value * multipliers.get(unit, 600.0)

    def _validate_ipv4(self, ip: str) -> str:
        """Validates and normalizes an IPv4 address string."""
        parsed = ipaddress.IPv4Address(ip)
        return str(parsed)

    async def record_violation(self, ip: str, reason: str) -> bool:
        """
        Records a security anomaly (e.g., malformed JSON, rate-limit abuse) for an IP.
        Automatically triggers a kernel-level ban if strikes reach `max_strikes`.
        Returns True if the IP was banned, False otherwise.
        """
        try:
            clean_ip = self._validate_ipv4(ip)
        except ValueError:
            logger.warning("Ignoring violation for non-IPv4 address: %s", ip)
            return False

        if clean_ip in self.protected_ips:
            logger.info("Protected IP %s triggered violation (%s), skipping ban.", clean_ip, reason)
            return False

        should_ban = False
        async with self._lock:
            now = time.monotonic()

            if clean_ip in self._active_bans and self._active_bans[clean_ip] > now:
                return True

            history = self._strikes.setdefault(clean_ip, deque())
            while history and (now - history[0]) > self.strike_window:
                history.popleft()

            history.append(now)
            logger.warning(
                "Security strike %d/%d for %s | Reason: %s",
                len(history),
                self.max_strikes,
                clean_ip,
                reason,
            )

            if len(history) >= self.max_strikes:
                history.clear()
                should_ban = True

        if should_ban:
            return await self.ban_ip(clean_ip, reason=reason)

        return False

    async def ban_ip(self, ip: str, reason: str = "Security policy violation") -> bool:
        """
        Asynchronously invokes the root-owned nftables wrapper via create_subprocess_exec
        to drop all packets from `ip` in the Linux kernel.
        """
        try:
            clean_ip = self._validate_ipv4(ip)
        except ValueError:
            logger.error("Refused to ban invalid IPv4 address: %s", ip)
            return False

        if clean_ip in self.protected_ips:
            return False

        async with self._lock:
            now = time.monotonic()
            if clean_ip in self._active_bans and self._active_bans[clean_ip] > now:
                return True
            ban_seconds = self._parse_duration_seconds(self.ban_duration)
            self._active_bans[clean_ip] = now + ban_seconds

        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo",
                "-n",
                self.wrapper_path,
                clean_ip,
                self.ban_duration,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode == 0:
                logger.critical(
                    "KERNEL BAN APPLIED: %s blackholed for %s | Reason: %s",
                    clean_ip,
                    self.ban_duration,
                    reason,
                )
                return True

            err_msg = stderr.decode().strip()
            logger.error("Failed to apply nftables ban for %s: %s", clean_ip, err_msg)
            async with self._lock:
                self._active_bans.pop(clean_ip, None)
            return False

        except Exception as exc:
            logger.exception("Unexpected error executing firewall ban for %s: %s", clean_ip, exc)
            async with self._lock:
                self._active_bans.pop(clean_ip, None)
            return False

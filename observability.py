"""
================================================================================
STROKE // OBSERVABILITY, TELEMETRY & AUDIT ENGINE
================================================================================
Provides enterprise-grade, zero-leak observability:
  1. Structured Event Schema (provider, tool, filesystem, terminal, mcp, download, auth, persistence)
  2. Correlated Task Identifiers across all subsystem executions
  3. Strict Multi-Tier Redaction Engine (keys, patterns, tokens, passwords, OTPs, private keys)
  4. Channel Separation: Clean user-visible progress vs internal diagnostic traces
  5. Authentic Metrics Calculation (Zero fabricated/synthetic metrics)
  6. Thread-Safe In-Memory Ring Buffer & Streaming Subscription
================================================================================
"""

import os
import re
import time
import json
import uuid
import logging
import threading
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Callable, Union
from contextlib import contextmanager

logger = logging.getLogger("stroke.observability")

# ==============================================================================
# 1. CANONICAL CATEGORIES & STATUSES
# ==============================================================================

class EventCategory(str, Enum):
    PROVIDER = "provider"
    TOOL = "tool"
    FILESYSTEM = "filesystem"
    TERMINAL = "terminal"
    MCP = "mcp"
    DOWNLOAD = "download"
    AUTH = "auth"
    PERSISTENCE = "persistence"


class EventStatus(str, Enum):
    START = "start"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    REQUIRES_APPROVAL = "requires_approval"


# ==============================================================================
# 2. STRICT REDACTION ENGINE
# ==============================================================================

class RedactionEngine:
    """
    Recursively scans and redacts sensitive data, secrets, tokens, OTPs,
    passwords, and credentials from all telemetry and diagnostic events.
    """
    SENSITIVE_KEY_PATTERNS = re.compile(
        r"(password|secret|token|otp|auth|bearer|pat|credential|key)",
        re.IGNORECASE
    )

    REGEX_REDACTIONS = [
        # GitHub Personal Access Tokens (classic and fine-grained)
        (re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"), "[REDACTED_GITHUB_PAT]"),
        (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "[REDACTED_GITHUB_PAT]"),
        (re.compile(r"\bgho_[A-Za-z0-9]{36,}\b"), "[REDACTED_GITHUB_OAUTH]"),

        # JWTs / Bearer Tokens
        (re.compile(r"Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_.+/=]*", re.IGNORECASE), "Bearer [REDACTED_JWT]"),
        (re.compile(r"\beyJ[A-Za-z0-9\-_=]+\.eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_.+/=]*\b"), "[REDACTED_JWT]"),

        # Common API Keys (OpenAI, Anthropic, Google Firebase)
        (re.compile(r"\bsk-[A-Za-z0-9\-_]{16,}\b"), "[REDACTED_API_KEY]"),
        (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "[REDACTED_FIREBASE_KEY]"),
        (re.compile(r"\bre_[A-Za-z0-9]{20,}\b"), "[REDACTED_RESEND_KEY]"),

        # PEM / Private Keys
        (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),

        # Passwords in URLs (e.g. redis://:pass@host, http://user:pass@host)
        (re.compile(r"://([^:]+):([^@]+)@"), r"://\1:[REDACTED_PWD]@"),

        # Explicit OTP / PIN patterns
        (re.compile(r"\b(otp|code|pin)\s*[:=]\s*\d{4,8}\b", re.IGNORECASE), r"\1:[REDACTED_OTP]"),
    ]

    @classmethod
    def redact_string(cls, text: str) -> str:
        """Applies regex redactions to a string value."""
        if not isinstance(text, str) or not text:
            return text
        result = text
        for pattern, replacement in cls.REGEX_REDACTIONS:
            result = pattern.sub(replacement, result)
        return result

    @classmethod
    def sanitize(cls, data: Any, max_depth: int = 10) -> Any:
        """
        Recursively redacts dictionary keys, values, lists, and strings.
        Protects against infinite recursion and payload bloat.
        """
        if max_depth <= 0:
            return "[TRUNCATED_MAX_DEPTH]"

        if data is None or isinstance(data, (int, float, bool)):
            return data

        if isinstance(data, str):
            return cls.redact_string(data)

        if isinstance(data, bytes):
            return f"[BINARY_DATA_{len(data)}_BYTES]"

        if isinstance(data, dict):
            sanitized = {}
            for k, v in data.items():
                str_k = str(k)
                if cls.SENSITIVE_KEY_PATTERNS.search(str_k):
                    sanitized[str_k] = "[REDACTED]"
                else:
                    sanitized[str_k] = cls.sanitize(v, max_depth=max_depth - 1)
            return sanitized

        if isinstance(data, (list, tuple, set)):
            return [cls.sanitize(item, max_depth=max_depth - 1) for item in data]

        # For arbitrary objects, sanitize their dict representation or string representation
        if hasattr(data, "__dict__"):
            try:
                return cls.sanitize(vars(data), max_depth=max_depth - 1)
            except Exception:
                return cls.redact_string(str(data))

        return cls.redact_string(str(data))


# ==============================================================================
# 3. STRUCTURED EVENT DATA MODEL
# ==============================================================================

@dataclass
class StrokeEvent:
    event_id: str
    timestamp: float
    iso_time: str
    task_id: str
    category: str
    action: str
    status: str
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "iso_time": self.iso_time,
            "task_id": self.task_id,
            "category": self.category,
            "action": self.action,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "error": self.error,
        }


# ==============================================================================
# 4. USER-VISIBLE PROGRESS FORMATTER (CHANNEL SEPARATION)
# ==============================================================================

class UserProgressFormatter:
    """
    Generates clean, human-readable status messages for the UI chat channel,
    completely separate from dense internal telemetry and diagnostics.
    """
    FRIENDLY_ACTIONS = {
        ("provider", "infer"): "Reasoning with AI model...",
        ("provider", "stream"): "Streaming response...",
        ("tool", "execute"): "Executing agent tool...",
        ("tool", "verify_code"): "Validating Luau code syntax...",
        ("terminal", "run"): "Running terminal command...",
        ("terminal", "requires_approval"): "Waiting for command authorization...",
        ("filesystem", "create_file"): "Writing project file...",
        ("filesystem", "edit_file"): "Applying code patch...",
        ("filesystem", "read_file"): "Inspecting codebase context...",
        ("mcp", "execute"): "Calling MCP service...",
        ("download", "fetch"): "Downloading assets...",
        ("auth", "verify_token"): "Authenticating session...",
        ("persistence", "save_state"): "Saving workspace state...",
    }

    @classmethod
    def format_event(cls, event: StrokeEvent) -> Optional[str]:
        """Returns a user-friendly progress message or None if purely internal."""
        key = (event.category, event.action)
        prefix = cls.FRIENDLY_ACTIONS.get(key)
        if not prefix:
            if event.status == EventStatus.FAILURE:
                return f"Task encountered an issue: {event.action}."
            return None

        if event.status == EventStatus.START:
            return prefix
        elif event.status == EventStatus.SUCCESS:
            return f"{prefix} Done."
        elif event.status == EventStatus.FAILURE:
            return f"{prefix} Failed."
        elif event.status == EventStatus.REQUIRES_APPROVAL:
            return f"{prefix} Action requires your approval."
        return None


# ==============================================================================
# 5. CORE OBSERVABILITY SYSTEM (SINGLETON)
# ==============================================================================

class StrokeObservability:
    """
    Central, thread-safe observability hub.
    Maintains ring buffer of structured events, live subscriber queues,
    and calculates real, non-fabricated metrics.
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self, max_events: int = 5000):
        self._max_events = max_events
        self._events: List[StrokeEvent] = []
        self._subscribers: List[Callable[[StrokeEvent], None]] = []
        self._buffer_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "StrokeObservability":
        with cls._lock:
            if cls._instance is None:
                cls._instance = StrokeObservability()
            return cls._instance

    def emit(
        self,
        category: Union[EventCategory, str],
        action: str,
        task_id: str,
        status: Union[EventStatus, str],
        details: Optional[Dict[str, Any]] = None,
        error: Optional[Union[str, Exception]] = None,
        latency_ms: Optional[float] = None
    ) -> StrokeEvent:
        """
        Emits a structured event, automatically redacting sensitive data.
        Thread-safe and non-blocking for callers.
        """
        cat_str = category.value if isinstance(category, EventCategory) else str(category)
        stat_str = status.value if isinstance(status, EventStatus) else str(status)

        # Sanitize details and error
        sanitized_details = RedactionEngine.sanitize(details or {})
        sanitized_error = None
        if error is not None:
            sanitized_error = RedactionEngine.redact_string(str(error))

        now = time.time()
        iso_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        event = StrokeEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            timestamp=now,
            iso_time=iso_str,
            task_id=str(task_id or "global_task"),
            category=cat_str,
            action=str(action),
            status=stat_str,
            latency_ms=round(latency_ms, 2) if latency_ms is not None else None,
            details=sanitized_details,
            error=sanitized_error
        )

        with self._buffer_lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                # Evict oldest events to maintain ring buffer bounds
                self._events = self._events[-self._max_events:]

            # Notify active subscribers
            subs = list(self._subscribers)

        for sub in subs:
            try:
                sub(event)
            except Exception as e:
                logger.warning(f"Error in observability event subscriber: {e}")

        return event

    @contextmanager
    def trace_span(
        self,
        category: Union[EventCategory, str],
        action: str,
        task_id: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager that automatically tracks execution span start, finish,
        latency calculation, and exception capture.
        """
        start_t = time.time()
        self.emit(
            category=category,
            action=action,
            task_id=task_id,
            status=EventStatus.START,
            details=details
        )
        try:
            yield
            latency = (time.time() - start_t) * 1000.0
            self.emit(
                category=category,
                action=action,
                task_id=task_id,
                status=EventStatus.SUCCESS,
                latency_ms=latency,
                details=details
            )
        except Exception as exc:
            latency = (time.time() - start_t) * 1000.0
            self.emit(
                category=category,
                action=action,
                task_id=task_id,
                status=EventStatus.FAILURE,
                latency_ms=latency,
                details=details,
                error=exc
            )
            raise

    def get_events(
        self,
        task_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Returns filtered event dictionaries from the memory ring buffer."""
        with self._buffer_lock:
            filtered = self._events
            if task_id:
                filtered = [e for e in filtered if e.task_id == task_id]
            if category:
                filtered = [e for e in filtered if e.category == category]
            if status:
                filtered = [e for e in filtered if e.status == status]

            slice_events = filtered[-limit:]
            return [e.to_dict() for e in slice_events]

    def subscribe(self, callback: Callable[[StrokeEvent], None]):
        """Subscribes a listener to live events (e.g. SSE stream or audit writer)."""
        with self._buffer_lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[StrokeEvent], None]):
        with self._buffer_lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def clear(self):
        """Clears events in buffer (for test isolation)."""
        with self._buffer_lock:
            self._events.clear()

    # ==========================================================================
    # 6. AUTHENTIC METRICS DERIVATION
    # ==========================================================================

    def get_metrics(
        self,
        task_id: Optional[str] = None,
        time_window_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Derives real metrics from actual historical events.
        NEVER computes random, simulated, or hardcoded numbers.
        """
        now = time.time()
        with self._buffer_lock:
            events = self._events[:]

        if task_id:
            events = [e for e in events if e.task_id == task_id]
        if time_window_sec:
            cutoff = now - time_window_sec
            events = [e for e in events if e.timestamp >= cutoff]

        total_events = len(events)
        if total_events == 0:
            return {
                "total_events": 0,
                "task_id": task_id,
                "time_window_sec": time_window_sec,
                "categories": {},
                "status_distribution": {},
                "average_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "error_rate": 0.0,
                "tool_call_count": 0,
                "approval_requests": 0,
                "authentic": True
            }

        categories_count: Dict[str, int] = {}
        status_count: Dict[str, int] = {}
        latencies: List[float] = []
        tool_calls = 0
        approval_reqs = 0
        failures = 0

        for e in events:
            categories_count[e.category] = categories_count.get(e.category, 0) + 1
            status_count[e.status] = status_count.get(e.status, 0) + 1

            if e.category == EventCategory.TOOL.value or e.category == "tool":
                tool_calls += 1
            if e.status == EventStatus.REQUIRES_APPROVAL.value or e.status == "requires_approval":
                approval_reqs += 1
            if e.status in (EventStatus.FAILURE.value, "failure", EventStatus.TIMEOUT.value, "timeout"):
                failures += 1
            if e.latency_ms is not None:
                latencies.append(e.latency_ms)

        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        p95_latency = 0.0
        if latencies:
            sorted_lat = sorted(latencies)
            idx = int(0.95 * len(sorted_lat))
            p95_latency = round(sorted_lat[min(idx, len(sorted_lat) - 1)], 2)

        error_rate = round((failures / total_events) * 100.0, 2)

        return {
            "total_events": total_events,
            "task_id": task_id,
            "time_window_sec": time_window_sec,
            "categories": categories_count,
            "status_distribution": status_count,
            "average_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "error_rate": error_rate,
            "tool_call_count": tool_calls,
            "approval_requests": approval_reqs,
            "authentic": True
        }


# Global helper functions for zero-ceremony imports
def emit_event(
    category: Union[EventCategory, str],
    action: str,
    task_id: str,
    status: Union[EventStatus, str],
    details: Optional[Dict[str, Any]] = None,
    error: Optional[Union[str, Exception]] = None,
    latency_ms: Optional[float] = None
) -> StrokeEvent:
    return StrokeObservability.get_instance().emit(
        category=category,
        action=action,
        task_id=task_id,
        status=status,
        details=details,
        error=error,
        latency_ms=latency_ms
    )


def trace_span(
    category: Union[EventCategory, str],
    action: str,
    task_id: str,
    details: Optional[Dict[str, Any]] = None
):
    return StrokeObservability.get_instance().trace_span(
        category=category,
        action=action,
        task_id=task_id,
        details=details
    )

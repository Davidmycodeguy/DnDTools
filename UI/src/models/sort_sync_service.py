"""
SortSyncService — learns from your own sorts, on this PC.

While "Sort learning" is on, a background worker trains the sort risk and item-priority models from
the local SortEventStore every half hour (and right after it is switched on). Nothing is uploaded
and no models are downloaded: the upstream version synced sort data with its author's server;
this app keeps it local.

Wire-up (in app.py):
    sync = SortSyncService(settings_manager=settings_manager, app_version=APP_VERSION)
    sync.start()
"""
import logging
import threading
from typing import Any, Dict, Optional

from src.models.sort_event_store import SortEventStore, get_event_store
from src.models.sort_model import SortAdaptiveModel, get_sort_adaptive_model

logger = logging.getLogger(__name__)

SETTING = "sortFeedbackSyncEnabled"  # the setting's historical name; it now means "learn locally"


class SortSyncService:
    TRAIN_INTERVAL = 60 * 30  # 30 minutes
    FIRST_RUN_DELAY = 5.0

    def __init__(
        self,
        *,
        settings_manager,
        app_version: str,
        model: Optional[SortAdaptiveModel] = None,
        event_store: Optional[SortEventStore] = None,
    ) -> None:
        self._settings = settings_manager
        self._app_version = app_version
        self.model = model or get_sort_adaptive_model()
        self.event_store = event_store or get_event_store()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._train_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._enabled_state = self._enabled()

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._enabled():
            logger.info("Sort learning is off")
            return
        self._ensure_worker()
        self.trigger_sync(immediate=True)

    def stop(self) -> None:
        self._stop_event.set()
        self._train_event.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=3.0)

    def apply_settings(self, settings: Dict[str, Any]) -> None:
        if SETTING not in settings:
            return
        enabled = bool(settings.get(SETTING))
        with self._lock:
            was_enabled, self._enabled_state = self._enabled_state, enabled
        if enabled and not was_enabled:
            logger.info("Sort learning switched on; training now")
            self._ensure_worker()
            self.trigger_sync(immediate=True)

    def trigger_sync(self, *, immediate: bool = False) -> None:
        """Ask for a training pass (the name is kept for callers)."""
        if not self._enabled():
            return
        self._train_event.set()
        if immediate:
            self._ensure_worker()

    # ── Worker ───────────────────────────────────────────────────────

    def _enabled(self) -> bool:
        try:
            return bool(self._settings.get(SETTING, False))
        except Exception:
            return False

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        worker = threading.Thread(target=self._worker_loop, name="SortLearning", daemon=True)
        self._worker = worker
        worker.start()

    def _worker_loop(self) -> None:
        self._stop_event.wait(self.FIRST_RUN_DELAY)
        while not self._stop_event.is_set():
            self._train_event.wait(timeout=self.TRAIN_INTERVAL)
            self._train_event.clear()
            if self._stop_event.is_set():
                break
            if self._enabled():
                self._train_locally()

    def _train_locally(self) -> None:
        """Train both heads from the local event store."""
        try:
            risk_events = self.event_store.get_risk_training_data(limit=5000)
            if risk_events:
                self.model.train_risk(risk_events, async_=True)
        except Exception as exc:
            logger.debug("Local risk training failed: %s", exc, exc_info=True)
        try:
            item_events = self.event_store.get_item_training_data(limit=10000)
            if item_events:
                self.model.train_items(item_events, async_=True)
        except Exception as exc:
            logger.debug("Local item training failed: %s", exc, exc_info=True)

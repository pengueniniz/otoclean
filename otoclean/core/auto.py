"""Arayüzsüz otomatik güvenli temizlik (zamanlanmış görev bunu çalıştırır)."""

from __future__ import annotations

import logging

from . import winapi
from .classifier import apply_protection, dedupe, evaluate_location_rules
from .cleaner import Cleaner, CleanOptions
from .history import History
from .models import CleanResult, RiskLevel
from .protected import ProtectionPolicy, default_policy
from .rules.catalog import LOCATION_RULES, LocationRule
from .settings import Settings, load_settings

log = logging.getLogger(__name__)


def auto_rules(rules: tuple[LocationRule, ...] = LOCATION_RULES, *,
               admin: bool) -> list[LocationRule]:
    """Sadece otomatik silinmesine izin verilen 🟢 kurallar."""
    return [r for r in rules
            if r.category.auto_ok and r.category.risk is RiskLevel.SAFE
            and (admin or not r.category.needs_admin)]


def run_auto_safe(*, policy: ProtectionPolicy | None = None, cleaner: Cleaner | None = None,
                  history: History | None = None, settings: Settings | None = None,
                  rules: tuple[LocationRule, ...] = LOCATION_RULES) -> CleanResult:
    policy = policy or default_policy()
    settings = settings or load_settings()
    selected = auto_rules(rules, admin=winapi.is_admin())
    findings = dedupe(apply_protection(evaluate_location_rules(selected), policy))
    result = (cleaner or Cleaner(policy)).clean(
        findings, CleanOptions(use_native=settings.use_native,
                               permanent_caches=settings.permanent_caches))
    try:
        (history or History()).record(result, "auto")
    except Exception:  # Temizlik yapıldı; geçmiş kaydı hatası sonucu bozmasın
        log.exception("Otomatik temizlik geçmişe yazılamadı")
    log.info("Otomatik temizlik: %d byte, %d öğe, %d atlandı",
             result.freed, len(result.deleted), len(result.skipped))
    return result

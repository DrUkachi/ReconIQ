import hashlib
from collections import Counter
from dataclasses import dataclass, field

from app.core.errors import BankReconError, ErrorCode
from app.services.llm.schemas import CallSite

# PRD section 08 hard budget. A per-run counter enforces this and logs E_LLM_BUDGET
# on breach, so "we use the LLM sparingly" is a checkable claim rather than a promise.

PER_SITE_LIMITS: dict[CallSite, int] = {
    CallSite.L1_COLUMN_MAP: 1,  # per statement
    CallSite.L2_COUNTERPARTY: 200,  # uncached, per reconciliation
    CallSite.L3_EVIDENCE_SUMMARY: 10,  # per case
    CallSite.L4_ORCHESTRATION: 6,  # turns per invocation
    CallSite.L5_REPLY_INTENT: 1,  # per reply
    CallSite.L6_CASE_ROUTING: 10,  # per run: one call per batch of cases, plus a retry
}


@dataclass
class RunBudget:
    """Counts calls per site and overall for one run.

    L2 is cached by sha256(narration): a repeat narration costs nothing and does
    not consume budget, which is what makes 200 enough for a real statement.
    """

    total_limit: int = 250
    counts: Counter[CallSite] = field(default_factory=Counter)
    total: int = 0
    _l2_cache: dict[str, str | None] = field(default_factory=dict)

    def check(self, site: CallSite, scope_limit: int | None = None) -> None:
        limit = scope_limit if scope_limit is not None else PER_SITE_LIMITS[site]
        if self.counts[site] >= limit:
            raise BankReconError(ErrorCode.E_LLM_BUDGET, site=str(site), limit=limit)
        if self.total >= self.total_limit:
            raise BankReconError(ErrorCode.E_LLM_BUDGET, site="total", limit=self.total_limit)

    def consume(self, site: CallSite) -> None:
        self.counts[site] += 1
        self.total += 1

    def remaining(self, site: CallSite) -> int:
        return max(0, PER_SITE_LIMITS[site] - self.counts[site])

    @staticmethod
    def narration_key(narration: str) -> str:
        return hashlib.sha256(narration.strip().upper().encode()).hexdigest()

    def cached_counterparty(self, narration: str) -> tuple[bool, str | None]:
        key = self.narration_key(narration)
        if key in self._l2_cache:
            return True, self._l2_cache[key]
        return False, None

    def cache_counterparty(self, narration: str, value: str | None) -> None:
        self._l2_cache[self.narration_key(narration)] = value

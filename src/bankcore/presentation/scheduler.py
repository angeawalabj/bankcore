"""
BankCore — Day 15: InterestScheduler (Primary Adapter)
========================================================
Applies annual interest to all eligible savings accounts.

This is a primary adapter (driving adapter) for scheduled operations.
It drives BankCore the same way a CLI or API would — through Commands.

Hexagonal Architecture rule:
    The scheduler knows WHEN to run and WHICH accounts to select.
    It does NOT know HOW interest is calculated (that's the Domain).
    It does NOT know WHERE data is stored (that's the Repository).

In production this would be triggered by:
    - A cron job: `0 0 1 1 * python -m bankcore.scheduler apply_interest`
    - A cloud scheduler (AWS EventBridge, GCP Cloud Scheduler)
    - A message queue consumer (Day 18)

Usage:
    scheduler = InterestScheduler(app_service, repo)
    report = scheduler.run()
    print(f"Applied interest to {report.accounts_processed} accounts")
    print(f"Total credited: {report.total_credited:.2f} EUR")
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bankcore.application.commands import ApplyInterestCommand
from bankcore.application.specifications import InterestEligibleSpec
from bankcore.application.ports import AccountRepositoryPort


@dataclass
class SchedulerReport:
    """Summary of a scheduler run."""
    run_at:              datetime = field(default_factory=datetime.now)
    accounts_processed:  int   = 0
    accounts_skipped:    int   = 0
    total_credited:      float = 0.0
    errors:              list  = field(default_factory=list)
    duration_ms:         float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.accounts_processed + len(self.errors)
        if total == 0:
            return 1.0
        return self.accounts_processed / total

    def summary(self) -> str:
        return (
            f"InterestScheduler — {self.run_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"  Processed : {self.accounts_processed} accounts\n"
            f"  Skipped   : {self.accounts_skipped} accounts\n"
            f"  Errors    : {len(self.errors)}\n"
            f"  Credited  : {self.total_credited:,.2f} EUR\n"
            f"  Duration  : {self.duration_ms:.1f}ms\n"
            f"  Success   : {self.success_rate * 100:.1f}%"
        )


class InterestScheduler:
    """
    Primary adapter: drives BankCore to apply interest to all eligible accounts.

    Uses Specification Pattern (Day 14) to find eligible accounts.
    Uses ApplyInterestCommand (Day 11) to execute the operation.
    Produces a SchedulerReport for monitoring and audit.
    """

    def __init__(
        self,
        app_service,
        repository: AccountRepositoryPort,
        page_size: int = 100,
    ) -> None:
        self._app      = app_service
        self._repo     = repository
        self._page_size = page_size

    def run(self, dry_run: bool = False) -> SchedulerReport:
        """
        Apply interest to all eligible accounts.

        Args:
            dry_run: if True, identify eligible accounts but don't apply.

        Returns:
            SchedulerReport with full execution summary.
        """
        import time
        start = time.perf_counter()

        report = SchedulerReport()
        spec   = InterestEligibleSpec()
        page   = 1

        while True:
            batch = self._repo.find(spec, page=page, page_size=self._page_size)

            if not batch.items:
                break

            for account in batch.items:
                try:
                    if dry_run:
                        # Preview only — don't execute
                        report.accounts_skipped += 1
                        continue

                    cmd    = ApplyInterestCommand(account.account_id, "scheduler")
                    result = self._app.apply_interest(cmd)

                    if result.success:
                        report.accounts_processed += 1
                        report.total_credited += result.data.get("interest_credited", 0.0)
                    else:
                        report.accounts_skipped += 1

                except Exception as exc:
                    report.errors.append({
                        "account_id": account.account_id,
                        "error":      str(exc),
                    })

            if not batch.has_next:
                break
            page += 1

        report.duration_ms = (time.perf_counter() - start) * 1000
        return report

    def preview(self) -> dict:
        """
        Returns a preview of what would happen on run() without executing.
        """
        spec     = InterestEligibleSpec()
        eligible = self._repo.find(spec, page=1, page_size=999_999)

        previews = []
        for account in eligible.items:
            interest = account.balance * account.interest_rate
            previews.append({
                "account_id":   account.account_id,
                "owner":        account.owner_name,
                "balance":      account.balance,
                "interest_rate": account.interest_rate,
                "would_credit": round(interest, 2),
            })

        return {
            "eligible_count":   len(previews),
            "total_to_credit":  sum(p["would_credit"] for p in previews),
            "accounts":         previews,
        }

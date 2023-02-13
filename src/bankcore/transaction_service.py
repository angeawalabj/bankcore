"""
BankCore — Day 03/06: TransactionService
==========================================
Day 06 SRP update: EventBuilder extracted.
TransactionService no longer constructs BankEvent objects inline.
It delegates event construction to EventBuilder.
"""

from bankcore.account import Account
from bankcore.alert_system import AlertSystem
from bankcore.config_manager import ConfigManager
from bankcore.event_builder import EventBuilder
from bankcore.transaction_processor import TransactionProcessor


class TransactionService(TransactionProcessor):
    """
    Core transaction engine — moves money between accounts.
    Single responsibility: execute financial operations correctly.
    Day 06: delegates event construction to EventBuilder.
    """

    def __init__(
        self,
        config=None,
        alert_system=None,
        event_builder=None,
    ) -> None:
        # DIP: accept injected dependencies; fall back to Singletons
        # for backward compatibility with all 308 existing tests.
        self._config       = config       or ConfigManager.get_instance()
        self._alert_system = alert_system or AlertSystem.get_instance()
        self._builder      = event_builder or EventBuilder()

    def deposit(self, account: Account, amount: float) -> dict:
        if amount <= 0:
            return {"success": False, "reason": "Amount must be positive."}

        success = account.deposit(amount, description="Deposit via TransactionService")

        if success:
            self._alert_system.publish(EventBuilder.deposit_event(account, amount))

        return {
            "success":      success,
            "account_id":   account.account_id,
            "amount":       amount,
            "balance_after": account.balance,
        }

    def withdraw(self, account: Account, amount: float) -> dict:
        if amount <= 0:
            return {"success": False, "reason": "Amount must be positive."}

        success = account.withdraw(amount, description="Withdrawal via TransactionService")

        if success:
            self._alert_system.publish(EventBuilder.withdrawal_event(account, amount))

        return {
            "success":      success,
            "account_id":   account.account_id,
            "amount":       amount,
            "balance_after": account.balance,
            "reason":       None if success else "Account rules rejected the withdrawal.",
        }

    def transfer(self, from_account: Account, to_account: Account, amount: float) -> dict:
        max_amount = self._config.get("limits.max_transfer_amount", 50_000.0)

        if amount <= 0:
            return {"success": False, "reason": "Amount must be positive."}
        if amount > max_amount:
            return {"success": False,
                    "reason": f"Exceeds maximum transfer limit of {max_amount:.2f} EUR."}
        if from_account.account_id == to_account.account_id:
            return {"success": False, "reason": "Cannot transfer to the same account."}

        withdrawn = from_account.withdraw(
            amount, description=f"Transfer to {to_account.account_id}"
        )
        if not withdrawn:
            return {
                "success":      False,
                "reason":       "Withdrawal refused (insufficient funds or account rules).",
                "balance_after": from_account.balance,
            }

        deposited = to_account.deposit(
            amount, description=f"Transfer from {from_account.account_id}"
        )
        if not deposited:
            from_account.deposit(amount, description="Transfer reversal")
            return {"success": False, "reason": "Deposit failed — withdrawal reversed."}

        self._alert_system.publish(
            EventBuilder.transfer_event(from_account, to_account, amount)
        )

        return {
            "success":           True,
            "from_account":      from_account.account_id,
            "to_account":        to_account.account_id,
            "amount":            amount,
            "from_balance_after": from_account.balance,
            "to_balance_after":   to_account.balance,
        }

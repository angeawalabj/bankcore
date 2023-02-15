"""
BankCore — Day 05: TransactionProcessor interface & base Decorator
===================================================================
Introduces a common interface that both TransactionService and all
Decorators implement — the key requirement of the Decorator pattern.

Before Day 05, TransactionService had no formal interface.
Decorators couldn't wrap it cleanly without one.

Design decision: extract the interface NOW, before the codebase grows.
Retrofitting an interface onto a large service is expensive.
This is the lesson of Day 05 applied to itself.
"""

from abc import ABC, abstractmethod
from bankcore.interfaces import Depositable, Withdrawable, Transferable


class TransactionProcessor(Depositable, Withdrawable, Transferable, ABC):
    """
    Common interface for TransactionService and all its Decorators.

    Day 09 (ISP): now explicitly implements the three granular interfaces:
      - Depositable  → deposit()
      - Withdrawable → withdraw()
      - Transferable → transfer()

    This allows clients to depend only on the capability they need:
      - A BatchTransferService only needs Transferable
      - A TopUpService only needs Depositable
      - A FullService needs TransactionProcessor (all three)
    """

    @abstractmethod
    def deposit(self, account, amount: float) -> dict:
        """Credit an account. Returns result dict with success status."""

    @abstractmethod
    def withdraw(self, account, amount: float) -> dict:
        """Debit an account. Returns result dict with success status."""

    @abstractmethod
    def transfer(self, from_account, to_account, amount: float) -> dict:
        """
        Move funds between accounts.
        Returns result dict with success status and balances.
        """


class TransactionDecorator(TransactionProcessor):
    """
    Base class for all TransactionProcessor decorators.

    Delegates all three operations to the wrapped processor by default.
    Subclasses override only the operations they care about.

    This avoids the boilerplate of re-implementing deposit/withdraw/transfer
    in every decorator that only cares about, say, logging.
    """

    def __init__(self, processor: TransactionProcessor) -> None:
        self._wrapped = processor

    def deposit(self, account, amount: float) -> dict:
        return self._wrapped.deposit(account, amount)

    def withdraw(self, account, amount: float) -> dict:
        return self._wrapped.withdraw(account, amount)

    def transfer(self, from_account, to_account, amount: float) -> dict:
        return self._wrapped.transfer(from_account, to_account, amount)

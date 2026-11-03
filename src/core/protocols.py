'''
src/core/protocols.py

-> do I need runtime_checkable if protocol inherit?
'''
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .router import EventRouter


class Subscribable(Protocol):

    def register_subscriptions(self, router: EventRouter) -> None:
        '''Registers methods to the Event'''
        ...


class Lifecycle(Protocol):
    def start(self) -> None:
        '''Initiates open connection with external components'''
        ...

    def stop(self) -> None:
        '''Stops and safely closes connection'''
        ...
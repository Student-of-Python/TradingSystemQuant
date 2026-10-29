'''
src/spine/router.py
#TODO: Make test cases
'''
from typing import Callable, Iterable, overload
from collections import defaultdict, deque
from .events import Event


class EventRouter:
    def __init__(self):
        self._queue: deque[Event] = deque()
        self._registry: defaultdict[type[Event], set[Callable[..., None]]] = defaultdict(set)

    @overload
    def subscribe[T: Event](self, event: type[T], contact: Callable[[T], None]) -> None:
        ...

    @overload
    def subscribe[T: Event](self, event: Iterable[type[T]], contact: Callable[[T], None]) -> None:
        ...

    def subscribe[T: Event](self, event: type[T] | Iterable[type[T]],
                            contact: Callable[[T], None]) -> None:
        """Adds event & func to the registry"""

        events = (event,) if isinstance(event, type) else event

        for e in events:
            self._registry[e].add(contact)


    def publish(self, *event: Event) -> None:
        '''Adds event to the queue'''
        self._queue.extend(event)


    def dispatch_next(self) -> None:
        '''Executes based on relevant event'''
        if len(self._queue) == 0:
            return

        _next = self._queue.popleft()
        _funcs = self._registry[type(_next)]

        if _funcs:

            for func in _funcs:
                func(_next)

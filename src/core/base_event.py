'''
src/core/base_event.py

This module holds events. An event is an immutable object that represents something that has already occured.
'''
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

@dataclass(frozen=True)
class BaseEvent:
    '''Base event'''

    event_id: uuid.UUID = field(default_factory=uuid.uuid4, kw_only=True) #May need a pip install for uuid 7? It has time based tracking
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
        kw_only=True,
    )

    @property
    def event_tag(self) -> str:
        '''Returns id of event

        returns format: {CLASSNAME}_{ID}
        '''
        return f"{type(self).__name__}_{self.event_id}"
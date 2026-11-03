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

    _event_id: uuid.UUID = field(default_factory=uuid.uuid7, kw_only=True) #May need a pip install for uuid 7

    @property
    def created_at(self) -> datetime:
        '''Returns time of creation'''
        timestamp_ms = self._event_id.int >> 80
        return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)

    @property
    def event_tag(self) -> str:
        '''Returns id of event

        returns format: {CLASSNAME}_{ID}"
        '''
        return f"{type(self).__name__}_{self._event_id}"
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from agent_spine.actions import value_redact
from agent_spine.auth import utc_now


CAPTURE_SINKS = ContextVar('agent_spine_audit_sinks', default=())


@contextmanager
def capture():
    events = []
    token = CAPTURE_SINKS.set(CAPTURE_SINKS.get() + (events.append,))
    try:
        yield events
    finally:
        CAPTURE_SINKS.reset(token)


def emit(store, ctx, event_type, resource_type='', resource_id='', outcome='',
         reason_code='', safe_details=None, trace_id=''):
    event = {
        'event_id': 'evt_%s' % uuid4().hex,
        'timestamp': utc_now(),
        'request_id': ctx.request_id,
        'run_id': ctx.run_id,
        'thread_id': ctx.thread_id,
        'organization_id': ctx.principal.organization_id,
        'principal_id': ctx.principal.principal_id,
        'event_type': event_type,
        'resource_type': resource_type or '',
        'resource_id': resource_id or '',
        'outcome': outcome or '',
        'reason_code': reason_code or '',
        'safe_details': value_redact(dict(safe_details or {})),
        'trace_id': trace_id or '',
    }
    if store is not None:
        store.audit_insert(event)
    sinks = CAPTURE_SINKS.get()
    for sink in sinks:
        sink(event)
    return event

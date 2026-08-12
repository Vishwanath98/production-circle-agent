from langsmith import traceable


def enable():
    return None


def disable():
    return None


def is_enabled():
    return True


def reset():
    return None


def events():
    return []


def emit(kind, name, **data):
    return None


def logic_node_named(name, fn):
    if getattr(fn, 'traceable', False):
        return fn
    rv = traceable(name=name, run_type='tool')(fn)
    return rv


def logic_node(fn):
    name = getattr(fn, '__name__', 'tool')
    rv = logic_node_named(name, fn)
    return rv


def logic_router(fn):
    return fn


def logic_tool(fn):
    name = getattr(fn, '__name__', 'tool')
    rv = logic_node_named(name, fn)
    return rv


def instrument(module, nodes=(), routers=(), tools=()):
    for name in tools:
        fn = getattr(module, name)
        setattr(module, name, logic_tool(fn))


def summarize(trace):
    rv = {
        'total_events': 0,
        'by_kind': {},
        'nodes': [],
        'decisions': [],
        'tools': [],
    }
    return rv

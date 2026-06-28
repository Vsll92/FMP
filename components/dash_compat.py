"""Dash compatibility fallback for headless QA. Uses real Dash when installed."""
try:
    import dash as dash
    from dash import dcc, html, Input, Output, State, callback, no_update
    DASH_AVAILABLE = True
except Exception:
    DASH_AVAILABLE = False
    no_update = object()
    class _Component:
        def __init__(self, *children, **props):
            if "children" in props:
                self.children = props.pop("children")
            elif len(children) == 0:
                self.children = None
            elif len(children) == 1:
                self.children = children[0]
            else:
                self.children = list(children)
            for k, v in props.items(): setattr(self, k, v)
            self.props = props
    class _Namespace:
        def __getattr__(self, name):
            cls = type(name, (_Component,), {})
            setattr(self, name, cls)
            return cls
    html = _Namespace(); dcc = _Namespace()
    class Input:
        def __init__(self, component_id, component_property): self.component_id=component_id; self.component_property=component_property
    class Output(Input): pass
    class State(Input): pass
    def callback(*args, **kwargs):
        def deco(fn): return fn
        return deco
    class _Dash:
        def __init__(self,*args,**kwargs): self.server=None; self.layout=None
        def callback(self,*args,**kwargs): return callback(*args,**kwargs)
        def run_server(self,*args,**kwargs): raise RuntimeError("Dash is not installed; install requirements.txt to run the app.")
    class _DashModule:
        Dash=_Dash
    dash=_DashModule()

from __future__ import absolute_import
import types

import weakref

from sentry_sdk.hub import Hub, _should_send_default_pii
from sentry_sdk.utils import capture_internal_exceptions, event_from_exception
from sentry_sdk.integrations import Integration
from sentry_sdk.integrations.wsgi import SentryWsgiMiddleware
from sentry_sdk.integrations._wsgi_common import RequestExtractor

if False:
    from sentry_sdk.integrations.wsgi import _ScopedResponse
    from typing import Any
    from typing import Dict
    from typing import Union
    from typing import Callable
    from bottle import FileUpload, FormsDict

#from flask import Request, Flask, _request_ctx_stack, _app_ctx_stack  # type: ignore
from bottle import Bottle, BaseRequest

#from flask.signals import (
    #appcontext_pushed,
    ##appcontext_tearing_down,
    #got_request_exception,
    #request_started,
#)


class BottleIntegration(Integration):
    identifier = "bottle"

    transaction_style = None

    def __init__(self, transaction_style="endpoint"):
        # type: (str) -> None
        TRANSACTION_STYLE_VALUES = ("endpoint", "url")
        if transaction_style not in TRANSACTION_STYLE_VALUES:
            raise ValueError(
                "Invalid value for transaction_style: %s (must be in %s)"
                % (transaction_style, TRANSACTION_STYLE_VALUES)
            )
        self.transaction_style = transaction_style

    @staticmethod
    def setup_once():
        # type: () -> None

        #appcontext_pushed.connect(_push_appctx)
        #appcontext_tearing_down.connect(_pop_appctx)
        #request_started.connect(_request_started)
        #got_request_exception.connect(_capture_exception)

        old_app = Bottle.__call__

        def sentry_patched_wsgi_app(self, environ, start_response):
            # type: (Any, Dict[str, str], Callable) -> _ScopedResponse

            hub = Hub.current
            integration = hub.get_integration(BottleIntegration)
            if integration is None:
                return old_app(self, environ, start_response)

            # monkey patch method self(Bottle).router.match -> (route, args)
            # to monkey patch route.call
            old_match = self.router.match

            def patched_match(*args, **kwargs):
                route, route_args = old_match(*args, **kwargs)
                old_call = route.call

                def patched_call(*args, **kwargs):
                    try:
                        old_call(*args, **kwargs)
                    except Exception as exception:
                        hub = Hub.current
                        event, hint = event_from_exception(
                            exception, client_options=hub.client.options,
                            mechanism={"type": "bottle", "handled": Bottle.catchall},
                        )
                        hub.capture_event(event, hint=hint)
                        raise exception

                route.call = patched_call
                return route, route_args

            self.router.match = patched_match

            # monkey patch method self(Bottle)._handle
            old_handle = self._handle

            def _patched_handle(self, environ):
                hub = Hub.current
                with open("/tmp/neco.txt", "a") as f: f.write("SSS %s\n" % [e[1] for e in hub._stack])
                # create new scope
                scope_manager = hub.push_scope()

                with scope_manager:

                    app = self
                    while hasattr(app, 'app'):
                        app = app.app  # to level app

                    with hub.configure_scope() as scope:
                        import bottle
                        scope._name = "bottle"

                        scope.add_event_processor(
                            _make_request_event_processor(
                                app, bottle.request, integration
                            )
                        )
                    res = old_handle(environ)
                    with open("/tmp/neco.txt", "a") as f: f.write("SSS %s\n" % [e[1] for e in hub._stack])

                # scope cleanup
                return res

            self._handle = types.MethodType(_patched_handle, self)

            return SentryWsgiMiddleware(lambda *a, **kw: old_app(self, *a, **kw))(
                environ, start_response
            )

        Bottle.__call__ = sentry_patched_wsgi_app  # type: ignore


def _push_appctx(*args, **kwargs):
    # type: (*Flask, **Any) -> None
    hub = Hub.current
    if hub.get_integration(FlaskIntegration) is not None:
        # always want to push scope regardless of whether WSGI app might already
        # have (not the case for CLI for example)
        scope_manager = hub.push_scope()
        scope_manager.__enter__()
        _app_ctx_stack.top.sentry_sdk_scope_manager = scope_manager
        with hub.configure_scope() as scope:
            scope._name = "flask"


def _pop_appctx(*args, **kwargs):
    # type: (*Flask, **Any) -> None
    scope_manager = getattr(_app_ctx_stack.top, "sentry_sdk_scope_manager", None)
    if scope_manager is not None:
        scope_manager.__exit__(None, None, None)


def _request_started(sender, **kwargs):
    # type: (Flask, **Any) -> None
    hub = Hub.current
    integration = hub.get_integration(FlaskIntegration)
    if integration is None:
        return

    weak_request = weakref.ref(_request_ctx_stack.top.request)
    app = _app_ctx_stack.top.app
    with hub.configure_scope() as scope:
        scope.add_event_processor(
            _make_request_event_processor(  # type: ignore
                app, weak_request, integration
            )
        )


class BottleRequestExtractor(RequestExtractor):
    def env(self):
        # type: () -> Dict[str, str]
        with open("/tmp/neco.txt", "a") as f: f.write("ENV\n")
        return self.request.environ

    def cookies(self):
        with open("/tmp/neco.txt", "a") as f: f.write("COOKIES\n")
        # type: () -> Dict[str, str]
        return self.request.cookies

    def raw_data(self):
        with open("/tmp/neco.txt", "a") as f: f.write("RAW\n")
        # type: () -> bytes
        return self.request.body.read()

    def form(self):
        with open("/tmp/neco.txt", "a") as f: f.write("FORM\n")
        # type: () -> FormsDict
        return self.request.forms

    def files(self):
        # type: () -> Dict[str, str]
        with open("/tmp/neco.txt", "a") as f: f.write("FILES\n")
        res = self.request.files
        with open("/tmp/neco.txt", "a") as f: f.write("FILESR %s\n" % res)
        return res

    def size_of_file(self, file):
        with open("/tmp/neco.txt", "a") as f: f.write("SIZE OF\n")
        # type: (FileUpload) -> int
        return file.content_length


def _make_request_event_processor(app, request, integration):
    # type: (Flask, Callable[[], Request], FlaskIntegration) -> Callable
    def inner(event, hint):
        with open("/tmp/neco.txt", "a") as f: f.write("III 0\n")
        # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]

        # if the request is gone we are fine not logging the data from
        # it.  This might happen if the processor is pushed away to
        # another thread.
        if request is None:
            return event

        with open("/tmp/neco.txt", "a") as f: f.write("III 1\n")
        try:
            if integration.transaction_style == "endpoint":
                event["transaction"] = request.url_rule.endpoint  # type: ignore
            elif integration.transaction_style == "url":
                event["transaction"] = request.url_rule.rule  # type: ignore
        except Exception:
            pass
        with open("/tmp/neco.txt", "a") as f: f.write("III 2\n")

        with capture_internal_exceptions():
            with open("/tmp/neco.txt", "a") as f: f.write("III 3\n")
            BottleRequestExtractor(request).extract_into_event(event)
            with open("/tmp/neco.txt", "a") as f: f.write("III 4\n")

        return event

    return inner


def _capture_exception(sender, exception, **kwargs):
    # type: (Flask, Union[ValueError, BaseException], **Any) -> None
    hub = Hub.current
    if hub.get_integration(FlaskIntegration) is None:
        return
    event, hint = event_from_exception(
        exception,
        client_options=hub.client.options,
        mechanism={"type": "flask", "handled": False},
    )

    hub.capture_event(event, hint=hint)

from io import BytesIO
from bottle import (
    Bottle, tob, py3k, debug as set_debug, abort
)
from sentry_sdk import (
    configure_scope,
    capture_message,
    capture_exception,
    last_event_id,
)

import sentry_sdk

from sentry_sdk.integrations.logging import LoggingIntegration
from werkzeug.test import Client

import sentry_sdk.integrations.bottle as bottle_sentry


app = Bottle()


@app.route("/message")
def hi():
    capture_message("hi")
    return "ok"


@app.route("/message-named-route", name="hi")
def named_hi():
    capture_message("hi")
    return "ok"




def sentry_init(*a, **kw):
    hub = sentry_sdk.Hub.current
    client = sentry_sdk.Client(*a, **kw)
    hub.bind_client(client)


sentry_init(integrations=[bottle_sentry.BottleIntegration()])

app.catchall = False


def crashing_app(environ, start_response):
    1 / 0


app.mount("/wsgi/", crashing_app)

client = Client(app)

#exceptions = capture_exceptions()
#events = capture_events()

client.get("/wsgi/")

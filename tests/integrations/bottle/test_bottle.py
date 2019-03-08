import json
import pytest
import wsgiref.validate
import wsgiref.util
import uuid
import mimetypes


pytest.importorskip("bottle")

from bottle import Bottle, tob, py3k, debug as set_debug, unicode
from sentry_sdk import (
    configure_scope,
    capture_message,
    capture_exception,
    last_event_id,
)

from sentry_sdk.integrations.logging import LoggingIntegration
from werkzeug.test import Client

import sentry_sdk.integrations.bottle as bottle_sentry


@pytest.fixture(scope="function")
def app(sentry_init):
    app = Bottle()

    @app.route("/capture")
    def capture_route():
        capture_message("captured")
        return "Captured"

    yield app


@pytest.fixture
def get_client(app):

    def inner():
        return Client(app)

    return inner


def test_has_context(sentry_init, app, capture_events, get_client):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()])
    events = capture_events()

    client = get_client()
    response = client.get("/capture")
    assert response[1] == '200 OK'

    event, = events
    assert event["message"] == "captured"
    assert "data" not in event["request"]
    assert event["request"]["url"] == "http://localhost/capture"


@pytest.mark.parametrize("debug", (True, False), ids=["debug", "nodebug"])
@pytest.mark.parametrize("catchall", (True, False), ids=["catchall", "nocatchall"])
def test_errors(sentry_init, capture_exceptions, capture_events, app, debug, catchall, get_client):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()])

    app.catchall = catchall
    set_debug(mode=debug)

    exceptions = capture_exceptions()
    events = capture_events()

    @app.route("/")
    def index():
        1 / 0

    client = get_client()
    try:
        client.get("/")
    except ZeroDivisionError:
        pass

    exc, = exceptions
    assert isinstance(exc, ZeroDivisionError)

    event, = events
    assert event["exception"]["values"][0]["mechanism"]["type"] == "bottle"


def test_bottle_large_json_request(sentry_init, capture_events, app, get_client):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()])

    data = {"foo": {"bar": "a" * 2000}}

    @app.route("/", method="POST")
    def index():
        import bottle
        assert bottle.request.json == data
        assert bottle.request.body.read() == json.dumps(data).encode("ascii")
        capture_message("hi")
        return "ok"

    events = capture_events()

    client = get_client()
    response = client.get("/")

    response = client.post(
        "/", content_type="application/json", data=json.dumps(data)
    )
    assert response[1] == '200 OK'

    event, = events
    #__import__("pdb").set_trace()
    assert event["_meta"]["request"]["data"]["foo"]["bar"] == {
        "": {"len": 2000, "rem": [["!limit", "x", 509, 512]]}
    }
    assert len(event["request"]["data"]["foo"]["bar"]) == 512

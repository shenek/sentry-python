import json
import pytest
import wsgiref.validate
import wsgiref.util
import uuid
import mimetypes


pytest.importorskip("bottle")

from io import BytesIO
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

    @app.route("/message")
    def hi():
        capture_message("hi")
        return "ok"

    @app.route("/message-named-route", name="hi")
    def named_hi():
        capture_message("hi")
        return "ok"

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
    response = client.get("/message")
    assert response[1] == '200 OK'

    event, = events
    assert event["message"] == "hi"
    assert "data" not in event["request"]
    assert event["request"]["url"] == "http://localhost/message"


@pytest.mark.parametrize(
    "url,transaction_style,expected_transaction", [
        ("/message", "endpoint", "hi"),
        ("/message", "url", "/message"),
        ("/message-named-route", "endpoint", "hi")
    ]
)
def test_transaction_style(
    sentry_init, app, capture_events, transaction_style, expected_transaction, url, get_client
):
    sentry_init(
        integrations=[
            bottle_sentry.BottleIntegration(transaction_style=transaction_style)
        ]
    )
    events = capture_events()

    client = get_client()
    response = client.get("/message")
    assert response[1] == '200 OK'

    event, = events
    assert event["transaction"] == expected_transaction


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


@pytest.mark.parametrize("data", [{}, []], ids=["empty-dict", "empty-list"])
def test_bottle_empty_json_request(sentry_init, capture_events, app, data, get_client):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()])

    @app.route("/", method="POST")
    def index():
        import bottle
        assert bottle.request.json == data
        assert bottle.request.body.read() == json.dumps(data).encode("ascii")
        #assert not bottle.request.forms
        capture_message("hi")
        return "ok"

    events = capture_events()

    client = get_client()
    response = client.post("/", content_type="application/json", data=json.dumps(data))
    assert response[1] == '200 OK'

    event, = events
    assert event["request"]["data"] == data


def test_bottle_medium_formdata_request(sentry_init, capture_events, app, get_client):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()])

    data = {"foo": "a" * 2000}

    @app.route("/", method="POST")
    def index():
        import bottle
        assert bottle.request.forms["foo"] == data["foo"]
        capture_message("hi")
        return "ok"

    events = capture_events()

    client = get_client()
    response = client.post("/", data=data)
    assert response[1] == '200 OK'

    event, = events
    assert event["_meta"]["request"]["data"]["foo"] == {
        "": {"len": 2000, "rem": [["!limit", "x", 509, 512]]}
    }
    assert len(event["request"]["data"]["foo"]) == 512


@pytest.mark.parametrize("input_char", [u"a", b"a"])
def test_flask_too_large_raw_request(sentry_init, input_char, capture_events, app, get_client):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()], request_bodies="small")

    data = input_char * 2000

    @app.route("/", method="POST")
    def index():
        import bottle
        if isinstance(data, bytes):
            assert bottle.request.body.read() == data
        else:
            assert bottle.request.body.read() == data.encode("ascii")
        assert not bottle.request.json
        capture_message("hi")
        return "ok"

    events = capture_events()

    client = get_client()
    response = client.post("/", data=data)
    assert response[1] == '200 OK'

    event, = events
    assert event["_meta"]["request"]["data"] == {
        "": {"len": 2000, "rem": [["!config", "x", 0, 2000]]}
    }
    assert not event["request"]["data"]


def test_bottle_files_and_form(sentry_init, capture_events, app, get_client):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()], request_bodies="always")

    data = {"foo": "a" * 2000, "file": (BytesIO(b"hello"), "hello.txt")}

    @app.route("/", method="POST")
    def index():
        import bottle
        assert list(bottle.request.forms) == ["foo"]
        assert list(bottle.request.files) == ["file"]
        assert not bottle.request.json
        capture_message("hi")
        return "ok"

    events = capture_events()

    client = get_client()
    response = client.post("/", data=data)
    assert response[1] == '200 OK'

    event, = events
    assert event["_meta"]["request"]["data"]["foo"] == {
        "": {"len": 2000, "rem": [["!limit", "x", 509, 512]]}
    }
    assert len(event["request"]["data"]["foo"]) == 512

    assert event["_meta"]["request"]["data"]["file"] == {
        "": {"len": 0, "rem": [["!raw", "x", 0, 0]]}
    }
    assert not event["request"]["data"]["file"]

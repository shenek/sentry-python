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
import sentry_sdk.integrations.bottle as bottle_sentry


def wsgistr(s):
    if py3k:
        return s.encode('utf8').decode('latin1')
    else:
        return s


# copied from bottle.py tests
def urlopen(wsgiapp, path, method='GET', post='', env=None, content_type=None):
    result = {'code': 0, 'status': 'error', 'header': {}, 'body': tob('')}

    def start_response(status, header, exc_info=None):
        result['code'] = int(status.split()[0])
        result['status'] = status.split(None, 1)[-1]
        for name, value in header:
            name = name.title()
            if name in result['header']:
                result['header'][name] += ', ' + value
            else:
                result['header'][name] = value
    env = env if env else {}
    wsgiref.util.setup_testing_defaults(env)
    env['REQUEST_METHOD'] = wsgistr(method.upper().strip())
    env['PATH_INFO'] = wsgistr(path)
    env['QUERY_STRING'] = wsgistr('')
    if content_type:
        env["CONTENT_TYPE"] = content_type
    if post:
        env['REQUEST_METHOD'] = 'POST'
        env['CONTENT_LENGTH'] = str(len(tob(post)))
        env['wsgi.input'].write(tob(post))
        env['wsgi.input'].seek(0)
    response = wsgiapp(env, start_response)
    for part in response:
        try:
            result['body'] += part
        except TypeError:
            raise TypeError('WSGI app yielded non-byte object %s', type(part))
    if hasattr(response, 'close'):
        response.close()
        del response
    return result


@pytest.fixture(scope="function")
def app(sentry_init):
    app = Bottle()

    @app.route("/capture")
    def capture_route():
        capture_message("captured")
        return "Captured"

    yield app


def test_has_context(sentry_init, app, capture_events):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()])
    events = capture_events()

    assert urlopen(wsgiref.validate.validator(app), "/capture")["code"] == 200

    event, = events
    assert event["message"] == "captured"
    assert "data" not in event["request"]
    assert event["request"]["url"] == "http://127.0.0.1/capture"


@pytest.mark.parametrize("debug", (True, False), ids=["debug", "nodebug"])
@pytest.mark.parametrize("catchall", (True, False), ids=["catchall", "nocatchall"])
def test_errors(sentry_init, capture_exceptions, capture_events, app, debug, catchall):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()])

    app.catchall = catchall
    set_debug(mode=debug)

    exceptions = capture_exceptions()
    events = capture_events()

    @app.route("/")
    def index():
        1 / 0

    try:
        urlopen(wsgiref.validate.validator(app), "/")
    except ZeroDivisionError:
        pass

    exc, = exceptions
    assert isinstance(exc, ZeroDivisionError)

    event, = events
    assert event["exception"]["values"][0]["mechanism"]["type"] == "bottle"


def test_bottle_large_json_request(sentry_init, capture_events, app):
    sentry_init(integrations=[bottle_sentry.BottleIntegration()], request_bodies="small")

    data = {"foo": {"bar": "a" * 2000}}

    @app.route("/", method="POST")
    def index():
        import bottle
        assert bottle.request.json == data
        assert bottle.request.body.read() == json.dumps(data).encode("ascii")
        capture_message("hi")
        return "ok"

    events = capture_events()

    response = urlopen(
        wsgiref.validate.validator(app),
        "/",
        method="POST",
        post=json.dumps(data),
        content_type="application/json",
    )
    #raise Exception(dir(response))
    assert response["code"] == 200

    event, = events
    __import__("pdb").set_trace()
    assert event["_meta"]["request"]["data"]["foo"]["bar"] == {
        "": {"len": 2000, "rem": [["!limit", "x", 509, 512]]}
    }
    assert len(event["request"]["data"]["foo"]["bar"]) == 512

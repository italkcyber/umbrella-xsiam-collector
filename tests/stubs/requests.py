"""Minimal requests stub: tests set `handler` to control responses."""


class Response:
    def __init__(self, status_code=200, text="", request_body=None, headers=None):
        self.status_code = status_code
        self.text = text
        self.request_body = request_body
        self.headers = headers or {}


class RequestException(Exception):
    pass


class _Exceptions:
    RequestException = RequestException


exceptions = _Exceptions()

CALLS = []
handler = None


def post(url, data=None, headers=None, verify=True, timeout=None):
    CALLS.append({"url": url, "data": data, "headers": headers,
                  "verify": verify, "timeout": timeout})
    if handler:
        return handler(url, data, headers)
    return Response(200)

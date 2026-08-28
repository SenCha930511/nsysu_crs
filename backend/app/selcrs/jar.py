"""Cookie jar <-> string codec for the Redis-only selcrs credential store.

The jar's TYPE is an adapter concern (httpx lives only in this package), so
the stable-string codec lives here too; app/auth/sessions.py stores and
retrieves the resulting opaque payload without ever naming httpx.
"""

import json

import httpx

#: The selcrs cookie-jar type, re-exported so business modules can annotate
#: without importing httpx themselves (the todo-3 guardrail allows httpx only
#: inside this package).
SelcrsJar = httpx.Cookies


def serialize_cookies(cookies: httpx.Cookies) -> str:
    """Jar -> JSON list of name/value pairs (deterministic order for diffing)."""
    pairs = sorted((cookie.name, cookie.value) for cookie in cookies.jar)
    return json.dumps(pairs)


def deserialize_cookies(payload: str) -> httpx.Cookies:
    """Inverse of ``serialize_cookies``; consumed by school reads (todo 9+)."""
    jar = httpx.Cookies()
    for name, value in json.loads(payload):
        jar.set(name, value)
    return jar

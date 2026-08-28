"""Regression: probe_stage must pass the session jar to the adapter (the
no-arg call used to TypeError live at 10:01 while mocks never noticed)."""

import httpx
import pytest
from fastapi import HTTPException

import app.api.write_probe as write_probe


@pytest.mark.anyio
async def test_probe_stage_passes_cookies_to_school_calls(monkeypatch):
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDTEST", "x", domain="selcrs.nsysu.edu.tw")
    seen: dict[str, httpx.Cookies] = {}

    async def fake_get_studfun(cookies: httpx.Cookies) -> str:
        seen["studfun"] = cookies
        return "<html><body>選課關閉</body></html>"

    monkeypatch.setattr(write_probe, "get_studfun", fake_get_studfun)
    probe = await write_probe.probe_stage(jar)
    assert seen["studfun"] is jar
    assert probe.detection.stage == "關閉"


@pytest.mark.anyio
async def test_probe_stage_passes_cookies_to_form_follow(monkeypatch):
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDTEST", "x", domain="selcrs.nsysu.edu.tw")
    seen: dict[str, httpx.Cookies] = {}

    async def fake_get_studfun(cookies: httpx.Cookies) -> str:
        seen["studfun"] = cookies
        return ('<html><a href="addcourse/ssform.asp?X1=1&X2=2">加退選</a></html>')

    async def fake_get_write_form(cookies: httpx.Cookies, url: str) -> str:
        seen["form"] = cookies
        return "<html><form></form></html>"

    monkeypatch.setattr(write_probe, "get_studfun", fake_get_studfun)
    monkeypatch.setattr(write_probe, "get_write_form", fake_get_write_form)
    probe = await write_probe.probe_stage(jar)
    assert seen["form"] is jar
    assert probe.form_url is not None and probe.form_url.endswith("ssform.asp?X1=1&X2=2")


@pytest.mark.anyio
async def test_preview_route_threads_jar_into_probe():
    source = (write_probe.__file__)
    text = __import__("pathlib").Path(source.replace("write_probe.py", "write.py")).read_text()
    assert "probe_stage(deserialize_cookies(jar_payload))" in text

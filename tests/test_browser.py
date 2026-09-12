"""Real browser regression test; uses only a disposable database."""

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="Set RUN_BROWSER_TESTS=1"),
]


@pytest.mark.parametrize("width", [1440, 390])
async def test_web_workflows(width):
    from playwright.async_api import async_playwright

    parts = urlsplit(os.environ["TEST_DATABASE_URL"])
    assert parts.path.endswith("_test"), "Browser tests require a disposable test database"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "APP_ENV": "test",
        "BOT_TOKEN": "123:test",
        "WEBAPP_DEV_USER_ID": "900001",
        "DATABASE_HOST": parts.hostname,
        "DATABASE_PORT": str(parts.port or 5432),
        "DATABASE_USER": parts.username,
        "DATABASE_PASSWORD": parts.password,
        "DATABASE_NAME": parts.path[1:],
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.webapp.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(base_url=base) as client:
            for _ in range(100):
                try:
                    if (await client.get("/ready")).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("Web server did not become ready")
            profile = (
                await client.post(
                    "/api/profiles", json={"name": f"Маша · 5Б · {width}", "color": "#275f50"}
                )
            ).json()
            assert (
                await client.patch("/api/me", json={"default_profile_id": profile["id"]})
            ).status_code == 200
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(base)
            assert (
                await page.locator('link[rel="stylesheet"]').get_attribute("href")
                == "/static/planner-v2.css?v=20260912.1"
            )
            assert (
                await page.evaluate("getComputedStyle(document.body).backgroundColor")
                == "rgb(243, 246, 251)"
            )
            stylesheet = await page.request.get(f"{base}/static/planner-v2.css?v=20260912.1")
            assert stylesheet.ok
            assert "text/css" in stylesheet.headers["content-type"]
            assert "immutable" in stylesheet.headers["cache-control"]
            legacy_stylesheet = await page.request.get(f"{base}/static/styles.css")
            assert legacy_stylesheet.ok
            assert "must-revalidate" in legacy_stylesheet.headers["cache-control"]
            assert "planner-v2.css?v=20260912.1" in await legacy_stylesheet.text()
            await page.get_by_role("button", name="Поделиться расписанием").click()
            await page.get_by_role("checkbox", name="Вс").uncheck()
            await page.get_by_role("button", name="Закрыть окно").click()
            await page.get_by_role("heading", name="Закрыть без сохранения изменений?").wait_for()
            await page.get_by_role("button", name="Закрыть", exact=True).click()
            await page.locator("dialog").wait_for(state="hidden")
            await page.get_by_role("button", name="+ Добавить занятие", exact=True).click()
            await page.locator("[name=label]").fill("Математика")
            await page.get_by_role("button", name="Сохранить", exact=True).click()
            await page.locator("dialog").wait_for(state="hidden")
            await page.get_by_role(
                "button", name="Математика, 08:30, редактировать", exact=True
            ).click()
            await page.locator("[name=label]").fill("Геометрия")
            await page.get_by_role("button", name="Сохранить", exact=True).click()
            await page.locator("dialog").wait_for(state="hidden")
            await page.get_by_role(
                "button", name="Геометрия, 08:30, редактировать", exact=True
            ).wait_for()
            await page.get_by_role("button", name="Задания", exact=False).first.click()
            await page.get_by_role("button", name="+ Добавить задание").click()
            await page.locator("[name=title]").fill("Решить задачи 1–5")
            await page.locator("[name=files]").set_input_files(
                {"name": "задание.txt", "mimeType": "text/plain", "buffer": "Материалы".encode()}
            )
            await page.get_by_role("button", name="Сохранить", exact=True).click()
            await page.locator("dialog").wait_for(state="hidden")
            await page.get_by_role("checkbox", name="Выполнено: Решить задачи 1–5").check()
            await page.get_by_role("button", name="Готово", exact=True).click()
            await page.get_by_text("Решить задачи 1–5", exact=True).wait_for()
            await page.get_by_role("button", name="Настройки", exact=False).first.click()
            await page.get_by_role("heading", name="Каждому — свой план").wait_for()
            await page.get_by_role("button", name="Расписание", exact=False).first.click()
            await page.get_by_role("button", name="Неделя", exact=True).click()
            await page.get_by_role("button", name="День", exact=True).click()
            assert await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
            assert not errors, errors
            await page.wait_for_timeout(7000)
            output = Path(os.getenv("BROWSER_SCREENSHOT_DIR", "test-results"))
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / f"planner-{width}.png"), full_page=True)
            await browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)

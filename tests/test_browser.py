"""Real browser regression test; uses only a disposable database."""

import asyncio
import base64
import os
import re
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
            await page.route(
                "https://telegram.org/js/telegram-web-app.js", lambda route: route.fulfill(body="")
            )
            await page.add_init_script("""
                window.Telegram = {WebApp: {
                    initData: '', ready() {}, expand() {}, onEvent() {},
                    BackButton: {
                        show() { this.visible = true; },
                        hide() { this.visible = false; },
                        onClick(callback) { this.callback = callback; }
                    }
                }};
            """)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(base)
            stylesheet_href = await page.locator('link[rel="stylesheet"]').get_attribute("href")
            assert re.fullmatch(r"/static/planner-v2\.css\?v=[0-9a-f]{16}", stylesheet_href)
            script_src = await page.locator('script[src^="/static/planner-v2.js"]').get_attribute(
                "src"
            )
            assert re.fullmatch(r"/static/planner-v2\.js\?v=[0-9a-f]{16}", script_src)
            assert (
                await page.evaluate("getComputedStyle(document.body).backgroundColor")
                == "rgb(243, 246, 251)"
            )
            stylesheet = await page.request.get(f"{base}{stylesheet_href}")
            assert stylesheet.ok
            assert "text/css" in stylesheet.headers["content-type"]
            assert "immutable" in stylesheet.headers["cache-control"]
            stale_stylesheet = await page.request.get(
                f"{base}/static/planner-v2.css?v=stale-version"
            )
            assert "immutable" not in stale_stylesheet.headers["cache-control"]
            assert "must-revalidate" in stale_stylesheet.headers["cache-control"]
            legacy_stylesheet = await page.request.get(f"{base}/static/styles.css")
            assert legacy_stylesheet.ok
            assert "must-revalidate" in legacy_stylesheet.headers["cache-control"]
            assert stylesheet_href in await legacy_stylesheet.text()
            legacy_javascript = await page.request.get(f"{base}/static/app.js")
            assert legacy_javascript.ok
            assert "must-revalidate" in legacy_javascript.headers["cache-control"]
            assert script_src in await legacy_javascript.text()
            await page.get_by_role("button", name="Поделиться расписанием").click()
            await page.get_by_role("checkbox", name="Вс").uncheck()
            await page.get_by_role("button", name="Закрыть окно").click()
            await page.get_by_role("heading", name="Закрыть без сохранения изменений?").wait_for()
            close_without_saving = page.get_by_role("button", name="Закрыть", exact=True)
            assert (
                await close_without_saving.evaluate("button => getComputedStyle(button).color")
                == "rgb(255, 255, 255)"
            )
            await close_without_saving.click()
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
                [
                    {
                        "name": "задание.txt",
                        "mimeType": "text/plain",
                        "buffer": "Материалы".encode(),
                    },
                    {
                        "name": "картинка.png",
                        "mimeType": "image/png",
                        "buffer": base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
                        ),
                    },
                ]
            )
            await page.get_by_role("button", name="Сохранить", exact=True).click()
            await page.locator("dialog").wait_for(state="hidden")
            await page.get_by_text("Решить задачи 1–5", exact=True).click()
            await page.locator("textarea[name=description]").fill("Несохранённая заметка")
            page_url = page.url
            for close_with in ("button", "escape", "telegram"):
                await page.get_by_role("button", name="картинка.png", exact=False).click()
                preview = page.get_by_role("dialog", name="картинка.png")
                await preview.wait_for(state="visible")
                await page.wait_for_function(
                    "document.querySelector('.attachment-preview img')?.naturalWidth > 0"
                )
                image_url = await preview.locator("img").get_attribute("src")
                assert page.url == page_url
                assert len(browser.contexts[0].pages) == 1
                if close_with == "button":
                    await preview.get_by_role("button", name="Назад к заданию").click()
                elif close_with == "escape":
                    await page.keyboard.press("Escape")
                else:
                    await page.evaluate("Telegram.WebApp.BackButton.callback()")
                await preview.wait_for(state="detached")
                assert await page.locator("#sheet").is_visible()
                assert (
                    await page.locator("textarea[name=description]").input_value()
                    == "Несохранённая заметка"
                )
                assert await page.evaluate("Telegram.WebApp.BackButton.visible")
                assert not await page.evaluate(
                    "url => fetch(url).then(() => true, () => false)", image_url
                )
            async with page.expect_download() as download_info:
                await page.get_by_role("button", name="задание.txt", exact=False).click()
            assert (await download_info.value).suggested_filename == "задание.txt"
            await page.get_by_role("button", name="Закрыть окно").click()
            await page.get_by_role("heading", name="Закрыть без сохранения изменений?").wait_for()
            await page.get_by_role("button", name="Остаться", exact=True).click()
            await page.get_by_role("button", name="Сохранить", exact=True).click()
            await page.locator("#sheet").wait_for(state="hidden")
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

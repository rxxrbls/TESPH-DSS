"""Manual browser smoke check: python tests/browser_week2.py (server on 8501)."""

from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


def main():
    output = Path(".runtime/browser-checks")
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8501", wait_until="domcontentloaded")
        page.get_by_text("PHP 25,366,956.00", exact=True).wait_for(timeout=120000)
        assert page.locator('[data-testid="stException"]').count() == 0
        assert page.locator('img').evaluate_all("imgs => imgs.every(i => i.complete && i.naturalWidth > 0)")
        page.screenshot(path=str(output / "desktop-sales.png"), full_page=True)
        page.get_by_role("tab", name="Trends", exact=True).click()
        chart = page.locator('[data-testid="stVegaLiteChart"]')
        chart.wait_for(state="visible", timeout=30000)
        chart.locator('canvas, svg.marks').first.wait_for(state="visible", timeout=30000)
        chart.screenshot(path=str(output / "chart.png"))
        assert len(Image.open(output / "chart.png").convert("RGB").getcolors(1000000)) > 10
        page.screenshot(path=str(output / "desktop-trends.png"), full_page=True)
        assert Image.open(output / "desktop-trends.png").convert("RGB").getextrema() != ((255, 255),) * 3
        page.get_by_text("Demand Forecast", exact=True).first.click()
        page.get_by_text("Selected Method:", exact=False).wait_for(timeout=120000)
        page.get_by_text("Adjusted MAPE", exact=True).wait_for(timeout=30000)
        page.get_by_text("Historical forecast only:", exact=False).wait_for(timeout=30000)
        assert page.locator('[data-testid="stException"]').count() == 0
        forecast_chart = page.locator('[data-testid="stVegaLiteChart"]')
        forecast_chart.screenshot(path=str(output / "forecast-chart.png"))
        assert len(Image.open(output / "forecast-chart.png").convert("RGB").getcolors(1000000)) > 10
        page.screenshot(path=str(output / "desktop-forecast.png"), full_page=True)
        page.get_by_text("Sales & Products", exact=True).first.click()
        page.get_by_text("PHP 25,366,956.00", exact=True).wait_for(timeout=30000)
        assert page.locator('[data-testid="stMetricValue"]').evaluate_all(
            "items => items.every(e => e.scrollWidth <= e.clientWidth)"
        )
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8501", wait_until="domcontentloaded")
        page.get_by_text("PHP 25,366,956.00", exact=True).wait_for(timeout=30000)
        page.screenshot(path=str(output / "mobile-sales.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_test_id("stExpandSidebarButton").click()
        page.get_by_text("Demand Forecast", exact=True).first.click()
        page.get_by_text("Selected Method:", exact=False).wait_for(timeout=120000)
        page.get_by_test_id("stSidebarCollapseButton").click()
        page.screenshot(path=str(output / "mobile-forecast.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator('[data-testid="stException"]').count() == 0
        assert not errors, errors
        browser.close()
    print("Browser checks passed; screenshots in", output)


if __name__ == "__main__":
    main()

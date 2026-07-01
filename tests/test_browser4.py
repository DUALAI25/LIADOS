"""Test E2E final v2 con Playwright - usa HTTPBasicCredentials del context."""
import asyncio

async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])

        # USAR http_credentials: el navegador reenvia automaticamente para el mismo origin
        context = await browser.new_context(
            http_credentials={'username': 'jefe', 'password': 'jefe2026'}
        )

        errors = []
        page = await context.new_page()
        page.on('console', lambda msg: errors.append(f'[{msg.type}] {msg.text[:200]}'))
        page.on('pageerror', lambda err: errors.append(f'[PAGE ERROR] {err.message[:200]}'))

        # Handler para prompts() JS (los que vienen del fix _getAuthHeaders)
        prompt_count = [0]
        async def handle_dialog(dialog):
            prompt_count[0] += 1
            print(f'  Dialog #{prompt_count[0]}: type={dialog.type} msg="{dialog.message[:80]}"')
            if prompt_count[0] == 1:
                await dialog.accept('jefe')
            else:
                await dialog.accept('jefe2026')
        page.on('dialog', lambda d: asyncio.create_task(handle_dialog(d)))

        print('=== Navegando ===')
        try:
            await page.goto('http://100.87.20.4:9121/', wait_until='networkidle', timeout=30000)
        except Exception as e:
            print(f'goto error: {e}')

        await page.wait_for_timeout(5000)

        print(f'\n=== Dialogs JS recibidos: {prompt_count[0]} ===')

        print(f'\n=== Console messages ({len(errors)}) ===')
        for e in errors[:30]:
            print(f'  {e}')

        print('\n=== Estado del DOM ===')
        try:
            hero = await page.locator('#heroValue').inner_text(timeout=3000)
            print(f'  Hero: "{hero}"')
        except Exception as e:
            print(f'  Hero: NO ENCONTRADO - {e}')

        try:
            kpis_text = await page.locator('#kpis').inner_text(timeout=3000)
            print(f'  #kpis (primeros 500): "{kpis_text[:500]}"')
        except Exception as e:
            print(f'  #kpis: NO ENCONTRADO - {e}')

        try:
            ingresos_text = await page.locator('#ingresos').inner_text(timeout=3000)
            print(f'  #ingresos (primeros 800): "{ingresos_text[:800]}"')
        except Exception as e:
            print(f'  #ingresos: NO ENCONTRADO - {e}')

        try:
            error_div = await page.locator('.state.error').inner_text(timeout=3000)
            print(f'  ERROR EN PANTALLA: "{error_div[:300]}"')
        except Exception:
            print('  Sin error visible (BIEN)')

        try:
            body = await page.locator('body').inner_text(timeout=2000)
            print(f'  Body (primeros 1500):')
            print(f'    {body[:1500]}')
        except Exception as e:
            print(f'  Body: {e}')

        await page.screenshot(path='/tmp/dashboard_v2.png', full_page=True)
        print('\nScreenshot: /tmp/dashboard_v2.png')

        await browser.close()

asyncio.run(main())
"""Test E2E completo del flujo demo - simula cliente real."""
import asyncio
import sys

async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(
            http_credentials={'username': 'jefe', 'password': 'jefe2026'}
        )

        errors = []
        page = await context.new_page()
        page.on('console', lambda msg: errors.append(f'[{msg.type}] {msg.text[:200]}'))
        page.on('pageerror', lambda err: errors.append(f'[PAGE ERROR] {err.message[:200]}'))

        # Handler: aceptar prompts JS
        prompt_count = [0]
        async def handle_dialog(dialog):
            prompt_count[0] += 1
            if prompt_count[0] == 1:
                await dialog.accept('jefe')
            else:
                await dialog.accept('jefe2026')
        page.on('dialog', lambda d: asyncio.create_task(handle_dialog(d)))

        print('=== PASO 1: cargar dashboard ===')
        await page.goto('http://100.87.20.4:9121/', wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(3000)

        # Verificar Hero
        try:
            hero = await page.locator('#heroValue').inner_text(timeout=3000)
            print(f'  Hero: {hero}')
        except Exception as e:
            print(f'  Hero ERROR: {e}')

        # Verificar KPIs
        kpis_count = await page.locator('#kpis .kpi').count()
        print(f'  KPI cards: {kpis_count}')

        # Verificar graficos canvas
        canvas_count = await page.locator('canvas').count()
        print(f'  Canvas graficos: {canvas_count}')

        # Verificar barras (proveedores/categorias)
        bar_count = await page.locator('.bar-row').count()
        print(f'  Bar rows: {bar_count}')

        print('\n=== PASO 2: abrir chat (C shortcut) ===')
        await page.keyboard.press('c')
        await page.wait_for_timeout(1000)
        chat_open = await page.locator('#chatPanel.open, #chatFab.active').count()
        print(f'  Chat abierto: {chat_open}')

        # Enviar mensaje
        if chat_open > 0:
            await page.locator('#chatText').fill('Cuanto llevo gastado este mes?')
            await page.locator('#chatSend').click()  # ajustar selector
            await page.wait_for_timeout(8000)
            try:
                last_msg = await page.locator('.msg.bot').last.inner_text(timeout=3000)
                print(f'  Ultimo msg bot: {last_msg[:200]}')
            except Exception as e:
                print(f'  No se encontro msg bot: {e}')

        print('\n=== PASO 3: cerrar chat y abrir search (/) ===')
        await page.keyboard.press('Escape')
        await page.wait_for_timeout(500)
        await page.keyboard.press('/')
        await page.wait_for_timeout(500)
        search_open = await page.locator('#searchModal.open').count()
        print(f'  Search modal abierto: {search_open}')

        if search_open > 0:
            await page.keyboard.type('ENVASES')
            await page.wait_for_timeout(2000)
            try:
                results_count = await page.locator('#searchResults .search-item').count()
                print(f'  Resultados busqueda: {results_count}')
            except:
                results_count = await page.locator('#searchResults > *').count()
                print(f'  Hijos de searchResults: {results_count}')

        print('\n=== PASO 4: cerrar modal y probar export CSV ===')
        await page.keyboard.press('Escape')
        await page.wait_for_timeout(500)

        # Buscar un enlace de export
        export_links = await page.locator('a[href*="/api/export/"]').count()
        print(f'  Enlaces de export CSV: {export_links}')

        print('\n=== PASO 5: atajos de teclado ===')
        for key, name in [('?', 'ayuda'), ('t', 'tema'), ('r', 'refresh')]:
            await page.keyboard.press(key)
            await page.wait_for_timeout(500)
            modals = await page.locator('.modal-overlay.open').count()
            print(f'  Apretar {key} ({name}): {modals} modal(es) abierto(s)')

        print('\n=== PASO 6: error final ===')
        if errors:
            print(f'  Errores ({len(errors)}):')
            for e in errors[:10]:
                print(f'    {e}')
        else:
            print('  Sin errores')

        await page.screenshot(path='/tmp/demo_final.png', full_page=True)
        print('\nScreenshot: /tmp/demo_final.png')

        await browser.close()

asyncio.run(main())
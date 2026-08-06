"""Test chat con espera mas larga para ver el reply completo."""
import asyncio
import os
import sys
if "pytest" in sys.modules and __name__ != "__main__":
    import pytest
    pytest.skip("script E2E: ejecutar directamente, no durante colección", allow_module_level=True)

async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(
            http_credentials={'username': 'jefe', 'password': 'jefe2026'},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        prompt_count = [0]
        async def handle_dialog(dialog):
            prompt_count[0] += 1
            if prompt_count[0] == 1:
                await dialog.accept('jefe')
            else:
                await dialog.accept('jefe2026')
        page.on('dialog', lambda d: asyncio.create_task(handle_dialog(d)))

        print('=== Cargar dashboard ===')
        base_url = os.getenv('LIADOS_TEST_URL', 'https://localhost:9121').rstrip('/')
        await page.goto(base_url + '/', wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(3000)

        print('=== Abrir chat ===')
        await page.keyboard.press('c')
        await page.wait_for_timeout(1000)

        print('=== Enviar pregunta y esperar reply completo ===')
        # Localizar el input correctamente
        try:
            await page.locator('textarea#chatText, input#chatText').fill('Cuanto llevo gastado este mes?')
        except:
            await page.keyboard.type('Cuanto llevo gastado este mes?')

        # Buscar boton enviar
        send_btn = page.locator('button#chatSend, button:has-text("Enviar"), button[onclick*="sendMsg"]').first
        await send_btn.click()
        print('  Mensaje enviado')

        # Esperar hasta que el ultimo msg del bot tenga mas de 100 chars (no solo tools)
        try:
            await page.wait_for_function(
                '''() => {
                    const msgs = document.querySelectorAll('.msg.bot');
                    if (msgs.length === 0) return false;
                    const last = msgs[msgs.length - 1];
                    const txt = last.textContent.trim();
                    return txt.length > 100;
                }''',
                timeout=30000
            )
            print('  Reply recibido!')
        except Exception as e:
            print(f'  Timeout esperando reply completo: {e}')

        # Tomar texto
        last_msg = await page.locator('.msg.bot').last.inner_text()
        print(f'\n=== ULTIMO MSG DEL BOT ({len(last_msg)} chars) ===')
        print(last_msg[:1000])

        await page.screenshot(path='/tmp/chat_reply.png', full_page=False)
        print('\nScreenshot: /tmp/chat_reply.png')

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
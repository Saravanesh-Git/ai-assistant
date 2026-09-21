"""Optional browser regression check. Install playwright and its Chromium browser first.

Run: .venv/bin/python scripts/verify_ui.py
Uses mocked desktop, microphone, Groq speech, and WebSocket adapters; never launches applications.
Screenshots are written to /tmp/amigo-desktop.png and /tmp/amigo-mobile.png.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).resolve().parents[1] / 'app/web/static'
FAKE_SPEECH = """
window.voiceSockets = [];
window.WebSocket = class {
  static OPEN = 1;
  constructor() { this.readyState = 1; window.voiceSockets.push(this); queueMicrotask(() => this.onopen?.()); }
  send(data) { this.lastAudio = data; }
  close() { this.readyState = 3; }
  emit(type, text='', utterance_id='') { this.onmessage?.({data:JSON.stringify({type, text, utterance_id, state:type, message:text})}); }
  disconnect() { this.readyState = 3; this.onclose?.(); }
};
Object.defineProperty(navigator, 'mediaDevices', {configurable:true, value:{
  getUserMedia: async () => ({getTracks:() => [{stop(){}}]})
}});
window.AudioContext = class {
  constructor() { this.sampleRate = 48000; this.destination = {}; }
  createMediaStreamSource() { return {connect(){}, disconnect(){}}; }
  createScriptProcessor() { return {connect(){}, disconnect(){}, onaudioprocess:null}; }
  createGain() { return {gain:{value:1}, connect(){}, disconnect(){}}; }
  close() {}
};
window.URL.createObjectURL = () => 'blob:test-audio';
window.URL.revokeObjectURL = () => {};
window.Audio = class {
  play() { queueMicrotask(() => this.onended?.()); return Promise.resolve(); }
  pause() {}
};
"""


async def main():
    calls, speech_calls, errors = [], [], []

    async def serve(route):
        path = urlsplit(route.request.url).path
        if path == '/api/config':
            return await route.fulfill(json={
                'token': 'test-session', 'tools': ['open_application', 'open_browser_search', 'create_directory'],
                'name': 'A.M.I.G.O.', 'wake_phrase': 'Hey Amigo', 'provider': 'rule_based',
                'confirm_actions': False, 'platform': 'Windows + WSL', 'windows_available': True,
                'voice_enabled': True, 'voice_available': True, 'voice_output_enabled': True,
                'voice_output_available': True,
                'allowed_paths': ['/home/user/Documents', '/mnt/c/Users/User/Downloads'],
            })
        if path == '/api/status':
            return await route.fulfill(json={
                'get_cpu_usage': {'cpu_percent': 12, 'cores': 8},
                'get_memory_usage': {'percent': 42, 'used': '6.7 GB', 'total': '16.0 GB'},
                'get_disk_usage': {'percent': 28, 'free': '360.2 GB'},
            })
        if path == '/api/command':
            data = route.request.post_data_json
            calls.append({key: value for key, value in data.items() if key != 'password'})
            await asyncio.sleep(.15)
            admin = {'kind': 'administrator', 'tool': 'create_directory', 'arguments': {'path': '/root/amigo-test'}}
            if data.get('message') == 'create folder /root/amigo-test':
                return await route.fulfill(json={**admin, 'approval': 'admin-proposal', 'description': 'Permission denied: /root'})
            if data.get('approval') == 'admin-proposal':
                return await route.fulfill(json={**admin, 'approval': 'admin-auth', 'description': 'Enter your Linux sudo password.', 'authentication_required': True})
            if data.get('approval') == 'admin-auth':
                assert data.get('password') == 'mock-password-only'
                return await route.fulfill(json={'reply': 'Created: /root/amigo-test'})
            return await route.fulfill(json={'reply': 'Completed: ' + data.get('message', '')})
        if path == '/api/speech':
            speech_calls.append(route.request.post_data_json['text'])
            return await route.fulfill(body=b'RIFF-test-audio', content_type='audio/wav')
        filename = 'index.html' if path == '/' else path.removeprefix('/static/')
        target = STATIC / filename
        if target.is_file() and target.resolve().is_relative_to(STATIC):
            content_type = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml'}[target.suffix]
            return await route.fulfill(body=target.read_bytes(), content_type=content_type, headers={
                'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            })
        await route.fulfill(status=404)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
        await context.add_init_script(FAKE_SPEECH)
        await context.route('http://localhost:8765/**', serve)
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto('http://localhost:8765/')
        await expect(page.locator("#cpu-value")).to_have_text("12%")
        await page.screenshot(path='/tmp/amigo-desktop.png', full_page=True)
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.screenshot(path='/tmp/amigo-mobile.png', full_page=True)
        await page.set_viewport_size({'width': 1440, 'height': 900})
        assert await page.title() == 'A.M.I.G.O. — Your personal command center'
        await page.locator('#help').click()
        assert await page.locator('#guide').is_visible()
        await page.keyboard.press('Escape')
        assert not await page.locator('#guide').is_visible()
        await page.locator('#mic').click()
        await page.wait_for_function('voiceSockets.length === 1')
        await page.evaluate("voiceSockets[0].emit('final', 'ambient speech', 'u0')")
        assert not calls
        await page.locator('#command').fill('my unfinished draft')
        await page.evaluate("voiceSockets[0].emit('interim', 'Hey Amigo show cpu')")
        assert await page.locator('#command').input_value() == 'my unfinished draft'
        assert not calls
        await page.evaluate("voiceSockets[0].emit('final', 'Hey Amigo', 'u1')")
        assert await page.locator('#reactor').get_attribute('data-state') == 'awake'
        await page.evaluate("voiceSockets[0].emit('final', 'show cpu', 'u2'); voiceSockets[0].emit('final', 'check ram', 'u3'); voiceSockets[0].emit('final', 'run date', 'u4')")
        await expect(page.locator("#activity")).to_have_text("READY")
        assert [call['message'] for call in calls] == ['show cpu', 'check ram', 'run date']
        assert len(speech_calls) == 3
        assert await page.locator('#command').input_value() == 'my unfinished draft'
        # A repeated final event must never execute an action twice.
        await page.evaluate("voiceSockets[0].emit('final', 'run date', 'u4')")
        assert len(calls) == 3
        await page.locator('#command').fill('run whoami')
        await page.locator('#command').press('Enter')
        await expect(page.locator("#activity")).to_have_text("READY")
        assert await page.locator('#reactor').get_attribute('data-state') == 'awake'
        assert len(speech_calls) == 3
        await page.evaluate("voiceSockets[0].disconnect()")
        await page.wait_for_timeout(1100)
        assert await page.evaluate('voiceSockets.length') == 2
        await page.evaluate("voiceSockets[1].emit('final', 'search for aurora in the web', 'u5')")
        await expect(page.locator("#activity")).to_have_text("READY")
        assert calls[-1]['message'] == 'search for aurora in the web'
        await page.evaluate("voiceSockets[1].emit('final', 'pause listening', 'u6'); voiceSockets[1].emit('final', 'open calculator', 'u7')")
        assert len(calls) == 5
        assert await page.locator('#pause').is_hidden()
        await page.evaluate("voiceSockets[1].emit('final', 'Hey Amigo, open calculator', 'u8')")
        await expect(page.locator("#activity")).to_have_text("READY")
        assert calls[-1]['message'] == 'open calculator'
        await page.evaluate("voiceSockets[1].emit('final', 'stop listening', 'u9')")
        assert await page.locator('#mic').get_attribute('aria-pressed') == 'false'
        await page.locator('#mic').click()
        await page.evaluate("voice.stop(); navigator.mediaDevices.getUserMedia = async () => {const error = new Error(); error.name='NotAllowedError'; throw error}; voice.start()")
        await page.wait_for_timeout(50)
        assert 'permission is blocked' in await page.locator('#voice-status').inner_text()
        assert await page.locator('#mic').get_attribute('aria-pressed') == 'false'
        await page.locator('#command').fill('<img src=x onerror=alert(1)>')
        await page.locator('#command').press('Enter')
        await expect(page.locator("#activity")).to_have_text("READY")
        assert await page.locator('#messages img').count() == 0
        await page.locator('#command').fill('create folder /root/amigo-test')
        await page.locator('#command').press('Enter')
        await page.get_by_role('button', name='Approve sudo action').click()
        password = page.get_by_label('Linux sudo password')
        await expect(password).to_be_visible()
        await password.fill('mock-password-only')
        await page.get_by_role('button', name='Authenticate & run').click()
        await expect(page.locator('#messages')).to_contain_text('Created: /root/amigo-test')
        assert await password.input_value() == ''
        assert 'mock-password-only' not in await page.locator('#messages').inner_text()
        await page.locator('#clear').click()
        for width in (320, 390, 768, 1024, 1440):
            await page.set_viewport_size({'width': width, 'height': 900})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
        assert not errors, errors
        unsupported = await browser.new_context()
        await unsupported.add_init_script("Object.defineProperty(navigator, 'mediaDevices', {configurable:true, value:undefined}); window.AudioContext = undefined;")
        await unsupported.route('http://localhost:8765/**', serve)
        fallback = await unsupported.new_page()
        await fallback.goto('http://localhost:8765/')
        assert await fallback.locator('#mic').is_disabled()
        await fallback.locator('#command').fill('show cpu')
        await fallback.locator('#command').press('Enter')
        await expect(fallback.locator("#messages")).to_contain_text("Completed: show cpu")
        await browser.close()
    print(json.dumps({'browser_checks': 'passed', 'command_requests': len(calls), 'viewports': [320, 390, 768, 1024, 1440], 'javascript_errors': errors}))


if __name__ == '__main__':
    asyncio.run(main())

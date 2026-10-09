"""Read-only Japan Embassy Tashkent short-stay slot watcher.

Setup: python monitor.py setup
Inspect: python monitor.py inspect
Watch: python monitor.py watch
No form submissions, bookings, CAPTCHA solving or credential entry are automated.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / '.private'
PROFILE = PRIVATE / 'browser_profile'
URL_FILE = PRIVATE / 'calendar_url.txt'
STATE_FILE = PRIVATE / 'state.json'
AUTH_STATE_FILE = PRIVATE / 'auth_state.json'
PAUSE_FILE = PRIVATE / 'cloud_paused.json'
HEALTH_FILE = PRIVATE / 'cloud_health.json'
ORIGIN = 'https://uzembassyryouji.rsvsys.jp'
DEFAULT_URL = ORIGIN + '/reservations/calendar'
TZ_UZB = ZoneInfo('Asia/Tashkent')
TZ_JAPAN = ZoneInfo('Asia/Tokyo')
MIN_INTERVAL_SECONDS = 600  # Respect the requested 10-minute schedule; no rapid polling.

# DOM selection is intentionally conservative. Slots are not identified until
# the user has calibrated a calendar scope, a readiness marker and open-slot CSS.
EXTRACT_JS = r"""({scopeSelector, slotSelector}) => {
  const scope = document.querySelector(scopeSelector);
  if (!scope) return {scopeFound:false, items:[]};
  const nodes = [...scope.querySelectorAll(slotSelector)];
  const textOf = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => !!el.getClientRects().length;
  const items = nodes.filter(el => {
    if (!visible(el) || el.matches(':disabled,[disabled],[aria-disabled="true"]')) return false;
    if (el.closest('[aria-disabled="true"], [hidden]')) return false;
    if (/disabled|unavailable|fully-booked|sold-out|closed/i.test(el.className?.toString() || '')) return false;
    // A candidate must be an actionable calendar control, not a status legend.
    return el.matches('a[href], button, [role="button"], [role="link"], [onclick]');
  }).map(el => {
    let carrier = el.closest('[data-date], [datetime], td, .fc-daygrid-day, .fc-event') || el.parentElement;
    return {
      label: [textOf(el), el.getAttribute('aria-label') || '', el.getAttribute('title') || '']
        .filter(Boolean).join(' | ').slice(0, 180),
      date: [el.dataset.date || '', el.getAttribute('datetime') || '',
             carrier?.getAttribute('data-date') || '', carrier?.getAttribute('datetime') || '',
             carrier?.getAttribute('aria-label') || ''].filter(Boolean).join(' | ').slice(0,120),
      context: textOf(carrier || el).slice(0, 220),
    };
  });
  return {scopeFound:true, items};
}"""

INSPECT_JS = r"""() => {
  const elems = [...document.querySelectorAll('a,button,[role="button"],[role="link"],[onclick], [data-date]')];
  const visible = el => !!el.getClientRects().length;
  const output = [];
  for (const el of elems) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const text = (el.textContent || '').replace(/\s+/g,' ').trim().slice(0, 90);
    const attr = (name) => (el.getAttribute(name) || '').slice(0, 120);
    const s = [tag, attr('id') ? '#'+attr('id') : '',
       attr('class') ? '.'+attr('class').trim().replace(/\s+/g,'.') : ''].join('');
    const hint = [text, attr('aria-label'), attr('title'), attr('data-date')].filter(Boolean).join(' | ').slice(0,140);
    if (!hint || /password|log\s?out|выход/i.test(hint)) continue;
    output.push({selectorHint:s.slice(0,110), label:hint});
    if (output.length >= 65) break;
  }
  return output;
}"""


class ActionRequired(Exception):
    """Need the operator to log in, solve CAPTCHA, or fix selector configuration."""


@dataclass(frozen=True)
class Config:
    chat_id: str
    bot_token: str
    scope: str
    ready: str
    slot: str
    category: str
    interval: int


def load_config() -> Config:
    load_dotenv(ROOT / '.env')
    interval = max(MIN_INTERVAL_SECONDS, int(os.getenv('INTERVAL_SECONDS', '600')))
    return Config(
        chat_id=os.getenv('TELEGRAM_CHAT_ID', '').strip(),
        bot_token=os.getenv('TELEGRAM_BOT_TOKEN', '').strip(),
        scope=os.getenv('SLOT_SCOPE_SELECTOR', '').strip(),
        ready=os.getenv('CALENDAR_READY_SELECTOR', '').strip(),
        slot=os.getenv('OPEN_SLOT_SELECTOR', '').strip(),
        category=os.getenv('SELECTED_CATEGORY_SELECTOR', '').strip(),
        interval=interval,
    )


def secure_private() -> None:
    PRIVATE.mkdir(exist_ok=True)
    if os.name != 'nt':
        PRIVATE.chmod(0o700)


def safe_site_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'uzembassyryouji.rsvsys.jp':
        raise ValueError('Only the official HTTPS embassy reservation domain is permitted.')
    if not parsed.path.startswith('/reservations/'):
        raise ValueError('Choose the specific short-stay reservation calendar URL, not the login page.')
    return url


def get_calendar_url() -> str:
    custom = os.getenv('CALENDAR_URL', '').strip()
    if custom:
        return safe_site_url(custom)
    if URL_FILE.exists():
        return safe_site_url(URL_FILE.read_text('utf-8').strip())
    return DEFAULT_URL


def write_json(path: Path, data: dict) -> None:
    secure_private()
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    if os.name != 'nt':
        tmp.chmod(0o600)
    tmp.replace(path)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def telegram_request(token: str, endpoint: str, payload: dict) -> dict:
    if not token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is missing in .env.')
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    connection = http.client.HTTPSConnection('api.telegram.org', timeout=15)
    try:
        connection.request('POST', f'/bot{token}/{endpoint}', body=data,
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        result = response.read()
        if response.status >= 400:
            # Never show bot token, request URL, or raw Telegram response.
            raise RuntimeError(f'Telegram HTTP {response.status}; verify bot token / chat id.')
        parsed = json.loads(result)
        if not parsed.get('ok'):
            raise RuntimeError('Telegram API rejected the request; check configuration.')
        return parsed
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError('Telegram network or response error.') from None
    finally:
        connection.close()


def notify(config: Config, message: str) -> None:
    if not config.bot_token or not config.chat_id:
        raise RuntimeError('Telegram not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.')
    telegram_request(config.bot_token, 'sendMessage', {
        'chat_id': config.chat_id,
        'text': message[:4096],
        'disable_web_page_preview': True,
    })


def local_times() -> str:
    return ('Тошкент: ' + datetime.now(TZ_UZB).strftime('%Y-%m-%d %H:%M') +
            ' | Япония: ' + datetime.now(TZ_JAPAN).strftime('%Y-%m-%d %H:%M'))


def normalize(text: str) -> str:
    return ' '.join(text.split())[:250]


def identity(item: dict) -> str:
    """Fingerprint text/date without needing private booking links."""
    parts = [normalize(str(item.get(k, ''))) for k in ('date', 'label', 'context')]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


def is_login_or_captcha(page) -> str | None:
    path = urlparse(page.url).path
    if '/auth/login' in path or '/auth/signin' in path:
        return 'Сессия тугаган: сайтга қўлда қайта логин қилинг.'
    if page.locator('input[type="password"]:visible').count():
        return 'Логин ойнаси очилган: қўлда қайта логин қилинг.'
    captcha = page.locator('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], '
                           '[class*="h-captcha"], [class*="g-recaptcha"], '
                           'input[name*="captcha" i]')
    if captcha.locator(':visible').count():
        return 'CAPTCHA аниқланди: уни қўлда бажариш керак; автоматик айланиб ўтилмайди.'
    return None


def require_calibration(config: Config) -> None:
    if not config.scope or not config.ready or not config.slot:
        raise ActionRequired('Календар мослаштирилмаган: .env ичида SLOT_SCOPE_SELECTOR, '
                             'CALENDAR_READY_SELECTOR ва OPEN_SLOT_SELECTOR ни тўлдиринг. '
                             'Аввал python monitor.py inspect ни ишлатинг.')
    if not config.category:
        raise ActionRequired('SELECTED_CATEGORY_SELECTOR ни ҳам белгиланг: фақат '
                             'Short stay (Applicant) танланганини тасдиқлаш керак.')


def scrape(page, config: Config) -> list[dict]:
    require_calibration(config)
    resp = page.goto(get_calendar_url(), wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(1700)
    if resp and resp.status >= 400:
        raise ActionRequired(f'Сайт HTTP {resp.status} қайтарди; автоматик текшириш тўхтатилди.')
    problem = is_login_or_captcha(page)
    if problem:
        raise ActionRequired(problem)
    if not page.locator(config.scope).count():
        raise ActionRequired('Календар доираси (SLOT_SCOPE_SELECTOR) топилмади.')
    if not page.locator(config.ready).count() or not page.locator(config.ready).first.is_visible():
        raise ActionRequired('Календар тўлиқ юкланмаган ёки CALENDAR_READY_SELECTOR ўзгарган.')
    if not page.locator(config.category).count() or not page.locator(config.category).first.is_visible():
        raise ActionRequired('Short Stay танлангани тасдиқланмади: SELECTED_CATEGORY_SELECTOR топилмади.')
    extracted = page.evaluate(EXTRACT_JS, {'scopeSelector': config.scope, 'slotSelector': config.slot})
    if not extracted['scopeFound']:
        raise ActionRequired('Календар scope элементи топилмади.')
    deduped: dict[str, dict] = {}
    for item in extracted['items']:
        if not (item['label'] or item['date'] or item['context']):
            continue
        deduped[identity(item)] = item
    return list(deduped.values())


def record_and_alert(config: Config, items: list[dict]) -> int:
    state = read_json(STATE_FILE)
    prev = set(state.get('slot_ids', []))
    current = {identity(item) for item in items}
    fresh = [x for x in items if identity(x) not in prev]
    if fresh:
        lines = [f'🟢 Янги Short Stay слот(лар): {len(fresh)}', local_times(), '']
        for x in fresh[:12]:
            lines.append('• ' + (x['date'] or x['context'] or x['label'])[:180])
        if len(fresh) > 12:
            lines.append(f'… яна {len(fresh)-12} та; сайтни очиб текширинг.')
        lines += ['', DEFAULT_URL, 'Брон автоматик амалга оширилмайди; сайтда тасдиқланг.']
        notify(config, '\n'.join(lines))  # Only mark as seen once Telegram succeeds.
    write_json(STATE_FILE, {'slot_ids': sorted(current), 'checked_at': local_times()})
    return len(fresh)


def start_context(playwright, *, headed: bool, portable: bool = False):
    secure_private()
    if portable:
        if not AUTH_STATE_FILE.is_file():
            raise ActionRequired('Cloud сессияси йўқ: аввал компьютерда export-session қилиб, '
                                 '.private/auth_state.json файлини VPSга хавфсиз ўтказинг.')
        # Portable storage state includes cookies, local storage and IndexedDB.
        # It is a secret equivalent to login and must never be logged or shared.
        browser = playwright.chromium.launch(headless=True)
        return browser.new_context(
            storage_state=str(AUTH_STATE_FILE), viewport={'width': 1280, 'height': 900},
            locale='en-US', timezone_id='Asia/Tashkent', accept_downloads=False)
    PROFILE.mkdir(exist_ok=True)
    if os.name != 'nt':
        PROFILE.chmod(0o700)
    return playwright.chromium.launch_persistent_context(
        str(PROFILE), headless=not headed,
        viewport={'width': 1280, 'height': 900}, locale='en-US',
        timezone_id='Asia/Tashkent',
        accept_downloads=False,
    )


def cmd_setup() -> None:
    print('Chrome ойнаси очилади. Элчихона сайтида қўлда логин қилинг,')
    print('VISA Application for short stay (Applicant) тоифасини танланг,')
    print('керакли брон календарини очинг. CAPTCHA бўлса қўлда бажаринг.')
    print('Бу ерда парол ёки код киритманг; фақат браузер ойнасидан фойдаланинг.')
    with sync_playwright() as playwright:
        context = start_context(playwright, headed=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(DEFAULT_URL, wait_until='domcontentloaded', timeout=30000)
            input('Short Stay календари ОЧИЛГАНДАН КЕЙИН Enter босинг ... ')
            problem = is_login_or_captcha(page)
            if problem:
                raise ActionRequired(problem)
            selected = safe_site_url(page.url)
            secure_private()
            URL_FILE.write_text(selected, encoding='utf-8')
            if os.name != 'nt':
                URL_FILE.chmod(0o600)
            print('Сессия локал браузер профилида сақланди; календар URL сақланди.')
            print('Кейинги қадам: python monitor.py inspect')
        finally:
            context.close()


def cmd_inspect() -> None:
    print('Фақат календаридаги кўринадиган элементларни кўрсатади, паролни чиқармайди.')
    with sync_playwright() as playwright:
        context = start_context(playwright, headed=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(get_calendar_url(), wait_until='domcontentloaded', timeout=30000)
            input('Қўлда Short Stay (Applicant) календарини танлаб, Enter босинг ... ')
            if is_login_or_captcha(page):
                print('Логин/CAPTCHA талаб қилиняпти; аввал қўлда амалга оширинг.')
                return
            print('URL:', safe_site_url(page.url))
            print('--- Кўринадиган интерактив элементлар: CSS_HINT | LABEL ---')
            for index, el in enumerate(page.evaluate(INSPECT_JS), 1):
                print(f'{index:02d}. {el["selectorHint"]} | {el["label"]}')
            print('Календардаги қисмлар учун CSS селекторларни .env га ёзинг.')
            print('Эслатма: бу тахминий рўйхат; жой бўшлигини исботламайди.')
        finally:
            context.close()


def check_once(config: Config, *, cloud: bool = False) -> None:
    with sync_playwright() as playwright:
        context = start_context(playwright, headed=False, portable=cloud)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            slots = scrape(page, config)
            if cloud:
                # Keep refreshed auth cookies, but only after successful authorized access.
                secure_private()
                tmp = AUTH_STATE_FILE.with_suffix('.json.tmp')
                try:
                    context.storage_state(path=str(tmp), indexed_db=True)
                    if os.name != 'nt':
                        tmp.chmod(0o600)
                    tmp.replace(AUTH_STATE_FILE)
                finally:
                    if tmp.exists():
                        tmp.unlink()
        finally:
            context.close()
    new = record_and_alert(config, slots)
    print(f'{local_times()} | CSS бўйича очиқ слот: {len(slots)} | янги: {new}')
    if not slots:
        print('Мос келувчи слот йўқ; бу сайтда умуман слот йўқлигини кафолатламайди.')


def cmd_watch(config: Config) -> None:
    print(f'Кузатиш бошланди: ҳар {config.interval // 60} дақиқада. Тўхтатиш: Ctrl+C')
    require_calibration(config)
    errors = 0
    while True:
        try:
            check_once(config)
            errors = 0
        except ActionRequired as exc:
            notify(config, '⚠️ Visa monitor тўхтади. ' + str(exc) + '\n' + local_times())
            print('Кузатиш тўхтади:', str(exc))
            return
        except Exception as exc:
            errors += 1
            print('Текшириш хатоси:', type(exc).__name__, '| уриниш:', errors)
            if errors == 1:
                try:
                    notify(config, '⚠️ Visa monitor сайтни текшира олмади. '\
                           'Тармоқ/сайт/созламани текширинг. ' + local_times())
                except Exception:
                    print('Telegram хабарномасини ҳам юбориб бўлмади.')
            if errors >= 3:
                print('Уч марта кетма-кет хатолик: кузатиш тўхтатилди.')
                return
        time.sleep(config.interval)



def cmd_export_session() -> None:
    """Export manually authorized local browser session for a single private VPS."""
    print('Қўлда очилган, авторизацияланган Short Stay календарини экспорт қилиш.')
    print('Файлда сессия токенлари бўлади: уни фақат ўз серверингизга SFTP билан ўтказинг.')
    with sync_playwright() as playwright:
        context = start_context(playwright, headed=True, portable=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(get_calendar_url(), wait_until='domcontentloaded', timeout=30000)
            input('Календар очилганидан кейин Enter босинг (CAPTCHA фақат қўлда) ... ')
            problem = is_login_or_captcha(page)
            if problem:
                raise ActionRequired(problem)
            selected = safe_site_url(page.url)
            secure_private()
            temp = AUTH_STATE_FILE.with_suffix('.json.tmp')
            try:
                context.storage_state(path=str(temp), indexed_db=True)
                if os.name != 'nt':
                    temp.chmod(0o600)
                temp.replace(AUTH_STATE_FILE)
            finally:
                if temp.exists():
                    temp.unlink()
            URL_FILE.write_text(selected, encoding='utf-8')
            if os.name != 'nt':
                URL_FILE.chmod(0o600)
            print('Экспорт қилинди: .private/auth_state.json ва .private/calendar_url.txt')
            print('Парол, токен ва cookie маълумотларини чатга ёки GitHubга юборманг.')
        finally:
            context.close()


def cmd_preflight(config: Config) -> None:
    require_calibration(config)
    if not config.bot_token or not config.chat_id:
        raise ActionRequired('Telegram токен ва chat ID .env да белгиланмаган.')
    if not AUTH_STATE_FILE.is_file():
        raise ActionRequired('Cloud сессия файли йўқ: .private/auth_state.json.')
    if AUTH_STATE_FILE.stat().st_size < 20:
        raise ActionRequired('Cloud сессия файли бўш ёки яроқсиз.')
    # Verify structure without printing secrets.
    saved = read_json(AUTH_STATE_FILE)
    if 'cookies' not in saved or 'origins' not in saved:
        raise ActionRequired('Cloud сессия файли Playwright storage_state форматида эмас.')
    get_calendar_url()
    print('Конфигурация текширилди (сайт билан уланиш ҳали синовдан ўтмаган).')


def cmd_cloud_once(config: Config) -> None:
    """One short, serialized VPS check. Run from systemd timer every 10 minutes."""
    if PAUSE_FILE.exists():
        print('Кузатиш хавфсизлик ёки авторизация сабаб тўхтатилган. '
              'Сабабни .private/cloud_paused.json да кўринг. Тузатгач resume қилинг.')
        return
    try:
        cmd_preflight(config)
        check_once(config, cloud=True)
    except ActionRequired as exc:
        reason = str(exc)
        write_json(PAUSE_FILE, {'reason': reason, 'paused_at': local_times()})
        print('PAUSED:', reason)
        try:
            notify(config, '⛔️ Visa Slot Monitor текширишни тўхтатди.\n'
                   + reason + '\n' + local_times()
                   + '\nСабабни бартараф этгандан кейин серверда resume қилинг.')
        except Exception:
            print('Тўхтатиш ҳақида Telegram хабар юбориб бўлмади. Сервер логларини кўринг.')
        return
    except Exception as exc:
        previous = read_json(HEALTH_FILE)
        now = time.time()
        next_alert_after = float(previous.get('last_alert_epoch', 0)) + 6*3600
        should_alert = previous.get('status') != 'error' or now >= next_alert_after
        last_sent = float(previous.get('last_alert_epoch', 0))
        if should_alert:
            try:
                notify(config, '⚠️ Visa Slot Monitor текшириш хатоси: '
                       + type(exc).__name__ + '.\n' + local_times()
                       + '\n10 дақиқадан кейин қайта уриниб кўради.')
                last_sent = now
            except Exception:
                print('Telegram огоҳлантиришини юбориб бўлмади.')
        write_json(HEALTH_FILE, {'status': 'error', 'last_alert_epoch': last_sent,
                                 'last_error_type': type(exc).__name__})
        print('ERROR:', type(exc).__name__, '(keyingi timerда қайта уринади)')
        return
    old = read_json(HEALTH_FILE)
    if old.get('status') == 'error':
        try:
            notify(config, '✅ Visa Slot Monitor яна ишлаяпти. ' + local_times())
        except Exception:
            print('Тикланиш хабарини юбориб бўлмади.')
    write_json(HEALTH_FILE, {'status': 'ok', 'last_success': local_times()})


def cmd_resume() -> None:
    if PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
    print('Пауза бекор қилинди. Кейинги текширувда қайта баҳоланади; '
          'CAPTCHA ёки блокировка автоматик айланиб ўтилмайди.')


def cmd_chat_id(config: Config) -> None:
    result = telegram_request(config.bot_token, 'getUpdates', {'limit': 20, 'timeout': 0})
    found = sorted({str((item.get('message') or {}).get('chat', {}).get('id'))
                    for item in result.get('result', [])
                    if (item.get('message') or {}).get('chat', {}).get('type') == 'private'
                    and str((item.get('message') or {}).get('text', '')).startswith('/start')})
    print('Telegram private chat IDs from /start:', ', '.join(found) or '(topilmadi)')
    if not found:
        print('Аввал Telegramда ўз ботингизга /start хабарини юборинг.')


def main() -> int:
    parser = argparse.ArgumentParser(description='Japan Embassy Short Stay read-only slot watcher')
    parser.add_argument('command', choices=['setup', 'inspect', 'once', 'watch', 'chat-id', 'telegram-test',
                                            'export-session', 'cloud-once', 'preflight', 'resume'])
    args = parser.parse_args()
    config = load_config()
    try:
        if args.command == 'setup':
            cmd_setup()
        elif args.command == 'inspect':
            cmd_inspect()
        elif args.command == 'once':
            check_once(config)
        elif args.command == 'watch':
            cmd_watch(config)
        elif args.command == 'export-session':
            cmd_export_session()
        elif args.command == 'cloud-once':
            cmd_cloud_once(config)
        elif args.command == 'preflight':
            cmd_preflight(config)
        elif args.command == 'resume':
            cmd_resume()
        elif args.command == 'chat-id':
            cmd_chat_id(config)
        elif args.command == 'telegram-test':
            notify(config, '✅ Visa Slot Monitor Telegram тест хабарномаси. ' + local_times())
            print('Telegram тест хабарномаси юборилди.')
        return 0
    except (ActionRequired, ValueError, RuntimeError, PlaywrightTimeoutError) as exc:
        print('Хатолик:', str(exc))
        return 1
    except KeyboardInterrupt:
        print('\nҚўлда тўхтатилди.')
        return 130


if __name__ == '__main__':
    sys.exit(main())

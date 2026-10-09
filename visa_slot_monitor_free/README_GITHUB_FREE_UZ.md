# Бепул вариант: GitHub Actions + Telegram (Windows + Codex)

## Муҳим фактлар

- **Сервер ёки карта талаб қилинмайди.** GitHub Free'да **Public** репозиторий билан стандарт GitHub Actions иш вақти бепул. Private репозиторийда 2000 дақиқа/ой лимит бор ва ҳар 10 дақиқалик job ундан ошади.
- **24/7 ишлашга уринади, аммо қатъий реал вақт кафолати ЙЎҚ**: scheduled job кечикиши ёки ўтказиб юборилиши мумкин. Слотлар тез тугаса, хабар кеч қолиши мумкин.
- **Код очиқ**, аммо парол, Telegram токени ва сессия cookie'лари ҳеч қачон репозиторийга қўшилмасин. GitHub **Secrets** (Settings -> Secrets and variables -> Actions) дан фойдаланинг.
- **Тўлиқ тайёр эмас**: Short Stay календарига киргач, CSS селекторларни қўлда мослаштириб тестдан ўтказиш керак. CAPTCHA айланиб ўтилмайди. Сайт автоматик текширишга рухсат беришини текширинг; рухсат бўлмаса ишлатманг.
- Очиқ репозиторийда schedule 60 кун давомида фаоллик бўлмаса ўчирилиши мумкин. Дастур ҳафталик махфий бўлмаган heartbeat файлини янгилайди, аммо schedule ишлашини Actions ойнасида вақти-вақти билан текширинг.
- **Автоматик брон қилмайди.** Фақат календардан маълумот олади.

## 1. Локал ишга тушириш (фақат бир марта)

1. Python 3.11+ ни ўрнатинг ва ушбу папкада Windows терминал очинг.
2. `install_windows.bat` ни ишга туширинг.
3. `.env.example` ни `.env` деб нусхаланг, Telegram BotFather токени ва chat ID ни киритинг. Telegramда ботга `/start` юборинг; `python monitor.py chat-id` орқали chat ID ни билиш мумкин.
4. `python monitor.py setup`, кейин `python monitor.py inspect` орқали сайтимизда ўзингиз логин қилинг. CAPTCHA бўлса фақат қўлда ҳал қилинг. Short Stay (Applicant) календари танланганини тасдиқланг.
5. `.env` да `SLOT_SCOPE_SELECTOR`, `CALENDAR_READY_SELECTOR`, `SELECTED_CATEGORY_SELECTOR`, `OPEN_SLOT_SELECTOR` ни ҳақиқий календар элементлари бўйича аниқлаш керак. **Бирон селекторни тахмин қилманг**. `python monitor.py once` ни локал синаб, текширув тўғри эканини тасдиқланг.
6. `python monitor.py export-session` деб, браузерда кириб Short Stay календарини очинг, Enter босинг. Бу `.private/auth_state.json` ва `.private/calendar_url.txt` ҳосил қилади. **Уларни GitHub'га юкламанг ва ChatGPT'га юборманг.**

## 2. GitHub аккаунти ва public репозиторий

1. [github.com](https://github.com/) да бепул аккаунт очинг.
2. `New repository`: `visa-slot-monitor`, **Public**. Парол ва шахсий маълумотни repo номи ёки README'га қўшманг.
3. `Add file -> Upload files` орқали **шу папкадаги лойиҳа файлларини ва `.github/workflows/visa_slot_check.yml` ни** repository root ичига жойланг. GitHub веб-юклаши яширин `.github` папкасини сақламаган бўлса, бу YAML файлни UI орқали `Create new file` билан айнан `.github/workflows/visa_slot_check.yml` йўлига яратинг.
4. **.env, .private, auth_state.json, telegram токени, cookie, screenshot** — ҳеч нарсани repo'га юкламанг.

## 3. GitHub Secrets

Repository -> `Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`.

- `TELEGRAM_BOT_TOKEN`: BotFather токенингиз.
- `TELEGRAM_CHAT_ID`: ўзингизнинг Telegram чат ID'ингиз.
- `SLOT_SCOPE_SELECTOR`: локалда тасдиқланган CSS.
- `CALENDAR_READY_SELECTOR`: локалда тасдиқланган CSS.
- `SELECTED_CATEGORY_SELECTOR`: Short Stay танланганини тасдиқловчи CSS.
- `OPEN_SLOT_SELECTOR`: ҳақиқий бўш слот элементлари CSS.
- `CALENDAR_URL`: `export-session` яратган `.private/calendar_url.txt` мазмуни (агар URL ни ўзгартириш шарт бўлса). Фақат расмий `https://uzembassyryouji.rsvsys.jp/reservations/...` URL.
- `AUTH_STATE_B64`: **Windows'да** `python github_secret_clipboard.py` ни ишга туширинг. Сессиянинг base64 шакли clipboard'га қўйилади, экранга чиқмайди. Уни GitHub secret майдонига Paste қилинг. Кейин clipboard'ни тозаланг. Base64 шифрлаш эмас, фақат кодлаш; хавфсизлик GitHub Secrets'га боғлиқ.

**Ҳеч қачон токен, cookie ёки AUTH_STATE_B64 ни Telegram, чат, public Issue ёки репозиторийга жойламанг.**

## 4. Биринчи ишга тушириш

1. GitHub repository -> `Actions` -> `Visa Slot Monitor (free public repository)` -> `Run workflow`.
2. Ишга туширишни кузатинг. Реал слот чиққанини сайт билан таққосланг. `monitor_checkpoint.json` фақат fingerprint ва ҳолатларни сақлайди (логин маълумотларини эмас).
3. Keyingi ишга тушишлар UTC cron `:07,:17,:27,:37,:47,:57` бўйича режалаштирилади. Кечикиш / job skip бўлиши мумкин.
4. Агар у тўхтаса (CAPTCHA, expired login, CSS), **локалда янги сессия экспорт қилиб**, `AUTH_STATE_B64` secret'ни янгиланг. Кейин `Actions -> Run workflow -> reset_pause=true` танланг. Шундан кейингина текшириш қайта давом этади.
5. `Settings -> Billing and licensing` орқали бепул лимит ва харажатларни текширинг. Public стандарт Actions бесплат, лекин репозиторий Private қилиб ўзгарса, ёки larger runner танланса, харажат пайдо бўлиши мумкин. Аввал репозиторийни Public сақланг.

## 5. Хавфсизлик ва чекловлар

- `AUTH_STATE_B64` сессия токени ҳисобланади; leaked бўлса аккаунтга рухсатсиз кириш хавфи бор. Аккаунтдан чиқиб токенни бекор қилинг ва Telegram бот токенини алмаштиринг.
- Сайт robots / шартлари ёки anti-bot сиёсати автоматизацияга рухсат бермаса, ҳеч қандай ботни ишга туширманг. Текшириш минимал сони 10 дақиқа, CAPTCHA айланиб ўтилмайди, 403/429 бўлса тўхтайди.
- GitHub Actions ephemeral VM: янгиланган сессия state кейинги runner'га кўчмайди. Cookie rotation бўлса қайта кириш зарур бўлади. Сессияни вақтинча файлда сақлайди, чекпоинт фақат non-secret. 
- Слот мониторинги сайтнинг авторизацияланган календар структураси ўзгарса нотўғри ишлаши мумкин; selector'ни қайта текширинг.
- Пул тўламасдан ва компьютер ўчиқ пайтда **10 дақиқалик қатъий SLA** берадиган хизмат йўқ: бу best-effort бепул вариант.

Манбалар: https://docs.github.com/en/billing/concepts/product-billing/github-actions , https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

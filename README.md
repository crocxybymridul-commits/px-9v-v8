# PX9V Landing Provisioner — updated template

This package contains a Telegram landing/store bot that provisions isolated PX9V bot instances from the supplied `9V-main.zip` template.

## Landing flow

`/start` → **BUY NEW BOT** → send access/create key → send customer bot token → send Admin ID → bot is provisioned and started.

If the access key was created with Premium enabled, the new PX9V instance receives a one-time PX9V-compatible Premium Key. The key uses the same `premium_keys` schema and redemption flow as the supplied PX9V source.

## Admin

`/admin` opens the landing admin panel.

**CREATE TOKEN** asks for:
1. USER / bot-creation count
2. Whether a Premium Key should be included
3. Premium KEY USER limit
4. Premium KEY REVENUE limit
5. Premium KEY TIME in days

The access key can therefore provision exactly the configured number of customer bots.

## Revoke

A customer can revoke their own bot with:

- `/revoke @botusername`
- `/revoke ACCESS_TOKEN`

Revoking an access token also revokes/stops every bot created from that access token.

The landing admin can revoke any bot/token.

## Important environment variables

```text
LANDING_BOT_TOKEN=...
LANDING_ADMIN_ID=...
LANDING_DB_PATH=/data/landing_bot.db
INSTANCE_ROOT=/data/instances
TEMPLATE_ROOT=px9v_template
MASTER_INSTANCE_KEY=<44-character URL-safe Fernet key>
REVOKE_DELETE_FILES=true
```

Generate `MASTER_INSTANCE_KEY` without installing cryptography on the phone:

```bash
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

## Railway

Add a Railway Volume mounted at `/data`. This keeps the landing DB and customer bot instances across redeployments.

Start command:

```text
python main.py
```

## PX9V template / QR handling

The customer bot template is the newly supplied `9V-main.zip`, not the previous template.

Its `requirements.txt` includes `qrcode[pil]>=8.0`. Additionally, the QR code handler has an HTTP QR fallback, so the customer bot does not show the old `QR module is missing on the server` error merely because the optional local QR package is unavailable.


## New son-bot permissions and themes

- Every ID in `LANDING_ADMIN_ID` and the optional comma-separated `LANDING_ADMIN_IDS` is passed into each provisioned son bot as `FATHER_ADMIN_IDS`.
- Those father-bot administrators receive `/padmin` and the same permanent-admin permissions inside every son bot. The customer-selected Admin ID remains a permanent admin too.
- Son-bot `/admin` includes **CHANGE THEME**, **WELCOME VIDEOS**, and **RESTRICT BOT**.
- Theme 1 preserves the existing layout. Themes 2 and 3 show every premium plan directly on the main menu, one button per row, followed by menu buttons in pairs (Menu 1 | Menu 2, then Menu 3, etc.).
- Theme 3 additionally sends up to five admin-configured welcome videos as one Telegram media album, followed by the saved welcome message and its main-menu buttons. Configure them from `/admin` → **WELCOME VIDEOS**. Send videos one by one, then press **DONE**. **CLEAR ALL** removes the saved list.
- `/buttoncolor [ID] [R/G/B]` controls premium-button colors in the currently selected theme; `/menucolor [ID] [R/G/B]` controls menu-button colors.

## Protected content limitation

**RESTRICT BOT** applies Telegram's `protect_content` flag to newly sent/copied bot content while enabled, including welcome albums, welcome copies, premium menus, QR images, and broadcast copies. The toggle takes effect immediately for supported sends; previously sent messages are not retroactively protected. Telegram bots cannot prevent screenshots, screen recordings, or external capture.


## Message auto-delete timers

- Theme 3 welcome videos (single video or every item in the welcome-video album) are scheduled for deletion 20 seconds after delivery. The welcome text/message is not deleted by this timer.
- The configured approved-content message sent after a manual admin approval is scheduled for deletion after 6 hours. The payment receipt text sent separately is not included in that deletion timer.

## Automatic payment verification status

Manual admin approval remains the active payment-verification flow in this build. Automatic verification is not enabled yet: the correct provider integration depends on the merchant product and its official API credentials/documentation. Do not use unofficial/private dashboard endpoints or share merchant secrets in chat.


## Approved-payment announcements

- After a payment changes from `pending` to `approved` for the first time, the bot sends the approved-payment record (including the submitted screenshot when available) to every distinct admin log channel configured with `/addlogchnl`.
- The same approval event is broadcast to registered live users as a photo/caption (or text if no screenshot exists), with the exact `main_menu()` keyboard used by `/start` beneath it. That keyboard includes the configured premium-price buttons and the normal menu buttons.
- Repeated approval clicks do not repeat the log or user broadcast because the database approval transition is conditional on `status='pending'`.
- Users who have blocked the bot are marked inactive for future broadcasts. The broadcast is rate-limited to avoid sending too quickly.


## Telegram Paytm credential wizard (secure-storage preparation)

- Son-bot Admin Panel includes **PAYMENT GATEWAY** → **SETUP PAYTM**.
- The wizard accepts MID, Merchant Key, Website Name (use `DEFAULT` if that is what Paytm assigned), and TEST/PRODUCTION environment.
- It only runs in the admin's private chat. Secret messages are deleted on a best-effort basis, never echoed, and the credential bundle is encrypted with Fernet before it is stored in that bot's SQLite settings.
- Each provisioned bot receives a distinct encryption key derived from the landing `MASTER_INSTANCE_KEY` and its instance ID at process start. The derived key is not written to the customer bot `.env`. Keep `MASTER_INSTANCE_KEY` private and backed up: losing it makes encrypted credentials unreadable.
- Removing credentials deletes the encrypted bundle. If a key may have been exposed, rotate/regenerate it in Paytm too.
- **Important limitation:** Telegram messages are not a secure secrets vault. Message deletion is best-effort; chat history, notifications, device backups, Telegram infrastructure, process memory, and server backups may retain data. A secure HTTPS credential form is safer.
- This wizard only stores credentials securely. Automatic payment verification remains OFF until the merchant's exact Paytm product/API, order creation, status query, checksum/signature verification, callback/webhook validation, and production activation are implemented and tested. Do not treat a redirect or screenshot as proof of payment.

## Father Bot profiles, premium slots, and support (V6 update)

- `/start` creates/updates a persistent user profile (Telegram ID, name, username, registration and last-seen timestamps) and displays the new menu: **MY PROFILE**, **MY BOT**, **REMOVE BOT**, **REDEEM KEY**, **CREATE NEW BOT**, and **CONTACT**.
- `/redeem KEY` or the REDEEM KEY button activates a premium subscription key. Premium keys are created from `/admin` → **CREATE PREMIUM KEY** and have a plan name, redeemable-user count, bots per user, duration in days, and price.
- While a subscription is active, **CREATE NEW BOT** checks the user's bot-slot limit. A removed bot frees one slot; removing a bot does not remove the premium plan. The existing legacy access-key creation flow remains available for compatibility.
- **REMOVE BOT** offers the user's active bot list and requires confirmation before revoking. `/remove @botusername` (or bot record ID) also works. `/revoke` remains as a legacy command.
- **CONTACT** accepts one text/media submission, copies it to configured Father Bot admins, includes user profile/subscription information, and provides **REPLY TO USER**. A per-user five-minute cooldown limits repeat submissions.
- Admin panel includes **CREATE PREMIUM KEY**, **CHECK ELITE USER**, **REMOVE PREMIUM**, **ADD PREMIUM**, **USERS**, **PREMIUM USERS**, **ALL BOTS**, support guidance, legacy token generation, and statistics. `/removep USER_ID` revokes a user's premium subscription and notifies them.
- Premium keys are stored as SHA-256 hashes. Subscription expiry and redemption history are persisted in SQLite.



## Father Admin Web Control Panel (new)

An owner dashboard can run alongside Telegram polling. It is disabled unless `FATHER_WEB_PASSWORD` is set. Configure these Railway variables:

```text
FATHER_WEB_PASSWORD=<long-random-password-at-least-12-characters>
FATHER_WEB_SECRET=<long-random-random-secret>
PORT=<Railway-provided-port>
```

Railway routes HTTPS traffic to the service port. The web panel is served on `0.0.0.0:$PORT`; open the generated Railway domain and log in. The panel includes overview statistics, registered users, bot instances, premium keys, active premium subscriptions, key creation, premium removal, and bot revocation. Tokens and merchant credentials are not displayed.

**Security:** use a unique password, keep `FATHER_WEB_SECRET` private and stable, and use a Railway HTTPS domain. Do not expose the panel on a public non-HTTPS server. This password-based panel is an initial owner dashboard; Telegram Login/OAuth and a persistent audit log are not included in this build.

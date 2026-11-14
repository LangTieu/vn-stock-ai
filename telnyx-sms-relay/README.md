# telnyx-sms-relay

A Cloudflare Worker (plain JavaScript, no build step) that receives inbound SMS
webhooks from Telnyx and forwards each message to Telegram, Discord and/or
WhatsApp. It stores nothing and never logs message content (sender, recipient
or text); logs contain only counts and error statuses.

## Behaviour

| Request | Response |
| --- | --- |
| `GET /` | `200 ok` (health check) |
| `POST /telnyx` or `POST /` with a Telnyx API v2 `message.received` event | `200 ok`; message forwarded in the background |
| `POST` with any other `data.event_type` | `200 ignored` |
| `POST` with a bad signature or a timestamp more than 5 minutes off (only when `TELNYX_PUBLIC_KEY` is set) | `401` |
| `POST` with a body that is not JSON | `400` |

Forwarding runs after the response is sent (`ctx.waitUntil`), so a failing
Telegram, Discord or WhatsApp call never fails or slows the Telnyx webhook.

Forwarded text looks like:

```
SMS from +1XXXXXXXXXX to +1XXXXXXXXXX

<message text>
```

MMS media is not forwarded; the message notes how many attachments were dropped.

### Signature verification

When `TELNYX_PUBLIC_KEY` is set, the worker verifies the Ed25519 signature in the
`telnyx-signature-ed25519` header over `<telnyx-timestamp>|<raw body>` and rejects
timestamps more than 5 minutes from now. When it is **not** set, requests are
accepted without verification (fail-open). Set it before relying on the relay.

## Environment variables

All are secrets; set them with `wrangler secret put`. Every forwarding target is
optional and is used only when all of its variables are set.

| Variable | Purpose |
| --- | --- |
| `TELNYX_PUBLIC_KEY` | Base64 Ed25519 public key from Telnyx Mission Control (Account Settings → Keys & Credentials → Public Key). Enables signature checks. |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather. |
| `TELEGRAM_CHAT_ID` | Chat/group/channel ID the bot posts to. |
| `DISCORD_WEBHOOK_URL` | Discord channel incoming-webhook URL. |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp Cloud API sender phone-number ID. |
| `WHATSAPP_TOKEN` | WhatsApp Cloud API access token. |
| `WHATSAPP_RECIPIENT` | Recipient number in international format without `+` (e.g. `1XXXXXXXXXX`). |

WhatsApp only delivers free-form text to a recipient who has messaged the sender
number in the last 24 hours; outside that window the Cloud API requires an
approved template, and the forward will fail (logged, webhook still returns 200).

## Deploy

```sh
cd telnyx-sms-relay
npx wrangler login            # once
npx wrangler deploy

# Set only the secrets you need; each command prompts for the value.
npx wrangler secret put TELNYX_PUBLIC_KEY
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_CHAT_ID
npx wrangler secret put DISCORD_WEBHOOK_URL
npx wrangler secret put WHATSAPP_PHONE_NUMBER_ID
npx wrangler secret put WHATSAPP_TOKEN
npx wrangler secret put WHATSAPP_RECIPIENT
```

Check the deployment: `curl https://telnyx-sms-relay.<your-subdomain>.workers.dev/`
should print `ok`.

Then, in Telnyx Mission Control → Messaging → your messaging profile, set the
inbound webhook URL to:

```
https://telnyx-sms-relay.<your-subdomain>.workers.dev/telnyx
```

Make sure the US number is assigned to that messaging profile, then send it a
test SMS. `npx wrangler tail` shows the count-only logs.

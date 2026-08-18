---
name: launch
description: Use when a product or feature is ready to go public — after shipping, when the user says "launch it", "announce it", "go live", or wants a release marketed end to end.
---

# Launch: ship → announce → measure

Chains existing capabilities into one launch pass. Draft everything, send nothing without approval — external comms are a CLAUDE.md Hard Stop.

## 1. Pre-flight (verify, don't assume)

- Uncommitted work? Run `/ship` first.
- Prod deploy live: check latest deployment status/logs (offlocal `get_latest_deployment_logs` / Vercel tools).
- Domain resolves, HTTPS works, OG meta + title + favicon present: fetch the live page and look.
- UI-facing? Run `/de-vibe` if it hasn't had a pass.

## 2. Assets

- Changelog entry (one contiguous pasteable block).
- Screenshot or demo GIF: chrome-devtools `take_screenshot` or claude-in-chrome `gif_creator` against the live site.
- Landing copy sanity: does the page pass the 10-second first-glance test?

## 3. Announcement drafts (draft only — approval gate before ANY send)

Write all of these, then stop and present for approval:

- X/Twitter thread (hook first, link in tweet 1 or 2).
- LinkedIn post.
- Discord/Telegram announcement.
- Email to list (Resend) if one exists for this product.

Copy rules (from CLAUDE.md, non-negotiable): no em dashes, no "delve/elevate/seamless" AI slop, write like a person, pasteable blocks with no mid-sentence newlines.

## 4. Publish (only after explicit approval, channel by channel)

- X/LinkedIn: claude-in-chrome through the logged-in browser session.
- Discord/Telegram: existing webhooks (curl).
- Email: Resend via offlocal (governed — DashClaw guard applies).

## 5. Post-launch loop

- Offer a next-day check: PostHog funnel/pageviews + Stripe events + Sentry errors for the new surface. `/schedule` a one-time run if the user wants it automated.

## Failure modes

- Announcing before the deploy is verified live — pre-flight is not optional.
- Sending anything without the per-channel approval gate.
- Marketing copy that reads AI-generated — apply the copy rules to every draft, not just finals.

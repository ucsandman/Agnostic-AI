---
name: seo-floor
description: What every public web surface ships with, in the same change that creates it, and where it gets registered. Loads when a sitemap, robots, llms.txt or a page's head is being touched.
context:
  triggers:
    keywords: [seo, sharecard, og.png, twitter card, sitemap, robots.txt, llms.txt, meta description, canonical, og image, search console, bing webmaster, public web surface, landing page]
    commands: [sitemap, robots.txt, llms.txt]
    paths: ["**/sitemap*", "**/robots*", "**/llms.txt", "**/app/layout.*", "**/pages/_document.*"]
  priority: 60
  stale_after: 180d
---
# SEO floor (loaded on demand)

A public web surface ships its SEO floor in the same change that creates it: sitemap, robots.txt, llms.txt, a real title and meta description per indexable page, canonical, OG image, `noindex` on thanks, dashboard and API pages. Title-tag wording comes from real search volume (treg keyword lookup), not guesses. Reference: `C:\Projects\callclaw\src\app\{sitemap,robots}.ts` and `public/llms.txt`; checked by the preflight skill, section 3.

The sharecard is part of the floor, not an extra: a 1200x630 `og.png`, `og:image`, `twitter:card=summary_large_image` and `twitter:image` on every indexable page, the image URL versioned (`?v=N`, bumped on every re-render so X and Slack refetch). Prove it as a crawler: fetch the image with `-A Twitterbot/1.0`, and read robots.txt for a prefix that swallows it (`Disallow: /og` also blocks `/og.png`; write `Disallow: /og$` and `Allow: /og.png`). Then paste the URL into a real X, Slack or Discord composer and look at the card. A link with no card reads as a scam beside one with a card. (Wes, 2026-09-19: legcli.com had the tags and the image for four days and no card on X, because robots.txt blocked the image.)

Register the surface in the session that deploys it, never a later sweep: Google Search Console property verified (URL prefix + meta tag, no DNS change) with the sitemap submitted and the home URL inspected; Bing Webmaster Tools imported from Search Console; the host's first-party analytics with its tag on every page (Vercel Web Analytics on Vercel). Procedure: `~/.claude/skills/preflight/references/search-registration.md`.

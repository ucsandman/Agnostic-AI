---
name: seo-floor
description: What every public web surface ships with, in the same change that creates it, and where it gets registered. Loads when a sitemap, robots, llms.txt or a page's head is being touched.
context:
  triggers:
    keywords: [seo, sitemap, robots.txt, llms.txt, meta description, canonical, og image, search console, bing webmaster, public web surface, landing page]
    commands: [sitemap, robots.txt, llms.txt]
    paths: ["**/sitemap*", "**/robots*", "**/llms.txt", "**/app/layout.*", "**/pages/_document.*"]
  priority: 60
  stale_after: 180d
---
# SEO floor (loaded on demand)

A public web surface ships its SEO floor in the same change that creates it: sitemap, robots.txt, llms.txt, a real title and meta description per indexable page, canonical, OG image, `noindex` on thanks, dashboard and API pages. Title-tag wording comes from real search volume (treg keyword lookup), not guesses. Reference: `C:\Projects\callclaw\src\app\{sitemap,robots}.ts` and `public/llms.txt`; checked by the preflight skill, section 3.

Register the surface in the session that deploys it, never a later sweep: Google Search Console property verified (URL prefix + meta tag, no DNS change) with the sitemap submitted and the home URL inspected; Bing Webmaster Tools imported from Search Console; the host's first-party analytics with its tag on every page (Vercel Web Analytics on Vercel). Procedure: `~/.claude/skills/preflight/references/search-registration.md`.

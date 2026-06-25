# Domain setup guide (do this BEFORE going live)

> You've picked your domain. This guide gets it pointed at AI Cost Calculator in ~30 minutes.

## 1. Register the domain

**Recommended registrar: Cloudflare Registrar (https://cloudflare.com/products/registrar)**
- At-cost pricing (no markup, no renewal bumps)
- Free WHOIS privacy
- DNS management integrated (no extra step)
- ~$10-15/year for .com, ~$60-100/year for .ai

Alternatives:
- Namecheap — popular, cheap first year, renewal bumps after
- Porkbun — generally cheapest .com renewals
- Gandi — no markup, good .io / .ai pricing

## 2. Set up DNS (in Cloudflare / your registrar)

Add these records (replace `YOUR_DOMAIN` with your actual domain):

```
Type    Name    Content                     Proxy
A       @       10.10.10.205                Proxied (orange cloud)
A       www     10.10.10.205                Proxied (orange cloud)
```

If you want HTTPS (you do), Cloudflare will auto-provision a free cert
once DNS propagates.

## 3. Update the site

The dev server currently listens on `http://10.10.10.205:3018`. Once
your domain is live:

1. **Test locally first**: `curl http://10.10.10.205:3018/` returns 200
2. **Verify DNS resolves**: `dig YOUR_DOMAIN` returns 10.10.10.205
3. **Test public access**: Open https://YOUR_DOMAIN in a browser
4. **Update all internal references**: the homepage, model pages, blog,
   compare pages all reference relative paths so they'll work on any
   domain. The only thing hardcoded is the logo path — already relative.

## 4. Twingate access (if you want private staging before public launch)

You mentioned Twingate for accessing the box from a separate laptop.
If you want to keep AI Cost Calculator private until you're ready to launch:

1. Add a Twingate Resource for port 3018 (TCP)
2. The resource should resolve to 10.10.10.205:3018 internally
3. Once you're ready to go public, remove the Twingate Resource

For public launch, you'll also need to make sure your box's firewall
allows inbound 80/443 (Cloudflare proxies through them).

## 5. Pre-launch checklist

Before pushing the public link anywhere:

- [ ] Domain resolves to 10.10.10.205 (or wherever the box lives)
- [ ] HTTPS works (free via Cloudflare)
- [ ] All 349 model pages return 200
- [ ] /models/index.html lists all 349 with filter
- [ ] /blog/ has 10 articles (pending SEO-2 blog card)
- [ ] /compare/ has 13 pages
- [ ] about.html has Andrew Morgado bio + Person schema
- [ ] Sitemap.xml includes all URLs
- [ ] robots.txt allows crawl
- [ ] Footer has "Pricing via OpenRouter · refreshed every 6h" attribution
- [ ] No "Coming Soon" or stub pages that 404

## 6. Post-launch: 24-hour monitoring

Watch for:
- 5xx errors (server overload)
- Slow load times (>3s)
- Crawler errors in Google Search Console (once verified)
- User feedback / bug reports

Have the Show HN post draft ready to go Tuesday morning.

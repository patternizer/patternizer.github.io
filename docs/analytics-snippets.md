# Analytics snippets (choose one)

Add exactly **one** of the following to the `<head>` of `index.html` (right before `</head>`).
Replace the placeholders (domain, token, measurement ID) with your values.

---

## 1) Plausible (privacy‑friendly, EU‑hosted)
```html
<!-- Plausible -->
<script defer data-domain="patternizer.github.io" src="https://plausible.io/js/script.js"></script>
```
**Custom events (optional):**
```html
<!-- Somewhere after the script is loaded -->
<script>
  // Example call-to-action button
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.querySelector('[data-track="contact"]');
    if(btn){
      btn.addEventListener('click', () => {
        if(window.plausible){ plausible('ContactClicked'); }
      });
    }
  });
</script>
```

---

## 2) Google Analytics 4 (gtag.js)
```html
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-XXXXXXXXXX');   // replace with your GA4 Measurement ID
</script>
```
**Custom event example:**
```html
<script>
  // Example call-to-action button
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.querySelector('[data-track="contact"]');
    if(btn){
      btn.addEventListener('click', () => {
        if(window.gtag){ gtag('event', 'contact_click', { method: 'button' }); }
      });
    }
  });
</script>
```

---

## 3) Cloudflare Web Analytics (free, no cookies)
```html
<!-- Cloudflare Web Analytics -->
<script defer src="https://static.cloudflareinsights.com/beacon.min.js"
        data-cf-beacon='{"token": "YOUR_CLOUDFLARE_TOKEN"}'></script>
```
(Find your token in Cloudflare’s Web Analytics dashboard.)

---

### Notes
- Use **only one** provider to avoid double‑counting.
- If you later add a Content‑Security‑Policy (CSP), include the chosen provider’s script URL and, if needed, `script-src` hashes/nonces.
- To exclude your own visits, use your provider’s ignore features (e.g., Plausible’s `localStorage.plausible_ignore`).

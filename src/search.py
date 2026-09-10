import os
import time

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
EXCLUDED_SITES = ["facebook.com", "linkedin.com"]

CAPTCHA_SELECTORS = [
    "iframe[src*='google.com/recaptcha']",
    "iframe[src*='hcaptcha.com']",
    "div.g-recaptcha",
    "div.h-captcha",
]


def _beep():
    try:
        if os.name == "nt":
            import winsound
            for _ in range(3):
                winsound.Beep(1000, 300)
                time.sleep(0.1)
    except Exception:
        pass


def _print_banner(url, wait_s):
    line = "=" * 78
    print(f"\n{line}")
    print("  *** CAPTCHA DETECTED — HUMAN ACTION REQUIRED ***")
    print(f"  Solve the captcha in the browser window.")
    print(f"  URL: {url}")
    print(f"  Waiting up to {wait_s}s...")
    print(line)

EXTRACT_RESULTS_JS = """
() => {
  const out = [];
  const seen = new Set();

  function unwrapUrl(rawUrl) {
    if (!rawUrl) return null;
    let href = rawUrl;

    if (href.includes('/url?') || href.includes('/goto?') || href.includes('/aclk?')) {
      try {
        const u = new URL(href, window.location.origin);
        for (const param of ['q', 'url', 'dest', 'target', 'adurl', 'u', 'r']) {
          const val = u.searchParams.get(param);
          if (val && /^https?:/i.test(val)) {
            href = val;
            break;
          }
        }
      } catch (e) {}
    }

    if (href.startsWith('/goto') || href.startsWith('/url') || href.startsWith('/aclk')) {
      try {
        return new URL(href, window.location.origin).href;
      } catch (e) {}
    }

    try {
      const urlObj = new URL(href, window.location.origin);
      if (!/^https?:$/.test(urlObj.protocol)) return null;
      const host = urlObj.hostname;
      if (/(^|\\.)(google|gstatic|googleusercontent|youtube)\\./i.test(host) || /(^|\\.)(schema|w3)\\.org$/i.test(host)) {
        return null;
      }
      return urlObj.href;
    } catch (e) {
      return null;
    }
  }

  const searchArea = document.querySelector('#rso') || document.querySelector('#search') || document.body;
  const cards = searchArea.querySelectorAll('div.g, div.MjjYud, div.yuRUbf, div.tF2Cxc, div[data-hveid]');

  cards.forEach(card => {
    const h3 = card.querySelector('h3');
    if (!h3) return;

    const title = h3.innerText.trim();
    if (!title || title.length < 2) return;

    const a = h3.closest('a') || card.querySelector('a[href]');
    if (!a) return;

    const candidates = [
      a.getAttribute('data-url'),
      a.getAttribute('data-href'),
      a.getAttribute('data-rw'),
      a.getAttribute('href'),
      a.href,
      a.getAttribute('ping')
    ];

    let cleanUrl = null;
    for (const cand of candidates) {
      if (!cand) continue;
      cleanUrl = unwrapUrl(cand);
      if (cleanUrl) break;
    }

    if (!cleanUrl) {
      const cite = card.querySelector('cite');
      if (cite) {
        let citeText = cite.innerText.split('›')[0].split(' › ')[0].trim();
        if (citeText) {
          if (!citeText.startsWith('http')) {
            citeText = 'https://' + citeText;
          }
          try {
            const u = new URL(citeText);
            if (/^https?:/.test(u.protocol) && !/(^|\\.)(google|gstatic)\\./i.test(u.hostname)) {
              cleanUrl = u.href;
            }
          } catch (e) {}
        }
      }
    }

    if (!cleanUrl || seen.has(cleanUrl)) return;

    seen.add(cleanUrl);
    out.push({ url: cleanUrl, title: title.slice(0, 200) });
  });

  if (out.length === 0) {
    const anchors = searchArea.querySelectorAll('a');
    anchors.forEach(a => {
      const h3 = a.querySelector('h3') || a.closest('div')?.querySelector('h3');
      if (!h3) return;
      const title = h3.innerText.trim();
      if (!title || title.length < 2) return;

      const cand = a.getAttribute('href') || a.href;
      const cleanUrl = unwrapUrl(cand);
      if (cleanUrl && !seen.has(cleanUrl)) {
        seen.add(cleanUrl);
        out.push({ url: cleanUrl, title: title.slice(0, 200) });
      }
    });
  }

  return out;
}
"""


def build_query(skills, is_remote, excluded=EXCLUDED_SITES):
    terms = [f'"{s}"' for s in skills]
    if is_remote:
        terms.append('"remote"')
    query = 'intitle:career AND ' + " AND ".join(terms)
    for site in excluded:
        query += f" -site:{site}"
    return query


class SearchSession:
    """Sync Playwright session used for both Google listing pages and candidate pages."""

    def __init__(self, headless=False, google_domain="google.com", timeout_ms=30000, captcha_wait_s=120, user_data_dir="./user_data"):
        from playwright.sync_api import sync_playwright
        try:
            from playwright_stealth import stealth_sync
        except ImportError:
            stealth_sync = None

        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"]
        )
        self._context.set_default_timeout(timeout_ms)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

        if stealth_sync:
            try:
                stealth_sync(self._page)
            except Exception:
                pass

        self._google_domain = google_domain
        self._timeout_ms = timeout_ms
        self._captcha_wait_s = captcha_wait_s

    # ---- captcha escalation ---------------------------------------------

    def _captcha_present(self, timeout_ms=1500):
        for sel in CAPTCHA_SELECTORS:
            try:
                if self._page.locator(sel).first.is_visible(timeout=timeout_ms):
                    return True
            except Exception:
                pass
        try:
            return "/sorry/" in (self._page.url or "")
        except Exception:
            return False

    def _escalate_captcha(self, url):
        """Notify the human and wait for the captcha to clear.
        Re-appearing captchas (2nd puzzle, etc.) are re-announced and each gets
        a full captcha_wait_s budget; give up only if one stays unsolved the whole window."""
        _beep()
        _print_banner(url, self._captcha_wait_s)
        REAPPEAR_DEBOUNCE_S = 3.0
        round_start = time.time()
        gone_since = None
        while True:
            time.sleep(1.0)
            present = self._captcha_present(timeout_ms=2500)
            if not present:
                if gone_since is None:
                    gone_since = time.time()
                elif time.time() - gone_since >= REAPPEAR_DEBOUNCE_S:
                    try:
                        self._page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    time.sleep(1.0)
                    print("  captcha solved; continuing.")
                    return True
            else:
                if gone_since is not None:
                    _beep()
                    line = "=" * 78
                    print(f"\n{line}\n  !! ANOTHER CAPTCHA APPEARED — solve it in the browser.")
                    print(f"  URL: {url}")
                    print(line)
                    gone_since = None
                    round_start = time.time()
                elif time.time() - round_start >= self._captcha_wait_s:
                    print(f"  captcha still present after {self._captcha_wait_s}s; skipping.")
                    return False

    # ---- search listing -------------------------------------------------

    def _dismiss_consent(self):
        try:
            btn = self._page.locator("#L2AGLb, button[aria-label='Accept all'], button:has-text('Accept all'), button:has-text('I agree')").first
            if btn.is_visible(timeout=2000):
                btn.click()
                self._page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

    def _extract_results(self):
        return self._page.evaluate(EXTRACT_RESULTS_JS)

    def _type_search(self, query):
        self._page.goto(f"https://{self._google_domain}/", wait_until="domcontentloaded")
        self._dismiss_consent()
        box = self._page.locator("textarea[name='q'], input[name='q']").first
        box.wait_for(state="visible", timeout=15000)
        box.fill(query)
        time.sleep(1.0)
        box.press("Enter")
        self._page.wait_for_load_state("domcontentloaded", timeout=15000)
        self._dismiss_consent()

    def collect_results(self, query, max_pages=2):
        """Collect {url, title} from up to max_pages Google result listing pages."""
        from urllib.parse import quote_plus

        all_results = []
        seen = set()
        for page_no in range(1, max_pages + 1):
            if page_no == 1:
                self._type_search(query)
            else:
                nxt = self._page.locator("a[aria-label='Next'], .pnf, a.pf.link, #pnnext, a#pnnext, td.b > a").first
                if not nxt.is_visible(timeout=4000):
                    print(f"      (no next-page link on listing page {page_no}; stopping)")
                    break
                try:
                    nxt.click()
                    self._page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception as e:
                    print(f"      (failed to click next-page link: {e}; stopping)")
                    break
                time.sleep(2.0)

            self._dismiss_consent()
            if self._captcha_present():
                if not self._escalate_captcha(self._page.url):
                    break

            # After potential captcha escalation, verify we are actually on search results page
            cur_url = self._page.url or ""
            if "/sorry/" in cur_url or "search" not in cur_url or ("q=" not in cur_url and "?q=" not in cur_url):
                search_url = f"https://{self._google_domain}/search?q={quote_plus(query)}"
                print(f"  Navigating to search results page: {search_url}")
                try:
                    self._page.goto(search_url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                    self._dismiss_consent()
                    if self._captcha_present():
                        if not self._escalate_captcha(self._page.url):
                            break
                except Exception as e:
                    print(f"  Navigation failed: {e}")

            # Wait for search results elements to render
            for selector in ["#rso", "div.g", "div.MjjYud", "div[data-sokoban-container]", "a[href^='http']"]:
                try:
                    self._page.wait_for_selector(selector, timeout=3000)
                    break
                except Exception:
                    pass
            time.sleep(1.5)

            # Retry extraction up to 3 times in case page is still rendering or navigating
            results = []
            for attempt in range(3):
                try:
                    results = self._extract_results()
                except Exception:
                    results = []
                if results:
                    break
                time.sleep(1.5)

            fresh = [r for r in results if r["url"] not in seen]
            seen.update(r["url"] for r in fresh)
            print(f"  listing page {page_no}: {len(fresh)} results")
            all_results.extend(fresh)

        return all_results

    # ---- candidate pages ------------------------------------------------

    def fetch_page(self, url):
        """Navigate to a candidate URL. Returns {"url", "title", "text"} or None on failure."""
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
        except Exception as e:
            print(f"      fetch failed: {e.__class__.__name__}")
            return None
        try:
            self._page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass
        time.sleep(1.0)
        if self._captcha_present():
            if not self._escalate_captcha(url):
                return {"url": url, "status": "captcha-timeout"}
        try:
            title = self._page.title() or ""
            text = self._page.evaluate(
                """
                () => {
                  const el = document.querySelector('main, article, [role="main"], .content');
                  return (el ? el.innerText : document.body.innerText) || '';
                }
                """
            )
        except Exception:
            return None
        return {"url": url, "title": title.strip(), "text": text.strip()}

    def close(self):
        try:
            if hasattr(self, "_context") and self._context:
                self._context.close()
            if hasattr(self, "_pw") and self._pw:
                self._pw.stop()
        except Exception:
            pass

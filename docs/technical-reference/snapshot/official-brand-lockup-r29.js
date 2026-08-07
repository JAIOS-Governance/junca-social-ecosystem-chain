(() => {
  const source = "/junca-chain-official-wordmark.png?v=20260727-r29";
  const image = (width, height) =>
    `<img data-official-junca-wordmark src="${source}" alt="JUNCA" width="${width}" height="${height}">`;

  const replace = (element, markup, className) => {
    if (!element || element.querySelector("img[data-official-junca-wordmark]")) return;
    if (className) element.className = className;
    element.innerHTML = markup;
  };

  const apply = () => {
    replace(document.querySelector(".wordmark"), image(190, 57), "wordmark");
    replace(
      document.querySelector(".documentation-nav-head strong"),
      `${image(200, 60)}<span>Social Ecosystem Chain</span>`,
      "official-brand-lockup",
    );
    replace(
      document.querySelector(".hero h1"),
      `${image(410, 123)}<span>Social Ecosystem Chain</span>`,
      "official-product-name",
    );
    for (const element of document.querySelectorAll("footer strong")) {
      if (element.textContent?.trim() === "JUNCA Social Ecosystem Chain") {
        replace(
          element,
          `${image(190, 57)}<span>Social Ecosystem Chain</span>`,
          "footer-brand-lockup",
        );
      }
    }
  };

  const style = document.createElement("style");
  style.id = "official-brand-lockup-r29-style";
  style.textContent = `
    .wordmark img[data-official-junca-wordmark]{display:block;width:190px;max-width:100%;height:auto;object-fit:contain}
    .documentation-nav-head .official-brand-lockup{display:block}
    .documentation-nav-head .official-brand-lockup img{display:block;width:200px;max-width:100%;height:auto}
    .documentation-nav-head .official-brand-lockup span{display:block;margin-top:.65rem}
    .hero .official-product-name img{display:block;width:min(410px,78vw);height:auto;margin-bottom:1rem}
    .hero .official-product-name span{display:block}
    .footer-brand-lockup{display:flex;flex-direction:column;gap:.55rem}
    .footer-brand-lockup img{display:block;width:190px;max-width:100%;height:auto}
    .footer-brand-lockup span{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase}
    @media(width<=720px){
      .wordmark img[data-official-junca-wordmark]{width:150px;max-width:min(150px,52vw)}
      .hero .official-product-name img{width:min(300px,82vw)}
      .official-product-name span{font-size:.72em}
    }
  `;
  document.head.append(style);

  apply();
  const observer = new MutationObserver(apply);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  addEventListener("DOMContentLoaded", apply, { once: true });
  addEventListener("load", apply, { once: true });
  setTimeout(() => {
    apply();
    observer.disconnect();
  }, 10_000);
})();

;(() => {
  const endpoint = "/current-release.json";
  const stale = /RUNTIME\s+DEPLOYMENT\s+IN\s+PROGRESS|NO\s+MONETARY\s+VALUE|\bNO\s+ACTIVE\b|\bNOT\s+ACTIVATED\b|\bNOT\s+YET\s+PUBLISHED\b/i;
  let navigating = false;
  const bodyText = () => document.body?.innerText ?? "";
  const verify = async () => {
    if (navigating) return;
    try {
      const response = await fetch(`${endpoint}?readback=${Date.now()}`, {
        cache: "no-store",
        headers: { Accept: "application/json", "Cache-Control": "no-cache, no-store, max-age=0", Pragma: "no-cache" },
      });
      if (!response.ok) return;
      const current = await response.json();
      const body = bodyText();
      const required = current.required_visible_terms.every((term) => body.includes(term));
      if (!stale.test(body) && required) return;
      const key = `jsec-docs-release-refresh:${current.token}`;
      if (sessionStorage.getItem(key) === "1") return;
      sessionStorage.setItem(key, "1");
      navigating = true;
      const target = new URL(current.canonical_url || "/", location.origin);
      target.searchParams.set("release", current.token);
      target.searchParams.set("refresh", String(Date.now()));
      location.replace(target.toString());
    } catch {
      // Preserve the last rendered page when the release endpoint is unavailable.
    }
  };
  addEventListener("pageshow", verify);
  addEventListener("focus", verify);
  addEventListener("online", verify);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void verify();
  });
  void verify();
})();

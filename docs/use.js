/*
 * use.js: minimal nav scroll-spy for the "Use the plugin" page.
 * Self-contained: this page deliberately does NOT load the concept page's app.js
 * (which builds page-1-only widgets). Plain anchors work without it; this just
 * highlights the active section as you scroll.
 */
(function () {
  const links = [...document.querySelectorAll('.nav-link')];
  const map = new Map(
    links
      .map((l) => [l.getAttribute('href'), l])
      .filter(([href]) => href && href.startsWith('#'))
      .map(([href, l]) => [href.slice(1), l])
  );
  const obs = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          links.forEach((l) => l.classList.remove('active'));
          map.get(e.target.id)?.classList.add('active');
        }
      });
    },
    { rootMargin: '-45% 0px -50% 0px' }
  );
  document.querySelectorAll('section[id]').forEach((s) => obs.observe(s));
})();

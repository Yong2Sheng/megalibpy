/* Mermaid renders asynchronously. Size each completed SVG from its own viewBox. */
(() => {
  const resizeDiagrams = () => {
    document.querySelectorAll(".mermaid svg:not([data-natural-size])").forEach((svg) => {
      const width = svg.viewBox.baseVal.width;
      if (!(width > 0)) return;
      // SVG text defaults to 1.1em rows; expand around the label's center.
      // Mermaid reserves padding during layout, so edges and node geometry stay valid.
      svg.querySelectorAll(".node text").forEach((text) => {
        const rows = [...text.querySelectorAll(".text-outer-tspan")];
        const font = parseFloat(getComputedStyle(text).fontSize);
        if (rows.length < 2 || !(font > 0)) return;
        rows.forEach((row, index) => {
          const y = row.getAttribute("y");
          if (!y || !y.endsWith("em")) return;
          const extra = (index - (rows.length - 1) / 2) * 0.4 * font;
          row.setAttribute("y", `${parseFloat(y) * font + extra}`);
        });
      });
      svg.style.setProperty("--diagram-natural-width", `${width}px`);
      // Shrink moderately; use figure-local scrolling before text becomes tiny.
      svg.style.setProperty("--diagram-readable-width", `${width * 0.875}px`);
      svg.dataset.naturalSize = "true";
    });
  };
  const start = () => {
    resizeDiagrams();
    let pending = false;
    new MutationObserver((records) => {
      if (pending || !records.some((record) => record.addedNodes.length)) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        resizeDiagrams();
      });
    }).observe(document.body, { childList: true, subtree: true });
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();

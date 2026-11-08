/** Align a section's visible content below the sticky header. */
export function sectionScrollTop(element: HTMLElement): number {
  const anchor =
    (element.dataset.pageSectionAnchor
      ? element.querySelector<HTMLElement>(element.dataset.pageSectionAnchor)
      : null) || element.closest(".section-snap-boundary") || element;
  const offset =
    (document.querySelector(".topbar")?.getBoundingClientRect().height || 72) + 16;
  const limit = Math.max(
    0,
    document.documentElement.scrollHeight - window.innerHeight,
  );
  return Math.min(
    limit,
    Math.max(0, anchor.getBoundingClientRect().top + window.scrollY - offset),
  );
}

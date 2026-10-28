"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { Icon } from "./Icon";

/** Navigate the currently rendered sections, including reports added after loading. */
export function SectionNavigation({
  root,
  paused,
}: {
  root: RefObject<HTMLElement | null>;
  paused: boolean;
}) {
  const [destinations, setDestinations] = useState({ up: "", down: "" });
  const frame = useRef(0);
  const targets = () => {
    const limit = Math.max(
      0,
      document.documentElement.scrollHeight - window.innerHeight,
    );
    const offset =
      (document.querySelector(".topbar")?.getBoundingClientRect().height ||
        72) + 16;
    return Array.from(
      root.current?.querySelectorAll<HTMLElement>("[data-page-section]") || [],
    )
      .filter(
        (element) =>
          element.getClientRects().length &&
          !element.closest("[hidden], [inert]"),
      )
      .map((element, index) => {
        const anchor = element.closest(".section-snap-boundary") || element;
        return {
          label: element.dataset.pageSection!,
          top:
            index === 0
              ? 0
              : Math.min(
                  limit,
                  Math.max(
                    0,
                    anchor.getBoundingClientRect().top +
                      window.scrollY -
                      offset,
                  ),
                ),
        };
      });
  };
  const neighbors = () => {
    const sections = targets();
    return {
      up: sections
        .filter((section) => section.top < window.scrollY - 24)
        .at(-1),
      down: sections.find((section) => section.top > window.scrollY + 24),
    };
  };
  useEffect(() => {
    const update = () => {
      frame.current = 0;
      const next = neighbors();
      setDestinations((current) => {
        const up = next.up?.label || "",
          down = next.down?.label || "";
        return current.up === up && current.down === down
          ? current
          : { up, down };
      });
    };
    const schedule = () => {
      if (!frame.current) frame.current = requestAnimationFrame(update);
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    const resize = new ResizeObserver(schedule);
    const mutations = new MutationObserver(schedule);
    if (root.current) {
      resize.observe(root.current);
      mutations.observe(root.current, { childList: true, subtree: true });
    }
    schedule();
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      resize.disconnect();
      mutations.disconnect();
      cancelAnimationFrame(frame.current);
      frame.current = 0;
    };
  }, [root]); // Destinations are read from the DOM, not captured report state.

  const move = (direction: "up" | "down") => {
    const destination = neighbors()[direction];
    if (!destination) return;
    window.scrollTo({
      top: destination.top,
      behavior:
        paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
    });
  };
  return (
    <nav className="section-navigation" aria-label="Page sections">
      <button
        type="button"
        className="section-navigation-button"
        aria-label="Previous section"
        title={
          destinations.up ? `Up to ${destinations.up}` : "At the first section"
        }
        disabled={!destinations.up}
        onClick={() => move("up")}
      >
        <Icon name="arrow-up" size={20} />
      </button>
      <button
        type="button"
        className="section-navigation-button"
        aria-label="Next section"
        title={
          destinations.down
            ? `Down to ${destinations.down}`
            : "At the last section"
        }
        disabled={!destinations.down}
        onClick={() => move("down")}
      >
        <Icon name="arrow-down" size={20} />
      </button>
    </nav>
  );
}

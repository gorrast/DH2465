"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Draggable } from "gsap/Draggable";
import { ReportFinding, type Report } from "./Home";
import { Icon } from "../ui/Icon";

gsap.registerPlugin(ScrollTrigger, Draggable);

// Adapted from https://codepen.io/GreenSock/pen/RwKwLWK:
// a smoothed proxy playhead, wrapped offsets, dragging and snapping. Keep the
// scroll surface local and horizontal so the rest of the report stays reachable.
export function ReportInsights({
  report,
  paused,
}: {
  report: Report;
  paused: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const navigate = useRef<(by: number) => void>(() => {});
  const [active, setActive] = useState(0);
  const count = report.content.findings.length;
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(preference.matches);
    update();
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);
  const staticCards = paused || reduced;
  useLayoutEffect(() => {
    if (!root.current || count < 2 || staticCards) return;
    const node = root.current;
    const scroller = node.querySelector<HTMLElement>(
      ".report-insights-scroll",
    )!;
    const cards = Array.from(
      node.querySelectorAll<HTMLElement>(".report-insight-card"),
    );
    const proxy = document.createElement("div");
    const step = 320;
    const cycle = count * step;
    const playhead = { offset: 0 };
    let target = 0;
    let startOffset = 0;
    let dragging = false;
    let lastScroll = cycle;
    let spacing = cards[0].offsetWidth + 24;
    let scrub: gsap.core.Tween | undefined;
    const render = () => {
      cards.forEach((card, index) => {
        const distance = gsap.utils.wrap(
          -count / 2,
          count / 2,
          index - playhead.offset,
        );
        const near = Math.abs(distance);
        gsap.set(card, {
          xPercent: -50,
          x: distance * spacing,
          scale: 1 - Math.min(near, 1) * 0.1,
          opacity: Math.max(0, 1 - near / Math.min(1.5, count / 2)),
          zIndex: 10 - Math.round(near),
        });
      });
    };
    const update = (offset: number) => {
      target = offset;
      scrub?.kill();
      scrub = gsap.to(playhead, {
        offset,
        duration: 0.4,
        ease: "power3.out",
        onUpdate: render,
      });
      const selected = gsap.utils.wrap(0, count, Math.round(offset));
      setActive(selected);
      cards.forEach((card, index) => {
        card.inert = index !== selected;
        card.setAttribute("aria-hidden", String(index !== selected));
      });
    };
    const syncScroll = () => {
      // Programmatic scrolling must never feed a second movement back into the
      // playhead. Store the actual (possibly rounded) position before its event.
      scroller.scrollLeft = cycle + gsap.utils.wrap(0, count, target) * step;
      lastScroll = scroller.scrollLeft;
    };
    const snap = () => {
      update(Math.round(target));
      syncScroll();
    };
    const delayedSnap = gsap.delayedCall(0.18, snap).pause();
    syncScroll();
    const readScroll = () => {
      const position = scroller.scrollLeft;
      const delta = position - lastScroll;
      lastScroll = position;
      if (dragging || Math.abs(delta) < 0.01) return;
      update(target + delta / step);
      if (position < step || position > cycle * 3 - step) syncScroll();
      delayedSnap.restart(true);
    };
    const trigger = ScrollTrigger.create({
      scroller,
      horizontal: true,
      start: 0,
      end: cycle * 3,
      onUpdate: readScroll,
    });
    scroller.addEventListener("scroll", readScroll);
    const onWheel = (event: WheelEvent) => {
      const delta = event.deltaX || (event.shiftKey ? event.deltaY : 0);
      if (!delta) return;
      event.preventDefault();
      const pixels =
        delta *
        (event.deltaMode === 1
          ? 16
          : event.deltaMode === 2
            ? scroller.clientWidth
            : 1);
      update(target + pixels / step);
      syncScroll();
      delayedSnap.restart(true);
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    const drag = Draggable.create(proxy, {
      type: "x",
      trigger: node.querySelector(".report-insights-stage"),
      allowNativeTouchScrolling: true,
      onPress() {
        dragging = true;
        delayedSnap.pause();
        startOffset = target;
      },
      onDrag() {
        update(startOffset + (this.startX - this.x) / spacing);
      },
      onRelease() {
        dragging = false;
        snap();
      },
    })[0];
    navigate.current = (by) => {
      delayedSnap.pause();
      update(Math.round(target) + by);
      syncScroll();
    };
    update(0);
    render();
    const resize = new ResizeObserver(() => {
      spacing = cards[0].offsetWidth + 24;
      const height = Math.max(...cards.map((card) => card.scrollHeight));
      node.style.setProperty("--insight-height", `${height + 32}px`);
      // A resize/refresh can clamp scrollLeft; it is layout, not user input.
      syncScroll();
      render();
      trigger.refresh();
    });
    cards.forEach((card) => resize.observe(card));
    return () => {
      navigate.current = () => {};
      resize.disconnect();
      scroller.removeEventListener("scroll", readScroll);
      node.removeEventListener("wheel", onWheel);
      delayedSnap.kill();
      drag.kill();
      trigger.kill();
      scrub?.kill();
      cards.forEach((card) => {
        gsap.set(card, { clearProps: "transform,opacity,zIndex" });
        card.inert = false;
        card.removeAttribute("aria-hidden");
      });
    };
  }, [count, staticCards, report]);

  if (!count)
    return (
      <p className="secondary">
        No individual insights stood out in this report.
      </p>
    );
  if (staticCards || count === 1)
    return (
      <ul className="v-home-findings report-insights-static">
        {report.content.findings.map((_, index) => (
          <ReportFinding key={index} report={report} index={index} />
        ))}
      </ul>
    );
  return (
    <div
      ref={root}
      className="report-insights"
      role="region"
      aria-roledescription="carousel"
      aria-label={`${report.kind === "weekly" ? "Weekly" : "Daily"} report insights`}
    >
      <p className="report-insights-hint">
        Drag or scroll sideways to explore the insights.
      </p>
      <div
        className="report-insights-stage"
        tabIndex={0}
        aria-label="Insight cards. Use left and right arrow keys to browse."
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            navigate.current(event.key === "ArrowLeft" ? -1 : 1);
          }
        }}
      >
        <div className="report-insights-scroll" aria-hidden="true">
          <div style={{ width: `calc(100% + ${count * 3 * 320}px)` }} />
        </div>
        <div className="v-home-findings report-insights-cards">
          {report.content.findings.map((_, index) => (
            <div
              className="report-insight-card"
              key={index}
              role="presentation"
            >
              <ul>
                <ReportFinding report={report} index={index} />
              </ul>
            </div>
          ))}
        </div>
      </div>
      <div className="report-insights-controls">
        <button
          className="btn btn-sm"
          type="button"
          aria-label="Previous insight"
          onClick={() => navigate.current(-1)}
        >
          <Icon name="chevron-left" size={16} />
        </button>
        <span role="status" aria-live="polite">
          Insight {active + 1} of {count}
        </span>
        <button
          className="btn btn-sm"
          type="button"
          aria-label="Next insight"
          onClick={() => navigate.current(1)}
        >
          <Icon name="chevron-right" size={16} />
        </button>
      </div>
    </div>
  );
}

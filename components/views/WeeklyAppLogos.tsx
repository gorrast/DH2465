"use client";

import { useLayoutEffect, useRef, type CSSProperties } from "react";
import { gsap } from "gsap";
import type { AppBrand } from "@/lib/app-brands";

export function WeeklyAppLogos({
  apps,
  paused,
}: {
  apps: AppBrand[];
  paused: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const animations = useRef<gsap.core.Tween[]>([]);
  // A stable key prevents unrelated report renders from restarting the wave.
  const identities = apps.map((app) => app.key).join("|");
  useLayoutEffect(() => {
    if (!root.current) return;
    animations.current = [];
    const context = gsap.context(() => {
      const logos = root.current!.querySelectorAll<HTMLElement>(
        ".weekly-floating-logo",
      );
      logos.forEach((logo, i) => {
        const tween = gsap.fromTo(
          logo,
          { y: -18 },
          {
            y: 18,
            duration: 3.4,
            ease: "sine.inOut",
            repeat: -1,
            yoyo: true,
          },
        );
        // Start each logo at a fixed phase of the same wave; horizontal positions stay fixed.
        tween.totalTime(i * 0.65 + 0.4);
        animations.current.push(tween);
      });
    }, root);
    return () => {
      context.revert();
      animations.current = [];
    };
  }, [identities]);
  useLayoutEffect(() => {
    animations.current.forEach((animation) => animation.paused(paused));
  }, [paused, identities]);
  if (!apps.length) return null;
  return (
    <div ref={root} className="weekly-floating-apps" aria-hidden="true">
      {apps.map((app) => (
        <span
          className="weekly-floating-logo"
          key={app.key}
          data-app={app.key}
          style={{ "--app-color": app.color } as CSSProperties}
        >
          {app.logo ? (
            <span
              className="weekly-floating-mark"
              style={{ maskImage: `url("${app.logo}")` }}
            />
          ) : (
            <span className="weekly-floating-initials">{app.initials}</span>
          )}
        </span>
      ))}
    </div>
  );
}

"use client";

import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from "react";
import { useInView } from "motion/react";
import { gsap } from "gsap";

export const WeeklyMotionContext = createContext(false);
export const useWeeklyMotion = () => useContext(WeeklyMotionContext);

/** Keep the final value available to screen readers while the visual value settles. */
export function WeeklyNumber({
  value,
  digits = 0,
  suffix = "",
}: {
  value: number;
  digits?: number;
  suffix?: string;
}) {
  const paused = useWeeklyMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const visible = useInView(ref, { once: true });
  const readout = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    if (!readout.current || !visible || paused) return;
    const target = readout.current;
    const counter = { value: 0 };
    const tween = gsap.to(counter, {
      value,
      duration: 0.9,
      ease: "power3.out",
      onUpdate: () => {
        target.textContent = counter.value.toFixed(digits) + suffix;
      },
    });
    return () => {
      tween.kill();
      target.textContent = value.toFixed(digits) + suffix;
    };
  }, [value, digits, suffix, paused, visible]);
  return (
    <span ref={ref} aria-label={value.toFixed(digits) + suffix}>
      <span ref={readout} aria-hidden="true">
        {value.toFixed(digits) + suffix}
      </span>
    </span>
  );
}

export function WeeklyReveal({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const paused = useWeeklyMotion();
  const ref = useRef<HTMLDivElement>(null);
  const entered = useInView(ref, { once: true, amount: 0.06 });
  useLayoutEffect(() => {
    if (paused || !entered || !ref.current) return;
    const context = gsap.context(() => {
      gsap.from(ref.current, {
        autoAlpha: 0,
        y: 22,
        duration: 0.65,
        delay,
        ease: "power3.out",
      });
    }, ref);
    return () => context.revert();
  }, [entered, paused, delay]);
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

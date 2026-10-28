"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type HTMLAttributes,
} from "react";
import { gsap } from "gsap";
import { SplitText } from "gsap/SplitText";

import {
  motion,
  useInView,
  useReducedMotion,
  stagger,
  type HTMLMotionProps,
} from "motion/react";

gsap.registerPlugin(SplitText);

export const calmTransition = {
  duration: 0.6,
  ease: [0.22, 0.61, 0.36, 1] as const,
};

/** Retain disclosure targets; collapsed content cannot receive focus. */
export function Collapse({
  open,
  id,
  children,
}: {
  open: boolean;
  id: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      id={id}
      inert={!open}
      aria-hidden={!open}
      initial={false}
      animate={{
        height: open ? "auto" : 0,
        opacity: open ? 1 : 0,
        visibility: open ? "visible" : "hidden",
      }}
      transition={{
        ...calmTransition,
        duration: reduced ? 0 : 0.48,
        visibility: { duration: 0, delay: open || reduced ? 0 : 0.48 },
      }}
      style={{ overflow: "hidden" }}
    >
      {children}
    </motion.div>
  );
}

/** Only below-fold sections wait; initial HTML remains readable. */
export function RevealSection({
  paused = false,
  id,
  tabIndex,
  onFocusCapture,
  ...props
}: HTMLMotionProps<"section"> & { paused?: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const entered = useInView(ref, { once: true, margin: "0px 0px -8% 0px" });
  const reduced = useReducedMotion();
  const [waiting, setWaiting] = useState(false);
  useEffect(() => {
    setWaiting(
      !!ref.current && ref.current.getBoundingClientRect().top > innerHeight,
    );
  }, []);
  const [focused, setFocused] = useState(false);
  const visible = !waiting || entered || reduced || paused;
  return (
    <div
      className="section-snap-boundary"
      id={id}
      tabIndex={tabIndex}
      onFocusCapture={(event) => {
        setFocused(true);
        setWaiting(false);
        onFocusCapture?.(event);
      }}
    >
      <motion.section
        {...props}
        ref={ref}
        initial={false}
        animate={{ opacity: visible ? 1 : 0, y: visible ? 0 : 28 }}
        transition={{
          ...calmTransition,
          duration: reduced || paused || focused ? 0 : 1,
        }}
      />
    </div>
  );
}

/** Native button semantics and existing focus styles remain intact. */
export function ActionButton(props: HTMLMotionProps<"button">) {
  const reduced = useReducedMotion();
  const inactive =
    props.disabled ||
    props["aria-disabled"] === true ||
    props["aria-disabled"] === "true" ||
    props["aria-busy"] === true ||
    props["aria-busy"] === "true";
  return (
    <motion.button
      {...props}
      className={`${props.className || ""} motion-action`}
      animate={{ scale: 1 }}
      whileHover={reduced || inactive ? undefined : { scale: 1.035 }}
      whileTap={reduced || inactive ? undefined : { scale: 0.965 }}
      transition={{
        ...calmTransition,
        duration: reduced || inactive ? 0 : 0.26,
      }}
    />
  );
}

export const quietItem = {
  open: { opacity: 1, y: 0 },
  closed: { opacity: 0, y: 16 },
};
export const quietGroup = {
  open: { transition: { delayChildren: stagger(0.11) } },
  closed: { transition: { delayChildren: 0 } },
};

export function MetricGroup({
  children,
  paused,
}: {
  children: ReactNode;
  paused: boolean;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const entered = useInView(ref, { once: true, amount: 0.15 });
  const [waiting, setWaiting] = useState(false);
  useEffect(() => {
    setWaiting(
      !!ref.current && ref.current.getBoundingClientRect().top > innerHeight,
    );
  }, []);
  return (
    <motion.div
      ref={ref}
      className="ah-metric-grid"
      initial={false}
      animate={!waiting || entered || reduced || paused ? "open" : "closed"}
      variants={reduced || paused ? undefined : quietGroup}
    >
      {children}
    </motion.div>
  );
}

/** GSAP's masked line reveal, shared by Daily, Weekly, Connect Your Data and sign-in. */
export function RevealHeading({
  as: Heading = "h2",
  lines,
  children,
  paused = false,
  duration = 1.2,
  ...props
}: HTMLAttributes<HTMLHeadingElement> & {
  as?: "h1" | "h2" | "h3";
  lines?: ReactNode[];
  paused?: boolean;
  duration?: number;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  const entered = useInView(ref, { once: true, amount: 0.25 });
  const reduced = useReducedMotion();
  const finished = useRef(false);
  const animation = useRef<gsap.core.Tween | null>(null);
  useLayoutEffect(() => {
    if (paused || reduced) {
      finished.current = true;
      return;
    }
    if (!entered || finished.current || !ref.current) return;
    const heading = ref.current;
    const context = gsap.context(() => {
      const targets = heading.querySelectorAll(".headline-line");
      // Keep provider logos and their flex layout intact; GSAP animates that entire line.
      if (heading.querySelector(".media-heading-content")) {
        animation.current = gsap.from(targets, {
          opacity: 0,
          y: 24,
          duration,
          stagger: 0.12,
          ease: "power3.out",
          onComplete: () => {
            finished.current = true;
          },
        });
        return;
      }
      SplitText.create(targets, {
        type: "lines",
        mask: "lines",
        linesClass: "gsap-heading-line",
        autoSplit: true,
        aria: "none",
        onSplit(split) {
          animation.current = gsap.from(split.lines, {
            yPercent: 110,
            duration,
            stagger: 0.14,
            ease: "power3.out",
            onComplete: () => {
              finished.current = true;
              split.revert();
            },
          });
          return animation.current;
        },
      });
    }, heading);
    return () => {
      context.revert();
      animation.current = null;
    };
  }, [entered, paused, reduced, duration]);
  return (
    <Heading
      {...props}
      ref={ref}
      onFocusCapture={(event) => {
        finished.current = true;
        animation.current?.progress(1);
        props.onFocusCapture?.(event);
      }}
    >
      {(lines || [children]).map((line, i) => (
        <span key={i} className="headline-line">
          {line}
        </span>
      ))}
    </Heading>
  );
}

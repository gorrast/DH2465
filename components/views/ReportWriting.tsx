"use client";
/* Shown while a report is being written: a spinning ring and the steps it goes through, ticked off one by one. */
import { useEffect, useState } from "react";
import { Icon } from "../ui/Icon";

const STEPS = {
  daily: [
    "Reading last night’s sleep",
    "Lining it up with your calendar, music and phone",
    "Finding the links that hold up",
    "Writing your report",
  ],
  weekly: [
    "Gathering the week’s nights",
    "Comparing them with your usual",
    "Finding the links that hold up",
    "Writing your weekly report",
  ],
};
const STEP_MS = 1500; // the last step stays until the report arrives

export function ReportWriting({ kind }: { kind: "daily" | "weekly" }) {
  const steps = STEPS[kind];
  const [step, setStep] = useState(0);
  useEffect(() => {
    const timer = setInterval(
      () => setStep((s) => Math.min(s + 1, steps.length - 1)),
      STEP_MS,
    );
    return () => clearInterval(timer);
  }, [steps.length]);
  return (
    <div className="report-writing" role="status" aria-live="polite">
      <span className="report-writing-ring" aria-hidden="true">
        <span className="report-writing-core">
          <Icon name="brain" size={18} />
        </span>
      </span>
      <ol className="report-writing-steps">
        {steps.map((text, i) => (
          <li
            key={text}
            className={
              i < step ? "is-done" : i === step ? "is-current" : undefined
            }
            aria-hidden={i > step}
          >
            <Icon name={i < step ? "check" : "dot"} size={14} />
            {text}
          </li>
        ))}
      </ol>
    </div>
  );
}

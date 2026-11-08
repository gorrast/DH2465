"use client";
/* One-click entry to the shared demo account: /auth/demo signs the visitor in on the server and redirects to ``next``. */
import { useState } from "react";

export function DemoButton({
  className = "btn btn-primary",
  label = "Try the demo",
  next = "/daily",
}: {
  className?: string;
  label?: string;
  next?: string;
}) {
  const [pending, setPending] = useState(false);
  return (
    <a
      className={className}
      href={"/auth/demo?next=" + encodeURIComponent(next)}
      onClick={() => setPending(true)}
      aria-disabled={pending}
    >
      {pending ? <span className="spinner" /> : null}
      {label}
    </a>
  );
}

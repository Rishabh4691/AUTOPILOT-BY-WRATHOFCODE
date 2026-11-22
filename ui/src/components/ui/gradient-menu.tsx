import * as React from "react";
import { cn } from "../../lib/utils";

export interface GradientMenuItem {
  title: string;
  /** Shown under the title on hover. */
  value?: string;
  /** A short tag on the round button at rest, e.g. "EN". */
  badge?: string;
  icon: React.ReactNode;
  gradientFrom: string;
  gradientTo: string;
  onClick?: () => void;
  hint?: string;
}

/**
 * Round icon buttons that, on hover or keyboard focus, stretch into a pill filled with their own
 * gradient, swap the icon for the label, and glow underneath in the same colours.
 */
export function GradientMenu({
  items,
  className,
  align = "end",
}: {
  items: GradientMenuItem[];
  className?: string;
  align?: "start" | "end";
}) {
  return (
    <ul className={cn("flex flex-col gap-3", align === "end" ? "items-end" : "items-start", className)}>
      {items.map((item) => (
        <li key={item.title}>
          <button
            type="button"
            onClick={item.onClick}
            title={item.hint}
            aria-label={item.value ? `${item.title}: ${item.value}` : item.title}
            style={{ "--gradient-from": item.gradientFrom, "--gradient-to": item.gradientTo } as React.CSSProperties}
            className="group relative flex h-14 w-14 cursor-pointer items-center justify-center rounded-full bg-panel shadow-[0_10px_25px_rgba(0,0,0,0.12)] outline-none transition-[width] duration-500 ease-[cubic-bezier(.2,.9,.25,1)] hover:w-48 focus-visible:w-48 hover:shadow-none focus-visible:shadow-none"
          >
            {/* gradient fill */}
            <span className="absolute inset-0 rounded-full bg-[linear-gradient(45deg,var(--gradient-from),var(--gradient-to))] opacity-0 transition-opacity duration-500 group-hover:opacity-100 group-focus-visible:opacity-100" />
            {/* glow */}
            <span className="absolute inset-x-0 top-2.5 -z-10 h-full rounded-full bg-[linear-gradient(45deg,var(--gradient-from),var(--gradient-to))] opacity-0 blur-[15px] transition-opacity duration-500 group-hover:opacity-50 group-focus-visible:opacity-50" />
            {/* icon */}
            <span className="relative z-10 text-zinc-400 transition-all duration-500 group-hover:scale-0 group-focus-visible:scale-0 [&_svg]:size-6">
              {item.icon}
            </span>
            {/* label */}
            <span className="absolute z-10 flex scale-0 flex-col items-center leading-tight text-white transition-transform delay-0 duration-500 group-hover:scale-100 group-hover:delay-150 group-focus-visible:scale-100 group-focus-visible:delay-150">
              <span className="text-[12px] font-bold uppercase tracking-[0.12em] text-[#fff]">{item.title}</span>
              {item.value && <span className="text-[11px] font-medium text-[#fff]/85">{item.value}</span>}
            </span>
            {/* value badge at rest */}
            {item.badge && (
              <span
                aria-hidden="true"
                className="absolute -top-1 -right-1 z-10 rounded-full bg-[linear-gradient(45deg,var(--gradient-from),var(--gradient-to))] px-1.5 py-0.5 text-[9px] font-bold uppercase leading-none text-[#fff] shadow transition-opacity duration-300 group-hover:opacity-0 group-focus-visible:opacity-0"
              >
                {item.badge}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

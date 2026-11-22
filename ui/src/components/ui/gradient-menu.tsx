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
 * Gradient Menu (after minhxthanh's 21st.dev component): a row of round icon buttons. On hover or
 * keyboard focus a button stretches to a pill of its own gradient, the icon shrinks away, the title
 * grows in, and a blurred copy of the gradient glows underneath. Buttons are glass at rest.
 */
export function GradientMenu({ items, className }: { items: GradientMenuItem[]; className?: string }) {
  return (
    <ul className={cn("flex gap-3 sm:gap-6", className)}>
      {items.map((item) => (
        <li key={item.title}>
          <button
            type="button"
            onClick={item.onClick}
            title={item.hint}
            aria-label={item.value ? `${item.title}: ${item.value}` : item.title}
            style={{ "--gradient-from": item.gradientFrom, "--gradient-to": item.gradientTo } as React.CSSProperties}
            className="glass group relative flex h-[60px] w-[60px] cursor-pointer items-center justify-center rounded-full outline-none transition-all duration-500 hover:w-[180px] focus-visible:w-[180px]"
          >
            {/* Gradient background on hover */}
            <span className="absolute inset-0 rounded-full bg-[linear-gradient(45deg,var(--gradient-from),var(--gradient-to))] opacity-0 transition-all duration-500 group-hover:opacity-100 group-focus-visible:opacity-100" />
            {/* Blur glow */}
            <span className="absolute inset-x-0 top-[10px] -z-10 h-full rounded-full bg-[linear-gradient(45deg,var(--gradient-from),var(--gradient-to))] opacity-0 blur-[15px] transition-all duration-500 group-hover:opacity-50 group-focus-visible:opacity-50" />

            {/* Icon */}
            <span className="relative z-10 transition-all delay-0 duration-500 group-hover:scale-0 group-focus-visible:scale-0">
              <span className="text-zinc-400 [&_svg]:size-6">{item.icon}</span>
            </span>

            {/* Title (and current value) */}
            <span className="absolute z-10 flex scale-0 flex-col items-center leading-tight transition-all delay-150 duration-500 group-hover:scale-100 group-focus-visible:scale-100">
              <span className="text-sm uppercase tracking-wide text-[#fff]">{item.title}</span>
              {item.value && <span className="text-[11px] text-[#fff]/85">{item.value}</span>}
            </span>

            {/* Current value at rest */}
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

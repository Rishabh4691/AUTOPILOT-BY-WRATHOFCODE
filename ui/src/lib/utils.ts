/** Joins class names, skipping empty ones (shadcn's `cn`, without the merge step). */
export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

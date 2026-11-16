import { ExternalLink, RefreshCw, TriangleAlert } from "lucide-react";
import { adminErrorMessage } from "../../services/adminFormat.js";

// Small building blocks of the admin review page (Tailwind, sizes in rem).

export function Card({ title, action, children, className = "" }) {
  return (
    <section className={`rounded-[0.875rem] border border-gray-200 bg-white p-5 dark:border-line-dark dark:bg-surface-dark ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h3 className="text-[0.9375rem] font-bold">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const BADGE_TONES = {
  brand: "bg-brand-soft text-brand dark:bg-[#3a2117] dark:text-[#ff8a5c]",
  green: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  amber: "bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  red: "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  blue: "bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  gray: "bg-zinc-100 text-zinc-600 dark:bg-zinc-700/50 dark:text-zinc-300",
};

export function Badge({ tone = "gray", children, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-[0.125rem] text-[0.75rem] font-semibold ${BADGE_TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

const BUTTON_TONES = {
  primary: "bg-brand text-white hover:bg-brand-hover",
  secondary: "border border-gray-300 bg-white text-ink hover:bg-zinc-50 dark:border-line-dark dark:bg-[#232323] dark:text-white dark:hover:bg-[#2b2b2b]",
  danger: "bg-red-600 text-white hover:bg-red-700",
  // A destructive choice before it is confirmed: red, but lighter than the solid "danger"
  dangerOutline: "border border-red-300 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300 dark:hover:bg-red-500/20",
  // Undo: a light grey fill with a border, so it does not look like the white "Change to ..."
  // buttons beside it
  undo: "border border-gray-300 bg-zinc-100 text-gray-600 hover:bg-zinc-200 hover:text-ink dark:border-line-dark dark:bg-[#2a2a2a] dark:text-zinc-300 dark:hover:bg-[#333] dark:hover:text-white",
  ghost: "text-gray-500 hover:bg-zinc-100 hover:text-ink dark:text-muted-dark dark:hover:bg-[#2b2b2b] dark:hover:text-white",
};

export function ActionButton({ tone = "secondary", className = "", children, ...props }) {
  return (
    <button
      type="button"
      className={`inline-flex h-[2.375rem] cursor-pointer items-center justify-center gap-2 rounded-[0.625rem] px-4 text-[0.8125rem] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:size-[1rem] ${BUTTON_TONES[tone]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function TextInput({ className = "", ...props }) {
  return (
    <input
      className={`h-[2.375rem] w-full rounded-[0.625rem] border border-gray-300 bg-white px-3 text-[0.8125rem] outline-none focus:border-brand dark:border-line-dark dark:bg-[#232323] dark:text-white ${className}`}
      {...props}
    />
  );
}

export function ExternalLinkText({ href, children }) {
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-brand hover:underline">
      {children}
      <ExternalLink className="size-[0.875rem]" />
    </a>
  );
}

export function Loading({ text = "Loading…" }) {
  return <p className="p-8 text-[0.875rem] text-gray-500 dark:text-muted-dark">{text}</p>;
}

export function EmptyState({ title, text }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-10 text-center">
      <p className="text-[1rem] font-semibold">{title}</p>
      {text && <p className="max-w-[32rem] text-[0.875rem] text-gray-500 dark:text-muted-dark">{text}</p>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-center gap-3 rounded-[0.625rem] border border-red-200 bg-red-50 px-4 py-3 text-[0.8125rem] text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300">
      <TriangleAlert className="size-[1.125rem] shrink-0" />
      <span className="flex-1">{typeof error === "string" ? error : adminErrorMessage(error)}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="inline-flex cursor-pointer items-center gap-1 font-semibold hover:underline">
          <RefreshCw className="size-[0.875rem]" /> Try again
        </button>
      )}
    </div>
  );
}

export function Notice({ children }) {
  if (!children) return null;
  return (
    <div role="status" className="rounded-[0.625rem] border border-emerald-200 bg-emerald-50 px-4 py-3 text-[0.8125rem] text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-300">
      {children}
    </div>
  );
}

// A list on the left, the selected item on the right: the layout of every decision tab.
export function SplitView({ list, children }) {
  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-[26rem] shrink-0 flex-col border-r border-gray-200 bg-white dark:border-line-dark dark:bg-surface-dark">
        {list}
      </aside>
      <div className="min-w-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}

export function ListButton({ selected, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`block w-full cursor-pointer border-b border-l-[0.1875rem] border-b-gray-100 px-4 py-3 text-left transition-colors dark:border-b-line-dark ${
        selected
          ? "border-l-brand bg-brand-soft/70 dark:bg-[#2a1b16]"
          : "border-l-transparent hover:bg-zinc-50 dark:hover:bg-[#222]"
      }`}
    >
      {children}
    </button>
  );
}

export function Field({ label, children }) {
  return (
    <div>
      <dt className="text-[0.75rem] font-semibold text-gray-500 dark:text-muted-dark">{label}</dt>
      <dd className="mt-0.5 text-[0.875rem] break-words">{children ?? "—"}</dd>
    </div>
  );
}

export function FilterChip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`cursor-pointer whitespace-nowrap rounded-full border px-3 py-1 text-[0.75rem] font-semibold transition-colors ${
        active
          ? "border-brand bg-brand text-white"
          : "border-gray-300 text-gray-600 hover:border-brand hover:text-brand dark:border-line-dark dark:text-muted-dark"
      }`}
    >
      {children}
    </button>
  );
}

import { ExternalLink, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { adminErrorMessage } from "../../services/adminFormat.js";

// Small building blocks of the pipeline review pages. They wear the business-submissions pages'
// look (the admin-* classes in styles/admin.css, sizes in rem); the rest is Tailwind (rem).

// A box like the submissions overview's cards (the weekly chart): its title inside
export function Card({ title, action, children, className = "" }) {
  return (
    <section className={`admin-box ${className}`}>
      {(title || action) && (
        <div className="admin-box-title">
          {title && <h2>{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

// A box like a submission's sections: its title in a bar across the top
export function Section({ title, action, children, className = "" }) {
  return (
    <section className={`admin-box is-section ${className}`}>
      {(title || action) && (
        <div className="admin-box-head">
          {title && <h2>{title}</h2>}
          {action}
        </div>
      )}
      <div className="admin-box-body">{children}</div>
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

// The submissions pages' buttons: orange like Apply / Next, white like Review, grey like Reset,
// red like Reject, and solid red for a confirmed delete
const BUTTON_TONES = {
  primary: "admin-btn-primary",
  secondary: "admin-btn-outline",
  undo: "admin-btn-muted",
  dangerOutline: "admin-btn-reject",
  danger: "admin-btn-danger",
};

export function ActionButton({ tone = "secondary", className = "", children, ...props }) {
  return (
    <button type="button" className={`admin-btn ${BUTTON_TONES[tone]} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function TextInput({ className = "", ...props }) {
  return (
    <input
      className={`h-[2.5rem] w-full rounded-[0.625rem] border border-gray-300 bg-white px-3 text-[0.8125rem] outline-none focus:border-brand dark:border-line-dark dark:bg-[#232323] dark:text-white ${className}`}
      {...props}
    />
  );
}

// The one search box of the admin pages (pipeline and submissions): a white box with a magnifier
export function SearchBox({ className = "", ...props }) {
  return (
    <div className={`relative ${className}`}>
      <Search className="pointer-events-none absolute top-1/2 left-3 size-[1rem] -translate-y-1/2 text-gray-400" aria-hidden="true" />
      <TextInput className="pl-9" {...props} />
    </div>
  );
}

// Tabs like the submissions' Waiting / Approved / Rejected. tabs: [{ id, label, count? }]
export function Tabs({ label, tabs, active, onChange }) {
  return (
    <div className="admin-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab) => (
        <button
          key={tab.id} type="button" role="tab" aria-selected={active === tab.id}
          className={`admin-tab${active === tab.id ? " is-active" : ""}`} onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.count != null && <span className="admin-tab-count">{tab.count}</span>}
        </button>
      ))}
    </div>
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
  return <p className="p-6 text-[0.875rem] text-gray-500 dark:text-muted-dark">{text}</p>;
}

// fill: take the whole height (an empty page or an empty right side), centred
export function EmptyState({ title, text, fill = true }) {
  return (
    <div className={`admin-fill flex flex-col items-center justify-center gap-2 p-10 text-center ${fill ? "h-full" : ""}`}>
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

// A list on the left, the selected item on the right: the layout of every decision page, in one
// bordered box like the submissions table. list: the left side's parts (SplitTools, a ListScroll ...)
export function SplitView({ list, children }) {
  return (
    <div className="admin-split">
      <aside className="admin-split-list">{list}</aside>
      <div className="admin-split-detail">{children}</div>
    </div>
  );
}

export function ListScroll({ children }) {
  return <div className="admin-split-scroll">{children}</div>;
}

export function ListButton({ selected, onClick, children }) {
  return (
    <button type="button" onClick={onClick} className={`admin-list-row${selected ? " is-selected" : ""}`}>
      {children}
    </button>
  );
}

// A label and its value, like the items of a submission
export function Field({ label, children }) {
  return (
    <div>
      <dt className="admin-item-label">{label}</dt>
      <dd className="admin-item-value">{children ?? "—"}</dd>
    </div>
  );
}

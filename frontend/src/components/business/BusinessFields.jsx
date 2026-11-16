import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, Flag, Info, Upload, X } from "lucide-react";
import { fileError, formatFileSize, sectionId } from "../../services/businessForm";

const errorId = (id) => `${id}-error`;

// Rejected-review flags that are about the whole section rather than one field.
export function FlagNotes({ issues }) {
  if (!issues.length) return null;
  return (
    <div className="business-flag-notes" role="note">
      <p className="business-flag-title"><Flag aria-hidden="true" /> Needs fixing</p>
      {issues.map((issue) => (
        <p key={issue.label}><strong>{issue.label}:</strong> {issue.note}</p>
      ))}
    </div>
  );
}

export function FormSection({ title, flags = [], children }) {
  return (
    <section id={sectionId(title)} className={`business-section${flags.length ? " is-flagged" : ""}`}>
      <h2>{title}</h2>
      <FlagNotes issues={flags} />
      <div className="business-grid">{children}</div>
    </section>
  );
}

function FieldShell({ id, label, required, hint, error, wide, children, as = "div", labelFor = true }) {
  const Wrapper = as;
  const Label = labelFor ? "label" : "span";
  return (
    <Wrapper className={`business-field${wide ? " is-wide" : ""}`}>
      {label && (
        <Label className="business-label" {...(labelFor ? { htmlFor: id } : { id: `${id}-label` })}>
          {label}
          {required && <span className="business-required" aria-hidden="true">*</span>}
        </Label>
      )}
      {hint && <p className="business-hint">{hint}</p>}
      {children}
      {error && (
        <p id={errorId(id)} className="business-error" role="alert">
          {error}
        </p>
      )}
    </Wrapper>
  );
}

export function TextInput({ id, label, required, error, wide, readOnly, ...inputProps }) {
  return (
    <FieldShell id={id} label={label} required={required} error={error} wide={wide}>
      <input
        id={id}
        className={`business-input${error ? " has-error" : ""}`}
        aria-invalid={Boolean(error)}
        aria-required={required}
        aria-describedby={error ? errorId(id) : undefined}
        readOnly={readOnly}
        {...inputProps}
      />
    </FieldShell>
  );
}

export function TextArea({ id, label, required, error, wide, maxRows = 4, value, ...inputProps }) {
  const ref = useRef(null);

  useLayoutEffect(() => {
    const box = ref.current;
    if (!box) return;
    const style = getComputedStyle(box);
    const edges = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
    const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    const tallest = parseFloat(style.lineHeight) * maxRows + padding + edges;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight + edges, tallest)}px`;
  }, [value, maxRows]);

  return (
    <FieldShell id={id} label={label} required={required} error={error} wide={wide}>
      <textarea
        ref={ref}
        id={id}
        rows={1}
        value={value}
        className={`business-input business-textarea${error ? " has-error" : ""}`}
        aria-invalid={Boolean(error)}
        aria-required={required}
        aria-describedby={error ? errorId(id) : undefined}
        {...inputProps}
      />
    </FieldShell>
  );
}

export function PhoneInput({ id, label, required, error, wide, value, onChange, ...inputProps }) {
  return (
    <FieldShell id={id} label={label} required={required} error={error} wide={wide}>
      <div className={`business-input business-phone${error ? " has-error" : ""}`}>
        <span className="business-phone-prefix" aria-hidden="true">+60</span>
        <input
          id={id}
          type="tel"
          inputMode="tel"
          value={value}
          onChange={(event) => onChange(event.target.value.replace(/[^\d\s-]/g, ""))}
          aria-label={`${label}, after +60`}
          aria-invalid={Boolean(error)}
          aria-required={required}
          aria-describedby={error ? errorId(id) : undefined}
          {...inputProps}
        />
      </div>
    </FieldShell>
  );
}

export function Dropdown({ id, value, options, onChange, placeholder = "Select", error, labelledBy, ariaLabel, describedBy, required, className = "" }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const listRef = useRef(null);
  const listId = `${id}-listbox`;
  const optionId = (index) => `${id}-option-${index}`;
  const selected = options.findIndex((option) => option.value === value);

  const usable = (index) => Boolean(options[index]) && !options[index].disabled;
  // Returns start itself when no enabled option is found.
  const nearest = (start, step) => {
    for (let index = start; index >= 0 && index < options.length; index += step) if (usable(index)) return index;
    return start;
  };

  const show = (index = selected >= 0 ? selected : nearest(0, 1)) => {
    setActive(index);
    setOpen(true);
  };
  const hide = (refocus = true) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  };
  const choose = (index) => {
    if (!usable(index)) return;
    onChange(options[index].value);
    hide();
  };

  useEffect(() => {
    if (!open) return undefined;
    listRef.current?.focus({ preventScroll: true });
    const close = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (open && active >= 0) document.getElementById(optionId(active))?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- optionId only depends on id
  }, [open, active]);

  const onListKey = (event) => {
    const last = options.length - 1;
    const moves = {
      ArrowDown: nearest(Math.min(active + 1, last), 1),
      ArrowUp: nearest(Math.max(active - 1, 0), -1),
      Home: nearest(0, 1),
      End: nearest(last, -1),
    };
    if (event.key in moves) {
      event.preventDefault();
      setActive(moves[event.key]);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Escape") {
      event.preventDefault();
      hide();
    } else if (event.key === "Tab") {
      hide(false);
    } else if (event.key.length === 1 && /\S/.test(event.key)) {
      const letter = event.key.toLowerCase();
      const matches = (option, index) => usable(index) && option.label.toLowerCase().startsWith(letter);
      const after = options.findIndex((option, index) => index > active && matches(option, index));
      const next = after >= 0 ? after : options.findIndex(matches);
      if (next >= 0) setActive(next);
    }
  };

  return (
    <div className={`business-dropdown ${className}`} ref={rootRef}>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        className={`business-input business-dropdown-toggle${error ? " has-error" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-labelledby={labelledBy ? `${labelledBy} ${id}-value` : undefined}
        aria-label={labelledBy ? undefined : ariaLabel}
        aria-invalid={Boolean(error)}
        aria-required={required}
        aria-describedby={describedBy}
        onClick={() => (open ? hide() : show())}
        onKeyDown={(event) => {
          if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
            event.preventDefault();
            show();
          }
        }}
      >
        <span id={`${id}-value`} className={selected >= 0 ? "business-dropdown-value" : "business-dropdown-value is-placeholder"}>
          {selected >= 0 ? options[selected].label : placeholder}
        </span>
        <ChevronDown className="business-select-chevron" aria-hidden="true" />
      </button>
      {open && (
        <ul
          ref={listRef}
          id={listId}
          className="business-options"
          role="listbox"
          tabIndex={-1}
          aria-labelledby={labelledBy}
          aria-label={labelledBy ? undefined : ariaLabel}
          aria-activedescendant={active >= 0 ? optionId(active) : undefined}
          onKeyDown={onListKey}
        >
          {options.map((option, index) => (
            <li
              key={option.value}
              id={optionId(index)}
              role="option"
              aria-selected={option.value === value}
              aria-disabled={option.disabled || undefined}
              className={`business-option${index === active ? " is-active" : ""}${option.disabled ? " is-disabled" : ""}`}
              onMouseEnter={() => setActive(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
            >
              <span>{option.label}</span>
              {option.value === value && <Check aria-hidden="true" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SelectInput({ id, label, required, error, value, onChange, options, placeholder }) {
  return (
    <FieldShell id={id} label={label} required={required} error={error} labelFor={false}>
      <Dropdown
        id={id} value={value} options={options} onChange={onChange} placeholder={placeholder} error={error}
        required={required} labelledBy={`${id}-label`} describedBy={error ? errorId(id) : undefined}
      />
    </FieldShell>
  );
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

// Dates are "YYYY-MM-DD" strings built in local time, so no time zone shifts the day.
const toIso = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const fromIso = (iso) => {
  if (!iso) return null;
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
};
const addDays = (date, days) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
// Clamped to the month's last day: 31 Jan + 1 month = 28/29 Feb.
const addMonths = (date, months) => {
  const lastDay = new Date(date.getFullYear(), date.getMonth() + months + 1, 0).getDate();
  return new Date(date.getFullYear(), date.getMonth() + months, Math.min(date.getDate(), lastDay));
};
const formatDate = (date) => `${date.getDate()} ${MONTHS[date.getMonth()].slice(0, 3)} ${date.getFullYear()}`;

export function DateInput({ id, label, required, error, value, onChange, min }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState("days");
  const [focused, setFocused] = useState(() => new Date());
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const panelRef = useRef(null);
  const selected = fromIso(value);
  const minDate = fromIso(min);
  const todayIso = toIso(new Date());
  const tooEarly = (date) => Boolean(minDate) && date < minDate;
  const monthTooEarly = (year, month) => Boolean(minDate) && new Date(year, month + 1, 0) < minDate;

  const show = () => {
    const start = selected ?? new Date();
    setFocused(minDate && start < minDate ? minDate : start);
    setView("days");
    setOpen(true);
  };
  const hide = (refocus = true) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  };
  const choose = (date) => {
    if (tooEarly(date)) return;
    onChange(toIso(date));
    hide();
  };

  useEffect(() => {
    if (!open) return undefined;
    panelRef.current?.querySelector('[tabindex="0"]')?.focus({ preventScroll: true });
    const close = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, view, focused]);

  const onDayKey = (event) => {
    const weekday = (focused.getDay() + 6) % 7;
    const moves = {
      ArrowLeft: addDays(focused, -1),
      ArrowRight: addDays(focused, 1),
      ArrowUp: addDays(focused, -7),
      ArrowDown: addDays(focused, 7),
      PageUp: addMonths(focused, event.shiftKey ? -12 : -1),
      PageDown: addMonths(focused, event.shiftKey ? 12 : 1),
      Home: addDays(focused, -weekday),
      End: addDays(focused, 6 - weekday),
    };
    if (event.key in moves) {
      event.preventDefault();
      const next = moves[event.key];
      setFocused(tooEarly(next) ? minDate : next);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(focused);
    }
  };

  const onPanelKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (view === "years") setView("months");
      else if (view === "months") setView("days");
      else hide();
    } else if (event.key === "Tab") {
      hide(false);
    }
  };

  const year = focused.getFullYear();
  const month = focused.getMonth();
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => new Date(year, month, index + 1)),
  ];
  // 12 years per page, counted from the earliest allowed year.
  const minYear = minDate?.getFullYear();
  const yearStart = minDate ? minYear + 12 * Math.floor((year - minYear) / 12) : year - (year % 12);
  const years = Array.from({ length: 12 }, (_, index) => yearStart + index);
  const canGoBack = {
    days: !monthTooEarly(year, month - 1),
    months: !monthTooEarly(year - 1, 11),
    years: !minDate || yearStart > minYear,
  }[view];
  const step = (direction) => {
    const next = addMonths(focused, direction * { days: 1, months: 12, years: 144 }[view]);
    setFocused(tooEarly(next) ? minDate : next);
  };
  const unit = { days: "month", months: "year", years: "12 years" }[view];
  const title = { days: `${MONTHS[month]} ${year}`, months: year, years: `${yearStart} – ${yearStart + 11}` }[view];
  const nextView = { days: "months", months: "years", years: "days" }[view];
  const pickYear = (picked) => {
    const next = addMonths(focused, (picked - year) * 12);
    setFocused(tooEarly(next) ? minDate : next);
    setView("months");
  };

  return (
    <FieldShell id={id} label={label} required={required} error={error} labelFor={false}>
      <div className="business-date" ref={rootRef}>
        <button
          ref={buttonRef}
          id={id}
          type="button"
          className={`business-input business-dropdown-toggle business-date-toggle${error ? " has-error" : ""}`}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-labelledby={`${id}-label ${id}-value`}
          aria-invalid={Boolean(error)}
          aria-required={required}
          aria-describedby={error ? errorId(id) : undefined}
          onClick={() => (open ? hide() : show())}
          onKeyDown={(event) => {
            if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
              event.preventDefault();
              show();
            }
          }}
        >
          <CalendarDays className="business-date-icon" aria-hidden="true" />
          <span id={`${id}-value`} className={selected ? "business-dropdown-value" : "business-dropdown-value is-placeholder"}>
            {selected ? formatDate(selected) : "Select"}
          </span>
          <ChevronDown className="business-select-chevron" aria-hidden="true" />
        </button>
        {open && (
          <div ref={panelRef} className="business-calendar" role="dialog" aria-label={`Choose ${label?.toLowerCase() ?? "a date"}`} onKeyDown={onPanelKey}>
            <div className="business-calendar-head">
              <button type="button" className="business-calendar-nav" onClick={() => step(-1)} disabled={!canGoBack}
                aria-label={`Previous ${unit}`}>
                <ChevronLeft aria-hidden="true" />
              </button>
              <button type="button" className="business-calendar-title" aria-live="polite"
                aria-label={view === "years" ? `${title}, back to days` : `${title}, choose ${view === "days" ? "month" : "year"}`}
                onClick={() => setView(nextView)}>
                {title}
                <ChevronDown className={view === "days" ? "" : "is-flipped"} aria-hidden="true" />
              </button>
              <button type="button" className="business-calendar-nav" onClick={() => step(1)}
                aria-label={`Next ${unit}`}>
                <ChevronRight aria-hidden="true" />
              </button>
            </div>

            {view === "days" ? (
              <div className="business-calendar-days" role="grid" onKeyDown={onDayKey}>
                {WEEKDAYS.map((day) => (
                  <span key={day} className="business-calendar-weekday" aria-hidden="true">{day}</span>
                ))}
                {cells.map((date, index) => {
                  if (!date) return <span key={`blank-${index}`} aria-hidden="true" />;
                  const iso = toIso(date);
                  const isFocused = iso === toIso(focused);
                  const classes = ["business-calendar-day"];
                  if (iso === value) classes.push("is-selected");
                  if (iso === todayIso) classes.push("is-today");
                  return (
                    <button
                      key={iso}
                      type="button"
                      className={classes.join(" ")}
                      tabIndex={isFocused ? 0 : -1}
                      disabled={tooEarly(date)}
                      aria-pressed={iso === value}
                      aria-label={`${formatDate(date)}${iso === todayIso ? ", today" : ""}`}
                      onClick={() => choose(date)}
                    >
                      {date.getDate()}
                    </button>
                  );
                })}
              </div>
            ) : view === "years" ? (
              <div className="business-calendar-months">
                {years.map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`business-calendar-month${selected?.getFullYear() === option ? " is-selected" : ""}`}
                    tabIndex={option === year ? 0 : -1}
                    disabled={Boolean(minDate) && option < minYear}
                    onClick={() => pickYear(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
            ) : (
              <div className="business-calendar-months">
                {MONTHS.map((name, index) => {
                  const isCurrent = index === month;
                  const isSelected = selected && selected.getFullYear() === year && selected.getMonth() === index;
                  return (
                    <button
                      key={name}
                      type="button"
                      className={`business-calendar-month${isSelected ? " is-selected" : ""}`}
                      tabIndex={isCurrent ? 0 : -1}
                      disabled={monthTooEarly(year, index)}
                      onClick={() => {
                        const next = new Date(year, index, Math.min(focused.getDate(), new Date(year, index + 1, 0).getDate()));
                        setFocused(tooEarly(next) ? minDate : next);
                        setView("days");
                      }}
                    >
                      {name.slice(0, 3)}
                    </button>
                  );
                })}
              </div>
            )}

            <div className="business-calendar-foot">
              {value ? (
                <button type="button" className="business-calendar-link" onClick={() => { onChange(""); hide(); }}>Clear</button>
              ) : <span />}
              <button type="button" className="business-calendar-link" disabled={tooEarly(fromIso(todayIso))}
                onClick={() => choose(fromIso(todayIso))}>
                Today
              </button>
            </div>
          </div>
        )}
      </div>
    </FieldShell>
  );
}

export function FileUpload({ id, label, title, required, optional, hint, types, file, onChange, error, wide = true }) {
  const inputRef = useRef(null);
  const [pickError, setPickError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const shownError = pickError ?? error;

  const take = (picked) => {
    if (!picked) return;
    const problem = fileError(picked, types);
    setPickError(problem);
    if (!problem) onChange(picked);
  };

  return (
    <FieldShell id={id} label={label} required={required} error={shownError} wide={wide} labelFor={false}>
      <div
        className={`business-upload${file ? " has-file" : ""}${dragging ? " is-dragging" : ""}${shownError ? " has-error" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          take(event.dataTransfer.files?.[0]);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          className="business-upload-input"
          accept={types.join(",")}
          aria-label={label ?? title}
          tabIndex={-1}
          aria-describedby={shownError ? errorId(id) : undefined}
          onChange={(event) => {
            take(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        {file ? (
          <>
            <span className="business-upload-icon is-done" aria-hidden="true"><Check /></span>
            <span className="business-upload-text">
              <strong>{file.name}</strong>
              <small>{formatFileSize(file.size)} · uploaded</small>
            </span>
            <button
              id={id}
              type="button"
              className="business-upload-remove"
              onClick={() => {
                setPickError(null);
                onChange(null);
              }}
            >
              Remove
            </button>
          </>
        ) : (
          <button
            id={id}
            type="button"
            className="business-upload-pick"
            aria-describedby={shownError ? errorId(id) : undefined}
            onClick={() => inputRef.current?.click()}>
            <span className="business-upload-icon" aria-hidden="true"><Upload /></span>
            <span className="business-upload-text">
              <strong>
                {title}
                {required && <span className="business-required" aria-hidden="true">*</span>}
                {optional && <em> · Optional</em>}
              </strong>
              <small>{hint}</small>
            </span>
          </button>
        )}
      </div>
    </FieldShell>
  );
}

export function ChoiceGroup({ id, label, required, options, value, onChange, error, columns = 3 }) {
  const name = useId();
  return (
    <FieldShell id={id} label={label} required={required} error={error} wide as="fieldset" labelFor={false}>
      <div
        className="business-choices"
        style={{ "--choice-columns": columns }}
        role="radiogroup"
        aria-labelledby={`${id}-label`}
        aria-describedby={error ? errorId(id) : undefined}
      >
        {options.map((option, index) => (
          <label key={option.value} className={`business-choice${value === option.value ? " is-selected" : ""}`}>
            <input
              id={index === 0 ? id : undefined}
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            <span className="business-radio" aria-hidden="true" />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </FieldShell>
  );
}

export function MultiPicker({ id, label, hint, required, error, options, value, onChange, max, placeholder = "Select", wide = true }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const full = value.length >= max;

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const labelOf = (picked) => options.find((option) => option.value === picked)?.label ?? picked;
  const toggle = (picked) => {
    if (value.includes(picked)) onChange(value.filter((item) => item !== picked));
    else if (!full) onChange([...value, picked]);
  };

  return (
    <FieldShell id={id} label={label} hint={hint} required={required} error={error} wide={wide} labelFor={false}>
      <div className="business-multiselect" ref={rootRef}>
        <div className={`business-input business-chips${error ? " has-error" : ""}`}>
          {value.map((picked) => (
            <span key={picked} className="business-chip">
              {labelOf(picked)}
              <button type="button" aria-label={`Remove ${labelOf(picked)}`} onClick={() => toggle(picked)}>
                <X aria-hidden="true" />
              </button>
            </span>
          ))}
          <button
            id={id}
            type="button"
            className="business-chips-toggle"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-labelledby={`${id}-label`}
            aria-required={required}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId(id) : undefined}
            onClick={() => setOpen((previous) => !previous)}
          >
            {!value.length && <span className="business-chips-placeholder">{placeholder}</span>}
            <ChevronDown className="business-select-chevron" aria-hidden="true" />
          </button>
        </div>
        {open && (
          <ul className="business-options" role="listbox" aria-multiselectable="true" aria-labelledby={`${id}-label`}>
            {options.map((option) => {
              const selected = value.includes(option.value);
              const disabled = full && !selected;
              return (
                <li key={option.value} role="option" aria-selected={selected} aria-disabled={disabled}>
                  <button type="button" disabled={disabled} onClick={() => toggle(option.value)}>
                    <span>{option.label}</span>
                    {selected && <Check aria-hidden="true" />}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </FieldShell>
  );
}

export function FieldNote({ children }) {
  return (
    <p className="business-note">
      <Info aria-hidden="true" />
      {children}
    </p>
  );
}

export function Switch({ id, checked, onChange, label }) {
  return (
    <label className="business-switch">
      <input id={id} type="checkbox" role="switch" checked={checked} onChange={(event) => onChange(event.target.checked)} aria-label={label} />
      <span className="business-switch-track" aria-hidden="true"><span className="business-switch-thumb" /></span>
    </label>
  );
}

export function CheckboxGroups({ groups, value, onChange }) {
  const toggle = (item) => onChange(value.includes(item) ? value.filter((picked) => picked !== item) : [...value, item]);
  return (
    <div className="business-checkbox-groups">
      {groups.map((group) => (
        <fieldset key={group.title} className="business-checkbox-group">
          <legend>{group.title}</legend>
          {group.items.map((item) => (
            <label key={item.value} className="business-checkbox">
              <input type="checkbox" checked={value.includes(item.value)} onChange={() => toggle(item.value)} />
              <span className="business-checkbox-box" aria-hidden="true"><Check /></span>
              <span>{item.label}</span>
            </label>
          ))}
        </fieldset>
      ))}
    </div>
  );
}

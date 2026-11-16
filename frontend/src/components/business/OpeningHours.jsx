import { Copy, Plus, TimerReset, X } from "lucide-react";
import {
  DAYS, TIME_OPTIONS, addPeriod, canAddPeriod, copyMondayToAll, dayId, hoursConflicts, timeAllowed, isOpenAllWeek, removePeriod, setDayOpen, setPeriod,
  toggleOpenAllWeek,
} from "../../services/businessHours";
import { sectionId } from "../../services/businessForm";
import { Dropdown, FlagNotes, Switch } from "./BusinessFields";

function TimeSelect({ id, value, onChange, label, error, describedBy, allowed }) {
  const options = TIME_OPTIONS.map((time) => ({ value: time, label: time, disabled: !allowed(time) }));
  return (
    <Dropdown
      id={id} value={value} options={options} onChange={onChange} placeholder="--:--" error={error}
      ariaLabel={label} describedBy={describedBy} className="business-time"
    />
  );
}

function OpeningHours({ hours, onChange, errors = {}, flags = [] }) {
  const allWeek = isOpenAllWeek(hours);
  // Clashes show straight away; missing times wait for Next.
  const conflicts = hoursConflicts(hours);

  return (
    <section id={sectionId("Opening hours")} className={`business-section business-hours${flags.length ? " is-flagged" : ""}`} aria-labelledby="hours-title">
      <div className="business-hours-head">
        <h2 id="hours-title">Opening hours</h2>
        <div className="business-hours-actions">
          <button type="button" className="business-ghost-btn" aria-pressed={allWeek} onClick={() => onChange(toggleOpenAllWeek(hours))}>
            <TimerReset aria-hidden="true" />
            {allWeek ? "Set own hours" : "Open 24 hours"}
          </button>
          <button type="button" className="business-ghost-btn" onClick={() => onChange(copyMondayToAll(hours))}>
            <Copy aria-hidden="true" />
            Copy Monday to all
          </button>
        </div>
      </div>

      <FlagNotes issues={flags} />
      {errors.hours && <p id="hours-error" className="business-error business-hours-error" role="alert">{errors.hours}</p>}

      <div className="business-hours-days">
        {hours.map((day, index) => {
          const name = DAYS[index];
          const id = dayId(index);
          const error = conflicts[id] ?? errors[id];
          return (
            <div key={name} className="business-hours-day" role="group" aria-label={name}>
              <span className="business-hours-name">{name}</span>
              <Switch id={id} checked={day.open} onChange={(open) => onChange(setDayOpen(hours, index, open))} label={`Open on ${name}`} />
              <div className="business-hours-periods">
                {!day.open && <span className="business-hours-closed">closed</span>}
                {day.open && day.allDay && <span className="business-hours-closed is-open">Open 24 hours</span>}
                {day.open && !day.allDay && day.periods.map((period, at) => (
                  <div key={at} className="business-hours-period">
                    <TimeSelect
                      id={`${id}-${at}-from`}
                      allowed={(time) => timeAllowed(hours, index, at, "from", time)}
                      value={period.from}
                      error={error}
                      onChange={(value) => onChange(setPeriod(hours, index, at, "from", value))}
                      label={`${name} opening time${day.periods.length > 1 ? ` ${at + 1}` : ""}`}
                      describedBy={error ? `${id}-error` : undefined}
                    />
                    <span className="business-hours-to">to</span>
                    <TimeSelect
                      id={`${id}-${at}-to`}
                      allowed={(time) => timeAllowed(hours, index, at, "to", time)}
                      value={period.to}
                      error={error}
                      onChange={(value) => onChange(setPeriod(hours, index, at, "to", value))}
                      label={`${name} closing time${day.periods.length > 1 ? ` ${at + 1}` : ""}`}
                      describedBy={error ? `${id}-error` : undefined}
                    />
                    {at === 0 ? (
                      canAddPeriod(day) && (
                        <button type="button" className="business-hours-icon-btn" onClick={() => onChange(addPeriod(hours, index))} aria-label={`Add another opening period on ${name}`}>
                          <Plus aria-hidden="true" />
                        </button>
                      )
                    ) : (
                      <button type="button" className="business-hours-icon-btn is-remove" onClick={() => onChange(removePeriod(hours, index, at))} aria-label={`Remove this opening period on ${name}`}>
                        <X aria-hidden="true" />
                      </button>
                    )}
                  </div>
                ))}
                {error && <p id={`${id}-error`} className="business-error" role="alert">{error}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default OpeningHours;

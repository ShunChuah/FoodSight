export const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const MAX_PERIODS = 3;
export const TIME_OPTIONS = Array.from({ length: 96 }, (_, index) => {
  const pad = (number) => String(number).padStart(2, "0");
  return `${pad(Math.floor(index / 4))}:${pad((index % 4) * 15)}`;
});
const DEFAULT_PERIOD = { from: "08:00", to: "22:00" };

export const dayId = (index) => `hours-${DAYS[index].toLowerCase()}`;

export function defaultHours() {
  return DAYS.map((_, index) => ({ open: index < 6, allDay: false, periods: [{ ...DEFAULT_PERIOD }] }));
}

const withDay = (hours, index, change) => hours.map((day, at) => (at === index ? change(day) : day));

export function setDayOpen(hours, index, open) {
  return withDay(hours, index, (day) => ({ ...day, open, allDay: open && day.allDay }));
}

export function setPeriod(hours, index, period, field, value) {
  return withDay(hours, index, (day) => ({
    ...day,
    periods: day.periods.map((item, at) => (at === period ? { ...item, [field]: value } : item)),
  }));
}

const SLOT = 15;
const LAST_SLOT = 23 * 60 + 45;
const asTime = (total) => `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;

// Only after a complete period that closes the same day with time left.
export function canAddPeriod(day) {
  const last = day.periods.at(-1);
  return day.periods.length < MAX_PERIODS && Boolean(last?.from && last?.to) && !isOvernight(last) && minutes(last.to) < LAST_SLOT;
}

// The new period starts an hour after the last one closes, or as soon as there's room.
export function addPeriod(hours, index) {
  return withDay(hours, index, (day) => {
    if (!canAddPeriod(day)) return day;
    const close = minutes(day.periods.at(-1).to);
    const from = asTime(Math.min(close + 60, Math.max(close + SLOT, LAST_SLOT)));
    return { ...day, allDay: false, periods: [...day.periods, { from, to: "" }] };
  });
}

export function removePeriod(hours, index, period) {
  return withDay(hours, index, (day) => ({ ...day, periods: day.periods.filter((_, at) => at !== period) }));
}

export const isOpenAllWeek = (hours) => hours.every((day) => day.open && day.allDay);

// Toggling off restores each day's own times.
export function toggleOpenAllWeek(hours) {
  const allDay = !isOpenAllWeek(hours);
  return hours.map((day) => ({ ...day, open: allDay ? true : day.open, allDay }));
}

export function copyMondayToAll(hours) {
  const [monday] = hours;
  return hours.map(() => ({ ...monday, periods: monday.periods.map((period) => ({ ...period })) }));
}

function minutes(time) {
  const [hour, minute] = time.split(":").map(Number);
  return hour * 60 + minute;
}

// Closing earlier than opening means past midnight ("22:00" to "02:00"); it must be the day's last period.
const isOvernight = (period) => Boolean(period.from && period.to) && minutes(period.to) < minutes(period.from);
const nextDay = (index) => (index + 1) % DAYS.length;
const previousDay = (index) => (index + DAYS.length - 1) % DAYS.length;

// Latest close for a past-midnight period: when the next day opens, or null if it's closed or has no time yet.
function overnightLimit(hours, index) {
  const next = hours[nextDay(index)];
  if (!next.open) return null;
  if (next.allDay) return 0;
  const first = next.periods[0];
  return first?.from ? minutes(first.from) : null;
}

function carriedOver(hours, index) {
  const before = hours[previousDay(index)];
  if (!before.open || before.allDay) return null;
  const last = before.periods.at(-1);
  return last && isOvernight(last) ? minutes(last.to) : null;
}

const ORDER = "Each period has to start after the one before it closes.";
const MIDNIGHT_LAST = "Only the day's last period can run past midnight.";

// Clashes: same open/close time, overlap with neighbours, or a past-midnight period running into the next day.
// Empty times are left for the Next check.
function periodProblem(hours, index, at) {
  const { periods } = hours[index];
  const period = periods[at];
  const previous = periods[at - 1];
  const next = periods[at + 1];
  if (period.from && period.to && period.from === period.to) return "The closing time can't be the same as the opening time.";
  if (next && isOvernight(period)) return MIDNIGHT_LAST;
  if (previous && period.from) {
    if (isOvernight(previous)) return MIDNIGHT_LAST;
    if (previous.to ? minutes(period.from) < minutes(previous.to) : previous.from && minutes(period.from) <= minutes(previous.from)) return ORDER;
  }
  if (next?.from) {
    if (period.to && minutes(period.to) > minutes(next.from)) return ORDER;
    if (!period.to && period.from && minutes(period.from) >= minutes(next.from)) return ORDER;
  }
  if (at === 0 && period.from) {
    const carried = carriedOver(hours, index);
    if (carried !== null && minutes(period.from) < carried) return `This opens before ${DAYS[previousDay(index)]}'s late-night hours end.`;
  }
  if (!next && isOvernight(period)) {
    const limit = overnightLimit(hours, index);
    if (limit !== null && minutes(period.to) > limit) return `This runs past midnight into ${DAYS[nextDay(index)]}'s opening hours.`;
  }
  return null;
}

export function timeAllowed(hours, index, at, field, time) {
  return !periodProblem(setPeriod(hours, index, at, field, time), index, at);
}

// Clashes only, so they can show immediately instead of on Next.
export function hoursConflicts(hours) {
  const conflicts = {};
  hours.forEach((day, index) => {
    if (!day.open || day.allDay) return;
    const problem = day.periods.map((_, at) => periodProblem(hours, index, at)).find(Boolean);
    if (problem) conflicts[dayId(index)] = problem;
  });
  return conflicts;
}

// Keyed by day id, plus "hours" when no day is open.
export function hoursErrors(hours) {
  const errors = {};
  if (!hours.some((day) => day.open)) errors.hours = "Open on at least one day.";
  hours.forEach((day, index) => {
    if (!day.open || day.allDay) return;
    if (!day.periods.length) {
      errors[dayId(index)] = "Add the opening hours, or switch this day off.";
      return;
    }
    const missing = day.periods.some((period) => !period.from || !period.to);
    const problem = missing ? "Enter both the opening and closing time." : day.periods.map((_, at) => periodProblem(hours, index, at)).find(Boolean);
    if (problem) errors[dayId(index)] = problem;
  });
  return errors;
}

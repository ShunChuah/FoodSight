import { useEffect, useRef, useState } from "react";
import { formatDateTime, formatNumber, formatShare } from "../../services/adminFormat.js";

// One series, so no legend: the share of records that changed in each compared extraction,
// one column per extraction, with the scheduler's threshold as a dashed line (dashed means
// a threshold; the grid is solid). The column colour #ee5320 passes the palette checks on
// white and on the dark surface #181818. Only the newest column carries its value; the
// others are in the tooltip and in the list under the chart (its table view).

const BAR = "#ee5320";
const BAR_HOVER = "#ff6129";
const STEPS = [0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1];

function niceTop(points, threshold) {
  const top = Math.max(threshold * 1.6, ...points.map((p) => p.share * 1.15));
  const step = STEPS.find((s) => top / s <= 5) || 1;
  return { step, max: Math.ceil(top / step) * step };
}

// A column with a 4px rounded top and a square foot on the baseline
function columnPath(x, y, w, h, r) {
  const radius = Math.min(r, h, w / 2);
  return `M${x},${y + h} V${y + radius} Q${x},${y} ${x + radius},${y} H${x + w - radius} Q${x + w},${y} ${x + w},${y + radius} V${y + h} Z`;
}

function shortDay(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export default function ChangeShareChart({ points, threshold }) {
  const box = useRef(null);
  const [size, setSize] = useState({ width: 0, rem: 16 });
  const [hover, setHover] = useState(null);

  // Sizes follow the root font size (it scales with the window height) and the box width
  useEffect(() => {
    const node = box.current;
    if (!node) return undefined;
    const measure = () => setSize({
      width: node.clientWidth,
      rem: parseFloat(getComputedStyle(document.documentElement).fontSize) || 16,
    });
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const unit = size.rem / 16;
  const pad = { top: 20 * unit, right: 64 * unit, bottom: 28 * unit, left: 40 * unit };
  const height = 13 * size.rem;
  const plotWidth = Math.max(0, size.width - pad.left - pad.right);
  const plotHeight = height - pad.top - pad.bottom;
  const { step, max } = niceTop(points, threshold);
  const y = (share) => pad.top + plotHeight * (1 - share / max);
  const band = plotWidth / Math.max(points.length, 1);
  const barWidth = Math.min(24 * unit, band * 0.5);
  const every = Math.max(1, Math.ceil(points.length / Math.max(1, Math.floor(plotWidth / (56 * unit)))));
  const ticks = [];
  for (let value = 0; value <= max + 1e-9; value += step) ticks.push(value);
  const text = { fontSize: "0.6875rem" };
  const shown = hover != null ? points[hover] : null;

  return (
    <div ref={box} className="relative w-full" style={{ height }}>
      {size.width > 0 && (
        <svg width={size.width} height={height} role="img" aria-label={`Share of records changed per extraction; the ${formatShare(threshold)} line is the scheduler's rule`}>
          {ticks.map((value) => (
            <g key={value}>
              <line x1={pad.left} x2={pad.left + plotWidth} y1={y(value)} y2={y(value)} className="stroke-gray-200 dark:stroke-line-dark" strokeWidth={1} />
              <text x={pad.left - 6 * unit} y={y(value)} dy="0.32em" textAnchor="end" style={text} className="fill-gray-500 tabular-nums dark:fill-muted-dark">
                {formatShare(value).replace(".0%", "%")}
              </text>
            </g>
          ))}
          {points.map((point, index) => {
            const center = pad.left + band * (index + 0.5);
            const top = y(point.share);
            const active = hover === index;
            return (
              <g key={point.key}>
                {point.share > 0 && (
                  <path d={columnPath(center - barWidth / 2, top, barWidth, pad.top + plotHeight - top, 4 * unit)} fill={active ? BAR_HOVER : BAR} />
                )}
                {index === points.length - 1 && (
                  <text x={center} y={top - 6 * unit} textAnchor="middle" style={text} className="fill-ink font-semibold dark:fill-white">
                    {formatShare(point.share)}
                  </text>
                )}
                {index % every === 0 && (
                  <text x={center} y={pad.top + plotHeight + 16 * unit} textAnchor="middle" style={text} className="fill-gray-500 dark:fill-muted-dark">
                    {shortDay(point.when)}
                  </text>
                )}
              </g>
            );
          })}
          <line x1={pad.left} x2={pad.left + plotWidth} y1={y(threshold)} y2={y(threshold)} strokeDasharray="5 4" strokeWidth={1.5} className="stroke-gray-500 dark:stroke-muted-dark" />
          <text x={pad.left + plotWidth + 6 * unit} y={y(threshold)} dy="0.32em" style={text} className="fill-gray-600 dark:fill-muted-dark">
            {formatShare(threshold).replace(".0%", "%")} rule
          </text>
          {/* Hit areas: the whole column slot, bigger than the column; also reachable by keyboard */}
          {points.map((point, index) => (
            <rect
              key={point.key}
              x={pad.left + band * index}
              y={pad.top}
              width={band}
              height={plotHeight}
              fill="transparent"
              tabIndex={0}
              aria-label={`${shortDay(point.when)}: ${formatShare(point.share)} changed`}
              onPointerEnter={() => setHover(index)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(index)}
              onBlur={() => setHover(null)}
              className="cursor-default outline-none"
            />
          ))}
        </svg>
      )}
      {shown && (
        <div
          className="pointer-events-none absolute z-10 min-w-[11rem] -translate-x-1/2 -translate-y-full rounded-[0.5rem] border border-gray-200 bg-white px-3 py-2 text-[0.75rem] shadow-md dark:border-line-dark dark:bg-[#232323]"
          style={{ left: pad.left + band * (hover + 0.5), top: y(shown.share) - 10 * unit }}
        >
          <p className="text-[0.875rem] font-bold">{formatShare(shown.share)} changed</p>
          <p className="text-gray-500 dark:text-muted-dark">{formatNumber(shown.changes)} of {formatNumber(shown.records)} records</p>
          <p className="text-gray-500 dark:text-muted-dark">{formatDateTime(shown.when)}</p>
          {shown.decision?.interval_after != null && (
            <p className="mt-1">Next interval: {shown.decision.interval_before ?? "—"} → {shown.decision.interval_after} days</p>
          )}
        </div>
      )}
    </div>
  );
}

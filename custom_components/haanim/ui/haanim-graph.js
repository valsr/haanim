/**
 * HAAnim graphs: pure functions that turn a graph block and its data into an SVG string.
 *
 * A graph block either names entities, whose recorded history the card fetches and hands in, or carries
 * series of the automation's own. Both are drawn here. Numbers are drawn as lines, areas or bars against a
 * value axis with round numbers on it; states that are not numbers (on, off, heat, ...) are drawn as a
 * timeline, one row per series, coloured by state. A legend shows the latest value of every series. Nothing
 * touches the DOM.
 */

import { escapeHtml, isActive } from './haanim-render.js';

/** The colours of the series, in order. A theme can replace each one with `--haanim-graph-color-<n>`. */
export const GRAPH_COLORS = ['#03a9f4', '#ff9800', '#4caf50', '#e91e63', '#9c27b0', '#795548', '#009688', '#607d8b'];

const WIDTH = 400;
const LEFT = 44;
const RIGHT = 8;
const TOP = 8;
const BOTTOM = 22;
const PLOT_HEIGHT = 150;
const ROW_PITCH = 30;
const ROW_LABEL = 10;
const ROW_BAR_TOP = 14;
const ROW_BAR_HEIGHT = 12;

/** States that say nothing about what the entity was doing: a timeline has a gap there. */
const NO_STATE = new Set(['unavailable', 'unknown', '']);

function finite(value) {
    return typeof value === 'number' && Number.isFinite(value);
}

/** The number a state stands for, or null if it is not a number (`unavailable`, `on`, ...). */
export function numericState(state) {
    if (state === null || state === undefined || String(state).trim() === '') return null;
    const value = Number(state);
    return Number.isFinite(value) ? value : null;
}

/** Format a value for an axis or the legend: at most two decimals, without trailing zeros. */
export function formatValue(value) {
    if (!finite(value)) return '';
    const rounded = Math.abs(value) >= 1000 ? Math.round(value) : Math.round(value * 100) / 100;
    return String(rounded);
}

function colorOf(index) {
    const fallback = GRAPH_COLORS[index % GRAPH_COLORS.length];
    return `var(--haanim-graph-color-${(index % GRAPH_COLORS.length) + 1}, ${fallback})`;
}

/**
 * Turn the history Home Assistant returns for an entity into points.
 *
 * `rows` are the compressed states of `history/history_during_period`: `s` is the state and `lu` the time
 * it was last updated, in seconds. Returns `[[milliseconds, state as text], ...]` in order of time.
 */
export function historyPoints(rows) {
    return (rows || [])
        .map((row) => [Math.round(Number(row.lu) * 1000), row.s === null || row.s === undefined ? '' : String(row.s)])
        .filter((point) => Number.isFinite(point[0]))
        .sort((a, b) => a[0] - b[0]);
}

/**
 * Decide how a series is drawn, and bring its values into that form.
 *
 * A series with at least one number is numeric: what is not a number in it becomes a gap. A series with
 * states only is a timeline: `unavailable`, `unknown` and nothing become gaps. Returns `{text, points}`.
 */
export function classify(points) {
    const numeric = points.some((point) => (typeof point[1] === 'number' ? finite(point[1]) : numericState(point[1]) !== null));
    if (numeric) {
        return { text: false, points: points.map((point) => [point[0], typeof point[1] === 'number' ? point[1] : numericState(point[1])]) };
    }
    const states = points.map((point) => {
        const state = typeof point[1] === 'string' ? point[1] : '';
        return [point[0], NO_STATE.has(state.toLowerCase()) ? null : state];
    });
    return { text: states.some((point) => point[1] !== null), points: states };
}

/**
 * Bring together what a graph draws.
 *
 * Returns `{series, domain, time, step}`: `series` is a list of `{name, points, text}`, with the horizontal
 * positions of time graphs in milliseconds and `text` saying whether the series is a timeline of states;
 * `domain` is the range of the horizontal axis; `time` says whether that axis is time; `step` whether a value
 * holds until the next one (entity history) or the points are joined by straight lines.
 *
 * `context` has `history` (points per entity for the block, by block ID), `states` and `now` (milliseconds).
 */
export function graphData(block, context = {}) {
    const now = finite(context.now) ? context.now : Date.now();
    if (block.entities) {
        const start = now - Number(block.hours || 24) * 3600000;
        const history = ((context.history || {})[block.id] || {}).points || {};
        const series = block.entities.map((entityId) => {
            const state = (context.states || {})[entityId];
            const name = (state && state.attributes && state.attributes.friendly_name) || entityId;
            let points = (history[entityId] || []).filter((point) => point[0] <= now);
            // What was recorded before the window began still holds at its start
            const before = points.filter((point) => point[0] < start);
            points = points.filter((point) => point[0] >= start);
            if (before.length) points.unshift([start, before[before.length - 1][1]]);
            // The latest value holds until now
            if (points.length) points.push([now, points[points.length - 1][1]]);
            return { name, ...classify(points) };
        });
        return { series, domain: [start, now], time: true, step: true };
    }
    const time = block.x === 'time';
    const series = Object.entries(block.series || {}).map(([name, points]) => ({
        name,
        ...classify((points || []).map((point) => [time ? point[0] * 1000 : point[0], point[1]])),
    }));
    const positions = series.flatMap((one) => one.points.map((point) => point[0])).filter(finite);
    const low = positions.length ? Math.min(...positions) : 0;
    let high = positions.length ? Math.max(...positions) : 1;
    // States given one after the other each take a slot of their own, the last one too
    if (block.x === 'index' && series.some((one) => one.text)) high += 1;
    return { series, domain: [low, high], time, step: false };
}

/** A round step for an axis: 1, 2, 2.5 or 5 times a power of ten, for about `count` steps over `range`. */
export function niceStep(range, count = 4) {
    if (!(range > 0) || !Number.isFinite(range)) return 1;
    const rough = range / count;
    const magnitude = 10 ** Math.floor(Math.log10(rough));
    const fraction = rough / magnitude;
    let factor = 10;
    if (fraction <= 1) factor = 1;
    else if (fraction <= 2) factor = 2;
    else if (fraction <= 2.5) factor = 2.5;
    else if (fraction <= 5) factor = 5;
    return factor * magnitude;
}

/**
 * The value axis: its range and the round numbers marked on it.
 *
 * The range is what the block asks for (`min`, `max`); an end it leaves open is the next round number
 * beyond the data. Bars always include zero. A range of no height is widened. Returns `{low, high, ticks}`.
 */
export function valueAxis(block, values, bars = false) {
    const fixedLow = finite(block.min);
    const fixedHigh = finite(block.max);
    let low = fixedLow ? block.min : Math.min(...values);
    let high = fixedHigh ? block.max : Math.max(...values);
    if (bars && !fixedLow) low = Math.min(low, 0);
    if (bars && !fixedHigh) high = Math.max(high, 0);
    if (high <= low) {
        const pad = Math.abs(low) > 0 ? Math.abs(low) * 0.1 : 1;
        if (!fixedLow) low -= pad;
        if (!fixedHigh || high <= low) high = low + 2 * pad;
    }
    const step = niceStep(high - low);
    const decimals = Math.max(0, Math.ceil(-Math.log10(step)) + (String(step / 10 ** Math.floor(Math.log10(step))).includes('.') ? 1 : 0));
    const snap = (value) => Number(value.toFixed(Math.min(decimals + 2, 12)));
    if (!fixedLow) low = snap(Math.floor(low / step + 1e-9) * step);
    if (!fixedHigh) high = snap(Math.ceil(high / step - 1e-9) * step);
    const ticks = [];
    for (let tick = Math.ceil(low / step - 1e-9) * step; tick <= high + step * 1e-9; tick += step) {
        ticks.push(snap(tick));
    }
    return { low, high, ticks };
}

function round(value) {
    return Math.round(value * 10) / 10;
}

/** The path of one series as a line: broken where a value is missing, stepped if values hold. */
function linePath(points, toX, toY, step) {
    let path = '';
    let drawing = false;
    let lastY = 0;
    for (const [position, value] of points) {
        if (!finite(position)) continue;
        if (!finite(value)) {
            // A value that holds, holds until the moment it is no longer known
            if (drawing && step) path += `H${round(toX(position))}`;
            drawing = false;
            continue;
        }
        const x = round(toX(position));
        const y = round(toY(value));
        if (!drawing) {
            // "h0" makes a point that stands alone visible: a line of no length with round ends is a dot
            path += `M${x} ${y}h0`;
        } else if (step) {
            path += `H${x}${y === lastY ? '' : `V${y}`}`;
        } else {
            path += `L${x} ${y}`;
        }
        drawing = true;
        lastY = y;
    }
    return path;
}

/** The same line closed down to the baseline, one closed shape per unbroken run. */
function areaPath(points, toX, toY, step, baseline) {
    const runs = [];
    let run = [];
    for (const point of points) {
        if (finite(point[1]) && finite(point[0])) {
            run.push(point);
        } else if (run.length) {
            runs.push(run);
            run = [];
        }
    }
    if (run.length) runs.push(run);
    return runs
        .map((one) => {
            const first = round(toX(one[0][0]));
            return `${linePath(one, toX, toY, step)}V${round(baseline)}H${first}Z`;
        })
        .join('');
}

const MINUTE = 60000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** The steps a time axis is marked in: from fifteen seconds to thirty days. */
const TIME_STEPS = [
    15000, 30000, MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE,
    HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY,
];

const MAX_MAJOR_TICKS = 12;
const MAX_MINOR_TICKS = 80;

/** How many bands a graph is divided into for hovering, at most. */
const MAX_HOVER_BANDS = 60;

/** A position on a time axis as text: a time of day, or a date if the marks are days apart. */
function formatTimeMark(position, step) {
    const date = new Date(position);
    if (Number.isNaN(date.getTime())) return '';
    if (step >= DAY) return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    const seconds = step < MINUTE ? { second: '2-digit' } : {};
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false, ...seconds });
}

/** A moment as text for the hover readout: the time of day, with the date if the graph spans more than a day. */
function formatMoment(position, span) {
    const date = new Date(position);
    if (Number.isNaN(date.getTime())) return '';
    const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    return span > DAY ? `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}` : time;
}

/** Every multiple of `step` in a range, counted from `origin`. */
function multiples(from, to, step, origin = 0) {
    const marks = [];
    const first = Math.ceil((from - origin) / step - 1e-9);
    for (let count = first; origin + count * step <= to + step * 1e-9; count += 1) {
        marks.push(origin + count * step);
        if (marks.length > 1000) break;
    }
    return marks;
}

/**
 * The marks of the horizontal axis: major ones, which are labelled, and minor ones between them.
 *
 * `domain` is the range of the axis and `kind` what runs along it: `time` (milliseconds), `number` or
 * `index`. `major` and `minor` are the distances the automation asked for, in the units of the axis (seconds
 * for time); without them, or if they would give too many marks, round distances are chosen: for time the
 * usual clock steps, on the local clock, so that marks fall on full hours and days; for numbers 1, 2, 2.5 or
 * 5 times a power of ten; for an index whole numbers only. Returns `{major, minor, step}`, where `step` is
 * the distance between major marks.
 */
export function axisTicks(domain, kind, major = null, minor = null) {
    const [from, to] = domain;
    const span = to - from;
    if (!(span > 0) || !finite(span)) return { major: [], minor: [], step: 0 };
    const time = kind === 'time';
    const scale = time ? 1000 : 1;
    // Local time is what a person reads off the axis: shift the origin so marks fall on local hours and days
    const origin = time ? new Date(from).getTimezoneOffset() * MINUTE : 0;

    let step = finite(major) && major > 0 ? major * scale : 0;
    if (!step || span / step > MAX_MAJOR_TICKS) {
        if (time) {
            step = TIME_STEPS.find((candidate) => span / candidate <= 6) || TIME_STEPS[TIME_STEPS.length - 1];
        } else {
            step = niceStep(span, 5);
            if (kind === 'index') step = Math.max(1, Math.ceil(step));
        }
    }

    let small = finite(minor) && minor > 0 ? minor * scale : 0;
    if (!small || small >= step || span / small > MAX_MINOR_TICKS) {
        if (time) {
            small = TIME_STEPS.find((candidate) => candidate < step && step % candidate === 0 && step / candidate <= 7) || 0;
        } else if (kind === 'index') {
            small = step > 1 ? (step % 5 === 0 ? step / 5 : 1) : 0;
        } else {
            small = step / 5;
        }
    }

    const marks = multiples(from, to, step, origin);
    const between = small
        ? multiples(from, to, small, origin).filter((mark) => !marks.some((one) => Math.abs(one - mark) < small / 1000))
        : [];
    return { major: marks, minor: between, step };
}

function formatPosition(position, data, step) {
    return data.time ? formatTimeMark(position, step) : formatValue(position);
}

/** Draw the marks of the horizontal axis below the content: short lines, and a label under each major one. */
function renderAxis(ticks, data, toX, bottom) {
    const minor = ticks.minor
        .map((mark) => {
            const x = round(toX(mark));
            return `<line class="tick-minor" x1="${x}" x2="${x}" y1="${bottom}" y2="${bottom + 3}"/>`;
        })
        .join('');
    const major = ticks.major
        .map((mark) => {
            const x = round(toX(mark));
            // Labels at the ends of the axis stay inside the graph
            let anchor = 'middle';
            if (x < LEFT + 16) anchor = 'start';
            else if (x > WIDTH - RIGHT - 16) anchor = 'end';
            return (
                `<line class="tick-major" x1="${x}" x2="${x}" y1="${bottom}" y2="${bottom + 5}"/>` +
                `<text class="tick" x="${x}" y="${bottom + 16}" text-anchor="${anchor}">` +
                `${escapeHtml(formatPosition(mark, data, ticks.step))}</text>`
            );
        })
        .join('');
    return `<line class="axis" x1="${LEFT}" x2="${WIDTH - RIGHT}" y1="${bottom}" y2="${bottom}"/>${minor}${major}`;
}

/** The value of a series at a position: the one that holds there, or the point at or nearest to it. */
function valueAt(one, position, holds) {
    let found = null;
    let distance = Infinity;
    for (const point of one.points) {
        if (!finite(point[0])) continue;
        if (holds) {
            if (point[0] <= position) found = point;
        } else if (Math.abs(point[0] - position) < distance) {
            distance = Math.abs(point[0] - position);
            found = point;
        }
    }
    return found ? found[1] : null;
}

/**
 * The bands a graph is divided into for hovering.
 *
 * A band belongs to one position: a position where a series has a point, or, if there are too many of
 * those, one of evenly spread positions. Returns the positions in order.
 */
export function hoverPositions(data) {
    const [from, to] = data.domain;
    const all = data.series.flatMap((one) => one.points.map((point) => point[0])).filter((position) => finite(position) && position >= from && position <= to);
    const distinct = [...new Set(all)].sort((a, b) => a - b);
    if (distinct.length <= MAX_HOVER_BANDS) return distinct;
    return Array.from({ length: MAX_HOVER_BANDS }, (_, index) => from + ((index + 0.5) / MAX_HOVER_BANDS) * (to - from));
}

/**
 * Draw what hovering shows: for each band an invisible area to hover over, a line at its position, a dot on
 * each line of the graph, and a box that names the position and the value of every series there.
 *
 * All of it is in the SVG from the start and shown by CSS while the pointer is over the band, so reading a
 * value needs no script.
 */
function renderHover(data, layout, unit) {
    const { toX, toY, top, bottom, low, high } = layout;
    const positions = hoverPositions(data);
    const span = data.domain[1] - data.domain[0];
    const suffix = unit ? ` ${unit}` : '';
    return positions
        .map((position, index) => {
            const x = toX(position);
            const left = index === 0 ? LEFT : (toX(positions[index - 1]) + x) / 2;
            const right = index === positions.length - 1 ? WIDTH - RIGHT : (x + toX(positions[index + 1])) / 2;
            const lines = [data.time ? formatMoment(position, span) : formatValue(position)];
            let dots = '';
            data.series.forEach((one, place) => {
                const value = valueAt(one, position, data.step || one.text);
                if (one.text) {
                    lines.push(`${one.name}: ${value === null ? '–' : value}`);
                } else {
                    lines.push(`${one.name}: ${finite(value) ? `${formatValue(value)}${suffix}` : '–'}`);
                    if (finite(value) && toY && value >= low && value <= high) {
                        dots += `<circle class="dot" cx="${round(x)}" cy="${round(toY(value))}" r="3" style="fill: ${colorOf(place)}"/>`;
                    }
                }
            });
            const width = Math.min(Math.max(...lines.map((line) => line.length)) * 5.4 + 14, WIDTH - LEFT - RIGHT);
            const height = lines.length * 12 + 8;
            const boxX = round(x < (LEFT + WIDTH - RIGHT) / 2 ? Math.min(x + 8, WIDTH - RIGHT - width) : Math.max(x - 8 - width, LEFT));
            const text = lines
                .map((line, row) => `<tspan x="${boxX + 7}" dy="${row === 0 ? 0 : 12}"${row === 0 ? ' class="readout-title"' : ''}>${escapeHtml(line)}</tspan>`)
                .join('');
            return (
                '<g class="hover">' +
                `<rect class="hit" x="${round(left)}" y="${top}" width="${round(Math.max(right - left, 1))}" height="${round(bottom - top)}"/>` +
                `<line class="guide" x1="${round(x)}" x2="${round(x)}" y1="${top}" y2="${bottom}"/>${dots}` +
                `<g class="readout"><rect x="${boxX}" y="${top + 2}" width="${round(width)}" height="${height}" rx="4"/>` +
                `<text x="${boxX + 7}" y="${top + 15}">${text}</text></g></g>`
            );
        })
        .join('');
}

/**
 * Give every state of the timelines a colour.
 *
 * States in which an entity is doing nothing (off, closed, idle, ...) share one muted colour; every other
 * state gets the next colour of the series colours, in the order the states first appear, so a state has
 * the same colour in every row. `first` is the number of series colours already taken by the lines of the
 * graph, so a state does not look like one of them. Returns a map from state to CSS colour.
 */
export function stateColors(rows, first = 0) {
    const colors = new Map();
    let next = first;
    for (const row of rows) {
        for (const point of row.points) {
            const state = point[1];
            if (state === null || colors.has(state)) continue;
            if (isActive({ state })) {
                colors.set(state, colorOf(next));
                next += 1;
            } else {
                colors.set(state, 'var(--haanim-graph-inactive, #bdbdbd)');
            }
        }
    }
    return colors;
}

/** One row of a timeline: the name of the series, and a bar of segments coloured by state. */
function timelineRow(row, top, toX, end, colors) {
    let segments = '';
    for (let index = 0; index < row.points.length; index += 1) {
        const [position, state] = row.points[index];
        const next = index + 1 < row.points.length ? row.points[index + 1][0] : end;
        if (state === null || !finite(position) || !(next > position)) continue;
        const x = round(toX(position));
        const width = round(Math.max(toX(next) - toX(position), 0.5));
        segments +=
            `<rect class="segment" x="${x}" y="${top + ROW_BAR_TOP}" width="${width}" height="${ROW_BAR_HEIGHT}"` +
            ` style="fill: ${colors.get(state)}"><title>${escapeHtml(state)}</title></rect>`;
    }
    return `<text class="row-label" x="${LEFT}" y="${top + ROW_LABEL}">${escapeHtml(row.name)}</text>${segments}`;
}

/**
 * Render a graph block as HTML: an optional title, the SVG, and a legend with the latest values.
 *
 * Series of numbers share the plot at the top; series of states each get a row of a timeline below it. The
 * horizontal axis has major marks with labels and minor marks between them. Hovering over the graph shows
 * the values of all series at that position.
 * `context` has `history` (the fetched history per graph block), `states` and `now`.
 */
export function renderGraph(block, context = {}) {
    const data = graphData(block, context);
    const title = block.title ? `<div class="graph-title">${escapeHtml(block.title)}</div>` : '';
    const state = block.entities ? (context.states || {})[block.entities[0]] : null;
    const unit = block.unit ?? ((state && state.attributes && state.attributes.unit_of_measurement) || '');
    const fetched = block.entities ? (context.history || {})[block.id] : null;
    const failure = fetched ? fetched.error : null;
    const lines = data.series.filter((one) => !one.text);
    const rows = data.series.filter((one) => one.text);
    const values = lines.flatMap((one) => one.points.map((point) => point[1])).filter(finite);

    if (failure || (values.length === 0 && rows.length === 0)) {
        const loading = block.entities && !(fetched && fetched.loaded);
        const text = failure ? `History is not available: ${failure}` : loading ? 'Loading history…' : 'No data';
        return `${title}<div class="graph-empty">${escapeHtml(text)}</div>`;
    }

    const [from, to] = data.domain;
    const span = to - from;
    const plotWidth = WIDTH - LEFT - RIGHT;
    const linear = (position) => (span > 0 ? LEFT + ((position - from) / span) * plotWidth : LEFT);
    const layout = { toX: linear, toY: null, top: TOP, bottom: TOP, low: 0, high: 0 };
    let shapes = '';
    let bottom = TOP;

    if (values.length) {
        const bars = block.kind === 'bar';
        const axis = valueAxis(block, values, bars);
        const { low, high } = axis;
        const longest = Math.max(...lines.map((one) => one.points.length));
        // Bars need half a slot of room at both ends of the axis
        const slot = bars ? plotWidth / Math.max(longest, 1) : 0;
        const toX = (position) =>
            span > 0 ? LEFT + slot / 2 + ((position - from) / span) * (plotWidth - slot) : LEFT + plotWidth / 2;
        const toY = (value) => TOP + (1 - (Math.min(Math.max(value, low), high) - low) / (high - low)) * PLOT_HEIGHT;
        const baseline = toY(Math.min(Math.max(0, low), high));

        shapes += axis.ticks
            .map((value) => {
                const y = round(toY(value));
                return (
                    `<line class="grid" x1="${LEFT}" x2="${WIDTH - RIGHT}" y1="${y}" y2="${y}"/>` +
                    `<text class="tick" x="${LEFT - 6}" y="${y + 4}" text-anchor="end">${formatValue(value)}</text>`
                );
            })
            .join('');
        shapes += lines
            .map((one) => {
                const color = colorOf(data.series.indexOf(one));
                if (bars) {
                    const width = Math.max((slot * 0.8) / lines.length, 1);
                    const place = lines.indexOf(one);
                    return one.points
                        .filter((point) => finite(point[1]) && finite(point[0]))
                        .map((point) => {
                            const x = round(toX(point[0]) - (slot * 0.8) / 2 + place * width);
                            const y = toY(point[1]);
                            const top = round(Math.min(y, baseline));
                            const height = round(Math.max(Math.abs(y - baseline), 0.5));
                            return `<rect class="bar" x="${x}" y="${top}" width="${round(width)}" height="${height}" style="fill: ${color}"/>`;
                        })
                        .join('');
                }
                const line = `<path class="line" d="${linePath(one.points, toX, toY, data.step)}" style="stroke: ${color}"/>`;
                if (block.kind !== 'area') return line;
                return `<path class="area" d="${areaPath(one.points, toX, toY, data.step, baseline)}" style="fill: ${color}"/>${line}`;
            })
            .join('');
        bottom = TOP + PLOT_HEIGHT;
        Object.assign(layout, { toX, toY, low, high });
    }

    const colors = stateColors(rows, lines.filter((one) => one.points.some((point) => finite(point[1]))).length);
    if (rows.length) {
        let top = values.length ? bottom + 6 : TOP;
        for (const row of rows) {
            shapes += timelineRow(row, top, linear, to, colors);
            top += ROW_PITCH;
        }
        bottom = top - (ROW_PITCH - ROW_BAR_TOP - ROW_BAR_HEIGHT);
    }

    layout.bottom = bottom;
    const height = bottom + BOTTOM;
    const kind = data.time ? 'time' : block.x === 'index' ? 'index' : 'number';
    const ticks = axisTicks(data.domain, kind, block.x_major, block.x_minor);
    const axis = renderAxis(ticks, data, layout.toX, bottom);
    const hover = renderHover(data, layout, unit);

    const legend = data.series
        .map((one) => {
            const latest = [...one.points].reverse().find((point) => (one.text ? point[1] !== null : finite(point[1])));
            let value = '–';
            let color = colorOf(data.series.indexOf(one));
            if (latest && one.text) {
                value = escapeHtml(latest[1]);
                color = colors.get(latest[1]);
            } else if (latest) {
                value = `${formatValue(latest[1])}${unit ? ` ${escapeHtml(unit)}` : ''}`;
            } else if (one.text) {
                color = 'transparent';
            }
            return (
                `<span class="legend-item"><span class="swatch" style="background: ${color}"></span>` +
                `<span class="legend-name">${escapeHtml(one.name)}</span><span class="legend-value">${value}</span></span>`
            );
        })
        .join('');
    // Which colour is which state, when there are more states than the rows' latest ones show
    const key =
        colors.size > 0
            ? `<div class="legend states">${[...colors]
                  .map(
                      ([name, color]) =>
                          `<span class="legend-item"><span class="swatch square" style="background: ${color}"></span>` +
                          `<span class="legend-name">${escapeHtml(name)}</span></span>`
                  )
                  .join('')}</div>`
            : '';

    return (
        `${title}<svg class="graph" viewBox="0 0 ${WIDTH} ${height}" role="img"` +
        ` aria-label="${escapeHtml(block.title || data.series.map((one) => one.name).join(', '))}">` +
        `${shapes}${axis}${hover}</svg><div class="legend">${legend}</div>${key}`
    );
}

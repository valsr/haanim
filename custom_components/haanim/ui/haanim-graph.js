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

function formatPosition(position, data, span) {
    if (!data.time) return formatValue(position);
    const date = new Date(position);
    if (Number.isNaN(date.getTime())) return '';
    return span > 24 * 3600000 ? date.toLocaleDateString() : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
 * Series of numbers share the plot at the top; series of states each get a row of a timeline below it.
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
    }

    const colors = stateColors(rows, lines.filter((one) => one.points.some((point) => finite(point[1]))).length);
    if (rows.length) {
        const toX = (position) => (span > 0 ? LEFT + ((position - from) / span) * plotWidth : LEFT);
        let top = values.length ? bottom + 6 : TOP;
        for (const row of rows) {
            shapes += timelineRow(row, top, toX, to, colors);
            top += ROW_PITCH;
        }
        bottom = top - (ROW_PITCH - ROW_BAR_TOP - ROW_BAR_HEIGHT);
    }

    const height = bottom + BOTTOM;
    const ends =
        `<text class="tick" x="${LEFT}" y="${height - 6}" text-anchor="start">${escapeHtml(formatPosition(from, data, span))}</text>` +
        `<text class="tick" x="${WIDTH - RIGHT}" y="${height - 6}" text-anchor="end">${escapeHtml(formatPosition(to, data, span))}</text>`;

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
        `${shapes}${ends}</svg><div class="legend">${legend}</div>${key}`
    );
}

/**
 * HAAnim graphs: pure functions that turn a graph block and its data into an SVG string.
 *
 * A graph block either names entities, whose recorded history the card fetches and hands in, or carries
 * series of the automation's own. Both are drawn here, as lines, areas or bars, with a value axis, the ends
 * of the horizontal axis, and a legend that shows the latest value of every series. Nothing touches the DOM.
 */

import { escapeHtml } from './haanim-render.js';

/** The colours of the series, in order. A theme can replace each one with `--haanim-graph-color-<n>`. */
export const GRAPH_COLORS = ['#03a9f4', '#ff9800', '#4caf50', '#e91e63', '#9c27b0', '#795548', '#009688', '#607d8b'];

const WIDTH = 400;
const HEIGHT = 180;
const LEFT = 44;
const RIGHT = 8;
const TOP = 8;
const BOTTOM = 22;

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
 * it was last updated, in seconds. Returns `[[milliseconds, value or null], ...]` in order of time.
 */
export function historyPoints(rows) {
    return (rows || [])
        .map((row) => [Math.round(Number(row.lu) * 1000), numericState(row.s)])
        .filter((point) => Number.isFinite(point[0]))
        .sort((a, b) => a[0] - b[0]);
}

/**
 * Bring together what a graph draws.
 *
 * Returns `{series, domain, time, step}`: `series` is a list of `{name, points}`, with the horizontal
 * positions of time graphs in milliseconds; `domain` is the range of the horizontal axis; `time` says
 * whether that axis is time; `step` whether a value holds until the next one (entity history) or the points
 * are joined by straight lines.
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
            return { name, points };
        });
        return { series, domain: [start, now], time: true, step: true };
    }
    const time = block.x === 'time';
    const series = Object.entries(block.series || {}).map(([name, points]) => ({
        name,
        points: (points || []).map((point) => [time ? point[0] * 1000 : point[0], point[1]]),
    }));
    const positions = series.flatMap((one) => one.points.map((point) => point[0])).filter(finite);
    const low = positions.length ? Math.min(...positions) : 0;
    const high = positions.length ? Math.max(...positions) : 1;
    return { series, domain: [low, high], time, step: false };
}

/** The range of the value axis: what the block asks for, else what the data needs, never of zero height. */
function valueDomain(block, values, bars) {
    let low = finite(block.min) ? block.min : Math.min(...values);
    let high = finite(block.max) ? block.max : Math.max(...values);
    if (bars && !finite(block.min)) low = Math.min(low, 0);
    if (bars && !finite(block.max)) high = Math.max(high, 0);
    if (high <= low) {
        const pad = Math.abs(low) > 0 ? Math.abs(low) * 0.1 : 1;
        if (!finite(block.min)) low -= pad;
        if (!finite(block.max) || high <= low) high = low + 2 * pad;
    }
    return [low, high];
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
 * Render a graph block as HTML: an optional title, the SVG, and a legend with the latest values.
 *
 * `context` has `history` (the fetched history per graph block), `states` and `now`.
 */
export function renderGraph(block, context = {}) {
    const data = graphData(block, context);
    const title = block.title ? `<div class="graph-title">${escapeHtml(block.title)}</div>` : '';
    const state = block.entities ? (context.states || {})[block.entities[0]] : null;
    const unit = block.unit ?? ((state && state.attributes && state.attributes.unit_of_measurement) || '');
    const fetched = block.entities ? (context.history || {})[block.id] : null;
    const failure = fetched ? fetched.error : null;
    const values = data.series.flatMap((one) => one.points.map((point) => point[1])).filter(finite);

    if (failure || values.length === 0) {
        const loading = block.entities && !(fetched && fetched.loaded);
        const text = failure ? `History is not available: ${failure}` : loading ? 'Loading history…' : 'No data';
        return `${title}<div class="graph-empty">${escapeHtml(text)}</div>`;
    }

    const bars = block.kind === 'bar';
    const [low, high] = valueDomain(block, values, bars);
    const [from, to] = data.domain;
    const span = to - from;
    const plotWidth = WIDTH - LEFT - RIGHT;
    const plotHeight = HEIGHT - TOP - BOTTOM;
    const longest = Math.max(...data.series.map((one) => one.points.length));
    // Bars need half a slot of room at both ends of the axis
    const slot = bars ? plotWidth / Math.max(longest, 1) : 0;
    const toX = (position) =>
        span > 0 ? LEFT + slot / 2 + ((position - from) / span) * (plotWidth - slot) : LEFT + plotWidth / 2;
    const toY = (value) => TOP + (1 - (Math.min(Math.max(value, low), high) - low) / (high - low)) * plotHeight;
    const baseline = toY(Math.min(Math.max(0, low), high));

    const grid = [low, (low + high) / 2, high]
        .map((value) => {
            const y = round(toY(value));
            return (
                `<line class="grid" x1="${LEFT}" x2="${WIDTH - RIGHT}" y1="${y}" y2="${y}"/>` +
                `<text class="tick" x="${LEFT - 6}" y="${y + 4}" text-anchor="end">${formatValue(value)}</text>`
            );
        })
        .join('');
    const ends =
        `<text class="tick" x="${LEFT}" y="${HEIGHT - 6}" text-anchor="start">${escapeHtml(formatPosition(from, data, span))}</text>` +
        `<text class="tick" x="${WIDTH - RIGHT}" y="${HEIGHT - 6}" text-anchor="end">${escapeHtml(formatPosition(to, data, span))}</text>`;

    const shapes = data.series
        .map((one, index) => {
            const color = colorOf(index);
            if (bars) {
                const width = Math.max((slot * 0.8) / data.series.length, 1);
                return one.points
                    .filter((point) => finite(point[1]) && finite(point[0]))
                    .map((point) => {
                        const x = round(toX(point[0]) - (slot * 0.8) / 2 + index * width);
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

    const legend = data.series
        .map((one, index) => {
            const latest = [...one.points].reverse().find((point) => finite(point[1]));
            const value = latest ? `${formatValue(latest[1])}${unit ? ` ${escapeHtml(unit)}` : ''}` : '–';
            return (
                `<span class="legend-item"><span class="swatch" style="background: ${colorOf(index)}"></span>` +
                `<span class="legend-name">${escapeHtml(one.name)}</span><span class="legend-value">${value}</span></span>`
            );
        })
        .join('');

    return (
        `${title}<svg class="graph" viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img"` +
        ` aria-label="${escapeHtml(block.title || data.series.map((one) => one.name).join(', '))}">` +
        `${grid}${ends}${shapes}</svg><div class="legend">${legend}</div>`
    );
}

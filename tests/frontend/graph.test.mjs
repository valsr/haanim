// The marks of a time axis fall on the local clock: the tests run on UTC, whatever the machine is set to
process.env.TZ = 'UTC';

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
    GRAPH_COLORS,
    axisTicks,
    classify,
    formatValue,
    graphData,
    historyPoints,
    hoverPositions,
    niceStep,
    numericState,
    renderGraph,
    stateColors,
    valueAxis,
} from '../../custom_components/haanim/ui/haanim-graph.js';
import { renderBlock } from '../../custom_components/haanim/ui/haanim-render.js';

const NOW = Date.UTC(2025, 0, 6, 12, 0, 0);
const HOUR = 3600000;

function supplied(extra = {}) {
    return { id: 'g', type: 'graph', kind: 'line', title: null, unit: null, min: null, max: null, x: 'index', series: { A: [[0, 1], [1, 2], [2, 4]] }, ...extra };
}

function history(extra = {}) {
    return { id: 'h', type: 'graph', kind: 'line', title: null, unit: null, min: null, max: null, entities: ['sensor.t'], hours: 2, ...extra };
}

function withHistory(points, more = {}) {
    return { now: NOW, history: { h: { points: { 'sensor.t': points }, loaded: true } }, ...more };
}

const paths = (html, cls = 'line') => [...html.matchAll(new RegExp(`<path class="${cls}" d="([^"]*)"`, 'g'))].map((match) => match[1]);

describe('numbers', () => {
    test('a state as a number', () => {
        assert.equal(numericState('21.5'), 21.5);
        assert.equal(numericState('0'), 0);
        assert.equal(numericState(3), 3);
        for (const state of ['unavailable', 'unknown', 'on', '', '  ', null, undefined, 'NaN', 'Infinity']) {
            assert.equal(numericState(state), null, String(state));
        }
    });
    test('values are shown with at most two decimals', () => {
        assert.equal(formatValue(21.456), '21.46');
        assert.equal(formatValue(20), '20');
        assert.equal(formatValue(0.5), '0.5');
        assert.equal(formatValue(-3.1), '-3.1');
        assert.equal(formatValue(12345.678), '12346');
        assert.equal(formatValue(NaN), '');
        assert.equal(formatValue(null), '');
    });
    test("Home Assistant's history as points, in order of time, states as text", () => {
        const rows = [{ s: '22', lu: 1736164900.5 }, { s: 'unavailable', lu: 1736165000 }, { s: '20', lu: 1736164800 }, { s: '1', lu: 'x' }, { s: null, lu: 1736165100 }];
        assert.deepEqual(historyPoints(rows), [[1736164800000, '20'], [1736164900500, '22'], [1736165000000, 'unavailable'], [1736165100000, '']]);
        assert.deepEqual(historyPoints(undefined), []);
    });
});

describe('numbers or states', () => {
    test('a series with a number in it is numeric, and what is not a number is a gap', () => {
        assert.deepEqual(classify([[0, '20'], [1, 'unavailable'], [2, 21.5], [3, null]]), { text: false, points: [[0, 20], [1, null], [2, 21.5], [3, null]] });
    });
    test('a series of states is a timeline, with gaps where the state says nothing', () => {
        assert.deepEqual(classify([[0, 'on'], [1, 'unavailable'], [2, 'off'], [3, 'Unknown'], [4, ''], [5, null]]), {
            text: true,
            points: [[0, 'on'], [1, null], [2, 'off'], [3, null], [4, null], [5, null]],
        });
    });
    test('nothing usable is neither', () => {
        assert.equal(classify([[0, 'unavailable'], [1, null]]).text, false);
        assert.equal(classify([]).text, false);
        assert.deepEqual(classify([[0, NaN]]).points, [[0, null]]);
    });
});

describe('round numbers on the value axis', () => {
    test('steps are 1, 2, 2.5 or 5 times a power of ten', () => {
        assert.equal(niceStep(3), 1);
        assert.equal(niceStep(8), 2);
        assert.equal(niceStep(10), 2.5);
        assert.equal(niceStep(14.11), 5);
        assert.equal(niceStep(40), 10);
        assert.equal(niceStep(0.3), 0.1);
        assert.equal(niceStep(1000), 250);
        assert.equal(niceStep(0), 1);
        assert.equal(niceStep(NaN), 1);
    });
    const axis = (values, block = {}, bars = false) => valueAxis(block, values, bars);
    test('the axis ends on round numbers beyond the data', () => {
        assert.deepEqual(axis([13.87, 27.98]), { low: 10, high: 30, ticks: [10, 15, 20, 25, 30] });
        assert.deepEqual(axis([1, 4]), { low: 1, high: 4, ticks: [1, 2, 3, 4] });
        assert.deepEqual(axis([0.12, 0.38]), { low: 0.1, high: 0.4, ticks: [0.1, 0.2, 0.3, 0.4] });
        assert.deepEqual(axis([-3, 7]), { low: -5, high: 7.5, ticks: [-5, -2.5, 0, 2.5, 5, 7.5] });
        assert.deepEqual(axis([980, 2040]), { low: 500, high: 2500, ticks: [500, 1000, 1500, 2000, 2500] });
    });
    test('an end the automation sets is kept, and the numbers between are still round', () => {
        assert.deepEqual(axis([17, 21.5], { min: 15, max: 25 }), { low: 15, high: 25, ticks: [15, 17.5, 20, 22.5, 25] });
        assert.deepEqual(axis([3, 18], { min: 1 }), { low: 1, high: 20, ticks: [5, 10, 15, 20] });
        assert.deepEqual(axis([3, 18], { max: 19 }), { low: 0, high: 19, ticks: [0, 5, 10, 15] });
    });
    test('bars include zero', () => {
        assert.deepEqual(axis([2, 4], {}, true), { low: 0, high: 4, ticks: [0, 1, 2, 3, 4] });
        assert.deepEqual(axis([-4, -2], {}, true), { low: -4, high: 0, ticks: [-4, -3, -2, -1, 0] });
        assert.equal(axis([2, 4], { min: 1 }, true).low, 1);
    });
    test('values that are all the same still get an axis around them', () => {
        assert.deepEqual(axis([5, 5]), { low: 4.5, high: 5.5, ticks: [4.5, 4.75, 5, 5.25, 5.5] });
        assert.deepEqual(axis([0]), { low: -1, high: 1, ticks: [-1, -0.5, 0, 0.5, 1] });
        assert.deepEqual(axis([5], { min: 5 }), { low: 5, high: 6, ticks: [5, 5.25, 5.5, 5.75, 6] });
        assert.deepEqual(axis([5], { max: 5 }), { low: 4.4, high: 5, ticks: [4.4, 4.6, 4.8, 5] });
    });
    test('no stray decimals from adding steps', () => {
        for (const tick of axis([0.1, 0.7]).ticks) assert.ok(String(tick).length <= 4, String(tick));
    });
});

describe('graphData', () => {
    test('series of the automation: positions as given, joined by straight lines', () => {
        const data = graphData(supplied());
        assert.deepEqual(data.series, [{ name: 'A', text: false, points: [[0, 1], [1, 2], [2, 4]] }]);
        assert.deepEqual(data.domain, [0, 2]);
        assert.equal(data.time, false);
        assert.equal(data.step, false);
    });
    test('series over time: seconds become milliseconds', () => {
        const data = graphData(supplied({ x: 'time', series: { A: [[1000, 1], [2000, 2]] } }));
        assert.deepEqual(data.series[0].points, [[1000000, 1], [2000000, 2]]);
        assert.equal(data.time, true);
    });
    test('no series at all', () => {
        assert.deepEqual(graphData(supplied({ series: {} })).domain, [0, 1]);
        assert.deepEqual(graphData(supplied({ series: undefined })).series, []);
    });
    test('entity history: the window ends now and values hold', () => {
        const data = graphData(history(), withHistory([[NOW - HOUR, 20], [NOW - HOUR / 2, 22]]));
        assert.deepEqual(data.domain, [NOW - 2 * HOUR, NOW]);
        assert.equal(data.time, true);
        assert.equal(data.step, true);
        assert.deepEqual(data.series[0].points, [[NOW - HOUR, 20], [NOW - HOUR / 2, 22], [NOW, 22]]);
    });
    test('entity history: what was recorded before the window holds at its start', () => {
        const data = graphData(history(), withHistory([[NOW - 5 * HOUR, 18], [NOW - 3 * HOUR, 19], [NOW - HOUR, 20]]));
        assert.deepEqual(data.series[0].points, [[NOW - 2 * HOUR, 19], [NOW - HOUR, 20], [NOW, 20]]);
    });
    test('entity history: the name of the entity is its friendly name', () => {
        const states = { 'sensor.t': { state: '20', attributes: { friendly_name: 'Temperature' } } };
        assert.equal(graphData(history(), withHistory([], { states })).series[0].name, 'Temperature');
        assert.equal(graphData(history(), withHistory([])).series[0].name, 'sensor.t');
        assert.deepEqual(graphData(history(), { now: NOW }).series[0].points, []);
    });
    test('the window defaults to a day, and to the present', () => {
        const data = graphData(history({ hours: undefined }));
        assert.equal(data.domain[1] - data.domain[0], 24 * HOUR);
        assert.ok(Math.abs(data.domain[1] - Date.now()) < 5000);
    });
});

describe('renderGraph: series of the automation', () => {
    test('a line per series, in its colour, with a legend of the latest values', () => {
        const html = renderGraph(supplied({ series: { Alerts: [[0, 1], [1, 2], [2, 4]], Resets: [[0, 0], [2, 1]] }, unit: 'x' }));
        assert.match(html, /^<svg class="graph" viewBox="0 0 400 180" role="img" aria-label="Alerts, Resets">/);
        assert.equal(paths(html).length, 2);
        assert.match(html, /stroke: var\(--haanim-graph-color-1, #03a9f4\)/);
        assert.match(html, /stroke: var\(--haanim-graph-color-2, #ff9800\)/);
        assert.match(html, /<span class="legend-name">Alerts<\/span><span class="legend-value">4 x<\/span>/);
        assert.match(html, /<span class="legend-name">Resets<\/span><span class="legend-value">1 x<\/span>/);
    });
    test('the line goes from the lowest value at the bottom to the highest at the top', () => {
        assert.deepEqual(paths(renderGraph(supplied())), ['M44 158h0L218 108L392 8']);
    });
    test('the value axis is marked with round numbers', () => {
        const ticks = (html) => [...html.matchAll(/class="tick" x="38"[^>]*>([^<]*)</g)].map((match) => match[1]);
        assert.deepEqual(ticks(renderGraph(supplied())), ['1', '2', '3', '4']);
        assert.deepEqual(ticks(renderGraph(supplied({ series: { A: [[0, 13.87], [1, 27.98]] } }))), ['10', '15', '20', '25', '30']);
    });
    test('min and max set the value axis, and values outside it stay inside the plot', () => {
        const html = renderGraph(supplied({ min: 0, max: 2 }));
        assert.match(html, />0<\/text>.*>1<\/text>.*>2<\/text>/);
        assert.deepEqual(paths(html), ['M44 83h0L218 8L392 8']);
    });
    test('a missing value leaves a gap, and a point on its own is still drawn', () => {
        assert.deepEqual(paths(renderGraph(supplied({ series: { A: [[0, 1], [1, 2], [2, null], [3, 4]] } }))), ['M44 158h0L160 108M392 8h0']);
    });
    test('all values the same still make a graph', () => {
        const html = renderGraph(supplied({ series: { A: [[0, 5], [1, 5]] } }));
        assert.deepEqual(paths(html), ['M44 83h0L392 83']);
        assert.match(renderGraph(supplied({ series: { A: [[0, 0]] } })), /<path class="line" d="M218 83h0"/);
    });
    test('an area is the line with the space down to zero filled', () => {
        const html = renderGraph(supplied({ kind: 'area', series: { A: [[0, 1], [1, 3]] } }));
        assert.deepEqual(paths(html, 'area'), ['M44 158h0L392 8V158H44Z']);
        assert.equal(paths(html).length, 1);
        const gap = renderGraph(supplied({ kind: 'area', series: { A: [[0, 1], [1, null], [2, 3], [3, 2]] } }));
        assert.equal((paths(gap, 'area')[0].match(/Z/g) || []).length, 2);
    });
    test('bars stand on zero, side by side for several series', () => {
        const html = renderGraph(supplied({ kind: 'bar', series: { A: [[0, 2], [1, 4]], B: [[0, 1], [1, 3]] } }));
        const bars = [...html.matchAll(/<rect class="bar" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"/g)].map((m) => m.slice(1).map(Number));
        assert.equal(bars.length, 4);
        assert.ok(bars.every((bar) => Math.abs(bar[1] + bar[3] - 158) < 0.2), 'every bar ends at zero');
        assert.ok(bars[0][0] + bars[0][2] <= bars[2][0] + 0.2, 'the second series stands beside the first');
        assert.ok(bars[1][3] > bars[0][3]);
        assert.doesNotMatch(html, /<path/);
    });
    test('bars below zero hang from it', () => {
        const html = renderGraph(supplied({ kind: 'bar', series: { A: [[0, 2], [1, -2], [2, null]] } }));
        const bars = [...html.matchAll(/<rect class="bar" x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)"/g)].map((m) => m.slice(1).map(Number));
        assert.equal(bars.length, 2);
        assert.equal(bars[0][0] + bars[0][1], bars[1][0]);
    });
    test('a title, and text that cannot be markup', () => {
        const html = renderGraph(supplied({ title: 'Alerts <today>', unit: '<u>', series: { '<b>A</b>': [[0, 1]] } }));
        assert.match(html, /^<div class="graph-title">Alerts &lt;today&gt;<\/div>/);
        assert.match(html, /aria-label="Alerts &lt;today&gt;"/);
        assert.match(html, /&lt;b&gt;A&lt;\/b&gt;/);
        assert.match(html, /1 &lt;u&gt;/);
        assert.doesNotMatch(html, /<b>|<u>/);
    });
    test('nothing to draw', () => {
        assert.equal(renderGraph(supplied({ series: { A: [] } })), '<div class="graph-empty">No data</div>');
        assert.match(renderGraph(supplied({ series: { A: [[0, null]] }, title: 'T' })), /graph-title">T<.*No data/);
    });
    test('a series without a value has a dash in the legend', () => {
        assert.match(renderGraph(supplied({ series: { A: [[0, 1]], B: [[0, null]] } })), /legend-name">B<\/span><span class="legend-value">–</);
    });
    test('more series than colours start over', () => {
        const series = Object.fromEntries(Array.from({ length: 9 }, (_, index) => [`S${index}`, [[0, index]]]));
        const html = renderGraph(supplied({ series }));
        assert.equal(GRAPH_COLORS.length, 8);
        assert.equal((html.match(/stroke: var\(--haanim-graph-color-1,/g) || []).length, 2);
    });
});

describe('renderGraph: entity history', () => {
    test('a value holds until the next one, and the latest until now', () => {
        const html = renderGraph(history(), withHistory([[NOW - 2 * HOUR, 20], [NOW - HOUR, 22]]));
        assert.deepEqual(paths(html), ['M44 158h0H218V8H392']);
    });
    test('the unit and the name come from the entity', () => {
        const states = { 'sensor.t': { state: '22', attributes: { friendly_name: 'Temperature', unit_of_measurement: '°C' } } };
        const html = renderGraph(history(), withHistory([[NOW - HOUR, 22]], { states }));
        assert.match(html, /<span class="legend-name">Temperature<\/span><span class="legend-value">22 °C<\/span>/);
        assert.match(renderGraph(history({ unit: 'deg' }), withHistory([[NOW - HOUR, 22]], { states })), /22 deg</);
        assert.match(renderGraph(history({ unit: '' }), withHistory([[NOW - HOUR, 22]], { states })), /legend-value">22</);
    });
    test('a time the entity was unavailable is a gap that starts when it became so', () => {
        const html = renderGraph(history(), withHistory([[NOW - 2 * HOUR, 20], [NOW - HOUR, null], [NOW - HOUR / 2, 22]]));
        assert.deepEqual(paths(html), ['M44 158h0H218M305 8h0H392']);
    });
    test('while the history is on its way, and when it cannot be had', () => {
        assert.equal(renderGraph(history(), { now: NOW, history: {} }), '<div class="graph-empty">Loading history…</div>');
        assert.equal(renderGraph(history(), { now: NOW }), '<div class="graph-empty">Loading history…</div>');
        const failed = { now: NOW, history: { h: { points: {}, error: 'Unknown <command>' } } };
        assert.equal(renderGraph(history(), failed), '<div class="graph-empty">History is not available: Unknown &lt;command&gt;</div>');
    });
    test('an entity with nothing recorded, or nothing numeric', () => {
        assert.equal(renderGraph(history(), withHistory([])), '<div class="graph-empty">No data</div>');
        assert.equal(renderGraph(history(), withHistory([[NOW - HOUR, null]])), '<div class="graph-empty">No data</div>');
    });
    test('several entities share the axes', () => {
        const context = { now: NOW, history: { h: { points: { 'sensor.a': [[NOW - HOUR, 10]], 'sensor.b': [[NOW - HOUR, 30]] } } } };
        const html = renderGraph(history({ entities: ['sensor.a', 'sensor.b'] }), context);
        assert.equal(paths(html).length, 2);
        assert.match(html, />10<\/text>.*>20<\/text>.*>30<\/text>/);
    });
});

describe('renderGraph: states over time', () => {
    const fan = (points, extra = {}) => ({ now: NOW, history: { h: { loaded: true, points: { 'fan.a': points, ...extra } } } });
    const segments = (html) =>
        [...html.matchAll(/<rect class="segment" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" style="fill: ([^"]*)"><title>([^<]*)<\/title>/g)].map((m) => ({
            x: Number(m[1]),
            y: Number(m[2]),
            width: Number(m[3]),
            fill: m[5],
            state: m[6],
        }));

    test('an entity whose states are not numbers is a row of segments, one per state it was in', () => {
        const html = renderGraph(history({ entities: ['fan.a'] }), fan([[NOW - 2 * HOUR, 'off'], [NOW - HOUR, 'on'], [NOW - HOUR / 2, 'off']]));
        assert.deepEqual(segments(html).map((one) => [one.state, one.x, one.width]), [['off', 44, 174], ['on', 218, 87], ['off', 305, 87]]);
        assert.match(html, /<text class="row-label" x="44" y="18">fan.a<\/text>/);
        assert.doesNotMatch(html, /<path|class="grid"/, 'no value axis without numbers');
        assert.match(html, /viewBox="0 0 400 56"/);
    });
    test('states in which nothing happens are muted, the others get a colour each, the same in every row', () => {
        const context = fan([[NOW - 2 * HOUR, 'off'], [NOW - HOUR, 'heat']], { 'fan.b': [[NOW - 2 * HOUR, 'cool'], [NOW - HOUR, 'heat'], [NOW - HOUR / 2, 'idle']] });
        const drawn = segments(renderGraph(history({ entities: ['fan.a', 'fan.b'] }), context));
        const fill = (state) => [...new Set(drawn.filter((one) => one.state === state).map((one) => one.fill))];
        assert.deepEqual(fill('off'), ['var(--haanim-graph-inactive, #bdbdbd)']);
        assert.deepEqual(fill('idle'), ['var(--haanim-graph-inactive, #bdbdbd)']);
        assert.deepEqual(fill('heat'), ['var(--haanim-graph-color-1, #03a9f4)']);
        assert.deepEqual(fill('cool'), ['var(--haanim-graph-color-2, #ff9800)']);
        assert.deepEqual([...new Set(drawn.map((one) => one.y))], [22, 52], 'a row per entity');
    });
    test('a time the entity was unavailable is a gap', () => {
        const drawn = segments(renderGraph(history({ entities: ['fan.a'] }), fan([[NOW - 2 * HOUR, 'on'], [NOW - HOUR, 'unavailable'], [NOW - HOUR / 2, 'on']])));
        assert.deepEqual(drawn.map((one) => [one.x, one.width]), [[44, 174], [305, 87]]);
    });
    test('the legend shows the state each row is in now, and which colour is which state', () => {
        const states = { 'fan.a': { state: 'on', attributes: { friendly_name: 'Fan <1>' } } };
        const html = renderGraph(history({ entities: ['fan.a'] }), { ...fan([[NOW - HOUR, 'off'], [NOW - HOUR / 2, 'on']]), states });
        assert.match(html, /<span class="swatch" style="background: var\(--haanim-graph-color-1, #03a9f4\)"><\/span><span class="legend-name">Fan &lt;1&gt;<\/span><span class="legend-value">on<\/span>/);
        assert.match(html, /<div class="legend states">.*legend-name">off<.*legend-name">on</);
        assert.match(html, /<text class="row-label" x="44" y="18">Fan &lt;1&gt;<\/text>/);
    });
    test('numbers and states in one graph: the plot on top, the timeline below, on the same time axis', () => {
        const context = { now: NOW, history: { h: { loaded: true, points: { 'sensor.t': [[NOW - 2 * HOUR, '20'], [NOW - HOUR, '22']], 'fan.a': [[NOW - 2 * HOUR, 'off'], [NOW - HOUR, 'on']] } } } };
        const html = renderGraph(history({ entities: ['sensor.t', 'fan.a'] }), context);
        assert.deepEqual(paths(html), ['M44 158h0H218V8H392']);
        assert.deepEqual(segments(html).map((one) => [one.state, one.x, one.y]), [['off', 44, 178], ['on', 218, 178]]);
        assert.match(html, /viewBox="0 0 400 212"/);
        assert.match(html, /legend-name">sensor.t<\/span><span class="legend-value">22</);
        assert.match(html, /legend-name">fan.a<\/span><span class="legend-value">on</);
        assert.match(html, /stroke: var\(--haanim-graph-color-1, #03a9f4\)/);
        assert.equal(segments(html)[1].fill, 'var(--haanim-graph-color-2, #ff9800)', 'a state does not take the colour of a line');
    });
    test('a state with markup in it is text', () => {
        const html = renderGraph(history({ entities: ['fan.a'] }), fan([[NOW - HOUR, '<b>x</b>']]));
        assert.match(html, /<title>&lt;b&gt;x&lt;\/b&gt;<\/title>/);
        assert.doesNotMatch(html, /<b>/);
    });
    test("states of the automation's own: each holds until the next point", () => {
        const html = renderGraph(supplied({ x: 'number', series: { Pump: [[0, 'on'], [6, 'off'], [8, 'on'], [10, 'on']] } }));
        assert.deepEqual(segments(html).map((one) => [one.state, one.x, one.width]), [['on', 44, 208.8], ['off', 252.8, 69.6], ['on', 322.4, 69.6]]);
    });
    test("states of the automation's own, one after the other: a slot each", () => {
        const html = renderGraph(supplied({ series: { Mode: [[0, 'heat'], [1, 'heat'], [2, 'off'], [3, null]] } }));
        assert.deepEqual(segments(html).map((one) => [one.state, one.x, one.width]), [['heat', 44, 87], ['heat', 131, 87], ['off', 218, 87]]);
        assert.deepEqual(graphData(supplied({ series: { Mode: [[0, 'heat'], [1, 'off']] } })).domain, [0, 2]);
    });
    test('a row without a state now has a dash in the legend', () => {
        const html = renderGraph(supplied({ series: { Mode: [[0, 'heat'], [1, null]], Other: [[0, null], [1, 'x']] } }));
        assert.match(html, /legend-name">Mode<\/span><span class="legend-value">heat</);
    });
    test('the colours of the states', () => {
        const colors = stateColors([{ points: [[0, 'off'], [1, 'on'], [2, null], [3, 'on'], [4, 'auto']] }]);
        assert.deepEqual([...colors.keys()], ['off', 'on', 'auto']);
        assert.equal(colors.get('auto'), 'var(--haanim-graph-color-2, #ff9800)');
        assert.equal(stateColors([]).size, 0);
        assert.equal(stateColors([{ points: [[0, 'on']] }], 3).get('on'), 'var(--haanim-graph-color-4, #e91e63)');
    });
});

describe('marks of the horizontal axis', () => {
    const MIN = 60000;
    const at = (hour, minute = 0) => Date.UTC(2025, 0, 6, hour, minute);
    const clock = (marks) => marks.map((mark) => new Date(mark).toISOString().slice(11, 16));

    test('time: round clock steps, with smaller ones between', () => {
        const ticks = axisTicks([at(10, 7), at(12, 7)], 'time');
        assert.equal(ticks.step, 30 * MIN);
        assert.deepEqual(clock(ticks.major), ['10:30', '11:00', '11:30', '12:00']);
        assert.deepEqual(clock(ticks.minor).slice(0, 6), ['10:10', '10:15', '10:20', '10:25', '10:35', '10:40']);
        assert.ok(ticks.minor.every((mark) => !ticks.major.includes(mark)));
    });
    test('time: the step grows with the span', () => {
        const step = (hours) => axisTicks([at(0), at(0) + hours * HOUR], 'time').step / MIN;
        assert.deepEqual([0.1, 1, 6, 24, 72, 240, 720].map(step), [1, 10, 60, 360, 720, 2880, 10080]);
    });
    test('time: days are marked at midnight', () => {
        const ticks = axisTicks([at(15), at(15) + 5 * 24 * HOUR], 'time');
        assert.equal(ticks.step, 24 * HOUR);
        assert.ok(ticks.major.every((mark) => new Date(mark).toISOString().endsWith('T00:00:00.000Z')));
        assert.equal(ticks.major.length, 5);
        assert.deepEqual(clock(ticks.minor).slice(0, 3), ['18:00', '06:00', '12:00']);
    });
    test('time: the distances the automation asks for, in seconds', () => {
        const ticks = axisTicks([at(10), at(12)], 'time', 3600, 900);
        assert.deepEqual(clock(ticks.major), ['10:00', '11:00', '12:00']);
        assert.deepEqual(clock(ticks.minor), ['10:15', '10:30', '10:45', '11:15', '11:30', '11:45']);
    });
    test('numbers: round steps, a fifth of them between', () => {
        const ticks = axisTicks([0, 22], 'number');
        assert.deepEqual(ticks.major, [0, 5, 10, 15, 20]);
        assert.deepEqual(ticks.minor.slice(0, 6), [1, 2, 3, 4, 6, 7]);
        assert.deepEqual(axisTicks([0, 1], 'number').major.map((mark) => Number(mark.toFixed(2))), [0, 0.2, 0.4, 0.6, 0.8, 1]);
    });
    test('an index is marked at whole numbers only', () => {
        assert.deepEqual(axisTicks([0, 8], 'index'), { major: [0, 2, 4, 6, 8], minor: [1, 3, 5, 7], step: 2 });
        assert.deepEqual(axisTicks([0, 3], 'index'), { major: [0, 1, 2, 3], minor: [], step: 1 });
        assert.deepEqual(axisTicks([0, 40], 'index').major, [0, 10, 20, 30, 40]);
        assert.deepEqual(axisTicks([0, 40], 'index').minor.slice(0, 4), [2, 4, 6, 8]);
    });
    test('numbers: the distances the automation asks for', () => {
        assert.deepEqual(axisTicks([0, 22], 'number', 10, 2), { major: [0, 10, 20], minor: [2, 4, 6, 8, 12, 14, 16, 18, 22], step: 10 });
        assert.deepEqual(axisTicks([0, 22], 'number', 11).major, [0, 11, 22]);
        assert.deepEqual(axisTicks([0, 22], 'number', null, 2.5).minor.slice(0, 3), [2.5, 7.5, 12.5]);
    });
    test('distances that would crowd the axis are replaced by round ones', () => {
        assert.deepEqual(axisTicks([0, 22], 'number', 0.5).major, [0, 5, 10, 15, 20]);
        assert.deepEqual(axisTicks([0, 22], 'number', 10, 0.01).minor.length, 9);
        assert.deepEqual(axisTicks([0, 22], 'number', 10, 10).minor.length, 9, 'a minor distance has to be the smaller one');
        assert.deepEqual(axisTicks([0, 22], 'number', -1).major, [0, 5, 10, 15, 20]);
    });
    test('an axis of no length has no marks', () => {
        assert.deepEqual(axisTicks([5, 5], 'number'), { major: [], minor: [], step: 0 });
        assert.deepEqual(axisTicks([0, NaN], 'number'), { major: [], minor: [], step: 0 });
    });
    test('the graph draws an axis line, the marks, and a label under each major one', () => {
        const html = renderGraph(supplied({ x: 'number', series: { A: [[0, 1], [22, 4]] } }));
        assert.match(html, /<line class="axis" x1="44" x2="392" y1="158" y2="158"\/>/);
        const majors = [...html.matchAll(/<line class="tick-major" x1="([\d.]+)"[^>]*y1="158" y2="163"\/><text class="tick" x="[\d.]+" y="174" text-anchor="(\w+)">([^<]*)</g)].map((m) => [Number(m[1]), m[2], m[3]]);
        assert.deepEqual(majors, [[44, 'start', '0'], [123.1, 'middle', '5'], [202.2, 'middle', '10'], [281.3, 'middle', '15'], [360.4, 'middle', '20']]);
        assert.equal((html.match(/class="tick-minor"/g) || []).length, 18);
        assert.match(html, /<line class="tick-minor" x1="59.8" x2="59.8" y1="158" y2="161"\/>/);
    });
    test('a label at the right end stays inside the graph', () => {
        const html = renderGraph(supplied({ x: 'number', series: { A: [[0, 1], [20, 4]] } }));
        assert.match(html, /<text class="tick" x="392" y="174" text-anchor="end">20</);
    });
    test('time is labelled as time of day, and as dates when the marks are days apart', () => {
        const labels = (html) => [...html.matchAll(/y="174" text-anchor="(?:start|middle|end)">([^<]*)</g)].map((m) => m[1]);
        const day = renderGraph(history(), withHistory([[NOW - HOUR, 20], [NOW - HOUR / 2, 22]]));
        assert.deepEqual(labels(day), ['10:00', '10:30', '11:00', '11:30', '12:00']);
        const month = renderGraph(history({ hours: 240 }), { now: NOW, history: { h: { loaded: true, points: { 'sensor.t': [[NOW - 100 * HOUR, 20]] } } } });
        assert.ok(labels(month).length >= 4);
        assert.ok(labels(month).every((label) => /Dec|Jan/.test(label) && !label.includes(':')), labels(month).join());
    });
    test('the distances of the block are used', () => {
        const html = renderGraph(history({ x_major: 3600, x_minor: 1800 }), withHistory([[NOW - HOUR, 20]]));
        assert.equal((html.match(/class="tick-major"/g) || []).length, 3);
        assert.equal((html.match(/class="tick-minor"/g) || []).length, 2);
    });
    test('bars are marked under the middle of their slots', () => {
        const html = renderGraph(supplied({ kind: 'bar', series: { A: [[0, 1], [1, 2], [2, 3], [3, 4]] } }));
        const marks = [...html.matchAll(/class="tick-major" x1="([\d.]+)"/g)].map((m) => Number(m[1]));
        assert.deepEqual(marks, [87.5, 174.5, 261.5, 348.5]);
    });
    test('a timeline has the axis below its last row', () => {
        const html = renderGraph(supplied({ x: 'number', series: { Pump: [[0, 'on'], [10, 'off']] } }));
        assert.match(html, /<line class="axis" x1="44" x2="392" y1="34" y2="34"\/>/);
        assert.match(html, /<text class="tick" x="44" y="50" text-anchor="start">0</);
    });
});

describe('hovering over a graph', () => {
    const bands = (html) =>
        [...html.matchAll(/<g class="hover"><rect class="hit" x="([\d.]+)" y="(\d+)" width="([\d.]+)" height="([\d.]+)"\/><line class="guide" x1="([\d.]+)"[^>]*\/>(.*?)<g class="readout">.*?<text[^>]*>(.*?)<\/text><\/g><\/g>/g)].map((m) => ({
            x: Number(m[1]),
            width: Number(m[3]),
            height: Number(m[4]),
            guide: Number(m[5]),
            dots: [...m[6].matchAll(/cx="([\d.]+)" cy="([\d.]+)"/g)].map((d) => [Number(d[1]), Number(d[2])]),
            lines: [...m[7].matchAll(/<tspan[^>]*>([^<]*)<\/tspan>/g)].map((t) => t[1]),
        }));

    test('a band for every position with a point, which together cover the plot', () => {
        const drawn = bands(renderGraph(supplied({ unit: 'x' })));
        assert.equal(drawn.length, 3);
        assert.deepEqual(drawn.map((band) => band.guide), [44, 218, 392]);
        assert.equal(drawn[0].x, 44);
        assert.equal(drawn[0].x + drawn[0].width, drawn[1].x);
        assert.equal(drawn[2].x + drawn[2].width, 392);
        assert.ok(drawn.every((band) => band.height === 150));
    });
    test('the readout names the position and the value of every series there, with the unit', () => {
        const html = renderGraph(supplied({ unit: '°C', series: { Indoor: [[0, 21.456], [1, 22]], Outdoor: [[0, 5], [1, null]] } }));
        assert.deepEqual(bands(html).map((band) => band.lines), [['0', 'Indoor: 21.46 °C', 'Outdoor: 5 °C'], ['1', 'Indoor: 22 °C', 'Outdoor: –']]);
    });
    test('a dot on each line at the value', () => {
        const drawn = bands(renderGraph(supplied({ series: { A: [[0, 1], [1, 2], [2, 4]], B: [[0, 4], [2, 1]] } })));
        assert.deepEqual(drawn[0].dots, [[44, 158], [44, 8]]);
        assert.deepEqual(drawn[2].dots, [[392, 8], [392, 158]]);
        assert.equal(drawn[1].dots.length, 2, 'a series without a point there shows its nearest one');
    });
    test('history: the value that held at that time', () => {
        const html = renderGraph(history(), withHistory([[NOW - 2 * HOUR, 20], [NOW - HOUR, 22]]));
        const drawn = bands(html);
        assert.deepEqual(drawn.map((band) => band.lines), [['10:00:00', 'sensor.t: 20'], ['11:00:00', 'sensor.t: 22'], ['12:00:00', 'sensor.t: 22']]);
    });
    test('states are named in the readout too, and get no dot', () => {
        const context = { now: NOW, history: { h: { loaded: true, points: { 'sensor.t': [[NOW - 2 * HOUR, '20']], 'fan.a': [[NOW - 2 * HOUR, 'off'], [NOW - HOUR, 'on']] } } } };
        const drawn = bands(renderGraph(history({ entities: ['sensor.t', 'fan.a'] }), context));
        assert.deepEqual(drawn[0].lines, ['10:00:00', 'sensor.t: 20', 'fan.a: off']);
        assert.deepEqual(drawn[1].lines, ['11:00:00', 'sensor.t: 20', 'fan.a: on']);
        assert.equal(drawn[1].dots.length, 1);
        assert.equal(drawn[0].height, 182, 'the band covers the plot and the rows');
    });
    test('a timeline alone can be hovered', () => {
        const drawn = bands(renderGraph(supplied({ x: 'number', series: { Pump: [[0, 'on'], [6, 'off'], [10, 'off']] } })));
        assert.deepEqual(drawn.map((band) => band.lines), [['0', 'Pump: on'], ['6', 'Pump: off'], ['10', 'Pump: off']]);
        assert.ok(drawn.every((band) => band.dots.length === 0));
    });
    test('a graph spanning days names the day', () => {
        const html = renderGraph(history({ hours: 72 }), { now: NOW, history: { h: { loaded: true, points: { 'sensor.t': [[NOW - 30 * HOUR, 20]] } } } });
        assert.match(bands(html)[0].lines[0], /Jan 5,? 06:00:00/);
    });
    test('many points share a limited number of bands', () => {
        const points = Array.from({ length: 500 }, (_, index) => [index, index % 7]);
        const html = renderGraph(supplied({ x: 'number', series: { A: points } }));
        assert.equal(bands(html).length, 60);
        assert.equal(hoverPositions({ domain: [0, 499], series: [{ points }] }).length, 60);
        assert.deepEqual(hoverPositions({ domain: [0, 2], series: [{ points: [[0, 1], [2, 1], [1, 1], [1, 2], [5, 1], [NaN, 1]] }] }), [0, 1, 2]);
    });
    test('the readout stays inside the graph, to the right of the pointer on the left half and to the left on the right', () => {
        const html = renderGraph(supplied());
        const boxes = [...html.matchAll(/<g class="readout"><rect x="([\d.-]+)" y="10" width="([\d.]+)"/g)].map((m) => [Number(m[1]), Number(m[2])]);
        assert.ok(boxes[0][0] > 44);
        assert.ok(boxes[2][0] + boxes[2][1] < 392);
        assert.ok(boxes.every(([x, width]) => x >= 44 && x + width <= 392));
    });
    test('text in the readout cannot be markup', () => {
        const html = renderGraph(supplied({ unit: '<u>', series: { '<b>A</b>': [[0, 1]] } }));
        assert.match(html, /<tspan[^>]*>&lt;b&gt;A&lt;\/b&gt;: 1 &lt;u&gt;<\/tspan>/);
    });
});

describe('graph block', () => {
    test('a graph is drawn inside its block', () => {
        const html = renderBlock(supplied());
        assert.match(html, /^<div class="block block-graph" data-block="g"><svg class="graph"/);
        assert.match(html, /<\/div><\/div>$/);
    });
});

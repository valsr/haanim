import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
    GRAPH_COLORS,
    formatValue,
    graphData,
    historyPoints,
    numericState,
    renderGraph,
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
    test("Home Assistant's history as points", () => {
        const rows = [{ s: '22', lu: 1736164900.5 }, { s: 'unavailable', lu: 1736165000 }, { s: '20', lu: 1736164800 }, { s: '1', lu: 'x' }];
        assert.deepEqual(historyPoints(rows), [[1736164800000, 20], [1736164900500, 22], [1736165000000, null]]);
        assert.deepEqual(historyPoints(undefined), []);
    });
});

describe('graphData', () => {
    test('series of the automation: positions as given, joined by straight lines', () => {
        const data = graphData(supplied());
        assert.deepEqual(data.series, [{ name: 'A', points: [[0, 1], [1, 2], [2, 4]] }]);
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
    test('the value axis shows the lowest, the middle and the highest value', () => {
        const ticks = [...renderGraph(supplied()).matchAll(/text-anchor="end">([^<]*)</g)].map((match) => match[1]);
        assert.deepEqual(ticks, ['1', '2.5', '4', '2']);
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
    test('time along the axis is shown as time, as dates for more than a day', () => {
        const day = renderGraph(supplied({ x: 'time', series: { A: [[NOW / 1000, 1], [NOW / 1000 + 3600, 2]] } }));
        const month = renderGraph(supplied({ x: 'time', series: { A: [[NOW / 1000, 1], [NOW / 1000 + 86400 * 20, 2]] } }));
        const ends = (html) => [...html.matchAll(/text-anchor="(?:start|end)">([^<]*)</g)].map((match) => match[1]).slice(-2);
        assert.ok(ends(day).every((text) => /\d/.test(text) && text.includes(':')));
        assert.ok(ends(month).every((text) => /\d/.test(text) && !text.includes(':')));
        assert.notEqual(ends(month)[0], ends(month)[1]);
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

describe('graph block', () => {
    test('a graph is drawn inside its block', () => {
        const html = renderBlock(supplied());
        assert.match(html, /^<div class="block block-graph" data-block="g"><svg class="graph"/);
        assert.match(html, /<\/div><\/div>$/);
    });
});

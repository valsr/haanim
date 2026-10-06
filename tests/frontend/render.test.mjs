import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
    MAX_LOG_RECORDS,
    escapeHtml,
    formatTime,
    renderActions,
    renderBlock,
    renderCard,
    renderConfig,
    renderContent,
    renderDetail,
    renderHeader,
    renderList,
    renderLog,
    renderMarkdown,
    safeUrl,
    serviceCall,
    stateLabel,
    stripHtml,
} from '../../custom_components/haanim/ui/haanim-render.js';

describe('escapeHtml', () => {
    test('escapes the characters that mean something in HTML', () => {
        assert.equal(escapeHtml(`<a href="x" title='y'>&</a>`), '&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;');
    });
    test('turns anything into text', () => {
        assert.equal(escapeHtml(null), '');
        assert.equal(escapeHtml(undefined), '');
        assert.equal(escapeHtml(0), '0');
        assert.equal(escapeHtml(false), 'false');
    });
});

describe('markdown is sanitised', () => {
    const attacks = [
        ['a script element', 'Hi<script>alert(1)</script> there'],
        ['a script in capitals', 'Hi<SCRIPT src="x.js"></SCRIPT>'],
        ['an event handler', '<img src=x onerror="alert(1)">'],
        ['an iframe', '<iframe src="https://evil.example"></iframe>'],
        ['a style element', '<style>body{display:none}</style>'],
        ['a nested tag', '<scr<script>ipt>alert(1)</scr</script>ipt>'],
        ['a javascript link', '[click](javascript:alert(1))'],
        ['a data link', '[click](data:text/html;base64,PHNjcmlwdD4=)'],
        ['a link that breaks out of its attribute', '[x](https://a.example/"onmouseover="alert(1))'],
        ['an image with a handler', '![x](https://a.example/x.png" onerror="alert(1))'],
        ['an unclosed tag', 'text <script'],
        ['a comment', '<!-- <script>alert(1)</script> -->'],
        ['an svg', '<svg onload=alert(1)>'],
    ];
    for (const [name, markdown] of attacks) {
        test(`${name} cannot run code`, () => {
            const html = renderMarkdown(markdown);
            assert.doesNotMatch(html, /<script|<iframe|<style|<svg|<img/i);
            assert.doesNotMatch(html, /href="(?!https?:|mailto:|\/)/i);
            // No attribute other than the ones the renderer itself writes
            for (const tag of html.match(/<[a-z][^>]*>/g) || []) {
                assert.match(tag, /^<(p|br|strong|em|code|pre|ul|ol|li|h[1-6]|a href="[^"]*" target="_blank" rel="noopener noreferrer")>$/);
            }
        });
    }
    test('raw HTML is removed, its text is kept', () => {
        assert.equal(renderMarkdown('a <b>bold</b> word'), '<p>a bold word</p>');
        assert.equal(stripHtml('x<script>bad()</script>y'), 'xy');
    });
    test('a lone angle bracket is text', () => {
        assert.equal(renderMarkdown('1 < 2 and 3 > 2'), '<p>1 &lt; 2 and 3 &gt; 2</p>');
    });
});

describe('renderMarkdown', () => {
    test('headings and paragraphs', () => {
        assert.equal(
            renderMarkdown('## Climate\nKeeps the house between **19** and **23** °C.'),
            '<h2>Climate</h2><p>Keeps the house between <strong>19</strong> and <strong>23</strong> °C.</p>'
        );
    });
    test('emphasis, code and line breaks', () => {
        assert.equal(renderMarkdown('*a* _b_ __c__ `d*e*`\nnext'), '<p><em>a</em> <em>b</em> <strong>c</strong> <code>d*e*</code><br>next</p>');
    });
    test('snake_case is not emphasis', () => {
        assert.equal(renderMarkdown('sensor.outdoor_temp_c'), '<p>sensor.outdoor_temp_c</p>');
    });
    test('lists', () => {
        assert.equal(renderMarkdown('- one\n- two\n\n1. first\n2. second'), '<ul><li>one</li><li>two</li></ul><ol><li>first</li><li>second</li></ol>');
        assert.equal(renderMarkdown('text\n* item\nmore'), '<p>text</p><ul><li>item</li></ul><p>more</p>');
    });
    test('links', () => {
        assert.equal(
            renderMarkdown('[docs](https://example.com/a?b=1&c=2) and [home](/lovelace)'),
            '<p><a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">docs</a> and ' +
                '<a href="/lovelace" target="_blank" rel="noopener noreferrer">home</a></p>'
        );
    });
    test('an image in markdown is its alternative text', () => {
        assert.equal(renderMarkdown('![logo](https://example.com/x.png)'), '<p>logo</p>');
    });
    test('fenced code is kept as written', () => {
        assert.equal(renderMarkdown('```\nif a < b:\n    **x**\n```\nafter'), '<pre><code>if a &lt; b:\n    **x**</code></pre><p>after</p>');
        assert.equal(renderMarkdown('```\nunclosed'), '<pre><code>unclosed</code></pre>');
    });
    test('empty input', () => {
        assert.equal(renderMarkdown(''), '');
        assert.equal(renderMarkdown(null), '');
    });
});

describe('safeUrl', () => {
    test('allows web addresses, mail and paths on this server', () => {
        assert.equal(safeUrl('https://example.com'), 'https://example.com');
        assert.equal(safeUrl(' HTTP://example.com '), 'HTTP://example.com');
        assert.equal(safeUrl('mailto:a@example.com'), 'mailto:a@example.com');
        assert.equal(safeUrl('/api/haanim/assets/a/b.png'), '/api/haanim/assets/a/b.png');
    });
    test('refuses everything else', () => {
        for (const url of ['javascript:alert(1)', 'data:text/html,x', '//evil.example/x', 'vbscript:x', 'file.png', '', null]) {
            assert.equal(safeUrl(url), null);
        }
    });
});

describe('renderBlock', () => {
    test('text', () => {
        assert.equal(renderBlock({ id: 'intro', type: 'text', markdown: '# Hi' }), '<div class="block block-text" data-block="intro"><h1>Hi</h1></div>');
    });
    test('value with and without a unit', () => {
        assert.match(renderBlock({ id: 'v', type: 'value', label: 'Alerts <today>', value: 3, unit: '' }), /<span class="label">Alerts &lt;today&gt;<\/span><span class="value">3<\/span>/);
        assert.match(renderBlock({ id: 'v', type: 'value', label: 'T', value: 21.5, unit: '°C' }), /<span class="value">21.5 <span class="unit">°C<\/span><\/span>/);
        assert.match(renderBlock({ id: 'v', type: 'value', label: 'On', value: false, unit: '' }), /<span class="value">false<\/span>/);
    });
    test('entity shows the live state', () => {
        const states = { 'sensor.temperature': { state: '21.4', attributes: { friendly_name: 'Temperature', unit_of_measurement: '°C' } } };
        const html = renderBlock({ id: 't', type: 'entity', entity_id: 'sensor.temperature' }, { states });
        assert.match(html, /<span class="label">Temperature<\/span>/);
        assert.match(html, /data-entity="sensor.temperature">21.4 <span class="unit">°C<\/span>/);
    });
    test('entity that does not exist is unavailable', () => {
        const html = renderBlock({ id: 't', type: 'entity', entity_id: 'sensor.gone' }, { states: {} });
        assert.match(html, /<span class="label">sensor.gone<\/span>/);
        assert.match(html, />unavailable<\/span>/);
        assert.match(renderBlock({ id: 't', type: 'entity', entity_id: 'sensor.gone' }), />unavailable</);
    });
    test('entity without a unit or name', () => {
        const html = renderBlock({ id: 't', type: 'entity', entity_id: 'light.a' }, { states: { 'light.a': { state: 'on' } } });
        assert.match(html, /<span class="label">light.a<\/span><span class="value" data-entity="light.a">on<\/span>/);
    });
    test('image from a URL', () => {
        assert.match(renderBlock({ id: 'i', type: 'image', url: 'https://example.com/a.png', alt: 'A "pic"' }), /<img src="https:\/\/example.com\/a.png" alt="A &quot;pic&quot;">/);
    });
    test('image from an unsafe URL is not shown', () => {
        const html = renderBlock({ id: 'i', type: 'image', url: 'javascript:alert(1)', alt: 'x' });
        assert.doesNotMatch(html, /<img|javascript/);
        assert.match(html, /image-pending">x</);
    });
    test('image from an asset waits until it is loaded', () => {
        const block = { id: 'i', type: 'image', asset: 'logo.png', url: '/api/haanim/assets/a/logo.png', alt: 'Logo' };
        assert.match(renderBlock(block, { images: {} }), /<span class="image-pending">Logo<\/span>/);
        assert.match(renderBlock(block), /image-pending/);
        assert.match(renderBlock(block, { images: { [block.url]: 'blob:abc' } }), /<img src="blob:abc" alt="Logo">/);
    });
    test('button carries its action, data and confirmation', () => {
        const html = renderBlock({ id: 'b', type: 'button', label: 'Reset <it>', action: 'reset_alerts', confirm: 'Reset "all"?', data: { room: 'hall' } });
        assert.match(html, /data-haanim="run" data-action="reset_alerts"/);
        assert.match(html, /data-payload="\{&quot;room&quot;:&quot;hall&quot;\}"/);
        assert.match(html, /data-confirm="Reset &quot;all&quot;\?"/);
        assert.match(html, />Reset &lt;it&gt;<\/button>/);
    });
    test('button without confirmation or data', () => {
        const html = renderBlock({ id: 'b', type: 'button', label: 'Go', action: 'go', confirm: null });
        assert.doesNotMatch(html, /data-confirm/);
        assert.match(html, /data-payload="\{\}"/);
    });
    test('unknown block type draws nothing', () => {
        assert.equal(renderBlock({ id: 'x', type: 'video' }), '');
    });
    test('the id is escaped', () => {
        assert.match(renderBlock({ id: '"><b>', type: 'text', markdown: 'x' }), /data-block="&quot;&gt;&lt;b&gt;"/);
    });
});

describe('renderContent', () => {
    test('blocks in order', () => {
        const html = renderContent([
            { id: 'a', type: 'text', markdown: 'one' },
            { id: 'b', type: 'value', label: 'L', value: 1, unit: '' },
        ]);
        assert.ok(html.indexOf('data-block="a"') < html.indexOf('data-block="b"'));
    });
    test('no blocks', () => {
        assert.equal(renderContent([]), '');
        assert.equal(renderContent(undefined), '');
    });
});

describe('stateLabel', () => {
    test("the design's words for each state", () => {
        assert.deepEqual(stateLabel('on', true), { label: 'Running', css: 'running' });
        assert.deepEqual(stateLabel('off', true), { label: 'Stopped', css: 'stopped' });
        assert.deepEqual(stateLabel('off', false), { label: 'Disabled', css: 'disabled' });
        assert.deepEqual(stateLabel('error', true), { label: 'Error', css: 'error' });
        assert.deepEqual(stateLabel('unavailable', true), { label: 'Unavailable', css: 'unavailable' });
    });
});

describe('renderHeader', () => {
    const controls = (automation) => [...renderHeader(automation).matchAll(/data-haanim="(\w+)"/g)].map((match) => match[1]);
    test('name, state and message', () => {
        const html = renderHeader({ id: 'climate', name: 'Climate <1>', state: 'on', enabled: true, message: 'All <good>' });
        assert.match(html, /<span class="name">Climate &lt;1&gt;<\/span>/);
        assert.match(html, /<span class="state state-running">Running<\/span>/);
        assert.match(html, /<div class="message">All &lt;good&gt;<\/div>/);
    });
    test('the id stands in for a missing name, and no message draws none', () => {
        const html = renderHeader({ id: 'climate', state: 'off', enabled: true, message: null });
        assert.match(html, /<span class="name">climate<\/span>/);
        assert.doesNotMatch(html, /class="message"/);
    });
    test('the controls that apply to each state', () => {
        assert.deepEqual(controls({ state: 'on', enabled: true }), ['disable', 'stop', 'restart']);
        assert.deepEqual(controls({ state: 'off', enabled: true }), ['disable', 'start']);
        assert.deepEqual(controls({ state: 'off', enabled: false }), ['enable']);
        assert.deepEqual(controls({ state: 'error', enabled: true }), ['disable', 'start']);
        assert.deepEqual(controls({ state: 'error', enabled: false }), ['enable']);
    });
});

describe('renderActions', () => {
    test('a run button per action', () => {
        const html = renderActions([{ name: 'alert', aliases: [], description: 'Count <one>' }, { name: 'reset', aliases: [], description: '' }]);
        assert.match(html, /<summary>Actions \(2\)<\/summary>/);
        assert.match(html, /data-haanim="run" data-action="alert"/);
        assert.match(html, /<span class="description">Count &lt;one&gt;<\/span>/);
        assert.equal((html.match(/class="description"/g) || []).length, 1);
        assert.doesNotMatch(html, /<details[^>]* open/);
    });
    test('none, and open', () => {
        assert.match(renderActions([], true), /<details class="section" data-section="actions" open>.*No actions/);
        assert.match(renderActions(undefined), /Actions \(0\)/);
    });
});

describe('renderLog', () => {
    test('records with their level', () => {
        const html = renderLog([
            { time: '2025-01-06T08:00:00+00:00', level: 'INFO', message: 'hello <b>' },
            { time: '2025-01-06T08:00:01+00:00', level: 'ERROR', message: 'failed', traceback: 'Traceback <x>' },
        ]);
        assert.match(html, /<summary>Log \(2\)<\/summary>/);
        assert.match(html, /class="record level-info"/);
        assert.match(html, /class="record level-error"/);
        assert.match(html, /<span class="text">hello &lt;b&gt;<\/span>/);
        assert.match(html, /<pre class="traceback">Traceback &lt;x&gt;<\/pre>/);
    });
    test('a level cannot carry markup into the class', () => {
        const html = renderLog([{ time: '', level: 'x" onclick="y', message: 'm' }]);
        assert.match(html, /class="record level-xonclicky"/);
    });
    test('only the latest records are drawn', () => {
        const records = Array.from({ length: MAX_LOG_RECORDS + 5 }, (_, index) => ({ time: '', level: 'INFO', message: `m${index}` }));
        const html = renderLog(records, true);
        assert.equal((html.match(/class="record/g) || []).length, MAX_LOG_RECORDS);
        assert.doesNotMatch(html, />m4</);
        assert.match(html, />m5</);
        assert.match(html, / open>/);
    });
    test('no records', () => {
        assert.match(renderLog([]), /No log records/);
        assert.match(renderLog(undefined), /Log \(0\)/);
        assert.match(renderLog([{ message: 'm' }]), /level-info/);
    });
});

describe('formatTime', () => {
    test('formats a time, passes through what is not one', () => {
        assert.equal(formatTime(null), '');
        assert.equal(formatTime('not a time'), 'not a time');
        assert.notEqual(formatTime('2025-01-06T08:00:00+00:00'), '');
        assert.ok(formatTime('2025-01-06T08:00:00+00:00', true).length > formatTime('2025-01-06T08:00:00+00:00').length);
    });
});

describe('renderCard', () => {
    const automation = { id: 'climate', name: 'Climate', state: 'on', enabled: true, message: null, actions: [{ name: 'alert', aliases: [], description: '' }] };
    test('header, content, actions and log in that order', () => {
        const html = renderCard({ automation, blocks: [{ id: 'a', type: 'text', markdown: 'hi' }], records: [], open: { log: true } });
        const order = ['class="header"', 'class="content"', 'data-section="actions"', 'data-section="log"'].map((part) => html.indexOf(part));
        assert.deepEqual([...order].sort((a, b) => a - b), order);
        assert.ok(order.every((index) => index >= 0));
        assert.match(html, /data-section="log" open/);
    });
    test('the fixed parts are shown without content', () => {
        const html = renderCard({ automation: { ...automation, state: 'off' }, blocks: [], records: [] });
        assert.doesNotMatch(html, /class="content"/);
        assert.match(html, /class="header"/);
        assert.match(html, /data-section="actions"/);
    });
    test('loading and error', () => {
        assert.match(renderCard({ automation: null }), /Loading/);
        assert.equal(renderCard({ error: 'No <such> automation' }), '<div class="card-error">No &lt;such&gt; automation</div>');
    });
});

describe('serviceCall', () => {
    test('a run button', () => {
        assert.deepEqual(serviceCall({ haanim: 'run', action: 'reset', payload: '{"room":"hall"}', confirm: 'Sure?' }, 'climate'), {
            service: 'run_action',
            data: { automation_id: 'climate', action: 'reset', data: { room: 'hall' } },
            confirm: 'Sure?',
        });
    });
    test('a run button without data, or with broken data', () => {
        assert.deepEqual(serviceCall({ haanim: 'run', action: 'go' }, 'a').data, { automation_id: 'a', action: 'go', data: {} });
        assert.deepEqual(serviceCall({ haanim: 'run', action: 'go', payload: '{broken' }, 'a').data.data, {});
        assert.equal(serviceCall({ haanim: 'run', action: 'go' }, 'a').confirm, null);
    });
    for (const service of ['enable', 'disable', 'start', 'stop', 'restart', 'reload']) {
        test(`the ${service} control`, () => {
            assert.deepEqual(serviceCall({ haanim: service }, 'climate'), { service, data: { automation_id: 'climate' }, confirm: null });
        });
    }
    test('anything else is not a control', () => {
        assert.equal(serviceCall({ haanim: 'delete_everything' }, 'a'), null);
        assert.equal(serviceCall({}, 'a'), null);
        assert.equal(serviceCall(undefined, 'a'), null);
    });
});

describe('panel pages', () => {
    test('the list', () => {
        const html = renderList([
            { id: 'climate', name: 'Climate', version: '1.2.0', state: 'on', enabled: true, message: 'ok <now>' },
            { id: 'broken', name: 'broken', version: '', state: 'error', enabled: true, message: 'main.py:1' },
            { id: 'off', name: '', state: 'off', enabled: false, message: null },
        ]);
        assert.match(html, /data-open="climate"/);
        assert.match(html, /<td>1.2.0<\/td>/);
        assert.match(html, /state-running">Running/);
        assert.match(html, /state-error">Error/);
        assert.match(html, /state-disabled">Disabled/);
        assert.match(html, /ok &lt;now&gt;/);
        assert.match(html, /<td class="name">off<div class="id">off<\/div>/);
    });
    test('the empty list', () => {
        assert.match(renderList([]), /No automations yet/);
        assert.match(renderList(null), /No automations yet/);
    });
    test('the detail', () => {
        const html = renderDetail({
            description: 'Keeps it <cool>',
            author: 'Ada',
            version: '1.2.0',
            running_actions: ['alert', 'reset'],
            last_action: 'alert',
            last_action_time: '2025-01-06T08:00:00+00:00',
            last_run: '2025-01-06T07:00:00+00:00',
            last_error: { action: 'boom', error_type: 'ValueError', message: 'bad' },
        });
        assert.match(html, /Description<\/span><span>Keeps it &lt;cool&gt;/);
        assert.match(html, /Author<\/span><span>Ada/);
        assert.match(html, /Current action<\/span><span>alert, reset/);
        assert.match(html, /Last error<\/span><span>boom: ValueError: bad/);
        assert.match(html, /Last started/);
    });
    test('the detail leaves out what is not there', () => {
        assert.equal(renderDetail({ description: '', author: '', version: '', running_actions: [], last_error: null }), '<div class="detail"></div>');
        assert.equal(renderDetail({}), '<div class="detail"></div>');
    });
    test('the configuration', () => {
        const html = renderConfig({ version: '0.1.0', options: { automation_path: '/config/haanim', import_allowlist: ['a', 'b'], allow_all_imports: false } });
        assert.match(html, /Version<\/span><span>0.1.0/);
        assert.match(html, /<td>automation path<\/td><td>\/config\/haanim<\/td>/);
        assert.match(html, /<td>import allowlist<\/td><td>a, b<\/td>/);
        assert.match(html, /<td>allow all imports<\/td><td>false<\/td>/);
        assert.match(renderConfig(null), /Loading/);
        assert.match(renderConfig({ version: '1' }), /<tbody><\/tbody>/);
    });
});

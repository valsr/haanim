import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
    MAX_LOG_RECORDS,
    CARD_PARTS,
    MAX_ROW_CELLS,
    PANEL_PATH,
    automationPath,
    escapeHtml,
    formatNumber,
    formatTime,
    iconColor,
    isActive,
    parseRoute,
    renderActionList,
    renderActionsDialog,
    renderBlock,
    renderCard,
    renderConfig,
    renderContent,
    renderControls,
    renderDetail,
    renderHeader,
    renderList,
    renderLog,
    renderMarkdown,
    renderToolbar,
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
    test('image is at the left unless the block says otherwise', () => {
        const image = (extra) => renderBlock({ id: 'i', type: 'image', url: '/a.png', alt: '', ...extra });
        assert.match(image({}), /^<div class="block block-image align-left" data-block="i"><img src="\/a.png" alt=""><\/div>$/);
        assert.match(image({ align: 'center' }), /class="block block-image align-center"/);
        assert.match(image({ align: 'right' }), /class="block block-image align-right"/);
        assert.match(image({ align: 'top"><script>' }), /class="block block-image align-left" data-block/);
    });
    test('image with a width, a height or both', () => {
        const image = (extra) => renderBlock({ id: 'i', type: 'image', url: '/a.png', alt: 'A', ...extra });
        assert.match(image({ width: '120px' }), /<img src="\/a.png" alt="A" style="width: 120px">/);
        assert.match(image({ height: '80px' }), /alt="A" style="height: 80px">/);
        assert.match(image({ width: '50%', height: '80px' }), /alt="A" style="width: 50%; height: 80px">/);
        assert.doesNotMatch(image({ width: null, height: null }), /style=/);
    });
    test('image size that is not one is left out', () => {
        const html = renderBlock({ id: 'i', type: 'image', url: '/a.png', alt: '', width: '10px; background: url(x)', height: 'calc(1px)' });
        assert.doesNotMatch(html, /style=|url\(|calc/);
        assert.doesNotMatch(renderBlock({ id: 'i', type: 'image', url: '/a.png', alt: '', width: 120 + 'em' }), /style=/);
    });
    test('image with a caption, also while it is not loaded', () => {
        const block = { id: 'i', type: 'image', asset: 'logo.png', url: '/api/haanim/assets/a/logo.png', alt: 'Logo', caption: 'The <logo>', align: 'center' };
        assert.match(renderBlock(block, { images: { [block.url]: 'blob:abc' } }), /<img src="blob:abc" alt="Logo"><div class="caption">The &lt;logo&gt;<\/div><\/div>$/);
        assert.match(renderBlock(block), /align-center" data-block="i"><span class="image-pending">Logo<\/span><div class="caption">The &lt;logo&gt;<\/div>/);
        assert.doesNotMatch(renderBlock({ ...block, caption: '' }), /class="caption"/);
        assert.match(renderBlock({ id: 'i', type: 'image', url: 'javascript:x' }), /<span class="image-pending"><\/span><\/div>$/);
        assert.match(renderBlock({ id: 'i', type: 'image', url: '/a.png' }), /<img src="\/a.png" alt="">/);
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

describe('icon block', () => {
    const fan = (state, attributes = {}) => ({ 'fan.bedroom': { state, attributes: { friendly_name: 'Bedroom fan', ...attributes } } });
    const block = (extra = {}) => ({ id: 'fan', type: 'icon', entity_id: 'fan.bedroom', icon: null, label: null, color: null, spin: false, follow_entity: true, ...extra });

    test('following an entity: its own icon, its name and its state', () => {
        const html = renderBlock(block(), { states: fan('on') });
        assert.match(html, /^<div class="block block-icon" data-block="fan" data-more-info="fan.bedroom">/);
        assert.match(html, /<ha-state-icon data-state-icon="fan.bedroom"><\/ha-state-icon>/);
        assert.match(html, /<span class="label">Bedroom fan<\/span>/);
        assert.match(html, /<span class="value">on<\/span>/);
    });
    test('following an entity: lit while it is active, dimmed while it is not', () => {
        assert.match(renderBlock(block(), { states: fan('on') }), /class="icon active" style="color: var\(--state-active-color, var\(--primary-color\)\)"/);
        const off = renderBlock(block(), { states: fan('off') });
        assert.match(off, /class="icon inactive">/);
        assert.doesNotMatch(off, /style=/);
    });
    test('following an entity: it turns only while the entity is active', () => {
        assert.match(renderBlock(block({ spin: true }), { states: fan('on') }), /class="icon active spin"/);
        assert.match(renderBlock(block({ spin: true }), { states: fan('off') }), /class="icon inactive">/);
        assert.doesNotMatch(renderBlock(block(), { states: fan('on') }), /spin/);
    });
    test('following an entity with an icon and a colour of the automation', () => {
        const html = renderBlock(block({ icon: 'mdi:fan', color: 'success', label: 'Fan' }), { states: fan('on') });
        assert.match(html, /<ha-icon icon="mdi:fan"><\/ha-icon>/);
        assert.doesNotMatch(html, /ha-state-icon/);
        assert.match(html, /style="color: var\(--success-color, #4caf50\)"/);
        assert.match(html, /<span class="label">Fan<\/span>/);
        assert.doesNotMatch(renderBlock(block({ color: 'success' }), { states: fan('off') }), /style=/, 'the colour is for the active state');
    });
    test('an entity that is not there is inactive and unavailable', () => {
        const html = renderBlock(block({ spin: true }), { states: {} });
        assert.match(html, /class="icon inactive">/);
        assert.match(html, /<span class="label">fan.bedroom<\/span><span class="value">unavailable<\/span>/);
        assert.match(renderBlock(block()), /unavailable/);
    });
    test('not following: exactly what the block says, whatever the entity does', () => {
        const fixed = block({ follow_entity: false, icon: 'mdi:fan', color: '#ff0000', spin: true, label: 'Always on' });
        for (const state of ['on', 'off']) {
            const html = renderBlock(fixed, { states: fan(state) });
            assert.match(html, /class="icon active spin" style="color: #ff0000"><ha-icon icon="mdi:fan">/);
            assert.match(html, /<span class="label">Always on<\/span><\/div>$/);
            assert.doesNotMatch(html, /class="value"/);
        }
    });
    test('without an entity: an icon, with or without label and colour', () => {
        const html = renderBlock({ id: 'i', type: 'icon', entity_id: null, icon: 'mdi:home', label: null, color: null, spin: false, follow_entity: false });
        assert.equal(html, '<div class="block block-icon" data-block="i"><span class="icon active"><ha-icon icon="mdi:home"></ha-icon></span></div>');
    });
    test('an icon or colour that is not one draws nothing harmful', () => {
        const html = renderBlock(block({ follow_entity: false, icon: 'x" onload="alert(1)', color: 'red; background: url(x)' }), { states: fan('on') });
        assert.doesNotMatch(html, /onload|background|style=|<ha-icon/);
        assert.match(renderBlock(block({ label: '<b>x</b>' }), { states: fan('on') }), /&lt;b&gt;x&lt;\/b&gt;/);
    });
    test('which states are active', () => {
        for (const state of ['on', 'open', 'home', 'playing', 'heat', 'above_horizon', '42']) assert.equal(isActive({ state }), true, state);
        for (const state of ['off', 'OFF', 'closed', 'idle', 'standby', 'not_home', 'locked', 'docked', 'below_horizon', 'paused', 'disarmed', 'unavailable', 'unknown', '', '0']) {
            assert.equal(isActive({ state }), false, state);
        }
        assert.equal(isActive(undefined), false);
        assert.equal(isActive(null), false);
    });
    test('colours', () => {
        assert.equal(iconColor('primary'), 'var(--primary-color)');
        assert.equal(iconColor('error'), 'var(--error-color, #f44336)');
        assert.equal(iconColor('red'), 'red');
        assert.equal(iconColor('dark-orange'), 'dark-orange');
        assert.equal(iconColor('#0af'), '#0af');
        for (const bad of ['', null, undefined, 'red;x', 'url(x)', '#12', 'rgb(1,2,3)']) {
            assert.equal(iconColor(bad), null, String(bad));
        }
        assert.equal(iconColor('constructor'), 'constructor', 'a word that is no theme colour is passed on as a colour name');
    });
});

describe('gauge block', () => {
    const gauge = (extra = {}) => ({ id: 'g', type: 'gauge', value: 42, entity_id: null, min: 0, max: 100, label: null, unit: null, kind: 'bar', color: null, ...extra });
    const battery = (state, attributes = {}) => ({ 'sensor.battery': { state, attributes } });

    test('a progress bar is filled as far as the value is along the range', () => {
        const html = renderBlock(gauge({ label: 'Done <so far>', unit: '%' }));
        assert.match(html, /^<div class="block block-gauge" data-block="g"><div class="gauge-head">/);
        assert.match(html, /<span class="label">Done &lt;so far&gt;<\/span><span class="value">42 <span class="unit">%<\/span><\/span>/);
        assert.match(html, /<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="42">/);
        assert.match(html, /<div class="fill" style="width: 42.0%; background: var\(--primary-color\)">/);
        assert.doesNotMatch(html, /data-more-info/);
    });
    test('the range need not start at zero', () => {
        assert.match(renderBlock(gauge({ value: 20, min: 10, max: 50 })), /width: 25.0%/);
        assert.match(renderBlock(gauge({ value: -5, min: -10, max: 10 })), /width: 25.0%/);
    });
    test('a value outside the range is shown as it is, with the gauge empty or full', () => {
        const over = renderBlock(gauge({ value: 130 }));
        assert.match(over, /width: 100.0%/);
        assert.match(over, /<span class="value">130<\/span>/);
        assert.match(renderBlock(gauge({ value: -3 })), /width: 0.0%/);
    });
    test('numbers are shown with at most two decimals', () => {
        assert.equal(formatNumber(42), '42');
        assert.equal(formatNumber(21.456), '21.46');
        assert.equal(formatNumber(0.1 + 0.2), '0.3');
        assert.match(renderBlock(gauge({ value: 33.3333 })), /<span class="value">33.33<\/span>/);
    });
    test('the colour is a theme colour or a plain one, and nothing else', () => {
        assert.match(renderBlock(gauge({ color: 'success' })), /background: var\(--success-color, #4caf50\)"/);
        assert.match(renderBlock(gauge({ color: '#ff0000' })), /background: #ff0000"/);
        assert.match(renderBlock(gauge({ color: 'red; x: url(y)' })), /background: var\(--primary-color\)"/);
    });
    test('following an entity: its state, its name and its unit', () => {
        const states = battery('87.5', { friendly_name: 'Battery', unit_of_measurement: '%' });
        const html = renderBlock(gauge({ value: null, entity_id: 'sensor.battery' }), { states });
        assert.match(html, /data-block="g" data-more-info="sensor.battery">/);
        assert.match(html, /<span class="label">Battery<\/span><span class="value">87.5 <span class="unit">%<\/span>/);
        assert.match(html, /width: 87.5%/);
    });
    test("the block's own label and unit win over the entity's", () => {
        const states = battery('50', { friendly_name: 'Battery', unit_of_measurement: '%' });
        const html = renderBlock(gauge({ value: null, entity_id: 'sensor.battery', label: 'Phone', unit: 'pct' }), { states });
        assert.match(html, /<span class="label">Phone<\/span><span class="value">50 <span class="unit">pct<\/span>/);
        assert.match(renderBlock(gauge({ value: null, entity_id: 'sensor.battery', unit: '' }), { states }), /<span class="value">50<\/span>/);
    });
    test('an entity without a name or unit', () => {
        const html = renderBlock(gauge({ value: null, entity_id: 'sensor.battery' }), { states: battery('10') });
        assert.match(html, /<span class="label">sensor.battery<\/span><span class="value">10<\/span>/);
    });
    test('a state that is not a number leaves the gauge empty and is shown as text', () => {
        const states = battery('unknown', { unit_of_measurement: '%' });
        const html = renderBlock(gauge({ value: null, entity_id: 'sensor.battery' }), { states });
        assert.match(html, /<span class="value">unknown<\/span>/);
        assert.match(html, /width: 0.0%/);
        assert.doesNotMatch(html, /aria-valuenow/);
        assert.match(renderBlock(gauge({ value: null, entity_id: 'sensor.gone' })), /<span class="value">unavailable<\/span>/);
        assert.match(renderBlock(gauge({ value: null, entity_id: 'sensor.battery' }), { states: battery('') }), /width: 0.0%/);
    });
    test('a gauge with neither a value nor an entity is empty', () => {
        const html = renderBlock(gauge({ value: null }));
        assert.match(html, /<span class="value"><\/span>/);
        assert.match(html, /width: 0.0%/);
        assert.match(renderBlock(gauge({ value: true })), /width: 0.0%/);
    });
    test('a range that is not one draws an empty gauge', () => {
        assert.match(renderBlock(gauge({ min: 5, max: 5 })), /width: 0.0%/);
    });
    test('a dial fills its arc', () => {
        const html = renderBlock(gauge({ kind: 'dial', value: 50, label: 'Load', unit: '%', color: 'warning' }));
        assert.match(html, /<svg class="dial" viewBox="0 0 120 70" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="50">/);
        assert.match(html, /<path class="dial-track" d="M 10 60 A 50 50 0 0 1 110 60"><\/path>/);
        assert.match(html, /<path class="dial-fill" d="M 10 60 A 50 50 0 0 1 110 60" style="stroke: var\(--warning-color, #ff9800\)" stroke-dasharray="78.54 157.08">/);
        assert.match(html, /<text class="dial-value" x="60" y="58" text-anchor="middle">50<tspan class="dial-unit"> %<\/tspan><\/text>/);
        assert.match(html, /<\/svg><span class="label">Load<\/span><\/div>$/);
    });
    test('a dial without a label or unit, and one whose entity has no number', () => {
        const plain = renderBlock(gauge({ kind: 'dial', value: 100 }));
        assert.match(plain, /stroke-dasharray="157.08 157.08"/);
        assert.match(plain, />100<\/text><\/svg><\/div>$/);
        const html = renderBlock(gauge({ kind: 'dial', value: null, entity_id: 'sensor.battery' }), { states: battery('unavailable', { unit_of_measurement: '%' }) });
        assert.match(html, /stroke-dasharray="0.00 157.08"/);
        assert.match(html, />unavailable<\/text>/);
        assert.match(html, /<span class="label">sensor.battery<\/span>/);
    });
});

describe('badge block', () => {
    const badge = (extra = {}) => ({ id: 'b', type: 'badge', text: 'OK', entity_id: null, icon: null, color: null, ...extra });

    test('a text in a pill', () => {
        assert.equal(
            renderBlock(badge()),
            '<div class="block block-badge" data-block="b"><span class="badge"><span class="badge-text">OK</span></span></div>'
        );
        assert.match(renderBlock(badge({ text: '<b>hot</b>' })), /<span class="badge-text">&lt;b&gt;hot&lt;\/b&gt;<\/span>/);
    });
    test('with an icon and a colour', () => {
        const html = renderBlock(badge({ icon: 'mdi:check', color: 'success' }));
        assert.match(html, /<span class="badge" style="background: var\(--success-color, #4caf50\)"><ha-icon icon="mdi:check"><\/ha-icon><span/);
    });
    test('an icon or colour that is not one is left out', () => {
        const html = renderBlock(badge({ icon: 'mdi:x"><script>', color: 'red;x' }));
        assert.doesNotMatch(html, /ha-icon|style=|script/);
    });
    test('following an entity: its state, and a click opens its dialog', () => {
        const html = renderBlock(badge({ text: null, entity_id: 'lock.door' }), { states: { 'lock.door': { state: 'locked' } } });
        assert.match(html, /data-block="b" data-more-info="lock.door"><span class="badge"><span class="badge-text">locked<\/span>/);
        assert.match(renderBlock(badge({ text: null, entity_id: 'lock.gone' })), /<span class="badge-text">unavailable<\/span>/);
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

describe('layout', () => {
    const blocks = [
        { id: 'a', type: 'text', markdown: 'A' },
        { id: 'b', type: 'text', markdown: 'B' },
        { id: 'c', type: 'text', markdown: 'C' },
        { id: 'd', type: 'text', markdown: 'D' },
    ];
    const ids = (html) => [...html.matchAll(/data-block="(\w+)"/g)].map((match) => match[1]);

    test('a row of one cell is the block itself', () => {
        const html = renderContent(blocks, {}, [{ cells: 1, elements: ['b'] }, { cells: 1, elements: ['a'] }]);
        assert.deepEqual(ids(html), ['b', 'a']);
        assert.doesNotMatch(html, /class="row"|class="cell"/);
    });
    test('a split row is a grid with a cell per element', () => {
        const html = renderContent(blocks, {}, [{ cells: 3, elements: ['a', 'b', 'c'] }, { cells: 1, elements: ['d'] }]);
        assert.match(html, /^<div class="row" style="--cells: 3"><div class="cell"><div class="block block-text" data-block="a">/);
        assert.equal((html.match(/class="cell"/g) || []).length, 3);
        assert.deepEqual(ids(html), ['a', 'b', 'c', 'd']);
        assert.match(html, /<\/div><\/div><div class="block block-text" data-block="d">/);
    });
    test('cells nobody filled stay empty', () => {
        const html = renderContent(blocks, {}, [{ cells: 3, elements: ['a'] }]);
        assert.equal((html.match(/<div class="cell"><\/div>/g) || []).length, 2);
        assert.deepEqual(ids(html), ['a']);
    });
    test('more elements than cells: the extra ones are not drawn', () => {
        const html = renderContent(blocks, {}, [{ cells: 2, elements: ['a', 'b', 'c'] }]);
        assert.deepEqual(ids(html), ['a', 'b']);
    });
    test('the order is the layout\'s, and a block it does not name is not drawn', () => {
        assert.deepEqual(ids(renderContent(blocks, {}, [{ cells: 2, elements: ['d', 'a'] }])), ['d', 'a']);
        assert.equal(renderContent(blocks, {}, []), '');
    });
    test('a row without anything to draw is left out', () => {
        assert.equal(renderContent(blocks, {}, [{ cells: 3, elements: [] }, { cells: 2, elements: ['missing'] }, { cells: 1 }]), '');
    });
    test('the number of cells is kept within one to six', () => {
        assert.equal(MAX_ROW_CELLS, 6);
        assert.match(renderContent(blocks, {}, [{ cells: 40, elements: ['a', 'b'] }]), /--cells: 6"/);
        assert.match(renderContent(blocks, {}, [{ cells: '3; color: red', elements: ['a', 'b'] }]), /^<div class="block/);
        assert.doesNotMatch(renderContent(blocks, {}, [{ cells: -2, elements: ['a'] }]), /class="row"/);
    });
    test('without a layout every block has a row of its own', () => {
        assert.deepEqual(ids(renderContent(blocks, {}, null)), ['a', 'b', 'c', 'd']);
        assert.deepEqual(ids(renderContent(blocks)), ['a', 'b', 'c', 'd']);
    });
    test('the card draws its content by the layout', () => {
        const automation = { id: 'x', name: 'X', state: 'on', enabled: true, actions: [] };
        const html = renderCard({ automation, blocks, layout: [{ cells: 2, elements: ['c', 'a'] }] });
        assert.match(html, /<div class="content"><div class="row" style="--cells: 2">/);
        assert.deepEqual(ids(html), ['c', 'a']);
    });
});

describe('stateLabel', () => {
    test('a running automation shows the action it is running, or Idle', () => {
        assert.deepEqual(stateLabel('on', true), { label: 'Idle', css: 'idle' });
        assert.deepEqual(stateLabel('on', true, []), { label: 'Idle', css: 'idle' });
        assert.deepEqual(stateLabel('on', true, null), { label: 'Idle', css: 'idle' });
        assert.deepEqual(stateLabel('on', true, ['toggle_frame']), { label: 'toggle_frame', css: 'running' });
    });
    test('several actions at once: the first and how many more', () => {
        assert.deepEqual(stateLabel('on', true, ['count', 'reset']), { label: 'count +1', css: 'running' });
        assert.deepEqual(stateLabel('on', true, ['a', 'b', 'c']), { label: 'a +2', css: 'running' });
    });
    test('the lifecycle handlers are shown by their plain names', () => {
        assert.equal(stateLabel('on', true, ['__startup__']).label, 'startup');
        assert.equal(stateLabel('on', true, ['__shutdown__']).label, 'shutdown');
    });
    test('an automation that is not running shows why, whatever is said to be running', () => {
        assert.deepEqual(stateLabel('off', true, ['count']), { label: 'Stopped', css: 'stopped' });
        assert.deepEqual(stateLabel('off', false), { label: 'Disabled', css: 'disabled' });
        assert.deepEqual(stateLabel('error', true), { label: 'Error', css: 'error' });
        assert.deepEqual(stateLabel('unavailable', true), { label: 'Unavailable', css: 'unavailable' });
    });
});

describe('renderHeader', () => {
    test('name, state and message', () => {
        const html = renderHeader({ id: 'climate', name: 'Climate <1>', state: 'on', enabled: true, message: 'All <good>' });
        assert.match(html, /<span class="name">Climate &lt;1&gt;<\/span>/);
        assert.match(html, /<span class="state state-idle">Idle<\/span>/);
        assert.match(html, /<div class="message">All &lt;good&gt;<\/div>/);
    });
    test('the id stands in for a missing name, and no message draws none', () => {
        const html = renderHeader({ id: 'climate', state: 'off', enabled: true, message: null });
        assert.match(html, /<span class="name">climate<\/span>/);
        assert.doesNotMatch(html, /class="message"/);
    });
    test('the title the automation set replaces the name', () => {
        const automation = { id: 'climate', name: 'Climate', state: 'on', enabled: true };
        assert.match(renderHeader(automation, 'Climate: 3 <alerts>'), /<span class="name">Climate: 3 &lt;alerts&gt;<\/span>/);
        assert.match(renderHeader(automation, null), /<span class="name">Climate<\/span>/);
        assert.match(renderHeader(automation, ''), /<span class="name">Climate<\/span>/);
    });
    test('the state shows the action that is running, as text', () => {
        const automation = { id: 'climate', name: 'Climate', state: 'on', enabled: true, running_actions: ['toggle_frame'] };
        assert.match(renderHeader(automation), /<span class="state state-running">toggle_frame<\/span>/);
        assert.match(renderHeader({ ...automation, running_actions: ['<b>x</b>'] }), /state-running">&lt;b&gt;x&lt;\/b&gt;</);
        assert.match(renderHeader({ ...automation, state: 'off' }), /state-stopped">Stopped</);
    });
    test('the header has no controls', () => {
        for (const state of ['on', 'off', 'error']) {
            const html = renderHeader({ id: 'climate', name: 'Climate', state, enabled: true });
            assert.doesNotMatch(html, /<button|data-haanim/);
        }
    });
});

describe('parts of the card the automation hides', () => {
    const automation = { id: 'climate', name: 'Climate', state: 'on', enabled: true, message: 'All good', actions: [{ name: 'alert', description: '' }] };
    const all = { title: true, state: true, message: true, actions: true, log: true };
    test('the five parts', () => {
        assert.deepEqual(CARD_PARTS, ['title', 'state', 'message', 'actions', 'log']);
    });
    test('everything is shown without options, and with all of them on', () => {
        for (const options of [null, undefined, {}, all]) {
            const html = renderCard({ automation, blocks: [], options });
            assert.match(html, /class="name"/);
            assert.match(html, /class="state /);
            assert.match(html, /class="message"/);
            assert.match(html, /data-haanim-ui="actions"/);
            assert.match(html, /data-haanim-ui="log"/);
        }
    });
    const parts = [
        ['title', /class="name"/],
        ['state', /class="state /],
        ['message', /class="message"/],
        ['actions', /data-haanim-ui="actions"/],
        ['log', /data-haanim-ui="log"/],
    ];
    for (const [part, pattern] of parts) {
        test(`hiding ${part} hides only that`, () => {
            const html = renderCard({ automation, blocks: [], options: { ...all, [part]: false } });
            assert.doesNotMatch(html, pattern);
            for (const [other, otherPattern] of parts) {
                if (other !== part) assert.match(html, otherPattern);
            }
        });
    }
    test('a header with nothing in it is not drawn', () => {
        assert.equal(renderHeader(automation, null, { title: false, state: false, message: false }), '');
        assert.equal(renderHeader({ ...automation, message: null }, null, { title: false, state: false }), '');
        assert.match(renderHeader(automation, null, { title: false, state: false }), /^<div class="header"><div class="message">All good<\/div><\/div>$/);
    });
    test('a toolbar with nothing in it is not drawn', () => {
        assert.equal(renderToolbar(automation, { actions: false, log: false }), '');
        assert.doesNotMatch(renderToolbar(automation, { actions: false }), /data-haanim-ui="actions"/);
        assert.doesNotMatch(renderToolbar(automation, { log: false }), /data-haanim-ui="log"/);
    });
    test('with everything hidden the card is the bare content', () => {
        const none = { title: false, state: false, message: false, actions: false, log: false };
        const html = renderCard({ automation, blocks: [{ id: 'a', type: 'text', markdown: 'hi' }], options: none });
        assert.equal(html, '<div class="content bare"><div class="block block-text" data-block="a"><p>hi</p></div></div>');
        assert.equal(renderCard({ automation, blocks: [], options: none }), '');
    });
    test('the popup cannot be open while the actions are hidden', () => {
        const html = renderCard({ automation, blocks: [], options: { actions: false }, showActions: true });
        assert.doesNotMatch(html, /class="overlay"/);
    });
});

describe('renderControls', () => {
    const controls = (automation) => [...renderControls(automation).matchAll(/data-haanim="(\w+)"/g)].map((match) => match[1]);
    test('the controls that apply to each state', () => {
        assert.deepEqual(controls({ state: 'on', enabled: true }), ['disable', 'stop', 'restart']);
        assert.deepEqual(controls({ state: 'off', enabled: true }), ['disable', 'start']);
        assert.deepEqual(controls({ state: 'off', enabled: false }), ['enable']);
        assert.deepEqual(controls({ state: 'error', enabled: true }), ['disable', 'start']);
        assert.deepEqual(controls({ state: 'error', enabled: false }), ['enable']);
    });
});

describe('renderActionList', () => {
    test('a run button per action', () => {
        const html = renderActionList([{ name: 'alert', aliases: [], description: 'Count <one>' }, { name: 'reset', aliases: [], description: '' }]);
        assert.match(html, /data-haanim="run" data-action="alert"/);
        assert.match(html, /data-haanim="run" data-action="reset"/);
        assert.match(html, /<span class="description">Count &lt;one&gt;<\/span>/);
        assert.equal((html.match(/class="description"/g) || []).length, 1);
    });
    test('none', () => {
        assert.match(renderActionList([]), /No actions/);
        assert.match(renderActionList(undefined), /No actions/);
    });
});

describe('renderToolbar', () => {
    test('a button for the actions and one for the log', () => {
        const html = renderToolbar({ actions: [{ name: 'a' }, { name: 'b' }] });
        assert.match(html, /<button class="tool" data-haanim-ui="actions">Actions \(2\)<\/button>/);
        assert.match(html, /<button class="tool" data-haanim-ui="log">Log<\/button>/);
        assert.match(renderToolbar({}), /Actions \(0\)/);
    });
    test('the actions and the log are not drawn on the card itself', () => {
        const html = renderToolbar({ actions: [{ name: 'alert', description: 'x' }] });
        assert.doesNotMatch(html, /data-haanim="run"|class="record|<details/);
    });
});

describe('renderActionsDialog', () => {
    test('all actions in a popup that can be closed', () => {
        const html = renderActionsDialog({ id: 'climate', name: 'Climate <x>', actions: [{ name: 'alert', description: '' }, { name: 'reset', description: '' }] });
        assert.match(html, /^<div class="overlay" data-haanim-ui="close"><div class="dialog" role="dialog" aria-modal="true" data-haanim-ui="dialog">/);
        assert.match(html, /Climate &lt;x&gt;: actions/);
        assert.equal((html.match(/data-haanim="run"/g) || []).length, 2);
        assert.match(html, /<button class="tool" data-haanim-ui="close">Close<\/button>/);
    });
    test('an automation without actions', () => {
        assert.match(renderActionsDialog({ id: 'plain', actions: [] }), /plain: actions.*No actions/);
    });
});

describe('renderLog', () => {
    test('records with their level', () => {
        const html = renderLog([
            { time: '2025-01-06T08:00:00+00:00', level: 'INFO', message: 'hello <b>' },
            { time: '2025-01-06T08:00:01+00:00', level: 'ERROR', message: 'failed', traceback: 'Traceback <x>' },
        ]);
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
        const html = renderLog(records);
        assert.equal((html.match(/class="record/g) || []).length, MAX_LOG_RECORDS);
        assert.doesNotMatch(html, />m4</);
        assert.match(html, />m5</);
    });
    test('no records', () => {
        assert.match(renderLog([]), /No log records/);
        assert.match(renderLog(undefined), /No log records/);
        assert.match(renderLog([{ message: 'm' }]), /level-info/);
    });
});

describe('panel addresses', () => {
    test('the path of an automation and of its log', () => {
        assert.equal(PANEL_PATH, '/haanim');
        assert.equal(automationPath('climate'), '/haanim/automation/climate');
        assert.equal(automationPath('climate', true), '/haanim/automation/climate/logs');
        assert.equal(automationPath('a b/c'), '/haanim/automation/a%20b%2Fc');
    });
    test('reading the address', () => {
        assert.deepEqual(parseRoute(''), { page: 'list', id: null, section: null });
        assert.deepEqual(parseRoute('/'), { page: 'list', id: null, section: null });
        assert.deepEqual(parseRoute(undefined), { page: 'list', id: null, section: null });
        assert.deepEqual(parseRoute('/config'), { page: 'config', id: null, section: null });
        assert.deepEqual(parseRoute('/automation/climate'), { page: 'detail', id: 'climate', section: null });
        assert.deepEqual(parseRoute('/automation/climate/logs'), { page: 'detail', id: 'climate', section: 'logs' });
        assert.deepEqual(parseRoute('/automation/climate/other'), { page: 'detail', id: 'climate', section: null });
        assert.deepEqual(parseRoute('/automation/a%20b'), { page: 'detail', id: 'a b', section: null });
        assert.deepEqual(parseRoute('/automation/%E0%A4%A'), { page: 'detail', id: '%E0%A4%A', section: null });
        assert.deepEqual(parseRoute('/automation'), { page: 'list', id: null, section: null });
        assert.deepEqual(parseRoute('/config/more'), { page: 'list', id: null, section: null });
        assert.deepEqual(parseRoute('/unknown'), { page: 'list', id: null, section: null });
    });
    test('an automation called config has its own page', () => {
        assert.deepEqual(parseRoute(automationPath('config').slice(PANEL_PATH.length)), { page: 'detail', id: 'config', section: null });
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
    test('header, content and the two buttons in that order', () => {
        const html = renderCard({ automation, blocks: [{ id: 'a', type: 'text', markdown: 'hi' }] });
        const order = ['class="header"', 'class="content"', 'class="toolbar"'].map((part) => html.indexOf(part));
        assert.deepEqual([...order].sort((a, b) => a - b), order);
        assert.ok(order.every((index) => index >= 0));
        assert.doesNotMatch(html, /class="overlay"/);
    });
    test('the header shows the title the automation set', () => {
        assert.match(renderCard({ automation, title: 'Climate: 2 alerts', blocks: [] }), /<span class="name">Climate: 2 alerts<\/span>/);
        assert.match(renderCard({ automation, title: null, blocks: [] }), /<span class="name">Climate<\/span>/);
    });
    test('no controls at the top of the card', () => {
        const html = renderCard({ automation, blocks: [] });
        assert.doesNotMatch(html, /data-haanim="(enable|disable|start|stop|restart)"/);
    });
    test('the actions popup is drawn only when it is open', () => {
        const html = renderCard({ automation, blocks: [], showActions: true });
        assert.match(html, /class="overlay"/);
        assert.match(html, /data-haanim="run" data-action="alert"/);
        assert.doesNotMatch(renderCard({ automation, blocks: [] }), /data-haanim="run" data-action="alert"/);
    });
    test('the fixed parts are shown without content', () => {
        const html = renderCard({ automation: { ...automation, state: 'off' }, blocks: [] });
        assert.doesNotMatch(html, /class="content"/);
        assert.match(html, /class="header"/);
        assert.match(html, /class="toolbar"/);
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
        assert.match(html, /state-idle">Idle/);
        assert.match(html, /state-error">Error/);
        assert.match(html, /state-disabled">Disabled/);
        assert.match(html, /ok &lt;now&gt;/);
        assert.match(html, /<td class="name">off<div class="id">off<\/div>/);
    });
    test('the list shows what each running automation is doing', () => {
        const html = renderList([
            { id: 'a', name: 'A', state: 'on', enabled: true, running_actions: ['water'] },
            { id: 'b', name: 'B', state: 'on', enabled: true, running_actions: [] },
        ]);
        assert.match(html, /state-running">water</);
        assert.match(html, /state-idle">Idle</);
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

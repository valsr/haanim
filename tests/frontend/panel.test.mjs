import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { FakeHass, clicked, installDom, settle } from './fake-dom.mjs';

const dom = installDom();
const { HAAnimPanel } = await import('../../custom_components/haanim/ui/haanim-panel.js');

const LIST = {
    automations: [
        { id: 'climate', name: 'Climate', version: '1.2.0', state: 'on', enabled: true, message: null },
        { id: 'broken', name: 'broken', version: '', state: 'error', enabled: true, message: 'main.py:1' },
    ],
};
const DETAIL_IDS = ['detail-header', 'detail-controls', 'detail-meta', 'detail-actions', 'detail-log', 'detail-log-title', 'page-error'];

function states(state = 'on') {
    return { 'sensor.haanim_climate': { state, attributes: { enabled: true } }, 'light.kitchen': { state: 'on' } };
}

function detail(message) {
    return {
        id: message.automation_id,
        name: 'Climate',
        state: 'on',
        enabled: true,
        message: 'All good',
        description: 'Keeps it cool',
        author: 'Ada',
        actions: [{ name: 'alert', aliases: [], description: 'Count one alert' }],
    };
}

async function opened(path = null) {
    const hass = new FakeHass(states());
    hass.answers['haanim/automations/list'] = () => LIST;
    hass.answers['haanim/automations/get'] = detail;
    hass.answers['haanim/config/get'] = () => ({ version: '0.1.0', options: { max_concurrent_actions: 20 } });
    const panel = new HAAnimPanel();
    const parts = Object.fromEntries(DETAIL_IDS.map((id) => [id, panel.shadowRoot.stub(id)]));
    const card = panel.shadowRoot.stub('detail-card', {
        configured: null,
        setConfig(config) {
            this.configured = config;
        },
    });
    panel.panel = {};
    panel.narrow = false;
    if (path !== null) panel.route = { prefix: '/haanim', path };
    panel.hass = hass;
    await settle();
    return { panel, hass, card, parts };
}

describe('haanim-panel', () => {
    test('is registered, and brings the card with it', () => {
        assert.equal(dom.registry.get('haanim-panel'), HAAnimPanel);
        assert.ok(dom.registry.get('haanim-card'));
    });

    test('lists the automations with state and version', async () => {
        const { panel, hass } = await opened();
        assert.deepEqual(hass.calls, [{ type: 'haanim/automations/list' }]);
        assert.match(panel.shadowRoot.innerHTML, /data-open="climate"/);
        assert.match(panel.shadowRoot.innerHTML, /<td>1.2.0<\/td>/);
        assert.match(panel.shadowRoot.innerHTML, /state-error">Error/);
        assert.match(panel.shadowRoot.innerHTML, /class="tab active" data-page="list"/);
        assert.equal(panel.hass, hass);
        assert.equal(hass.subscriptions.length, 0, 'no log is followed on the list');
    });

    test('reads the list again only when an automation entity changed', async () => {
        const { panel, hass } = await opened();
        hass.states = { ...states(), 'light.kitchen': { state: 'off' } };
        panel.hass = hass;
        await settle();
        assert.equal(hass.calls.length, 1);

        hass.states = states('off');
        panel.hass = hass;
        await settle();
        assert.equal(hass.calls.length, 2);
    });

    test('a row goes to the page of the automation', async () => {
        const { panel, hass, card, parts } = await opened();
        dom.visited.length = 0;
        panel.shadowRoot.fire('click', clicked({ open: 'climate' }));
        await settle();

        assert.deepEqual(dom.visited, ['/haanim/automation/climate']);
        assert.match(panel.shadowRoot.innerHTML, /<haanim-card id="detail-card"><\/haanim-card>/);
        assert.match(panel.shadowRoot.innerHTML, /data-page="list">← All automations/);
        assert.deepEqual(card.configured, { automation_id: 'climate' });
        assert.equal(card.hass, hass);
        assert.deepEqual(hass.calls.at(-1), { type: 'haanim/automations/get', automation_id: 'climate' });
        assert.match(parts['detail-header'].innerHTML, /<span class="name">Climate<\/span>/);
        assert.match(parts['detail-header'].innerHTML, /All good/);
        assert.match(parts['detail-meta'].innerHTML, /Description<\/span><span>Keeps it cool/);
    });

    test('the page of an automation has the controls the card no longer has', async () => {
        const { panel, hass, parts } = await opened('/automation/climate');
        const controls = [...parts['detail-controls'].innerHTML.matchAll(/data-haanim="(\w+)"/g)].map((match) => match[1]);
        assert.deepEqual(controls, ['disable', 'stop', 'restart']);

        panel.shadowRoot.fire('click', clicked({ haanim: 'stop' }));
        await settle();
        assert.deepEqual(hass.services, [{ domain: 'haanim', service: 'stop', data: { automation_id: 'climate' } }]);
        assert.deepEqual(hass.calls.at(-1), { type: 'haanim/automations/get', automation_id: 'climate' }, 'the page is read again');
    });

    test('the page of an automation lists its actions, and runs them', async () => {
        const { panel, hass, parts } = await opened('/automation/climate');
        assert.match(parts['detail-actions'].innerHTML, /data-haanim="run" data-action="alert"/);
        assert.match(parts['detail-actions'].innerHTML, /Count one alert/);

        panel.shadowRoot.fire('click', clicked({ haanim: 'run', action: 'alert' }));
        await settle();
        assert.deepEqual(hass.services[0], {
            domain: 'haanim',
            service: 'run_action',
            data: { automation_id: 'climate', action: 'alert', data: {} },
        });
    });

    test('the page of an automation shows its log: the recent records, then each new one', async () => {
        const { hass, parts } = await opened('/automation/climate');
        assert.deepEqual(hass.active('haanim/logs/subscribe').map((subscription) => subscription.message), [
            { type: 'haanim/logs/subscribe', automation_id: 'climate' },
        ]);
        assert.match(parts['detail-log'].innerHTML, /No log records/);

        hass.push('haanim/logs/subscribe', { records: [{ time: '', level: 'INFO', message: 'first' }] });
        hass.push('haanim/logs/subscribe', { record: { time: '', level: 'ERROR', message: 'second', traceback: 'Traceback' } });
        hass.push('haanim/logs/subscribe', {});
        assert.match(parts['detail-log'].innerHTML, /first[\s\S]*second/);
        assert.match(parts['detail-log'].innerHTML, /level-error/);
        assert.match(parts['detail-log'].innerHTML, /class="traceback"/);
    });

    test('the address of the log opens the page of the automation at its log', async () => {
        const { panel, card, parts } = await opened('/automation/climate/logs');
        assert.deepEqual(card.configured, { automation_id: 'climate' });
        assert.match(panel.shadowRoot.innerHTML, /<h2 id="detail-log-title">Log<\/h2>/);
        assert.equal(parts['detail-log-title'].scrolled, 1);
    });

    test('the log button of the card on the page scrolls to the log without rebuilding the page', async () => {
        const { panel, hass, card, parts } = await opened('/automation/climate');
        assert.equal(parts['detail-log-title'].scrolled, 0);
        card.configured = null;

        panel.route = { prefix: '/haanim', path: '/automation/climate/logs' };
        await settle();
        assert.equal(parts['detail-log-title'].scrolled, 1);
        assert.equal(card.configured, null, 'the card is not created again');
        assert.equal(hass.active('haanim/logs/subscribe').length, 1);

        panel.route = { prefix: '/haanim', path: '/automation/climate' };
        assert.equal(parts['detail-log-title'].scrolled, 1);
    });

    test('leaving the page of an automation stops following its log', async () => {
        const { panel, hass } = await opened('/automation/climate');
        hass.push('haanim/logs/subscribe', { record: { time: '', level: 'INFO', message: 'old' } });
        dom.visited.length = 0;
        panel.shadowRoot.fire('click', clicked({ page: 'list' }));
        await settle();
        assert.deepEqual(dom.visited, ['/haanim']);
        assert.equal(hass.active('haanim/logs/subscribe').length, 0);
        assert.match(panel.shadowRoot.innerHTML, /data-open="climate"/);

        panel.route = { prefix: '/haanim', path: '/automation/broken' };
        await settle();
        assert.deepEqual(hass.active('haanim/logs/subscribe').map((subscription) => subscription.message.automation_id), ['broken']);
    });

    test('removed from the page, it stops following the log', async () => {
        const { panel, hass } = await opened('/automation/climate');
        panel.disconnectedCallback();
        await settle();
        assert.equal(hass.active('haanim/logs/subscribe').length, 0);
    });

    test('a log that cannot be followed leaves the page working', async () => {
        const hass = new FakeHass(states());
        hass.failSubscribe = new Error('not found');
        hass.answers['haanim/automations/get'] = detail;
        const panel = new HAAnimPanel();
        const header = panel.shadowRoot.stub('detail-header');
        panel.shadowRoot.stub('detail-card', { setConfig() {} });
        panel.route = { prefix: '/haanim', path: '/automation/climate' };
        panel.hass = hass;
        await settle();
        assert.match(header.innerHTML, /Climate/);
    });

    test('the configuration tab shows the version and the options', async () => {
        const { panel, hass } = await opened();
        dom.visited.length = 0;
        panel.shadowRoot.fire('click', clicked({ page: 'config' }));
        assert.match(panel.shadowRoot.innerHTML, /Loading/);
        await settle();
        assert.deepEqual(dom.visited, ['/haanim/config']);
        assert.deepEqual(hass.calls.at(-1), { type: 'haanim/config/get' });
        assert.match(panel.shadowRoot.innerHTML, /<td>max concurrent actions<\/td><td>20<\/td>/);
        assert.match(panel.shadowRoot.innerHTML, /class="tab active" data-page="config"/);

        panel.shadowRoot.fire('click', clicked({ page: 'list' }));
        await settle();
        assert.match(panel.shadowRoot.innerHTML, /data-open="climate"/);
    });

    test('the address decides the page, also when Home Assistant sets it first', async () => {
        const { panel, hass } = await opened('/config');
        assert.deepEqual(hass.calls, [{ type: 'haanim/config/get' }]);
        assert.match(panel.shadowRoot.innerHTML, /class="tab active" data-page="config"/);
        panel.route = { prefix: '/haanim', path: '' };
        await settle();
        assert.match(panel.shadowRoot.innerHTML, /data-open="climate"/);
        panel.route = undefined;
        await settle();
        assert.match(panel.shadowRoot.innerHTML, /data-open="climate"/);
    });

    test('reload all calls the reload service and reads the list again', async () => {
        const { panel, hass } = await opened();
        panel.shadowRoot.fire('click', clicked({ reload: 'all' }));
        await settle();
        assert.deepEqual(hass.services, [{ domain: 'haanim', service: 'reload', data: {} }]);
        assert.equal(hass.calls.length, 2);
    });

    test('a failing service is shown', async () => {
        const hass = new FakeHass(states());
        hass.answers['haanim/automations/list'] = () => LIST;
        const panel = new HAAnimPanel();
        panel.hass = hass;
        await settle();
        hass.failService = new Error('could <not> reload');
        panel.shadowRoot.fire('click', clicked({ reload: 'all' }));
        await settle();
        assert.match(panel.shadowRoot.innerHTML, /<div class="error">could &lt;not&gt; reload<\/div>/);
    });

    test('a failing control on the page of an automation is shown there', async () => {
        const { panel, hass, parts } = await opened('/automation/climate');
        hass.failService = new Error('AutomationDisabledError: climate');
        panel.shadowRoot.fire('click', clicked({ haanim: 'start' }));
        await settle();
        assert.match(parts['page-error'].innerHTML, /AutomationDisabledError: climate/);
    });

    test('a failing command is shown, and cleared when it works again', async () => {
        const hass = new FakeHass(states());
        hass.answers['haanim/automations/list'] = new Error('HAAnim is not set up');
        const panel = new HAAnimPanel();
        panel.hass = hass;
        await settle();
        assert.match(panel.shadowRoot.innerHTML, /<div class="error">HAAnim is not set up<\/div>/);
        assert.match(panel.shadowRoot.innerHTML, /Loading/);

        hass.answers['haanim/automations/list'] = () => LIST;
        hass.states = states('off');
        panel.hass = hass;
        await settle();
        assert.doesNotMatch(panel.shadowRoot.innerHTML, /class="error"/);
    });

    test('a click on nothing in particular does nothing', async () => {
        const { panel, hass } = await opened();
        panel.shadowRoot.fire('click', clicked({}));
        panel.shadowRoot.fire('click', clicked({ haanim: 'stop' }));
        panel.shadowRoot.fire('click', { target: null });
        await settle();
        assert.equal(hass.calls.length, 1);
        assert.equal(hass.services.length, 0, 'a control means nothing on the list');

        const page = await opened('/automation/climate');
        page.panel.shadowRoot.fire('click', clicked({ haanim: 'format_disk' }));
        await settle();
        assert.equal(page.hass.services.length, 0);
    });
});

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

function states(state = 'on') {
    return { 'sensor.haanim_climate': { state, attributes: { enabled: true } }, 'light.kitchen': { state: 'on' } };
}

async function opened() {
    const hass = new FakeHass(states());
    hass.answers['haanim/automations/list'] = () => LIST;
    hass.answers['haanim/automations/get'] = (message) => ({ id: message.automation_id, description: 'Keeps it cool', author: 'Ada' });
    hass.answers['haanim/config/get'] = () => ({ version: '0.1.0', options: { max_concurrent_actions: 20 } });
    const panel = new HAAnimPanel();
    panel.panel = {};
    panel.narrow = false;
    panel.hass = hass;
    await settle();
    return { panel, hass };
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

    test('a row opens the detail page with the metadata and the card of the automation', async () => {
        const { panel, hass } = await opened();
        const card = { configured: null, setConfig(config) { this.configured = config; } };
        const meta = { innerHTML: '' };
        panel.shadowRoot.byId['detail-card'] = card;
        panel.shadowRoot.byId['detail-meta'] = meta;

        panel.shadowRoot.fire('click', clicked({ open: 'climate' }));
        await settle();

        assert.match(panel.shadowRoot.innerHTML, /<haanim-card id="detail-card"><\/haanim-card>/);
        assert.match(panel.shadowRoot.innerHTML, /data-page="list">← All automations/);
        assert.deepEqual(card.configured, { automation_id: 'climate' });
        assert.equal(card.hass, hass);
        assert.deepEqual(hass.calls.at(-1), { type: 'haanim/automations/get', automation_id: 'climate' });
        assert.match(meta.innerHTML, /Description<\/span><span>Keeps it cool/);

        const other = new FakeHass(states('off'));
        other.answers = hass.answers;
        panel.hass = other;
        await settle();
        assert.equal(card.hass, other, 'the card gets every new hass');
    });

    test('the configuration tab shows the version and the options', async () => {
        const { panel, hass } = await opened();
        panel.shadowRoot.fire('click', clicked({ page: 'config' }));
        assert.match(panel.shadowRoot.innerHTML, /Loading/);
        await settle();
        assert.deepEqual(hass.calls.at(-1), { type: 'haanim/config/get' });
        assert.match(panel.shadowRoot.innerHTML, /<td>max concurrent actions<\/td><td>20<\/td>/);
        assert.match(panel.shadowRoot.innerHTML, /class="tab active" data-page="config"/);

        panel.shadowRoot.fire('click', clicked({ page: 'list' }));
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

    test('a failing reload is shown', async () => {
        const { panel, hass } = await opened();
        hass.failService = new Error('could <not> reload');
        panel.shadowRoot.fire('click', clicked({ reload: 'all' }));
        await settle();
        assert.match(panel.shadowRoot.innerHTML, /<div class="error">could &lt;not&gt; reload<\/div>/);
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
        panel.shadowRoot.fire('click', { target: null });
        await settle();
        assert.equal(hass.calls.length, 1);
        assert.equal(hass.services.length, 0);
    });
});

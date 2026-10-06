import assert from 'node:assert/strict';
import { beforeEach, describe, test } from 'node:test';

import { FakeHass, clicked, installDom, settle } from './fake-dom.mjs';

const dom = installDom();
const { HAAnimCard } = await import('../../custom_components/haanim/ui/haanim-card.js');

const DETAIL = {
    id: 'climate',
    name: 'Climate',
    state: 'on',
    enabled: true,
    message: null,
    actions: [{ name: 'reset_alerts', aliases: [], description: '' }],
};
const ENTITY = 'sensor.haanim_climate';

function entity(state, updated = '1') {
    return { state, last_updated: updated, attributes: {} };
}

async function mounted(states = { [ENTITY]: entity('on') }) {
    const hass = new FakeHass(states);
    hass.answers['haanim/automations/get'] = () => ({ ...DETAIL });
    const card = new HAAnimCard();
    card.setConfig({ automation_id: 'climate' });
    card.connectedCallback();
    card.hass = hass;
    await settle();
    return { card, hass };
}

describe('haanim-card', () => {
    beforeEach(() => {
        dom.window.confirm = () => true;
    });

    test('is registered as an element and as a custom card', () => {
        assert.equal(dom.registry.get('haanim-card'), HAAnimCard);
        assert.deepEqual(dom.window.customCards.map((entry) => entry.type), ['haanim-card']);
        assert.deepEqual(HAAnimCard.getStubConfig(), { automation_id: '' });
    });

    test('needs an automation ID', () => {
        const card = new HAAnimCard();
        assert.throws(() => card.setConfig({}), /automation_id is required/);
        assert.throws(() => card.setConfig(null), /automation_id is required/);
    });

    test('subscribes to the card and the log of its automation and reads its details', async () => {
        const { card, hass } = await mounted();
        assert.deepEqual(hass.subscriptions.map((subscription) => subscription.message), [
            { type: 'haanim/card/subscribe', automation_id: 'climate' },
            { type: 'haanim/logs/subscribe', automation_id: 'climate' },
        ]);
        assert.deepEqual(hass.calls[0], { type: 'haanim/automations/get', automation_id: 'climate' });
        assert.match(card.shadowRoot.innerHTML, /<ha-card>/);
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Climate<\/span>/);
        assert.equal(card.hass, hass);
    });

    test('does not subscribe before it is on a page and has hass', async () => {
        const hass = new FakeHass();
        const card = new HAAnimCard();
        card.setConfig({ automation_id: 'climate' });
        card.hass = hass;
        await settle();
        assert.equal(hass.subscriptions.length, 0);
        assert.match(card.shadowRoot.innerHTML, /Loading/);
    });

    test('draws the content the automation sends, and each update of it', async () => {
        const { card, hass } = await mounted();
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'alerts', type: 'value', label: 'Alerts today', value: 0, unit: '' }] });
        assert.match(card.shadowRoot.innerHTML, /Alerts today<\/span><span class="value">0</);
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'alerts', type: 'value', label: 'Alerts today', value: 3, unit: '' }] });
        assert.match(card.shadowRoot.innerHTML, /<span class="value">3</);
        assert.equal(card.getCardSize(), 4);
        hass.push('haanim/card/subscribe', {});
        assert.doesNotMatch(card.shadowRoot.innerHTML, /class="content"/);
    });

    test('shows the recent log records and adds new ones', async () => {
        const { card, hass } = await mounted();
        hass.push('haanim/logs/subscribe', { records: [{ time: '', level: 'INFO', message: 'first' }] });
        hass.push('haanim/logs/subscribe', { record: { time: '', level: 'WARNING', message: 'second' } });
        hass.push('haanim/logs/subscribe', {});
        assert.match(card.shadowRoot.innerHTML, /Log \(2\)/);
        assert.match(card.shadowRoot.innerHTML, /first[\s\S]*second/);
    });

    test('a control calls its service', async () => {
        const { card, hass } = await mounted();
        card.shadowRoot.fire('click', clicked({ haanim: 'stop' }));
        assert.deepEqual(hass.services, [{ domain: 'haanim', service: 'stop', data: { automation_id: 'climate' } }]);
    });

    test('a card button runs its action with its data', async () => {
        const { card, hass } = await mounted();
        card.shadowRoot.fire('click', clicked({ haanim: 'run', action: 'reset_alerts', payload: '{"room":"hall"}' }));
        assert.deepEqual(hass.services[0], {
            domain: 'haanim',
            service: 'run_action',
            data: { automation_id: 'climate', action: 'reset_alerts', data: { room: 'hall' } },
        });
    });

    test('a button with a confirmation asks first', async () => {
        const { card, hass } = await mounted();
        const asked = [];
        dom.window.confirm = (text) => {
            asked.push(text);
            return false;
        };
        card.shadowRoot.fire('click', clicked({ haanim: 'run', action: 'reset_alerts', confirm: 'Reset the counter?' }));
        assert.deepEqual(asked, ['Reset the counter?']);
        assert.equal(hass.services.length, 0);

        dom.window.confirm = () => true;
        card.shadowRoot.fire('click', clicked({ haanim: 'run', action: 'reset_alerts', confirm: 'Reset the counter?' }));
        assert.equal(hass.services.length, 1);
    });

    test('a click on anything else does nothing', async () => {
        const { card, hass } = await mounted();
        card.shadowRoot.fire('click', clicked({}));
        card.shadowRoot.fire('click', clicked({ haanim: 'format_disk' }));
        card.shadowRoot.fire('click', { target: null });
        assert.equal(hass.services.length, 0);
    });

    test('a failing service is reported as a notification', async () => {
        const { card, hass } = await mounted();
        hass.failService = new Error('AutomationDisabledError: climate');
        card.shadowRoot.fire('click', clicked({ haanim: 'start' }));
        await settle();
        assert.equal(card.dispatched[0].type, 'hass-notification');
        assert.equal(card.dispatched[0].detail.message, 'AutomationDisabledError: climate');
    });

    test('reads the details again when the entity of the automation changes', async () => {
        const { card, hass } = await mounted();
        hass.answers['haanim/automations/get'] = () => ({ ...DETAIL, state: 'off' });
        card.hass = Object.assign(hass, { states: { [ENTITY]: entity('off', '2') } });
        await settle();
        assert.equal(hass.calls.length, 2);
        assert.match(card.shadowRoot.innerHTML, /state-stopped">Stopped/);

        card.hass = hass;
        await settle();
        assert.equal(hass.calls.length, 2, 'nothing changed, nothing is read');
    });

    test('redraws when an entity shown on the card changes', async () => {
        const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'sensor.t': { state: '20', last_updated: '1', attributes: {} } });
        hass.push('haanim/card/subscribe', { blocks: [{ id: 't', type: 'entity', entity_id: 'sensor.t' }] });
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /data-entity="sensor.t">20</);
        hass.states = { ...hass.states, 'sensor.t': { state: '25', last_updated: '2', attributes: {} } };
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /data-entity="sensor.t">25</);
    });

    test('subscribes again after the integration was reloaded', async () => {
        const { card, hass } = await mounted();
        hass.states = { [ENTITY]: entity('unavailable', '2') };
        card.hass = hass;
        await settle();
        hass.states = { [ENTITY]: entity('on', '3') };
        card.hass = hass;
        await settle();
        assert.equal(hass.subscriptions.length, 4);
        assert.equal(hass.active('haanim/card/subscribe').length, 1);
        assert.equal(hass.active('haanim/logs/subscribe').length, 1);
    });

    test('an automation that is not there shows why, and is tried again when its entity changes', async () => {
        const hass = new FakeHass({});
        hass.failSubscribe = { code: 'not_found', message: "No automation 'climate'" };
        hass.answers['haanim/automations/get'] = () => ({ ...DETAIL });
        const card = new HAAnimCard();
        card.setConfig({ automation_id: 'climate' });
        card.connectedCallback();
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /card-error">Automation &quot;climate&quot; is not available: No automation/);

        hass.failSubscribe = null;
        hass.states = { [ENTITY]: entity('on') };
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Climate<\/span>/);
    });

    test('loads asset images with the session and shows them when they arrive', async () => {
        const { card, hass } = await mounted();
        const url = '/api/haanim/assets/climate/logo.png';
        hass.push('haanim/card/subscribe', {
            blocks: [
                { id: 'logo', type: 'image', asset: 'logo.png', url, alt: 'Logo' },
                { id: 'web', type: 'image', url: 'https://example.com/a.png', alt: '' },
                { id: 'gone', type: 'image', asset: 'missing.png', url: '/api/haanim/assets/climate/missing.png', alt: 'Gone' },
            ],
        });
        assert.match(card.shadowRoot.innerHTML, /image-pending">Logo</);
        await settle();
        assert.deepEqual(hass.fetched, [url, '/api/haanim/assets/climate/missing.png']);
        assert.match(card.shadowRoot.innerHTML, new RegExp(`<img src="blob:${url}" alt="Logo">`));
        assert.match(card.shadowRoot.innerHTML, /image-pending">Gone</);

        hass.push('haanim/card/subscribe', { blocks: [{ id: 'logo', type: 'image', asset: 'logo.png', url, alt: 'Logo' }] });
        await settle();
        assert.equal(hass.fetched.filter((fetched) => fetched === url).length, 1, 'a loaded image is not fetched again');
    });

    test('remembers which sections are open across redraws', async () => {
        const { card, hass } = await mounted();
        card.shadowRoot.fire('toggle', { target: { dataset: { section: 'log' }, open: true } });
        card.shadowRoot.fire('toggle', { target: { dataset: {} } });
        hass.push('haanim/logs/subscribe', { record: { time: '', level: 'INFO', message: 'x' } });
        assert.match(card.shadowRoot.innerHTML, /data-section="log" open/);
        assert.doesNotMatch(card.shadowRoot.innerHTML, /data-section="actions" open/);
    });

    test('ends its subscriptions when it leaves the page', async () => {
        const { card, hass } = await mounted();
        card.disconnectedCallback();
        await settle();
        assert.equal(hass.active('haanim/card/subscribe').length, 0);
        assert.equal(hass.active('haanim/logs/subscribe').length, 0);
    });

    test('a new automation ID starts over', async () => {
        const { card, hass } = await mounted();
        hass.answers['haanim/automations/get'] = (message) => ({ ...DETAIL, id: message.automation_id, name: 'Other' });
        card.setConfig({ automation_id: 'other' });
        await settle();
        assert.deepEqual(hass.active('haanim/card/subscribe').map((subscription) => subscription.message.automation_id), ['other']);
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Other<\/span>/);
        card.setConfig({ automation_id: 'other' });
        await settle();
        assert.equal(hass.active('haanim/card/subscribe').length, 1);
    });
});

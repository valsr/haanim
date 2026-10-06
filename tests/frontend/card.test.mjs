import assert from 'node:assert/strict';
import { beforeEach, describe, test } from 'node:test';

import { FakeHass, clicked, installDom, settle } from './fake-dom.mjs';

const dom = installDom();
const { HAAnimCard, REGISTRATION_CHECK, keepRegistered, registerCard } = await import('../../custom_components/haanim/ui/haanim-card.js');

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

    test('registers again in a registry that does not know it, and only once in one that does', () => {
        assert.equal(registerCard(), false, 'it is registered already');

        // Home Assistant replaces the registry after the module was loaded
        const native = globalThis.customElements;
        const replaced = new Map();
        globalThis.customElements = { define: (name, constructor) => replaced.set(name, constructor), get: (name) => replaced.get(name) };
        assert.equal(registerCard(), true);
        assert.equal(replaced.get('haanim-card'), HAAnimCard);
        assert.equal(dom.window.customCards.length, 1, 'the card is listed once');

        // A registry that refuses is tried again later
        globalThis.customElements = { define: () => { throw new Error('not now'); }, get: () => undefined };
        assert.equal(registerCard(), false);
        globalThis.customElements = native;
    });

    test('the registration is checked for the first seconds after loading, then no more', () => {
        const native = globalThis.customElements;
        let run = null;
        let period = null;
        let stopped = null;
        const timer = keepRegistered((callback, every) => { run = callback; period = every; return 'timer'; }, (which) => { stopped = which; });
        assert.equal(timer, 'timer');
        assert.equal(period, REGISTRATION_CHECK.every);

        const replaced = new Map();
        globalThis.customElements = { define: (name, constructor) => replaced.set(name, constructor), get: (name) => replaced.get(name) };
        run();
        assert.equal(replaced.get('haanim-card'), HAAnimCard, 'the first check after the registry was replaced makes it good');
        for (let check = 1; check < REGISTRATION_CHECK.times - 1; check += 1) run();
        assert.equal(stopped, null);
        run();
        assert.equal(stopped, 'timer');
        globalThis.customElements = native;
    });

    test('needs an automation ID', () => {
        const card = new HAAnimCard();
        assert.throws(() => card.setConfig({}), /automation_id is required/);
        assert.throws(() => card.setConfig(null), /automation_id is required/);
    });

    test('subscribes to the card of its automation and reads its details', async () => {
        const { card, hass } = await mounted();
        assert.deepEqual(hass.subscriptions.map((subscription) => subscription.message), [
            { type: 'haanim/card/subscribe', automation_id: 'climate' },
        ]);
        assert.deepEqual(hass.calls[0], { type: 'haanim/automations/get', automation_id: 'climate' });
        assert.match(card.shadowRoot.innerHTML, /<ha-card>/);
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Climate<\/span>/);
        assert.equal(card.hass, hass);
    });

    test('has no controls at the top, and draws neither the actions nor the log', async () => {
        const { card } = await mounted();
        assert.doesNotMatch(card.shadowRoot.innerHTML, /data-haanim="(enable|disable|start|stop|restart)"/);
        assert.doesNotMatch(card.shadowRoot.innerHTML, /data-haanim="run"|class="record|<details/);
        assert.match(card.shadowRoot.innerHTML, /data-haanim-ui="actions">Actions \(1\)</);
        assert.match(card.shadowRoot.innerHTML, /data-haanim-ui="log">Log</);
    });

    test('shows the title the automation sets, and follows it', async () => {
        const { card, hass } = await mounted();
        hass.push('haanim/card/subscribe', { blocks: [], title: 'Climate: 1 alert' });
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Climate: 1 alert<\/span>/);
        hass.push('haanim/card/subscribe', { blocks: [], title: 'Climate: 2 alerts' });
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Climate: 2 alerts<\/span>/);
        hass.push('haanim/card/subscribe', { blocks: [], title: null });
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Climate<\/span>/);
    });

    test('places the elements as the layout says, and follows it', async () => {
        const { card, hass } = await mounted();
        const blocks = [{ id: 'a', type: 'text', markdown: 'A' }, { id: 'b', type: 'text', markdown: 'B' }];
        hass.push('haanim/card/subscribe', { blocks, layout: [{ cells: 2, elements: ['a', 'b'] }] });
        assert.match(card.shadowRoot.innerHTML, /<div class="row" style="--cells: 2">/);
        hass.push('haanim/card/subscribe', { blocks, layout: [{ cells: 1, elements: ['b'] }, { cells: 1, elements: ['a'] }] });
        assert.doesNotMatch(card.shadowRoot.innerHTML, /class="row"/);
        assert.ok(card.shadowRoot.innerHTML.indexOf('data-block="b"') < card.shadowRoot.innerHTML.indexOf('data-block="a"'));
        hass.push('haanim/card/subscribe', { blocks });
        assert.ok(card.shadowRoot.innerHTML.indexOf('data-block="a"') < card.shadowRoot.innerHTML.indexOf('data-block="b"'));
    });

    test('hides the parts the automation hides, and shows them again', async () => {
        const { card, hass } = await mounted();
        const bare = { title: false, state: false, message: false, actions: false, log: false };
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'a', type: 'text', markdown: 'only this' }], options: bare });
        assert.doesNotMatch(card.shadowRoot.innerHTML, /class="header"|class="toolbar"|class="name"|class="state /);
        assert.match(card.shadowRoot.innerHTML, /class="content bare"/);
        assert.match(card.shadowRoot.innerHTML, /only this/);

        hass.push('haanim/card/subscribe', { blocks: [], options: { ...bare, title: true, log: true } });
        assert.match(card.shadowRoot.innerHTML, /class="name"/);
        assert.match(card.shadowRoot.innerHTML, /data-haanim-ui="log"/);
        assert.doesNotMatch(card.shadowRoot.innerHTML, /data-haanim-ui="actions"|class="state /);

        hass.push('haanim/card/subscribe', { blocks: [] });
        assert.match(card.shadowRoot.innerHTML, /data-haanim-ui="actions"/);
        assert.match(card.shadowRoot.innerHTML, /class="state /);
    });

    test('the state shows the action the entity says is running, at once, and Idle when none is', async () => {
        const running = (actions, updated, state = 'on') => ({ state, last_updated: updated, attributes: { running_actions: actions, enabled: true } });
        const { card, hass } = await mounted({ [ENTITY]: running([], '1') });
        assert.match(card.shadowRoot.innerHTML, /state-idle">Idle</);

        hass.answers['haanim/automations/get'] = () => new Promise(() => {});
        hass.states = { [ENTITY]: running(['toggle_frame'], '2') };
        card.hass = hass;
        assert.match(card.shadowRoot.innerHTML, /state-running">toggle_frame</, 'without waiting for the details');

        hass.states = { [ENTITY]: running([], '3') };
        card.hass = hass;
        assert.match(card.shadowRoot.innerHTML, /state-idle">Idle</);

        hass.states = { [ENTITY]: running([], '4', 'off') };
        card.hass = hass;
        assert.match(card.shadowRoot.innerHTML, /state-stopped">Stopped</);

        hass.states = { [ENTITY]: { state: 'unavailable', last_updated: '5', attributes: {} } };
        card.hass = hass;
        assert.match(card.shadowRoot.innerHTML, /state-unavailable">Unavailable</);
    });

    test('the actions button opens a popup with all actions, which can be closed', async () => {
        const { card, hass } = await mounted();
        card.shadowRoot.fire('click', clicked({ 'haanim-ui': 'actions' }));
        assert.match(card.shadowRoot.innerHTML, /class="overlay"/);
        assert.match(card.shadowRoot.innerHTML, /data-haanim="run" data-action="reset_alerts"/);

        card.shadowRoot.fire('click', clicked({ 'haanim-ui': 'dialog' }));
        assert.match(card.shadowRoot.innerHTML, /class="overlay"/, 'a click inside the popup keeps it open');

        hass.push('haanim/card/subscribe', { blocks: [] });
        assert.match(card.shadowRoot.innerHTML, /class="overlay"/, 'an update of the card keeps it open');

        card.shadowRoot.fire('click', clicked({ 'haanim-ui': 'close' }));
        assert.doesNotMatch(card.shadowRoot.innerHTML, /class="overlay"/);
        assert.equal(hass.services.length, 0);
    });

    test('running an action from the popup calls it and closes the popup', async () => {
        const { card, hass } = await mounted();
        card.shadowRoot.fire('click', clicked({ 'haanim-ui': 'actions' }));
        card.shadowRoot.fire('click', clicked({ haanim: 'run', action: 'reset_alerts' }));
        assert.deepEqual(hass.services, [
            { domain: 'haanim', service: 'run_action', data: { automation_id: 'climate', action: 'reset_alerts', data: {} } },
        ]);
        assert.doesNotMatch(card.shadowRoot.innerHTML, /class="overlay"/);
    });

    test('the log button goes to the log of the automation in the HAAnim panel', async () => {
        const { card, hass } = await mounted();
        dom.visited.length = 0;
        dom.fired.length = 0;
        card.shadowRoot.fire('click', clicked({ 'haanim-ui': 'log' }));
        assert.deepEqual(dom.visited, ['/haanim/automation/climate/logs']);
        assert.deepEqual(dom.fired, ['location-changed']);
        assert.equal(hass.services.length, 0);
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
        card.shadowRoot.fire('click', clicked({ 'haanim-ui': 'something' }));
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
        assert.equal(hass.subscriptions.length, 2);
        assert.equal(hass.active('haanim/card/subscribe').length, 1);
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

    test('an icon follows its entity', async () => {
        const fan = (state, updated) => ({ state, last_updated: updated, attributes: { friendly_name: 'Fan' } });
        const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'fan.bedroom': fan('off', '1') });
        hass.push('haanim/card/subscribe', {
            blocks: [{ id: 'fan', type: 'icon', entity_id: 'fan.bedroom', icon: 'mdi:fan', spin: true, follow_entity: true }],
        });
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /class="icon inactive"/);

        hass.states = { ...hass.states, 'fan.bedroom': fan('on', '2') };
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /class="icon active spin"/);
        assert.match(card.shadowRoot.innerHTML, /<span class="value">on<\/span>/);
    });

    test('a gauge and a badge follow their entities', async () => {
        const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'sensor.battery': entity('40'), 'lock.door': entity('locked') });
        hass.push('haanim/card/subscribe', {
            blocks: [
                { id: 'g', type: 'gauge', value: null, entity_id: 'sensor.battery', min: 0, max: 100, kind: 'bar' },
                { id: 'b', type: 'badge', text: null, entity_id: 'lock.door' },
                { id: 'own', type: 'gauge', value: 5, entity_id: null, min: 0, max: 10, kind: 'bar' },
            ],
        });
        assert.match(card.shadowRoot.innerHTML, /width: 40.0%/);
        assert.match(card.shadowRoot.innerHTML, /<span class="badge-text">locked<\/span>/);
        hass.states = { ...hass.states, 'sensor.battery': entity('65', '2'), 'lock.door': entity('unlocked', '2') };
        card.hass = hass;
        assert.match(card.shadowRoot.innerHTML, /width: 65.0%/);
        assert.match(card.shadowRoot.innerHTML, /<span class="badge-text">unlocked<\/span>/);
        assert.match(card.shadowRoot.innerHTML, /width: 50.0%/);
    });

    describe('camera pictures', () => {
        const PICTURE = '/api/camera_proxy/camera.door?token=abc';
        const camera = (token = 'abc', updated = '1') => ({
            state: 'idle',
            last_updated: updated,
            attributes: { entity_picture: `/api/camera_proxy/camera.door?token=${token}` },
        });
        const door = (extra = {}) => ({ id: 'door', type: 'image', entity_id: 'camera.door', refresh: 2, alt: 'Door', ...extra });
        let timers;

        /** A clock the test moves by hand: `tick()` is one second. */
        beforeEach(() => {
            timers = [];
            globalThis.setInterval = (callback, period) => {
                const timer = { callback, period, running: true };
                timers.push(timer);
                return timer;
            };
            globalThis.clearInterval = (timer) => {
                timer.running = false;
            };
            delete globalThis.document;
        });
        const running = () => timers.filter((timer) => timer.running);
        const tick = (times = 1) => {
            for (let turn = 0; turn < times; turn += 1) running().forEach((timer) => timer.callback());
        };

        test('no clock runs while the card shows no camera', async () => {
            const { hass } = await mounted();
            hass.push('haanim/card/subscribe', { blocks: [{ id: 'logo', type: 'image', url: '/a.png', alt: '' }] });
            assert.deepEqual(timers, []);
        });

        test('the picture is shown at once, and fetched again when its time has come', async () => {
            const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'camera.door': camera() });
            hass.push('haanim/card/subscribe', { blocks: [door()] });
            assert.match(card.shadowRoot.innerHTML, /<img src="\/api\/camera_proxy\/camera.door\?token=abc" alt="Door" data-camera="door">/);
            assert.deepEqual(running().map((timer) => timer.period), [1000]);

            const image = { dataset: { camera: 'door' }, src: PICTURE };
            const other = { dataset: { camera: 'gone' }, src: 'kept' };
            card.shadowRoot.found = { 'img[data-camera]': [image, other] };
            tick();
            assert.equal(image.src, PICTURE, 'after one second of two nothing is fetched');
            tick();
            assert.match(image.src, /^\/api\/camera_proxy\/camera.door\?token=abc&t=\d+$/);
            assert.equal(other.src, 'kept');
            const first = image.src;
            tick(2);
            assert.notEqual(image.src, first, 'every picture has an address of its own');
        });

        test('a redraw keeps the picture last fetched', async () => {
            const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'camera.door': camera() });
            hass.push('haanim/card/subscribe', { blocks: [door({ refresh: 1 })] });
            tick();
            hass.push('haanim/card/subscribe', { blocks: [door({ refresh: 1 })], title: 'Door' });
            assert.match(card.shadowRoot.innerHTML, /token=abc&amp;t=\d+" alt="Door"/);
            assert.equal(running().length, 1, 'one clock, however often the card changes');
        });

        test('follows the camera when Home Assistant gives it a new address', async () => {
            const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'camera.door': camera() });
            hass.push('haanim/card/subscribe', { blocks: [door()] });
            hass.states = { ...hass.states, 'camera.door': camera('xyz', '2') };
            card.hass = hass;
            assert.match(card.shadowRoot.innerHTML, /camera.door\?token=xyz"/);
        });

        test('each camera has its own time, and one without a time gets ten seconds', async () => {
            const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'camera.door': camera() });
            hass.push('haanim/card/subscribe', { blocks: [door({ id: 'fast', refresh: 1 }), door({ id: 'slow', refresh: undefined })] });
            const fast = { dataset: { camera: 'fast' }, src: '' };
            const slow = { dataset: { camera: 'slow' }, src: '' };
            card.shadowRoot.found = { 'img[data-camera]': [fast, slow] };
            tick(9);
            assert.match(fast.src, /&t=\d+$/);
            assert.equal(slow.src, '');
            tick();
            assert.match(slow.src, /&t=\d+$/);
        });

        test('a camera without a picture is left alone', async () => {
            const { card, hass } = await mounted({ [ENTITY]: entity('on') });
            hass.push('haanim/card/subscribe', { blocks: [door({ refresh: 1 })] });
            const image = { dataset: { camera: 'door' }, src: 'kept' };
            card.shadowRoot.found = { 'img[data-camera]': [image] };
            tick();
            assert.equal(image.src, 'kept');
            card._hass = null;
            tick();
            assert.equal(image.src, 'kept');
        });

        test('nothing is fetched while the page is hidden', async () => {
            const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'camera.door': camera() });
            hass.push('haanim/card/subscribe', { blocks: [door({ refresh: 1 })] });
            const image = { dataset: { camera: 'door' }, src: 'kept' };
            card.shadowRoot.found = { 'img[data-camera]': [image] };
            globalThis.document = { hidden: true };
            tick(3);
            assert.equal(image.src, 'kept');
            globalThis.document = { hidden: false };
            tick();
            assert.match(image.src, /&t=\d+$/);
            delete globalThis.document;
        });

        test('the clock stops when the camera goes, the card leaves the page or shows another automation', async () => {
            const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'camera.door': camera() });
            hass.push('haanim/card/subscribe', { blocks: [door()] });
            assert.equal(running().length, 1);
            hass.push('haanim/card/subscribe', { blocks: [] });
            assert.equal(running().length, 0);

            hass.push('haanim/card/subscribe', { blocks: [door()] });
            assert.equal(running().length, 1);
            card.disconnectedCallback();
            assert.equal(running().length, 0);
            card.connectedCallback();
            await settle();
            assert.equal(running().length, 1);

            card.setConfig({ automation_id: 'other' });
            assert.equal(running().length, 0);
        });
    });

    test("raw HTML goes into its own element as it is, and a button in it runs an action", async () => {
        const { card, hass } = await mounted();
        const holder = { dataset: { html: 'raw' }, innerHTML: '' };
        const stale = { dataset: { html: 'gone' }, innerHTML: 'kept' };
        card.shadowRoot.found = { '[data-html]': [holder, stale] };
        const raw = '<table><tr><td style="color:red">A</td></tr></table><button data-haanim="run" data-action="reset_alerts">Reset</button><div>never closed';
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'raw', type: 'html', html: raw }, { id: 'after', type: 'text', markdown: 'after' }] });

        assert.equal(holder.innerHTML, raw);
        assert.equal(stale.innerHTML, 'kept');
        assert.match(card.shadowRoot.innerHTML, /data-html="raw"><\/div><div class="block block-text" data-block="after"><p>after<\/p>/);
        assert.doesNotMatch(card.shadowRoot.innerHTML, /never closed/, 'the HTML is not part of the markup of the card');

        hass.push('haanim/card/subscribe', { blocks: [{ id: 'raw', type: 'html' }] });
        assert.equal(holder.innerHTML, '');

        card.shadowRoot.fire('click', clicked({ haanim: 'run', action: 'reset_alerts' }));
        await settle();
        assert.equal(hass.services.at(-1).data.action, 'reset_alerts');
    });

    test('an icon that does not follow its entity is not redrawn when the entity changes', async () => {
        const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'fan.bedroom': { state: 'off', last_updated: '1' } });
        hass.push('haanim/card/subscribe', {
            blocks: [{ id: 'fan', type: 'icon', entity_id: 'fan.bedroom', icon: 'mdi:fan', follow_entity: false }],
        });
        card.hass = hass;
        await settle();
        const calls = hass.calls.length;
        hass.states = { ...hass.states, 'fan.bedroom': { state: 'on', last_updated: '2' } };
        card.hass = hass;
        await settle();
        assert.equal(hass.calls.length, calls);
        assert.match(card.shadowRoot.innerHTML, /class="icon active"/);
    });

    test("hands Home Assistant's state icon the entity it stands for", async () => {
        const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'fan.bedroom': { state: 'on', last_updated: '1' } });
        const element = { dataset: { stateIcon: 'fan.bedroom' } };
        card.shadowRoot.found = { '[data-state-icon]': [element] };
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'fan', type: 'icon', entity_id: 'fan.bedroom', follow_entity: true }] });
        assert.equal(element.hass, hass);
        assert.equal(element.stateObj, hass.states['fan.bedroom']);
    });

    test("a click on an entity's icon opens the entity's own dialog", async () => {
        const { card, hass } = await mounted();
        card.shadowRoot.fire('click', clicked({ 'more-info': 'fan.bedroom' }));
        assert.equal(card.dispatched[0].type, 'hass-more-info');
        assert.deepEqual(card.dispatched[0].detail, { entityId: 'fan.bedroom' });
        assert.equal(hass.services.length, 0);
    });

    test('fetches the history of a graph once and draws it', async () => {
        const temperature = (state, updated) => ({ state, last_updated: updated, attributes: { friendly_name: 'Temperature' } });
        const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'sensor.t': temperature('22', new Date(Date.now() - 60000).toISOString()) });
        const lu = Date.now() / 1000;
        hass.answers['history/history_during_period'] = () => ({ 'sensor.t': [{ s: '20', lu: lu - 3000 }, { s: '22', lu: lu - 60 }] });
        const graph = { id: 'h', type: 'graph', kind: 'line', entities: ['sensor.t'], hours: 1 };

        hass.push('haanim/card/subscribe', { blocks: [graph] });
        assert.match(card.shadowRoot.innerHTML, /Loading history/);
        await settle();

        const request = hass.calls.find((call) => call.type === 'history/history_during_period');
        assert.deepEqual(request.entity_ids, ['sensor.t']);
        assert.equal(request.minimal_response, true);
        assert.equal(request.no_attributes, true);
        assert.equal(Date.parse(request.end_time) - Date.parse(request.start_time), 3600000);
        assert.match(card.shadowRoot.innerHTML, /<svg class="graph"/);
        assert.match(card.shadowRoot.innerHTML, /legend-name">Temperature<\/span><span class="legend-value">22</);

        hass.push('haanim/card/subscribe', { blocks: [graph, { id: 'a', type: 'text', markdown: 'more' }] });
        await settle();
        assert.equal(hass.calls.filter((call) => call.type === 'history/history_during_period').length, 1, 'not fetched again');
    });

    test('a graph follows its entity after the history was fetched', async () => {
        const temperature = (state, updated) => ({ state, last_updated: updated, attributes: {} });
        const { card, hass } = await mounted({ [ENTITY]: entity('on'), 'sensor.t': temperature('22', new Date(Date.now() - 60000).toISOString()) });
        hass.answers['history/history_during_period'] = () => ({ 'sensor.t': [{ s: '20', lu: Date.now() / 1000 - 3000 }] });
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'h', type: 'graph', kind: 'line', entities: ['sensor.t'], hours: 1 }] });
        await settle();
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /legend-value">22</);

        hass.states = { ...hass.states, 'sensor.t': temperature('27.5', new Date().toISOString()) };
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /legend-value">27.5</);
        assert.equal(hass.calls.filter((call) => call.type === 'history/history_during_period').length, 1);

        hass.states = { ...hass.states, 'sensor.t': temperature('unavailable', new Date(Date.now() + 1000).toISOString()), 'sensor.gone': undefined };
        card.hass = hass;
        await settle();
        assert.match(card.shadowRoot.innerHTML, /legend-value">27.5</, 'the latest number stays in the legend');
    });

    test('a change of the entities or the time span of a graph fetches its history again', async () => {
        const { hass } = await mounted();
        hass.answers['history/history_during_period'] = () => ({});
        const fetched = () => hass.calls.filter((call) => call.type === 'history/history_during_period').length;
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'h', type: 'graph', entities: ['sensor.t'], hours: 1 }] });
        await settle();
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'h', type: 'graph', entities: ['sensor.t'], hours: 6 }] });
        await settle();
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'h', type: 'graph', entities: ['sensor.t', 'sensor.u'], hours: 6 }] });
        await settle();
        assert.equal(fetched(), 3);
        hass.push('haanim/card/subscribe', { blocks: [] });
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'h', type: 'graph', entities: ['sensor.t', 'sensor.u'], hours: 6 }] });
        await settle();
        assert.equal(fetched(), 4, 'a graph that was removed and set again is new');
    });

    test('history that cannot be fetched is said on the graph', async () => {
        const { card, hass } = await mounted();
        hass.answers['history/history_during_period'] = new Error('Unknown command');
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'h', type: 'graph', entities: ['sensor.t'], hours: 1 }] });
        await settle();
        assert.match(card.shadowRoot.innerHTML, /History is not available: Unknown command/);
    });

    test("a graph of the automation's own series needs no history", async () => {
        const { card, hass } = await mounted();
        hass.push('haanim/card/subscribe', { blocks: [{ id: 'g', type: 'graph', kind: 'bar', x: 'index', series: { A: [[0, 1], [1, 3]] } }] });
        await settle();
        assert.equal(hass.calls.filter((call) => call.type === 'history/history_during_period').length, 0);
        assert.match(card.shadowRoot.innerHTML, /<rect class="bar"/);
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

    test('ends its subscriptions when it leaves the page', async () => {
        const { card, hass } = await mounted();
        card.disconnectedCallback();
        await settle();
        assert.equal(hass.active('haanim/card/subscribe').length, 0);
    });

    test('a new automation ID starts over', async () => {
        const { card, hass } = await mounted();
        hass.answers['haanim/automations/get'] = (message) => ({ ...DETAIL, id: message.automation_id, name: 'Other' });
        hass.push('haanim/card/subscribe', { blocks: [], title: 'Old title' });
        card.shadowRoot.fire('click', clicked({ 'haanim-ui': 'actions' }));
        card.setConfig({ automation_id: 'other' });
        await settle();
        assert.doesNotMatch(card.shadowRoot.innerHTML, /Old title|class="overlay"/);
        assert.deepEqual(hass.active('haanim/card/subscribe').map((subscription) => subscription.message.automation_id), ['other']);
        assert.match(card.shadowRoot.innerHTML, /<span class="name">Other<\/span>/);
        card.setConfig({ automation_id: 'other' });
        await settle();
        assert.equal(hass.active('haanim/card/subscribe').length, 1);
    });
});

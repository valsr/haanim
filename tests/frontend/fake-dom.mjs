/**
 * The few browser globals the HAAnim elements use, so they can run in node.
 *
 * A shadow root keeps its HTML as a string and its listeners in a map; elements a test wants found by ID are
 * put into `byId`. That is enough to drive the elements' logic; what they draw is checked as HTML text.
 */

export class FakeShadowRoot {
    constructor() {
        this.innerHTML = '';
        this.listeners = {};
        this.byId = {};
    }

    addEventListener(type, listener) {
        (this.listeners[type] = this.listeners[type] || []).push(listener);
    }

    getElementById(id) {
        return this.byId[id] || null;
    }

    /** Elements a test wants found by a selector: put them into `found[selector]`. */
    querySelectorAll(selector) {
        return (this.found && this.found[selector]) || [];
    }

    /** Put a stand-in element under an ID, so the element under test finds it. */
    stub(id, extra = {}) {
        this.byId[id] = {
            innerHTML: '',
            scrolled: 0,
            scrollIntoView() {
                this.scrolled += 1;
            },
            ...extra,
        };
        return this.byId[id];
    }

    /** Deliver an event to the listeners, as the browser does for an event inside the shadow root. */
    fire(type, event) {
        for (const listener of this.listeners[type] || []) listener(event);
    }
}

export class FakeHTMLElement {
    attachShadow() {
        this.shadowRoot = new FakeShadowRoot();
        return this.shadowRoot;
    }

    dispatchEvent(event) {
        (this.dispatched = this.dispatched || []).push(event);
        return true;
    }
}

/**
 * An element as a click reports it: `closest` finds it by the data attribute it carries.
 *
 * The keys of `dataset` are written as in HTML without the `data-` prefix (`'haanim-ui'`); the element's
 * dataset has them in camel case, as in the browser.
 */
export function clicked(attributes) {
    const dataset = {};
    for (const [name, value] of Object.entries(attributes)) {
        dataset[name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
    }
    return {
        target: {
            dataset,
            closest(selector) {
                const name = /^\[data-([a-z-]+)\]$/.exec(selector)[1];
                return name in attributes ? this : null;
            },
        },
    };
}

/** Install the globals. Returns what the tests inspect: the registry and the window. */
export function installDom() {
    const registry = new Map();
    globalThis.HTMLElement = FakeHTMLElement;
    globalThis.customElements = {
        define: (name, constructor) => registry.set(name, constructor),
        get: (name) => registry.get(name),
    };
    const visited = [];
    const fired = [];
    globalThis.window = {
        confirm: () => true,
        customCards: undefined,
        dispatchEvent: (event) => fired.push(event.type),
    };
    globalThis.history = { pushState: (state, title, path) => visited.push(path) };
    globalThis.CustomEvent = class {
        constructor(type, init) {
            this.type = type;
            Object.assign(this, init);
        }
    };
    globalThis.URL.createObjectURL = (blob) => `blob:${blob.name}`;
    return { registry, window: globalThis.window, visited, fired };
}

/** A stand-in for the `hass` object: records calls and lets a test push subscription messages. */
export class FakeHass {
    constructor(states = {}) {
        this.states = states;
        this.calls = [];
        this.services = [];
        this.subscriptions = [];
        this.answers = {};
        this.fetched = [];
        this.failSubscribe = null;
        this.connection = {
            subscribeMessage: async (callback, message) => {
                if (this.failSubscribe) throw this.failSubscribe;
                const subscription = { callback, message, active: true };
                this.subscriptions.push(subscription);
                return () => {
                    subscription.active = false;
                };
            },
        };
    }

    async callWS(message) {
        this.calls.push(message);
        const answer = this.answers[message.type];
        if (answer instanceof Error) throw answer;
        return typeof answer === 'function' ? answer(message) : answer;
    }

    async callService(domain, service, data) {
        this.services.push({ domain, service, data });
        if (this.failService) throw this.failService;
    }

    async fetchWithAuth(url) {
        this.fetched.push(url);
        return { ok: !url.includes('missing'), status: 404, blob: async () => ({ name: url }) };
    }

    /** Deliver a message to the active subscriptions of a type. */
    push(type, message) {
        for (const subscription of this.subscriptions) {
            if (subscription.active && subscription.message.type === type) subscription.callback(message);
        }
    }

    active(type) {
        return this.subscriptions.filter((subscription) => subscription.active && subscription.message.type === type);
    }
}

/** Let pending promise callbacks run. */
export async function settle() {
    for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
}

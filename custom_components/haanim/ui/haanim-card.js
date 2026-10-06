/**
 * custom:haanim-card
 *
 * The card of one automation: a header with the title, state and status message, the content the automation
 * puts there through `haa.card`, a button that opens its actions in a popup, and one that goes to its log in
 * the HAAnim panel. Configured with the automation ID:
 *
 *     type: custom:haanim-card
 *     automation_id: climate
 */

import { automationPath, renderCard, serviceCall } from './haanim-render.js';

const DOMAIN = 'haanim';

/** Go to another page of Home Assistant without reloading it. */
export function navigate(path) {
    history.pushState(null, '', path);
    window.dispatchEvent(new CustomEvent('location-changed', { detail: { replace: false } }));
}

const STYLES = `
    :host { display: block; }
    .card { padding: 16px; }
    .header .title { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
    .name { font-size: 1.3em; font-weight: 500; color: var(--primary-text-color); }
    .state { padding: 2px 10px; border-radius: 12px; font-size: 0.85em; color: white; white-space: nowrap; }
    .state-running { background: var(--success-color, #4caf50); }
    .state-stopped { background: var(--warning-color, #ff9800); }
    .state-disabled, .state-unavailable { background: var(--disabled-color, #9e9e9e); }
    .state-error { background: var(--error-color, #f44336); }
    .message { margin-top: 4px; color: var(--secondary-text-color); }
    button {
        background: var(--primary-color); color: var(--text-primary-color, white); border: none;
        padding: 6px 14px; border-radius: 4px; cursor: pointer; font: inherit;
    }
    .content { margin-top: 12px; border-top: 1px solid var(--divider-color); padding-top: 12px; }
    .content.bare { margin-top: 0; border-top: none; padding-top: 0; }
    .title .state:only-child { margin-left: auto; }
    .block { margin-bottom: 10px; }
    .block-value, .block-entity { display: flex; justify-content: space-between; gap: 12px; }
    .block .label { color: var(--secondary-text-color); }
    .block .value { font-weight: 500; }
    .block img { max-width: 100%; border-radius: 4px; }
    .block-icon { display: flex; align-items: center; gap: 12px; }
    .block-icon[data-more-info] { cursor: pointer; }
    .block-icon .icon { --mdc-icon-size: 32px; display: inline-flex; color: var(--primary-text-color); }
    .block-icon .icon.inactive { color: var(--state-inactive-color, var(--disabled-color, #9e9e9e)); }
    .block-icon .icon.spin { animation: haanim-spin 1.5s linear infinite; }
    .block-icon .value { margin-left: auto; }
    @keyframes haanim-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .block-icon .icon.spin { animation: none; } }
    .block-text p, .block-text h1, .block-text h2, .block-text h3 { margin: 0 0 6px 0; }
    ul { list-style: none; margin: 8px 0 0 0; padding: 0; }
    .block-text ul { list-style: disc; padding-left: 20px; }
    .toolbar {
        margin-top: 12px; border-top: 1px solid var(--divider-color); padding-top: 12px;
        display: flex; gap: 8px;
    }
    button.tool { background: transparent; color: var(--primary-color); border: 1px solid var(--primary-color); }
    .overlay {
        position: fixed; inset: 0; z-index: 10; background: rgba(0, 0, 0, 0.45);
        display: flex; align-items: center; justify-content: center;
    }
    .dialog {
        background: var(--card-background-color, white); color: var(--primary-text-color);
        border-radius: 12px; padding: 20px; min-width: 280px; max-width: min(560px, 90vw);
        max-height: 80vh; overflow-y: auto; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
    }
    .dialog-title { font-size: 1.2em; font-weight: 500; margin-bottom: 8px; }
    .dialog-buttons { margin-top: 16px; display: flex; justify-content: flex-end; }
    .actions li { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
    .description { color: var(--secondary-text-color); font-size: 0.9em; }
    .empty, .card-loading { color: var(--secondary-text-color); font-style: italic; margin-top: 8px; }
    .card-error { color: var(--error-color, #f44336); }
`;

export class HAAnimCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._config = null;
        this._hass = null;
        this._automation = null;
        this._blocks = [];
        this._title = null;
        this._options = null;
        this._images = {};
        this._showActions = false;
        this._error = null;
        this._unsubscribe = [];
        this._subscribed = false;
        this._connected = false;
        this._watched = '';
        this.shadowRoot.addEventListener('click', (event) => this._onClick(event));
    }

    /** Called by the dashboard with the card's configuration. */
    setConfig(config) {
        if (!config || !config.automation_id) {
            throw new Error('haanim-card: automation_id is required');
        }
        const changed = this._config && this._config.automation_id !== config.automation_id;
        this._config = config;
        if (changed) {
            this._stop();
            this._automation = null;
            this._blocks = [];
            this._title = null;
            this._options = null;
            this._showActions = false;
            this._start();
        }
        this._render();
    }

    /** Called by Home Assistant whenever anything in it changes. */
    set hass(hass) {
        this._hass = hass;
        this._start();
        this._onStates();
    }

    get hass() {
        return this._hass;
    }

    connectedCallback() {
        this._connected = true;
        this._start();
        this._render();
    }

    disconnectedCallback() {
        this._connected = false;
        this._stop();
    }

    getCardSize() {
        return 3 + Math.ceil(this._blocks.length / 2);
    }

    static getStubConfig() {
        return { automation_id: '' };
    }

    get _automationId() {
        return this._config ? this._config.automation_id : null;
    }

    get _entityId() {
        return `sensor.${DOMAIN}_${this._automationId}`;
    }

    /** Subscribe to the automation's card content and read its details. */
    async _start() {
        if (this._subscribed || !this._connected || !this._hass || !this._automationId) return;
        this._subscribed = true;
        const automationId = this._automationId;
        try {
            const card = await this._hass.connection.subscribeMessage((message) => this._onCard(message), {
                type: `${DOMAIN}/card/subscribe`,
                automation_id: automationId,
            });
            this._unsubscribe.push(card);
            this._error = null;
            await this._loadAutomation();
        } catch (error) {
            // Not there (yet): try again when the automation's entity next changes
            this._stop();
            this._error = `Automation "${automationId}" is not available: ${(error && error.message) || error}`;
            this._render();
        }
    }

    _stop() {
        for (const unsubscribe of this._unsubscribe) {
            Promise.resolve()
                .then(() => unsubscribe())
                .catch(() => undefined);
        }
        this._unsubscribe = [];
        this._subscribed = false;
    }

    async _loadAutomation() {
        if (!this._hass || !this._automationId) return;
        this._automation = await this._hass.callWS({
            type: `${DOMAIN}/automations/get`,
            automation_id: this._automationId,
        });
        this._render();
    }

    _onCard(message) {
        this._blocks = message.blocks || [];
        this._title = message.title || null;
        this._options = message.options || null;
        this._loadImages();
        this._render();
    }

    /** Fetch asset images with the session's credentials: an <img> request would not carry them. */
    _loadImages() {
        for (const block of this._blocks) {
            if (block.type !== 'image' || !block.asset || block.url in this._images) continue;
            this._images[block.url] = null;
            this._hass
                .fetchWithAuth(block.url)
                .then((response) => (response.ok ? response.blob() : Promise.reject(new Error(response.status))))
                .then((blob) => {
                    this._images[block.url] = URL.createObjectURL(blob);
                    this._render();
                })
                .catch(() => {
                    delete this._images[block.url];
                });
        }
    }

    /** React to state changes: the automation's own entity, and the entities its card shows. */
    _onStates() {
        if (!this._hass || !this._automationId) return;
        const states = this._hass.states || {};
        const own = states[this._entityId];
        const ids = this._blocks
            .filter((block) => block.type === 'entity' || (block.type === 'icon' && block.follow_entity))
            .map((block) => block.entity_id);
        const watched = [this._entityId, ...ids]
            .map((id) => `${id}=${states[id] ? `${states[id].state}@${states[id].last_updated}` : ''}`)
            .join('|');
        if (watched === this._watched) return;
        const before = this._ownState;
        this._watched = watched;
        this._ownState = own ? own.state : 'unavailable';
        if (!this._subscribed) {
            this._start();
        } else if (before === 'unavailable' && this._ownState !== 'unavailable') {
            // The integration was reloaded: the old subscriptions are dead
            this._stop();
            this._start();
        } else if (before !== undefined) {
            // The first time, subscribing reads the details itself
            this._loadAutomation().catch(() => undefined);
        }
        this._render();
    }

    _onClick(event) {
        const target = event.target && event.target.closest ? event.target : null;
        if (!target || !this._hass) return;
        const control = target.closest('[data-haanim]');
        if (control) {
            this._call(control.dataset);
            return;
        }
        const more = target.closest('[data-more-info]');
        if (more) {
            this.dispatchEvent(
                new CustomEvent('hass-more-info', {
                    detail: { entityId: more.dataset.moreInfo },
                    bubbles: true,
                    composed: true,
                })
            );
            return;
        }
        const own = target.closest('[data-haanim-ui]');
        const what = own ? own.dataset.haanimUi : null;
        if (what === 'actions') {
            this._showActions = true;
            this._render();
        } else if (what === 'close') {
            this._showActions = false;
            this._render();
        } else if (what === 'log') {
            navigate(automationPath(this._automationId, true));
        }
    }

    /** Call the service a clicked control stands for; running an action from the popup closes it. */
    _call(dataset) {
        const call = serviceCall(dataset, this._automationId);
        if (!call) return;
        if (call.confirm && !window.confirm(call.confirm)) return;
        if (this._showActions) {
            this._showActions = false;
            this._render();
        }
        this._hass.callService(DOMAIN, call.service, call.data).catch((error) => {
            this.dispatchEvent(
                new CustomEvent('hass-notification', {
                    detail: { message: (error && error.message) || String(error) },
                    bubbles: true,
                    composed: true,
                })
            );
        });
    }

    _render() {
        const body = renderCard({
            automation: this._automation,
            title: this._title,
            options: this._options,
            blocks: this._blocks,
            states: this._hass ? this._hass.states : {},
            images: this._images,
            showActions: this._showActions,
            error: this._config ? this._error : 'No automation configured',
        });
        this.shadowRoot.innerHTML = `<style>${STYLES}</style><ha-card><div class="card">${body}</div></ha-card>`;
        // Home Assistant's own state icons take the entity's state as a property, not as markup
        const states = this._hass ? this._hass.states || {} : {};
        const icons = this.shadowRoot.querySelectorAll ? this.shadowRoot.querySelectorAll('[data-state-icon]') : [];
        for (const icon of icons) {
            icon.hass = this._hass;
            icon.stateObj = states[icon.dataset.stateIcon];
        }
    }
}

if (!customElements.get('haanim-card')) {
    customElements.define('haanim-card', HAAnimCard);
    window.customCards = window.customCards || [];
    window.customCards.push({
        type: 'haanim-card',
        name: 'HAAnim automation',
        description: 'The card of one HAAnim automation: its title, state, content and actions',
    });
}

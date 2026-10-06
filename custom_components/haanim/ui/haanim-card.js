/**
 * custom:haanim-card
 *
 * The card of one automation: a fixed header with controls, the content the automation puts there through
 * `haa.card`, its actions and its recent log. Configured with the automation ID:
 *
 *     type: custom:haanim-card
 *     automation_id: climate
 */

import { MAX_LOG_RECORDS, renderCard, serviceCall } from './haanim-render.js';

const DOMAIN = 'haanim';

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
    .controls { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; }
    button {
        background: var(--primary-color); color: var(--text-primary-color, white); border: none;
        padding: 6px 14px; border-radius: 4px; cursor: pointer; font: inherit;
    }
    button.control { background: transparent; color: var(--primary-color); border: 1px solid var(--primary-color); }
    .content { margin-top: 12px; border-top: 1px solid var(--divider-color); padding-top: 12px; }
    .block { margin-bottom: 10px; }
    .block-value, .block-entity { display: flex; justify-content: space-between; gap: 12px; }
    .block .label { color: var(--secondary-text-color); }
    .block .value { font-weight: 500; }
    .block img { max-width: 100%; border-radius: 4px; }
    .block-text p, .block-text h1, .block-text h2, .block-text h3 { margin: 0 0 6px 0; }
    .section { margin-top: 12px; border-top: 1px solid var(--divider-color); padding-top: 8px; }
    summary { cursor: pointer; color: var(--secondary-text-color); }
    ul { list-style: none; margin: 8px 0 0 0; padding: 0; }
    .block-text ul { list-style: disc; padding-left: 20px; }
    .actions li { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
    .description { color: var(--secondary-text-color); font-size: 0.9em; }
    .log { max-height: 260px; overflow-y: auto; font-family: var(--code-font-family, monospace); font-size: 0.85em; }
    .record { display: flex; flex-wrap: wrap; gap: 8px; padding: 2px 0; }
    .record .time, .record .level { color: var(--secondary-text-color); }
    .level-warning .level, .level-warning .text { color: var(--warning-color, #ff9800); }
    .level-error .level, .level-error .text, .level-critical .level, .level-critical .text {
        color: var(--error-color, #f44336);
    }
    .level-debug .text { color: var(--secondary-text-color); }
    .traceback { flex-basis: 100%; margin: 2px 0 6px 0; white-space: pre-wrap; }
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
        this._records = [];
        this._images = {};
        this._open = { actions: false, log: false };
        this._error = null;
        this._unsubscribe = [];
        this._subscribed = false;
        this._connected = false;
        this._watched = '';
        this.shadowRoot.addEventListener('click', (event) => this._onClick(event));
        this.shadowRoot.addEventListener('toggle', (event) => this._onToggle(event), true);
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
            this._records = [];
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

    /** Subscribe to the automation's card content and log, and read its details. */
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
            const log = await this._hass.connection.subscribeMessage((message) => this._onLog(message), {
                type: `${DOMAIN}/logs/subscribe`,
                automation_id: automationId,
            });
            this._unsubscribe.push(log);
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
        this._loadImages();
        this._render();
    }

    _onLog(message) {
        if (message.records) {
            this._records = message.records.slice(-MAX_LOG_RECORDS);
        } else if (message.record) {
            this._records = [...this._records, message.record].slice(-MAX_LOG_RECORDS);
        }
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
        const ids = this._blocks.filter((block) => block.type === 'entity').map((block) => block.entity_id);
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
        const element = event.target && event.target.closest ? event.target.closest('[data-haanim]') : null;
        if (!element || !this._hass) return;
        const call = serviceCall(element.dataset, this._automationId);
        if (!call) return;
        if (call.confirm && !window.confirm(call.confirm)) return;
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

    _onToggle(event) {
        const section = event.target && event.target.dataset ? event.target.dataset.section : null;
        if (section) this._open[section] = Boolean(event.target.open);
    }

    _render() {
        const body = renderCard({
            automation: this._automation,
            blocks: this._blocks,
            records: this._records,
            states: this._hass ? this._hass.states : {},
            images: this._images,
            open: this._open,
            error: this._config ? this._error : 'No automation configured',
        });
        this.shadowRoot.innerHTML = `<style>${STYLES}</style><ha-card><div class="card">${body}</div></ha-card>`;
    }
}

if (!customElements.get('haanim-card')) {
    customElements.define('haanim-card', HAAnimCard);
    window.customCards = window.customCards || [];
    window.customCards.push({
        type: 'haanim-card',
        name: 'HAAnim automation',
        description: 'State, controls, content, actions and log of one HAAnim automation',
    });
}

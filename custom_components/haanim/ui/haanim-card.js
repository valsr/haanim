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

import { historyPoints } from './haanim-graph.js';
import { automationPath, cameraUrl, renderCard, serviceCall } from './haanim-render.js';

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
    .state-idle { background: var(--primary-color, #03a9f4); }
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
    /* Cells share the row equally, and wrap onto further lines when the card is too narrow for them */
    .row {
        display: grid; gap: 4px 12px; align-items: start;
        grid-template-columns: repeat(auto-fit, minmax(max(40px, calc(100% / var(--cells) - 12px)), 1fr));
    }
    .cell { min-width: 0; }
    .cell button.card-button { width: 100%; }
    .block-value, .block-entity { display: flex; justify-content: space-between; gap: 12px; }
    .block .label { color: var(--secondary-text-color); }
    .block .value { font-weight: 500; }
    .block img { max-width: 100%; border-radius: 4px; object-fit: contain; vertical-align: top; }
    .block-image[data-more-info] img { cursor: pointer; }
    .block-image.align-center { text-align: center; }
    .block-image.align-right { text-align: right; }
    .block-image .caption { color: var(--secondary-text-color); font-size: 0.9em; margin-top: 4px; }
    .graph { width: 100%; height: auto; display: block; }
    .graph .grid { stroke: var(--divider-color, #e0e0e0); stroke-width: 1; }
    .graph .tick { fill: var(--secondary-text-color, #727272); font-size: 10px; }
    .graph .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
    .graph .area { fill-opacity: 0.18; stroke: none; }
    .graph { overflow: visible; }
    .graph .axis, .graph .tick-major { stroke: var(--secondary-text-color, #727272); stroke-width: 1; }
    .graph .tick-minor { stroke: var(--divider-color, #bdbdbd); stroke-width: 1; }
    .graph .hit { fill: transparent; }
    .graph .guide { stroke: var(--secondary-text-color, #727272); stroke-width: 1; stroke-dasharray: 3 3; }
    .graph .dot { stroke: var(--card-background-color, white); stroke-width: 1.5; }
    .graph .readout rect {
        fill: var(--card-background-color, white); stroke: var(--divider-color, #e0e0e0); fill-opacity: 0.95;
    }
    .graph .readout text { fill: var(--primary-text-color, #212121); font-size: 10px; }
    .graph .readout-title { font-weight: 600; }
    .graph .guide, .graph .dot, .graph .readout { opacity: 0; pointer-events: none; }
    .graph .hover:hover .guide, .graph .hover:hover .dot, .graph .hover:hover .readout { opacity: 1; }
    .graph .row-label { fill: var(--secondary-text-color, #727272); font-size: 10px; }
    .graph .segment { stroke: none; }
    .swatch.square { border-radius: 2px; }
    .legend.states { font-size: 0.8em; }
    .graph-title { font-weight: 500; margin-bottom: 4px; }
    .graph-empty { color: var(--secondary-text-color); font-style: italic; padding: 24px 0; text-align: center; }
    .legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 4px; font-size: 0.9em; }
    .legend-item { display: inline-flex; align-items: center; gap: 6px; }
    .swatch { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .legend-name { color: var(--secondary-text-color); }
    .legend-value { font-weight: 500; }
    .block-icon { display: flex; align-items: center; gap: 12px; }
    .block-icon[data-more-info] { cursor: pointer; }
    /* In a cell there is no room for icon, name and state side by side: they go below each other */
    .cell .block-icon { flex-direction: column; gap: 2px; text-align: center; }
    .cell .block-icon .value { margin-left: 0; }
    .cell .block-icon .label, .cell .block-icon .value { max-width: 100%; overflow-wrap: anywhere; }
    .block-icon .icon { --mdc-icon-size: 32px; display: inline-flex; color: var(--primary-text-color); }
    .block-icon .icon.inactive { color: var(--state-inactive-color, var(--disabled-color, #9e9e9e)); }
    .block-icon .icon.spin { animation: haanim-spin 1.5s linear infinite; }
    .block-icon .value { margin-left: auto; }
    @keyframes haanim-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .block-icon .icon.spin { animation: none; } }
    .block-gauge[data-more-info], .block-badge[data-more-info] { cursor: pointer; }
    .gauge-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
    .block-gauge .bar {
        height: 8px; border-radius: 4px; overflow: hidden;
        background: var(--divider-color, #e0e0e0);
    }
    .block-gauge .fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
    .block-gauge .dial { display: block; width: 100%; max-width: 180px; margin: 0 auto; }
    .block-gauge .dial ~ .label { display: block; text-align: center; }
    .dial-track, .dial-fill { fill: none; stroke-width: 10; stroke-linecap: round; }
    .dial-track { stroke: var(--divider-color, #e0e0e0); }
    .dial-fill { transition: stroke-dasharray 0.3s ease; }
    .dial-value { fill: var(--primary-text-color, #212121); font-size: 18px; font-weight: 500; }
    .dial-unit { font-size: 10px; font-weight: 400; fill: var(--secondary-text-color, #727272); }
    .block-badge { display: flex; }
    .badge {
        display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 12px;
        background: var(--primary-color); color: white; font-size: 0.85em; font-weight: 500;
        --mdc-icon-size: 16px; max-width: 100%;
    }
    .badge-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    @media (prefers-reduced-motion: reduce) { .block-gauge .fill, .dial-fill { transition: none; } }
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
        this._layout = null;
        this._images = {};
        this._history = {};
        // Camera pictures: a clock that counts seconds while the card shows cameras, and the stamp of the
        // picture each camera block last fetched
        this._timer = null;
        this._seconds = 0;
        this._stampBase = Date.now();
        this._stamps = {};
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
            this._layout = null;
            this._history = {};
            this._stamps = {};
            this._showActions = false;
            this._watchCameras();
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
        this._watchCameras();
        this._render();
    }

    disconnectedCallback() {
        this._connected = false;
        this._watchCameras();
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
        this._layout = Array.isArray(message.layout) ? message.layout : null;
        this._loadImages();
        this._loadHistory();
        this._watchCameras();
        this._render();
    }

    /** The image blocks that show the picture of a camera. */
    _cameras() {
        return this._blocks.filter((block) => block.type === 'image' && block.entity_id);
    }

    /** Run the clock that fetches camera pictures while the card is on a page and shows a camera. */
    _watchCameras() {
        const wanted = this._connected && this._cameras().length > 0;
        if (wanted && this._timer === null) {
            this._timer = setInterval(() => this._onSecond(), 1000);
        } else if (!wanted && this._timer !== null) {
            clearInterval(this._timer);
            this._timer = null;
        }
    }

    /**
     * Fetch the picture of every camera whose time has come.
     *
     * Only the address of the image is changed, so the old picture stays until the new one is there.
     * Nothing is fetched while the page is not visible.
     */
    _onSecond() {
        if (typeof document !== 'undefined' && document.hidden) return;
        this._seconds += 1;
        const due = new Map();
        for (const block of this._cameras()) {
            const every = Math.max(1, Math.round(Number(block.refresh) || 10));
            if (this._seconds % every !== 0) continue;
            this._stamps[block.id] = this._stampBase + this._seconds;
            due.set(String(block.id), block);
        }
        if (due.size === 0) return;
        const states = this._hass ? this._hass.states || {} : {};
        for (const image of this.shadowRoot.querySelectorAll('img[data-camera]')) {
            const block = due.get(image.dataset.camera);
            const url = block ? cameraUrl(states[block.entity_id], this._stamps[block.id]) : null;
            if (url) image.src = url;
        }
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

    /**
     * Fetch the recorded history of the entities of the card's graphs.
     *
     * It is fetched once per graph, and again only if the graph's entities or time span change. From then
     * on the graph follows the entities' states as Home Assistant reports them.
     */
    _loadHistory() {
        const graphs = this._blocks.filter((block) => block.type === 'graph' && block.entities);
        const kept = {};
        for (const block of graphs) {
            const key = `${block.entities.join(',')}|${block.hours}`;
            const known = this._history[block.id];
            if (known && known.key === key) {
                kept[block.id] = known;
                continue;
            }
            const entry = { key, points: {}, loaded: false };
            kept[block.id] = entry;
            const end = new Date();
            const start = new Date(end.getTime() - block.hours * 3600000);
            this._hass
                .callWS({
                    type: 'history/history_during_period',
                    start_time: start.toISOString(),
                    end_time: end.toISOString(),
                    entity_ids: block.entities,
                    minimal_response: true,
                    no_attributes: true,
                    include_start_time_state: true,
                    significant_changes_only: false,
                })
                .then((result) => {
                    for (const entityId of block.entities) {
                        // Changes that arrived while the history was on its way come after it
                        const live = entry.points[entityId] || [];
                        entry.points[entityId] = [...historyPoints((result || {})[entityId]), ...live];
                    }
                    entry.loaded = true;
                })
                .catch((error) => {
                    entry.error = (error && error.message) || String(error);
                })
                .then(() => {
                    if (this._history[block.id] === entry) this._render();
                });
        }
        this._history = kept;
    }

    /** Add the current state of every graphed entity to its history, if it is a new one. */
    _followHistory(states) {
        for (const block of this._blocks) {
            const entry = block.type === 'graph' && block.entities ? this._history[block.id] : null;
            if (!entry) continue;
            for (const entityId of block.entities) {
                const state = states[entityId];
                if (!state) continue;
                const points = entry.points[entityId] || (entry.points[entityId] = []);
                const time = Date.parse(state.last_updated) || Date.now();
                const last = points[points.length - 1];
                if (!last || time > last[0]) points.push([time, String(state.state)]);
            }
        }
    }

    /** React to state changes: the automation's own entity, and the entities its card shows. */
    _onStates() {
        if (!this._hass || !this._automationId) return;
        const states = this._hass.states || {};
        const own = states[this._entityId];
        const ids = this._blocks.flatMap((block) => {
            if (block.type === 'graph') return block.entities || [];
            // Every other block with an entity shows its state; an icon only if it follows the entity
            const follows = block.entity_id && (block.type !== 'icon' || block.follow_entity);
            return follows ? [block.entity_id] : [];
        });
        const watched = [this._entityId, ...ids]
            .map((id) => `${id}=${states[id] ? `${states[id].state}@${states[id].last_updated}` : ''}`)
            .join('|');
        if (watched === this._watched) return;
        const before = this._ownState;
        this._watched = watched;
        this._followHistory(states);
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
            navigate(automationPath(this._automationId, 'logs'));
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

    /**
     * The automation as last read, with what its entity says now.
     *
     * The entity is told about every action that starts and ends, so the state badge follows the
     * automation without a round trip for each change.
     */
    _withEntity(automation) {
        const entity = automation && this._hass && this._hass.states ? this._hass.states[this._entityId] : null;
        if (!entity || !entity.attributes) return automation;
        const now = { ...automation };
        if (['on', 'off', 'error', 'unavailable'].includes(entity.state)) now.state = entity.state;
        if (Array.isArray(entity.attributes.running_actions)) now.running_actions = entity.attributes.running_actions;
        if (typeof entity.attributes.enabled === 'boolean') now.enabled = entity.attributes.enabled;
        return now;
    }

    _render() {
        const body = renderCard({
            automation: this._withEntity(this._automation),
            title: this._title,
            options: this._options,
            blocks: this._blocks,
            layout: this._layout,
            states: this._hass ? this._hass.states : {},
            images: this._images,
            stamps: this._stamps,
            history: this._history,
            showActions: this._showActions,
            error: this._config ? this._error : 'No automation configured',
        });
        this.shadowRoot.innerHTML = `<style>${STYLES}</style><ha-card><div class="card">${body}</div></ha-card>`;
        // Raw HTML of the automation goes into its own element, so that it cannot break the rest of the card
        const raw = new Map(this._blocks.filter((block) => block.type === 'html').map((block) => [String(block.id), block]));
        const holders = this.shadowRoot.querySelectorAll ? this.shadowRoot.querySelectorAll('[data-html]') : [];
        for (const holder of holders) {
            const block = raw.get(holder.dataset.html);
            if (block) holder.innerHTML = String(block.html ?? '');
        }
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

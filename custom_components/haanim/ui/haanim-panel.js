/**
 * HAAnim panel: the management page.
 *
 * - `/haanim/config`: the integration's configuration.
 * - `/haanim`: the automations with their state and version, and the controls of each.
 * - `/haanim/automation/<id>`: one automation: a header with its state, controls and metadata, and three
 *   tabs below it. The page opens on the first, the preview of its card.
 * - `/haanim/automation/<id>/actions`: the same page with the actions tab open.
 * - `/haanim/automation/<id>/logs`: the same page with the log tab open. The card's Log button goes here.
 */

import { navigate } from './haanim-card.js';
import {
    MAX_LOG_RECORDS,
    PANEL_PATH,
    DETAIL_TABS,
    automationPath,
    detailTab,
    escapeHtml,
    parseRoute,
    renderActionList,
    renderConfig,
    renderControls,
    renderDetail,
    renderHeader,
    renderList,
    renderLog,
    renderLogTools,
    renderTabs,
    serviceCall,
} from './haanim-render.js';

const DOMAIN = 'haanim';

const STYLES = `
    :host { display: block; min-height: 100vh; background: var(--primary-background-color); }
    .top {
        display: flex; align-items: center; gap: 16px; padding: 12px 24px;
        background: var(--card-background-color); border-bottom: 1px solid var(--divider-color);
    }
    h1 { font-size: 22px; font-weight: 400; margin: 0; color: var(--primary-text-color); flex: 1; }
    h2 { font-size: 16px; font-weight: 500; margin: 24px 0 8px 0; color: var(--primary-text-color); }
    button {
        background: var(--primary-color); color: var(--text-primary-color, white); border: none;
        padding: 8px 16px; border-radius: 4px; cursor: pointer; font: inherit;
    }
    button.tab { background: transparent; color: var(--secondary-text-color); border-radius: 0; }
    button.tab.active { color: var(--primary-color); border-bottom: 2px solid var(--primary-color); }
    button.link { background: transparent; color: var(--primary-color); padding: 8px 0; }
    button.control { background: transparent; color: var(--primary-color); border: 1px solid var(--primary-color); }
    td .controls { margin: 0; flex-wrap: nowrap; }
    td button.control { padding: 4px 10px; font-size: 0.9em; }
    td.row-controls { width: 1%; white-space: nowrap; }
    .tabs { display: flex; gap: 4px; margin: 16px 0; border-bottom: 1px solid var(--divider-color); }
    .tabs button.tab { padding: 10px 20px; margin-bottom: -1px; border-bottom: 2px solid transparent; }
    .tabs button.tab.active { border-bottom-color: var(--primary-color); }
    [hidden] { display: none !important; }
    .log-tools { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
    .log-tools label { color: var(--secondary-text-color); }
    .log-tools select {
        font: inherit; padding: 4px 8px; margin-left: 6px; border-radius: 4px;
        color: var(--primary-text-color); background: var(--card-background-color);
        border: 1px solid var(--divider-color);
    }
    .log-tools button.control { padding: 4px 12px; }
    .page { padding: 24px; max-width: 1000px; margin: 0 auto; color: var(--primary-text-color); }
    table { width: 100%; border-collapse: collapse; background: var(--card-background-color); }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--divider-color); }
    th { color: var(--secondary-text-color); font-weight: 500; }
    tr.row { cursor: pointer; }
    tr.row:hover { background: var(--secondary-background-color); }
    .id, .hint, .empty, td.message, .message { color: var(--secondary-text-color); font-size: 0.9em; }
    .header .title { display: flex; align-items: center; gap: 12px; }
    .name { font-size: 1.4em; font-weight: 500; }
    .state { padding: 2px 10px; border-radius: 12px; font-size: 0.85em; color: white; white-space: nowrap; }
    .state-running { background: var(--success-color, #4caf50); }
    .state-idle { background: var(--primary-color, #03a9f4); }
    .state-stopped { background: var(--warning-color, #ff9800); }
    .state-disabled, .state-unavailable { background: var(--disabled-color, #9e9e9e); }
    .state-error { background: var(--error-color, #f44336); }
    .controls { margin: 12px 0; display: flex; flex-wrap: wrap; gap: 8px; }
    .detail { margin: 8px 0 16px 0; }
    .meta { display: flex; gap: 12px; padding: 3px 0; }
    .meta .label { color: var(--secondary-text-color); min-width: 140px; }
    haanim-card { display: block; max-width: 520px; }
    ul { list-style: none; margin: 0; padding: 0; }
    .actions li { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
    .description { color: var(--secondary-text-color); font-size: 0.9em; }
    .log {
        background: var(--card-background-color); padding: 12px; border-radius: 8px;
        font-family: var(--code-font-family, monospace); font-size: 0.85em; max-height: 60vh; overflow-y: auto;
    }
    .record { display: flex; flex-wrap: wrap; gap: 8px; padding: 2px 0; }
    .record .time, .record .level { color: var(--secondary-text-color); }
    .level-warning .level, .level-warning .text { color: var(--warning-color, #ff9800); }
    .level-error .level, .level-error .text, .level-critical .level, .level-critical .text {
        color: var(--error-color, #f44336);
    }
    .level-debug .text { color: var(--secondary-text-color); }
    .traceback { flex-basis: 100%; margin: 2px 0 6px 0; white-space: pre-wrap; }
    .error { color: var(--error-color, #f44336); }
`;

export class HAAnimPanel extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._hass = null;
        this._view = { page: 'list', id: null, section: null };
        this._automations = null;
        this._automation = null;
        this._configuration = null;
        this._records = [];
        this._unsubscribeLog = null;
        this._error = null;
        this._seen = null;
        this.shadowRoot.addEventListener('click', (event) => this._onClick(event));
        this.shadowRoot.addEventListener('change', (event) => this._onChange(event));
    }

    /** Called by Home Assistant whenever anything in it changes. */
    set hass(hass) {
        const first = this._hass === null;
        this._hass = hass;
        const card = this.shadowRoot.getElementById('detail-card');
        if (card) card.hass = hass;
        const seen = this._signature();
        if (seen !== this._seen) {
            this._seen = seen;
            this._load();
        }
        if (first) this._followLog();
    }

    get hass() {
        return this._hass;
    }

    /** Called by Home Assistant with the part of the address after the panel's own path. */
    set route(route) {
        this._open(parseRoute(route && route.path));
    }

    set panel(panel) {
        this._panel = panel;
    }

    set narrow(narrow) {
        this._narrow = narrow;
    }

    disconnectedCallback() {
        this._stopLog();
    }

    /** What the pages depend on: the state, the flags and the message of every automation entity. */
    _signature() {
        const states = (this._hass && this._hass.states) || {};
        return Object.keys(states)
            .filter((id) => id.startsWith(`sensor.${DOMAIN}_`))
            .sort()
            .map((id) => {
                const attributes = states[id].attributes || {};
                return `${id}=${states[id].state}/${attributes.enabled}/${attributes.message}/${attributes.last_action_time}`;
            })
            .join('|');
    }

    async _load() {
        if (!this._hass) return;
        const view = this._view;
        try {
            if (view.page === 'list') {
                const answer = await this._hass.callWS({ type: `${DOMAIN}/automations/list` });
                this._automations = answer.automations;
            } else if (view.page === 'detail') {
                const automation = await this._hass.callWS({ type: `${DOMAIN}/automations/get`, automation_id: view.id });
                if (view !== this._view) return;
                this._automation = automation;
            } else {
                this._configuration = await this._hass.callWS({ type: `${DOMAIN}/config/get` });
            }
            this._error = null;
        } catch (error) {
            this._error = (error && error.message) || String(error);
        }
        this._render();
    }

    /** Show a page. Does nothing if it is the page already shown, except to go to the section asked for. */
    _open(view) {
        const same = view.page === this._view.page && view.id === this._view.id;
        this._view = same ? Object.assign(this._view, { section: view.section }) : view;
        if (same) {
            this._showSection();
            return;
        }
        this._automation = null;
        this._records = [];
        this._stopLog();
        this._render(true);
        this._followLog();
        this._load();
    }

    /** Change the address, so the page can be linked to and the back button works, and show the page. */
    _go(path) {
        navigate(path);
        this._open(parseRoute(path.slice(PANEL_PATH.length)));
    }

    /** On an automation's page, follow its log: the recent records, then each new one. */
    async _followLog() {
        if (this._view.page !== 'detail' || !this._hass || this._unsubscribeLog) return;
        const view = this._view;
        this._unsubscribeLog = () => undefined;
        try {
            const unsubscribe = await this._hass.connection.subscribeMessage((message) => this._onLog(view, message), {
                type: `${DOMAIN}/logs/subscribe`,
                automation_id: view.id,
            });
            if (view === this._view) {
                this._unsubscribeLog = unsubscribe;
            } else {
                unsubscribe();
            }
        } catch (error) {
            this._unsubscribeLog = null;
        }
    }

    _stopLog() {
        const unsubscribe = this._unsubscribeLog;
        this._unsubscribeLog = null;
        if (unsubscribe) {
            Promise.resolve()
                .then(() => unsubscribe())
                .catch(() => undefined);
        }
    }

    _onLog(view, message) {
        if (view !== this._view) return;
        if (message.records) {
            this._records = message.records.slice(-MAX_LOG_RECORDS);
        } else if (message.record) {
            this._records = [...this._records, message.record].slice(-MAX_LOG_RECORDS);
        }
        this._fill('detail-log', renderLog(this._records));
    }

    _onClick(event) {
        const target = event.target && event.target.closest ? event.target : null;
        if (!target || !this._hass) return;
        const control = target.closest('[data-haanim]');
        const row = target.closest('[data-open]');
        const page = target.closest('[data-page]');
        const tab = target.closest('[data-section]');
        if (control) {
            // A control names its automation: in the list every row has its own
            const call = serviceCall(control.dataset, control.dataset.automation || this._view.id);
            if (call && call.data.automation_id) this._callService(call.service, call.data);
        } else if (tab && this._view.page === 'detail') {
            this._go(automationPath(this._view.id, tab.dataset.section));
        } else if (target.closest('[data-reload]')) {
            this._callService('reload', {});
        } else if (page) {
            this._go(page.dataset.page === 'config' ? `${PANEL_PATH}/config` : PANEL_PATH);
        } else if (row) {
            this._go(automationPath(row.dataset.open));
        }
    }

    /** A choice was made in a select: the log level of an automation. */
    _onChange(event) {
        const target = event.target && event.target.closest ? event.target.closest('[data-log-level]') : null;
        if (!target || !this._hass) return;
        this._callService('set_log_level', { automation_id: target.dataset.logLevel, level: target.value });
    }

    _callService(service, data) {
        this._hass.callService(DOMAIN, service, data).then(
            () => this._load(),
            (error) => {
                this._error = (error && error.message) || String(error);
                this._fill('page-error', this._errorHtml()) || this._render();
            }
        );
    }

    _errorHtml() {
        return this._error ? `<div class="error">${escapeHtml(this._error)}</div>` : '';
    }

    /** Put HTML into an element of the page; returns whether the element is there. */
    _fill(id, html) {
        const element = this.shadowRoot.getElementById(id);
        // What is there already is left alone: an open select or a scrolled log would lose its place
        if (element && element.innerHTML !== html) element.innerHTML = html;
        return Boolean(element);
    }

    /**
     * Show the tab the address names, and hide the others.
     *
     * All three stay on the page: the card in the preview keeps what it shows, and the log keeps filling.
     */
    _showSection() {
        const open = detailTab(this._view.section);
        this._fill('detail-tabs', renderTabs(open, this._automation));
        for (const tab of DETAIL_TABS) {
            const pane = this.shadowRoot.getElementById(`tab-${tab.section}`);
            if (pane) pane.hidden = tab.section !== open;
        }
    }

    /** The parts of an automation's page that follow the automation. The card looks after itself. */
    _fillDetail() {
        const automation = this._automation;
        this._fill('page-error', this._errorHtml());
        this._fill('detail-header', automation ? renderHeader(automation) : '');
        this._fill('detail-controls', automation ? renderControls(automation) : '');
        this._fill('detail-meta', automation ? renderDetail(automation) : '');
        this._fill('detail-actions', automation ? renderActionList(automation.actions) : '');
        this._fill('detail-log-tools', automation ? renderLogTools(automation) : '');
        this._fill('detail-log', renderLog(this._records));
        this._showSection();
    }

    /** Draw the page. An automation's page is only rebuilt when asked: rebuilding would recreate its card. */
    _render(rebuild = false) {
        const page = this._view.page;
        if (page === 'detail' && !rebuild && this.shadowRoot.getElementById('detail-card')) {
            this._fillDetail();
            return;
        }
        const tab = (name, label) =>
            `<button class="tab${page === name ? ' active' : ''}" data-page="${name}">${label}</button>`;
        let body;
        if (page === 'detail') {
            body =
                '<button class="link" data-page="list">← All automations</button>' +
                '<div id="detail-header"></div><div id="detail-controls"></div><div id="detail-meta"></div>' +
                '<div id="detail-tabs"></div>' +
                '<div id="tab-preview" role="tabpanel"><haanim-card id="detail-card"></haanim-card></div>' +
                '<div id="tab-actions" role="tabpanel" hidden><div id="detail-actions"></div></div>' +
                '<div id="tab-logs" role="tabpanel" hidden><div id="detail-log-tools"></div><div id="detail-log"></div></div>';
        } else if (page === 'config') {
            body = renderConfig(this._configuration);
        } else {
            body = this._automations === null ? '<div class="empty">Loading…</div>' : renderList(this._automations);
        }
        this.shadowRoot.innerHTML =
            `<style>${STYLES}</style>` +
            '<div class="top"><h1>HAAnim</h1>' +
            `${tab('list', 'Automations')}${tab('config', 'Configuration')}` +
            '<button data-reload="all">Reload all</button></div>' +
            `<div class="page"><div id="page-error">${this._errorHtml()}</div>${body}</div>`;
        const card = this.shadowRoot.getElementById('detail-card');
        if (card) {
            card.setConfig({ automation_id: this._view.id });
            card.hass = this._hass;
            this._fillDetail();
        }
    }
}

if (!customElements.get('haanim-panel')) {
    customElements.define('haanim-panel', HAAnimPanel);
}

/**
 * HAAnim panel: the management page.
 *
 * A list of the automations with their state and version, the integration's configuration on a second tab,
 * and a detail page per automation that shows its metadata and its card.
 */

import './haanim-card.js';
import { escapeHtml, renderConfig, renderDetail, renderList } from './haanim-render.js';

const DOMAIN = 'haanim';

const STYLES = `
    :host { display: block; min-height: 100vh; background: var(--primary-background-color); }
    .top {
        display: flex; align-items: center; gap: 16px; padding: 12px 24px;
        background: var(--card-background-color); border-bottom: 1px solid var(--divider-color);
    }
    h1 { font-size: 22px; font-weight: 400; margin: 0; color: var(--primary-text-color); flex: 1; }
    button {
        background: var(--primary-color); color: var(--text-primary-color, white); border: none;
        padding: 8px 16px; border-radius: 4px; cursor: pointer; font: inherit;
    }
    button.tab { background: transparent; color: var(--secondary-text-color); border-radius: 0; }
    button.tab.active { color: var(--primary-color); border-bottom: 2px solid var(--primary-color); }
    button.link { background: transparent; color: var(--primary-color); padding: 8px 0; }
    .page { padding: 24px; max-width: 1000px; margin: 0 auto; color: var(--primary-text-color); }
    table { width: 100%; border-collapse: collapse; background: var(--card-background-color); }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--divider-color); }
    th { color: var(--secondary-text-color); font-weight: 500; }
    tr.row { cursor: pointer; }
    tr.row:hover { background: var(--secondary-background-color); }
    .id, .hint, .empty, td.message { color: var(--secondary-text-color); font-size: 0.9em; }
    .state { padding: 2px 10px; border-radius: 12px; font-size: 0.85em; color: white; white-space: nowrap; }
    .state-running { background: var(--success-color, #4caf50); }
    .state-stopped { background: var(--warning-color, #ff9800); }
    .state-disabled, .state-unavailable { background: var(--disabled-color, #9e9e9e); }
    .state-error { background: var(--error-color, #f44336); }
    .detail { margin: 8px 0 16px 0; }
    .meta { display: flex; gap: 12px; padding: 3px 0; }
    .meta .label { color: var(--secondary-text-color); min-width: 140px; }
    .error { color: var(--error-color, #f44336); }
`;

export class HAAnimPanel extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._hass = null;
        this._view = { page: 'list', id: null };
        this._automations = null;
        this._automation = null;
        this._configuration = null;
        this._error = null;
        this._seen = null;
        this.shadowRoot.addEventListener('click', (event) => this._onClick(event));
    }

    /** Called by Home Assistant whenever anything in it changes. */
    set hass(hass) {
        this._hass = hass;
        const card = this.shadowRoot.getElementById('detail-card');
        if (card) card.hass = hass;
        const seen = this._signature();
        if (seen !== this._seen) {
            this._seen = seen;
            this._load();
        }
    }

    get hass() {
        return this._hass;
    }

    set panel(panel) {
        this._panel = panel;
    }

    set narrow(narrow) {
        this._narrow = narrow;
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
        try {
            if (this._view.page === 'list') {
                const answer = await this._hass.callWS({ type: `${DOMAIN}/automations/list` });
                this._automations = answer.automations;
            } else if (this._view.page === 'detail') {
                this._automation = await this._hass.callWS({
                    type: `${DOMAIN}/automations/get`,
                    automation_id: this._view.id,
                });
            } else {
                this._configuration = await this._hass.callWS({ type: `${DOMAIN}/config/get` });
            }
            this._error = null;
        } catch (error) {
            this._error = (error && error.message) || String(error);
        }
        this._render();
    }

    _show(page, id = null) {
        this._view = { page, id };
        this._automation = null;
        this._render(true);
        this._load();
    }

    _onClick(event) {
        const target = event.target && event.target.closest ? event.target : null;
        if (!target) return;
        const row = target.closest('[data-open]');
        const page = target.closest('[data-page]');
        if (target.closest('[data-reload]')) {
            this._hass.callService(DOMAIN, 'reload', {}).then(
                () => this._load(),
                (error) => {
                    this._error = (error && error.message) || String(error);
                    this._render();
                }
            );
        } else if (page) {
            this._show(page.dataset.page);
        } else if (row) {
            this._show('detail', row.dataset.open);
        }
    }

    /** Draw the page. The detail page is only rebuilt when asked: rebuilding would recreate its card. */
    _render(rebuild = false) {
        const page = this._view.page;
        if (page === 'detail' && !rebuild && this.shadowRoot.getElementById('detail-card')) {
            const meta = this.shadowRoot.getElementById('detail-meta');
            if (meta) meta.innerHTML = this._automation ? renderDetail(this._automation) : '';
            return;
        }
        const tab = (name, label) =>
            `<button class="tab${page === name ? ' active' : ''}" data-page="${name}">${label}</button>`;
        let body;
        if (page === 'detail') {
            body =
                '<button class="link" data-page="list">← All automations</button>' +
                `<div id="detail-meta">${this._automation ? renderDetail(this._automation) : ''}</div>` +
                '<haanim-card id="detail-card"></haanim-card>';
        } else if (page === 'config') {
            body = renderConfig(this._configuration);
        } else {
            body = this._automations === null ? '<div class="empty">Loading…</div>' : renderList(this._automations);
        }
        const error = this._error ? `<div class="error">${escapeHtml(this._error)}</div>` : '';
        this.shadowRoot.innerHTML =
            `<style>${STYLES}</style>` +
            '<div class="top"><h1>HAAnim</h1>' +
            `${tab('list', 'Automations')}${tab('config', 'Configuration')}` +
            '<button data-reload="all">Reload all</button></div>' +
            `<div class="page">${error}${body}</div>`;
        const card = this.shadowRoot.getElementById('detail-card');
        if (card) {
            card.setConfig({ automation_id: this._view.id });
            card.hass = this._hass;
        }
    }
}

if (!customElements.get('haanim-panel')) {
    customElements.define('haanim-panel', HAAnimPanel);
}

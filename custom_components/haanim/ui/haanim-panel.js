/**
 * HAAnim Panel Web Component
 *
 * A custom element that integrates with Home Assistant's frontend.
 * Receives the hass object directly from HA for seamless integration.
 */

class HAAnimPanel extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._hass = null;
        this._narrow = false;
        this._panel = null;
        this._automationsData = [];
        this._config = null;
    }

    // Called by Home Assistant when hass object is available/updated
    set hass(hass) {
        this._hass = hass;
        if (!this._initialized) {
            this._initialize();
        }
    }

    // Called by Home Assistant with panel configuration
    set panel(panel) {
        this._panel = panel;
    }

    // Called by Home Assistant when layout changes
    set narrow(narrow) {
        this._narrow = narrow;
    }

    _initialize() {
        if (this._initialized) return;
        this._initialized = true;
        this._render();
        this._loadData();
    }

    _render() {
        this.shadowRoot.innerHTML = `
            <style>
                ${this._getStyles()}
            </style>
            <div class="container">
                <div class="header">
                    <div class="title-section">
                        <h1 class="title">HAAnim</h1>
                        <span class="subtitle">Python Automations</span>
                    </div>
                    <div class="button-section">
                        <mwc-button raised id="reload-btn">
                            <ha-icon icon="mdi:refresh"></ha-icon>
                            Reload Automations
                        </mwc-button>
                    </div>
                </div>

                <div class="content">
                    <div id="loading" class="loading">
                        <ha-circular-progress indeterminate></ha-circular-progress>
                        <div>Loading automations...</div>
                    </div>

                    <div id="empty-state" class="empty-state" style="display: none;">
                        <ha-icon icon="mdi:file-document-outline" class="empty-icon"></ha-icon>
                        <div class="empty-text">No automations yet</div>
                        <div class="empty-subtext">
                            Add Python automations to your <code id="automation-folder-path">/config/haanim/</code> folder to get started.
                            <br>Automations are automatically loaded and watched for changes.
                        </div>
                    </div>

                    <div id="automations-container" class="automations-container" style="display: none;">
                    </div>

                    <div id="error-state" class="error-state" style="display: none;">
                        <ha-icon icon="mdi:alert-circle" class="error-icon"></ha-icon>
                        <div class="error-text">Failed to load automations</div>
                        <div class="error-subtext" id="error-message"></div>
                        <mwc-button raised id="retry-btn">Retry</mwc-button>
                    </div>
                </div>
            </div>
        `;

        // Attach event listeners
        this.shadowRoot.getElementById('reload-btn').addEventListener('click', () => this._reloadAutomations());
        this.shadowRoot.getElementById('retry-btn')?.addEventListener('click', () => this._loadData());
    }

    _getStyles() {
        return `
            :host {
                display: block;
                --primary-color: var(--primary-color, #03a9f4);
                --primary-text-color: var(--primary-text-color, #212121);
                --secondary-text-color: var(--secondary-text-color, #727272);
                --card-background-color: var(--card-background-color, #ffffff);
                --primary-background-color: var(--primary-background-color, #fafafa);
                --divider-color: var(--divider-color, #e0e0e0);
            }

            .container {
                min-height: 100vh;
                background-color: var(--primary-background-color);
            }

            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 24px;
                background-color: var(--card-background-color);
                border-bottom: 1px solid var(--divider-color);
            }

            .title-section {
                display: flex;
                flex-direction: column;
            }

            .title {
                font-size: 24px;
                font-weight: 400;
                margin: 0;
                color: var(--primary-text-color);
            }

            .subtitle {
                font-size: 14px;
                color: var(--secondary-text-color);
                margin-top: 4px;
            }

            .button-section {
                display: flex;
                align-items: center;
                gap: 12px;
            }

            .button-section mwc-button {
                --mdc-theme-primary: var(--primary-color);
            }

            .content {
                padding: 24px;
                max-width: 1200px;
                margin: 0 auto;
            }

            /* Loading state */
            .loading {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 64px;
                color: var(--secondary-text-color);
                gap: 16px;
            }

            /* Empty state */
            .empty-state {
                text-align: center;
                padding: 64px 32px;
                color: var(--secondary-text-color);
            }

            .empty-icon {
                --mdc-icon-size: 64px;
                opacity: 0.5;
                margin-bottom: 16px;
            }

            .empty-text {
                font-size: 18px;
                margin-bottom: 8px;
                color: var(--primary-text-color);
            }

            .empty-subtext {
                font-size: 14px;
                line-height: 1.6;
            }

            .empty-subtext code {
                background-color: var(--divider-color);
                padding: 2px 6px;
                border-radius: 3px;
                font-family: monospace;
            }

            /* Error state */
            .error-state {
                text-align: center;
                padding: 64px 32px;
            }

            .error-icon {
                --mdc-icon-size: 48px;
                color: var(--error-color, #f44336);
                margin-bottom: 16px;
            }

            .error-text {
                font-size: 18px;
                margin-bottom: 8px;
                color: var(--error-color, #f44336);
            }

            .error-subtext {
                font-size: 14px;
                color: var(--secondary-text-color);
                margin-bottom: 24px;
            }

            /* Automations container */
            .automations-container {
                display: grid;
                gap: 16px;
            }

            /* Automation card */
            .automation-card {
                background-color: var(--card-background-color);
                border-radius: 8px;
                box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0, 0, 0, 0.1));
                overflow: hidden;
            }

            .automation-header {
                padding: 16px 20px;
                border-bottom: 1px solid var(--divider-color);
            }

            .automation-info {
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .automation-name {
                font-size: 18px;
                font-weight: 500;
                color: var(--primary-text-color);
            }

            .automation-meta {
                display: flex;
                gap: 16px;
                font-size: 13px;
                color: var(--secondary-text-color);
            }

            .automation-status {
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 12px;
            }

            .status-enabled {
                background-color: var(--success-color, #4caf50);
                color: white;
            }

            .status-disabled {
                background-color: var(--error-color, #f44336);
                color: white;
            }

            .automation-actions {
                padding: 16px 20px;
                background-color: var(--secondary-background-color, rgba(0,0,0,0.03));
            }

            .actions-label {
                font-size: 12px;
                font-weight: 500;
                color: var(--secondary-text-color);
                text-transform: uppercase;
                margin-bottom: 12px;
            }

            .actions-list {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
            }

            .action-btn {
                background-color: var(--primary-color);
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
                border-radius: 4px;
                cursor: pointer;
                transition: all 0.2s ease;
            }

            .action-btn:hover {
                opacity: 0.9;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            }

            .action-btn:active {
                transform: scale(0.98);
            }

            .no-actions {
                color: var(--secondary-text-color);
                font-style: italic;
                font-size: 13px;
            }
        `;
    }

    async _loadData() {
        this._showLoading(true);
        this._hideError();

        try {
            // Fetch config
            this._config = await this._fetchConfig();
            this._updateConfigDisplay();

            // Fetch automations
            this._automationsData = await this._fetchAutomations();
            this._renderAutomations();
        } catch (e) {
            console.error('Failed to load data:', e);
            this._showError('Could not load automations. Make sure HAAnim is properly configured.');
        } finally {
            this._showLoading(false);
        }
    }

    async _fetchAutomations() {
        try {
            // Use hass.callApi for authenticated requests
            if (this._hass) {
                const data = await this._hass.callApi('GET', 'haanim/automations');
                return data.automations || [];
            }
        } catch (e) {
            console.error('Failed to fetch automations:', e);
        }
        return [];
    }

    async _fetchConfig() {
        try {
            // Use hass.callApi for authenticated requests
            if (this._hass) {
                return await this._hass.callApi('GET', 'haanim/config');
            }
        } catch (e) {
            console.error('Failed to fetch config:', e);
        }
        return null;
    }

    _updateConfigDisplay() {
        if (this._config) {
            const pathEl = this.shadowRoot.getElementById('automation-folder-path');
            if (pathEl) {
                pathEl.textContent = this._config.automation_path + '/';
            }
        }
    }

    _renderAutomations() {
        const container = this.shadowRoot.getElementById('automations-container');
        const emptyState = this.shadowRoot.getElementById('empty-state');

        if (!this._automationsData || this._automationsData.length === 0) {
            container.style.display = 'none';
            emptyState.style.display = 'block';
            return;
        }

        emptyState.style.display = 'none';
        container.style.display = 'block';

        let html = '';
        for (const automation of this._automationsData) {
            html += this._renderAutomationCard(automation);
        }
        container.innerHTML = html;

        // Attach action button listeners
        container.querySelectorAll('.action-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const automationId = e.target.dataset.automation;
                const actionName = e.target.dataset.action;
                this._runAction(automationId, actionName);
            });
        });
    }

    _renderAutomationCard(automation) {
        const actionsHtml = automation.actions && automation.actions.length > 0
            ? automation.actions.map(action => `
                <button class="action-btn" data-automation="${this._escapeHtml(automation.name)}" data-action="${this._escapeHtml(action.func_name)}">
                    ▶ ${this._escapeHtml(action.name)}
                </button>
            `).join('')
            : '<span class="no-actions">No actions defined</span>';

        const triggersText = automation.triggers > 0
            ? `${automation.triggers} trigger${automation.triggers > 1 ? 's' : ''}`
            : 'No triggers';

        const statusClass = automation.enabled ? 'status-enabled' : 'status-disabled';
        const statusText = automation.enabled ? 'Enabled' : 'Disabled';

        return `
            <div class="automation-card">
                <div class="automation-header">
                    <div class="automation-info">
                        <div class="automation-name">${this._escapeHtml(automation.name)}</div>
                        <div class="automation-meta">
                            <span class="automation-triggers">${triggersText}</span>
                            <span class="automation-status ${statusClass}">${statusText}</span>
                        </div>
                    </div>
                </div>
                <div class="automation-actions">
                    <div class="actions-label">Actions:</div>
                    <div class="actions-list">
                        ${actionsHtml}
                    </div>
                </div>
            </div>
        `;
    }

    async _runAction(automationId, actionName) {
        this._showToast(`Running ${actionName}...`, 'info');

        try {
            // Use hass.callService if available
            if (this._hass) {
                await this._hass.callService('haanim', 'run_action', {
                    automation_id: automationId,
                    action_name: actionName
                });
                this._showToast(`Action "${actionName}" executed successfully`, 'success');
                return;
            }

            // Fallback to REST API with hass.callApi
            const data = await this._hass.callApi('POST', 'haanim/run_action', {
                automation_id: automationId,
                action_name: actionName
            });

            if (data.success) {
                this._showToast(`Action "${actionName}" executed successfully`, 'success');
            } else {
                this._showToast(`Failed to run action: ${data.error}`, 'error');
            }
        } catch (e) {
            console.error('Failed to run action:', e);
            this._showToast('Failed to run action: ' + e.message, 'error');
        }
    }

    async _reloadAutomations() {
        this._showToast('Reloading automations...', 'info');

        try {
            // Use hass.callService if available
            if (this._hass) {
                await this._hass.callService('haanim', 'reload_automations', {});
                this._showToast('Automations reloaded', 'success');
                setTimeout(() => this._loadData(), 1000);
                return;
            }

            // Fallback to REST API with hass.callApi
            const data = await this._hass.callApi('POST', 'haanim/reload', {});

            if (data.success) {
                this._showToast('Automations reloaded', 'success');
                setTimeout(() => this._loadData(), 1000);
            } else {
                this._showToast(`Failed to reload: ${data.error}`, 'error');
            }
        } catch (e) {
            console.error('Failed to reload:', e);
            this._showToast('Failed to reload: ' + e.message, 'error');
        }
    }

    _showLoading(show) {
        const loading = this.shadowRoot.getElementById('loading');
        if (loading) {
            loading.style.display = show ? 'flex' : 'none';
        }
    }

    _showError(message) {
        const errorState = this.shadowRoot.getElementById('error-state');
        const errorMessage = this.shadowRoot.getElementById('error-message');
        const automationsContainer = this.shadowRoot.getElementById('automations-container');
        const emptyState = this.shadowRoot.getElementById('empty-state');

        if (errorState) errorState.style.display = 'block';
        if (errorMessage) errorMessage.textContent = message;
        if (automationsContainer) automationsContainer.style.display = 'none';
        if (emptyState) emptyState.style.display = 'none';
    }

    _hideError() {
        const errorState = this.shadowRoot.getElementById('error-state');
        if (errorState) {
            errorState.style.display = 'none';
        }
    }

    _showToast(message, type = 'info') {
        // Use Home Assistant's notification system if available
        if (this._hass) {
            const event = new CustomEvent('hass-notification', {
                detail: { message },
                bubbles: true,
                composed: true
            });
            this.dispatchEvent(event);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Register the custom element
customElements.define('haanim-panel', HAAnimPanel);

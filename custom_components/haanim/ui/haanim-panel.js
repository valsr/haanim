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
        this._scriptsData = [];
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
                        <span class="subtitle">Python Automation Scripts</span>
                    </div>
                    <div class="button-section">
                        <mwc-button raised id="reload-btn">
                            <ha-icon icon="mdi:refresh"></ha-icon>
                            Reload Scripts
                        </mwc-button>
                    </div>
                </div>

                <div class="content">
                    <div id="loading" class="loading">
                        <ha-circular-progress indeterminate></ha-circular-progress>
                        <div>Loading scripts...</div>
                    </div>

                    <div id="empty-state" class="empty-state" style="display: none;">
                        <ha-icon icon="mdi:file-document-outline" class="empty-icon"></ha-icon>
                        <div class="empty-text">No automation scripts yet</div>
                        <div class="empty-subtext">
                            Add Python scripts to your <code id="script-folder-path">/config/haanim/</code> folder to get started.
                            <br>Scripts are automatically loaded and watched for changes.
                        </div>
                    </div>

                    <div id="scripts-container" class="scripts-container" style="display: none;">
                    </div>

                    <div id="error-state" class="error-state" style="display: none;">
                        <ha-icon icon="mdi:alert-circle" class="error-icon"></ha-icon>
                        <div class="error-text">Failed to load scripts</div>
                        <div class="error-subtext" id="error-message"></div>
                        <mwc-button raised id="retry-btn">Retry</mwc-button>
                    </div>
                </div>
            </div>
        `;

        // Attach event listeners
        this.shadowRoot.getElementById('reload-btn').addEventListener('click', () => this._reloadScripts());
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

            /* Scripts container */
            .scripts-container {
                display: grid;
                gap: 16px;
            }

            /* Script card */
            .script-card {
                background-color: var(--card-background-color);
                border-radius: 8px;
                box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0, 0, 0, 0.1));
                overflow: hidden;
            }

            .script-header {
                padding: 16px 20px;
                border-bottom: 1px solid var(--divider-color);
            }

            .script-info {
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .script-name {
                font-size: 18px;
                font-weight: 500;
                color: var(--primary-text-color);
            }

            .script-meta {
                display: flex;
                gap: 16px;
                font-size: 13px;
                color: var(--secondary-text-color);
            }

            .script-status {
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

            .script-actions {
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

            // Fetch scripts
            this._scriptsData = await this._fetchScripts();
            this._renderScripts();
        } catch (e) {
            console.error('Failed to load data:', e);
            this._showError('Could not load scripts. Make sure HAAnim is properly configured.');
        } finally {
            this._showLoading(false);
        }
    }

    async _fetchScripts() {
        try {
            // Use hass.callApi for authenticated requests
            if (this._hass) {
                const data = await this._hass.callApi('GET', 'haanim/scripts');
                return data.scripts || [];
            }
        } catch (e) {
            console.error('Failed to fetch scripts:', e);
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
            const pathEl = this.shadowRoot.getElementById('script-folder-path');
            if (pathEl) {
                pathEl.textContent = this._config.script_path + '/';
            }
        }
    }

    _renderScripts() {
        const container = this.shadowRoot.getElementById('scripts-container');
        const emptyState = this.shadowRoot.getElementById('empty-state');

        if (!this._scriptsData || this._scriptsData.length === 0) {
            container.style.display = 'none';
            emptyState.style.display = 'block';
            return;
        }

        emptyState.style.display = 'none';
        container.style.display = 'block';

        let html = '';
        for (const script of this._scriptsData) {
            html += this._renderScriptCard(script);
        }
        container.innerHTML = html;

        // Attach action button listeners
        container.querySelectorAll('.action-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const scriptName = e.target.dataset.script;
                const actionName = e.target.dataset.action;
                this._runAction(scriptName, actionName);
            });
        });
    }

    _renderScriptCard(script) {
        const actionsHtml = script.actions && script.actions.length > 0
            ? script.actions.map(action => `
                <button class="action-btn" data-script="${this._escapeHtml(script.name)}" data-action="${this._escapeHtml(action.func_name)}">
                    ▶ ${this._escapeHtml(action.name)}
                </button>
            `).join('')
            : '<span class="no-actions">No actions defined</span>';

        const triggersText = script.triggers > 0
            ? `${script.triggers} trigger${script.triggers > 1 ? 's' : ''}`
            : 'No triggers';

        const statusClass = script.enabled ? 'status-enabled' : 'status-disabled';
        const statusText = script.enabled ? 'Enabled' : 'Disabled';

        return `
            <div class="script-card">
                <div class="script-header">
                    <div class="script-info">
                        <div class="script-name">${this._escapeHtml(script.name)}</div>
                        <div class="script-meta">
                            <span class="script-triggers">${triggersText}</span>
                            <span class="script-status ${statusClass}">${statusText}</span>
                        </div>
                    </div>
                </div>
                <div class="script-actions">
                    <div class="actions-label">Actions:</div>
                    <div class="actions-list">
                        ${actionsHtml}
                    </div>
                </div>
            </div>
        `;
    }

    async _runAction(scriptName, actionName) {
        this._showToast(`Running ${actionName}...`, 'info');

        try {
            // Use hass.callService if available
            if (this._hass) {
                await this._hass.callService('haanim', 'run_action', {
                    script_name: scriptName,
                    action_name: actionName
                });
                this._showToast(`Action "${actionName}" executed successfully`, 'success');
                return;
            }

            // Fallback to REST API with hass.callApi
            const data = await this._hass.callApi('POST', 'haanim/run_action', {
                script_name: scriptName,
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

    async _reloadScripts() {
        this._showToast('Reloading scripts...', 'info');

        try {
            // Use hass.callService if available
            if (this._hass) {
                await this._hass.callService('haanim', 'reload_scripts', {});
                this._showToast('Scripts reloaded', 'success');
                setTimeout(() => this._loadData(), 1000);
                return;
            }

            // Fallback to REST API with hass.callApi
            const data = await this._hass.callApi('POST', 'haanim/reload', {});

            if (data.success) {
                this._showToast('Scripts reloaded', 'success');
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
        const scriptsContainer = this.shadowRoot.getElementById('scripts-container');
        const emptyState = this.shadowRoot.getElementById('empty-state');

        if (errorState) errorState.style.display = 'block';
        if (errorMessage) errorMessage.textContent = message;
        if (scriptsContainer) scriptsContainer.style.display = 'none';
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

/**
 * HAAnim Panel JavaScript
 * Handles script listing, action execution, and UI interactions
 */

let scriptsData = [];
let hassConnection = null;
let haanimConfig = null;

/**
 * Detect and apply Home Assistant theme
 */
function detectTheme() {
    try {
        const parentTheme = window.parent.document.documentElement.style.getPropertyValue(
            '--primary-background-color'
        );
        if (parentTheme) {
            const rgb = parentTheme.match(/\d+/g);
            if (rgb && rgb.length >= 3) {
                const brightness =
                    (parseInt(rgb[0]) * 299 + parseInt(rgb[1]) * 587 + parseInt(rgb[2]) * 114) / 1000;
                if (brightness < 128) {
                    document.body.classList.add('dark-theme');
                }
            }
        }
    } catch (e) {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.body.classList.add('dark-theme');
        }
    }
}

/**
 * Try to get Home Assistant connection from parent window
 */
function getHassConnection() {
    try {
        if (window.parent && window.parent.hassConnection) {
            return window.parent.hassConnection;
        }
        if (window.parent && window.parent.hass) {
            return window.parent.hass;
        }
    } catch (e) {
        console.log('Could not access parent window:', e);
    }
    return null;
}

/**
 * Call a Home Assistant service
 */
async function callService(domain, service, data = {}) {
    try {
        const hass = getHassConnection();
        if (hass && hass.callService) {
            await hass.callService(domain, service, data);
            return true;
        }

        // Fallback: try REST API
        const response = await fetch('/api/services/' + domain + '/' + service, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error('Service call failed: ' + response.status);
        }
        return true;
    } catch (e) {
        console.error('Failed to call service:', e);
        showNotification('Failed to call service: ' + e.message, 'error');
        return false;
    }
}

/**
 * Fetch scripts list from Home Assistant
 */
async function fetchScripts() {
    try {
        // Try calling the list_scripts service
        const response = await fetch('/api/services/haanim/list_scripts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({}),
            credentials: 'same-origin'
        });

        if (response.ok) {
            const data = await response.json();
            return data.scripts || [];
        }
    } catch (e) {
        console.log('Could not fetch scripts via service:', e);
    }

    // Return empty array if we can't fetch
    return [];
}

/**
 * Fetch HAAnim configuration
 */
async function fetchConfig() {
    try {
        const response = await fetch('/api/services/haanim/get_config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({}),
            credentials: 'same-origin'
        });

        if (response.ok) {
            const data = await response.json();
            return data;
        }
    } catch (e) {
        console.log('Could not fetch config:', e);
    }

    return null;
}

/**
 * Load and display scripts
 */
async function loadScripts() {
    showLoading(true);
    hideError();

    try {
        // Fetch config first
        haanimConfig = await fetchConfig();
        updateConfigDisplay();

        scriptsData = await fetchScripts();
        renderScripts();
    } catch (e) {
        console.error('Failed to load scripts:', e);
        showError('Could not load scripts. Make sure HAAnim is properly configured.');
    } finally {
        showLoading(false);
    }
}

/**
 * Update UI elements with config values
 */
function updateConfigDisplay() {
    if (haanimConfig) {
        const pathEl = document.getElementById('script-folder-path');
        if (pathEl) {
            pathEl.textContent = haanimConfig.script_path + '/';
        }
    }
}

/**
 * Render the scripts list
 */
function renderScripts() {
    const container = document.getElementById('scripts-container');
    const emptyState = document.getElementById('empty-state');

    if (!scriptsData || scriptsData.length === 0) {
        container.style.display = 'none';
        emptyState.style.display = 'block';
        return;
    }

    emptyState.style.display = 'none';
    container.style.display = 'block';

    let html = '';
    for (const script of scriptsData) {
        html += renderScript(script);
    }
    container.innerHTML = html;
}

/**
 * Render a single script card
 */
function renderScript(script) {
    const actionsHtml = script.actions && script.actions.length > 0
        ? script.actions.map(action => `
            <button class="action-btn" onclick="runAction('${escapeHtml(script.name)}', '${escapeHtml(action)}')">
                ▶ ${escapeHtml(action)}
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
                    <div class="script-name">${escapeHtml(script.name)}</div>
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

/**
 * Run an action
 */
async function runAction(scriptName, actionName) {
    showNotification(`Running ${actionName}...`, 'info');

    const success = await callService('haanim', 'run_action', {
        script_name: scriptName,
        action_name: actionName
    });

    if (success) {
        showNotification(`Action "${actionName}" executed successfully`, 'success');
    }
}

/**
 * Reload all scripts
 */
async function reloadScripts() {
    showNotification('Reloading scripts...', 'info');

    const success = await callService('haanim', 'reload_scripts', {});

    if (success) {
        showNotification('Scripts reloaded', 'success');
        // Refresh the display after a short delay
        setTimeout(loadScripts, 1000);
    }
}

/**
 * Open the script folder (shows a message with the path)
 */
function openScriptFolder() {
    const scriptPath = haanimConfig?.script_path || '/config/haanim';
    showNotification(
        `Scripts are located in: ${scriptPath}/\nAdd .py files there and they will be auto-loaded.`,
        'info',
        5000
    );
}

/**
 * Show loading state
 */
function showLoading(show) {
    document.getElementById('loading').style.display = show ? 'flex' : 'none';
}

/**
 * Show error state
 */
function showError(message) {
    document.getElementById('error-state').style.display = 'block';
    document.getElementById('error-message').textContent = message;
    document.getElementById('scripts-container').style.display = 'none';
    document.getElementById('empty-state').style.display = 'none';
}

/**
 * Hide error state
 */
function hideError() {
    document.getElementById('error-state').style.display = 'none';
}

/**
 * Show a notification toast
 */
function showNotification(message, type = 'info', duration = 3000) {
    // Remove any existing notification
    const existing = document.querySelector('.notification');
    if (existing) {
        existing.remove();
    }

    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);

    // Trigger animation
    setTimeout(() => notification.classList.add('show'), 10);

    // Remove after duration
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, duration);
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Initialize the panel
 */
function init() {
    detectTheme();

    // Listen for theme changes
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
            if (e.matches) {
                document.body.classList.add('dark-theme');
            } else {
                document.body.classList.remove('dark-theme');
            }
        });
    }

    // Listen for messages from parent
    window.addEventListener('message', function (event) {
        if (event.data.type === 'theme-changed') {
            detectTheme();
        }
    });

    // Load scripts
    loadScripts();

    // Refresh periodically
    setInterval(loadScripts, 30000);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

/**
 * HAAnim rendering: pure functions that turn data into HTML strings.
 *
 * Nothing here touches the DOM, so it runs in the browser and in the unit tests alike. Everything an
 * automation supplies (markdown, labels, values, log messages) is escaped or sanitised here: an automation
 * cannot put markup or scripts into the page.
 */

/** The controls of the card header: which service, and for which states it is offered. */
const CONTROLS = [
    { service: 'enable', label: 'Enable', when: (a) => !a.enabled },
    { service: 'disable', label: 'Disable', when: (a) => a.enabled },
    { service: 'start', label: 'Start', when: (a) => a.enabled && (a.state === 'off' || a.state === 'error') },
    { service: 'stop', label: 'Stop', when: (a) => a.state === 'on' },
    { service: 'restart', label: 'Restart', when: (a) => a.state === 'on' },
];

const CONTROL_SERVICES = new Set(['enable', 'disable', 'start', 'stop', 'restart', 'reload']);

/** How many log records the card shows. */
export const MAX_LOG_RECORDS = 200;

/** Escape text for use in HTML content and in double-quoted attributes. */
export function escapeHtml(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Remove raw HTML from markdown: script and style elements with their content, and every other tag. */
export function stripHtml(text) {
    let result = String(text ?? '').replace(/\u0000/g, '');
    let previous;
    do {
        previous = result;
        result = result
            .replace(/<(script|style|iframe|object|embed)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '')
            .replace(/<!--[\s\S]*?-->/g, '')
            .replace(/<\/?[a-zA-Z!?][^>]*>/g, '');
    } while (result !== previous);
    return result;
}

/** Return a URL if a link or image may point to it: http, https, mailto or a path on this server. */
export function safeUrl(url) {
    const value = String(url ?? '').trim();
    if (/^(https?:\/\/|mailto:)/i.test(value)) return value;
    if (/^\/(?!\/)/.test(value)) return value;
    return null;
}

/** Render the inline markdown of one piece of already escaped text. */
function renderInline(escaped) {
    const kept = [];
    const keep = (html) => `\u0000${kept.push(html) - 1}\u0000`;

    let text = escaped.replace(/`([^`]+)`/g, (_, code) => keep(`<code>${code}</code>`));
    text = text.replace(/!?\[([^\]]*)\]\(([^)\s]+)\)/g, (whole, label, url) => {
        if (whole.startsWith('!')) return label;
        // The text is escaped already; a safe URL contains nothing that escaping changed except "&"
        const target = safeUrl(url.replace(/&amp;/g, '&'));
        if (target === null) return label;
        return keep(`<a href="${escapeHtml(target)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
    });
    text = text
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/__([^_]+)__/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/(^|[^\w])_([^_]+)_(?!\w)/g, '$1<em>$2</em>');
    return text.replace(/\u0000(\d+)\u0000/g, (_, index) => kept[Number(index)]);
}

/**
 * Render markdown as sanitised HTML.
 *
 * Supported: headings, paragraphs, bold, italic, inline code, fenced code, links, bullet and numbered
 * lists. Raw HTML is removed, and whatever is left is escaped before any markup is added.
 */
export function renderMarkdown(markdown) {
    const lines = stripHtml(markdown).replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    let paragraph = [];
    let list = null;
    let code = null;

    const closeParagraph = () => {
        if (paragraph.length) html.push(`<p>${paragraph.join('<br>')}</p>`);
        paragraph = [];
    };
    const closeList = () => {
        if (list) html.push(`</${list}>`);
        list = null;
    };
    const openList = (kind) => {
        closeParagraph();
        if (list !== kind) {
            closeList();
            html.push(`<${kind}>`);
            list = kind;
        }
    };

    for (const line of lines) {
        if (code !== null) {
            if (/^\s*```/.test(line)) {
                html.push(`<pre><code>${code.join('\n')}</code></pre>`);
                code = null;
            } else {
                code.push(escapeHtml(line));
            }
            continue;
        }
        if (/^\s*```/.test(line)) {
            closeParagraph();
            closeList();
            code = [];
            continue;
        }
        const heading = /^(#{1,6})\s+(.*)$/.exec(line);
        const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
        const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
        if (heading) {
            closeParagraph();
            closeList();
            const level = heading[1].length;
            html.push(`<h${level}>${renderInline(escapeHtml(heading[2].trim()))}</h${level}>`);
        } else if (bullet) {
            openList('ul');
            html.push(`<li>${renderInline(escapeHtml(bullet[1]))}</li>`);
        } else if (numbered) {
            openList('ol');
            html.push(`<li>${renderInline(escapeHtml(numbered[1]))}</li>`);
        } else if (line.trim() === '') {
            closeParagraph();
            closeList();
        } else {
            closeList();
            paragraph.push(renderInline(escapeHtml(line.trim())));
        }
    }
    if (code !== null) html.push(`<pre><code>${code.join('\n')}</code></pre>`);
    closeParagraph();
    closeList();
    return html.join('');
}

/** The words the design uses for an automation's state. */
export function stateLabel(state, enabled) {
    if (state === 'on') return { label: 'Running', css: 'running' };
    if (state === 'error') return { label: 'Error', css: 'error' };
    if (state === 'off') return enabled ? { label: 'Stopped', css: 'stopped' } : { label: 'Disabled', css: 'disabled' };
    return { label: 'Unavailable', css: 'unavailable' };
}

/** Format an ISO time for display; an empty string for no time, the text itself if it is not a time. */
export function formatTime(iso, withDate = false) {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return String(iso);
    return withDate ? date.toLocaleString() : date.toLocaleTimeString();
}

/** Render one content block. `context` has `states` (entity states by ID) and `images` (loaded asset URLs). */
export function renderBlock(block, context = {}) {
    const id = escapeHtml(block.id);
    const open = `<div class="block block-${escapeHtml(block.type)}" data-block="${id}">`;
    switch (block.type) {
        case 'text':
            return `${open}${renderMarkdown(block.markdown)}</div>`;
        case 'image': {
            const source = block.asset ? (context.images || {})[block.url] : safeUrl(block.url);
            if (!source) {
                return `${open}<span class="image-pending">${escapeHtml(block.alt || '')}</span></div>`;
            }
            return `${open}<img src="${escapeHtml(source)}" alt="${escapeHtml(block.alt || '')}"></div>`;
        }
        case 'value': {
            const unit = block.unit ? ` <span class="unit">${escapeHtml(block.unit)}</span>` : '';
            return (
                `${open}<span class="label">${escapeHtml(block.label)}</span>` +
                `<span class="value">${escapeHtml(block.value)}${unit}</span></div>`
            );
        }
        case 'entity': {
            const state = (context.states || {})[block.entity_id];
            const attributes = (state && state.attributes) || {};
            const name = attributes.friendly_name || block.entity_id;
            const unit = attributes.unit_of_measurement
                ? ` <span class="unit">${escapeHtml(attributes.unit_of_measurement)}</span>`
                : '';
            const value = state ? `${escapeHtml(state.state)}${unit}` : 'unavailable';
            return (
                `${open}<span class="label">${escapeHtml(name)}</span>` +
                `<span class="value" data-entity="${escapeHtml(block.entity_id)}">${value}</span></div>`
            );
        }
        case 'button': {
            const confirm = block.confirm ? ` data-confirm="${escapeHtml(block.confirm)}"` : '';
            return (
                `${open}<button class="card-button" data-haanim="run" data-action="${escapeHtml(block.action)}"` +
                ` data-payload="${escapeHtml(JSON.stringify(block.data || {}))}"${confirm}>` +
                `${escapeHtml(block.label)}</button></div>`
            );
        }
        default:
            return '';
    }
}

/** Render the content area: the automation's blocks in order. */
export function renderContent(blocks, context = {}) {
    return (blocks || []).map((block) => renderBlock(block, context)).join('');
}

/** Render the fixed header: name, state, status message and the controls that apply. */
export function renderHeader(automation) {
    const state = stateLabel(automation.state, automation.enabled);
    const controls = CONTROLS.filter((control) => control.when(automation))
        .map((control) => `<button class="control" data-haanim="${control.service}">${control.label}</button>`)
        .join('');
    const message = automation.message ? `<div class="message">${escapeHtml(automation.message)}</div>` : '';
    return (
        '<div class="header">' +
        `<div class="title"><span class="name">${escapeHtml(automation.name || automation.id)}</span>` +
        `<span class="state state-${state.css}">${state.label}</span></div>` +
        `${message}<div class="controls">${controls}</div></div>`
    );
}

/** Render the collapsible list of actions, each with a run button. */
export function renderActions(actions, open = false) {
    const rows = (actions || [])
        .map((action) => {
            const description = action.description
                ? `<span class="description">${escapeHtml(action.description)}</span>`
                : '';
            return (
                `<li><button class="run" data-haanim="run" data-action="${escapeHtml(action.name)}">Run</button>` +
                `<span class="action-name">${escapeHtml(action.name)}</span>${description}</li>`
            );
        })
        .join('');
    const body = rows ? `<ul class="actions">${rows}</ul>` : '<div class="empty">No actions</div>';
    return (
        `<details class="section" data-section="actions"${open ? ' open' : ''}>` +
        `<summary>Actions (${(actions || []).length})</summary>${body}</details>`
    );
}

/** Render the collapsible log: the recent records, newest last, with the level as a class. */
export function renderLog(records, open = false) {
    const rows = (records || [])
        .slice(-MAX_LOG_RECORDS)
        .map((record) => {
            const level = String(record.level || 'INFO').toLowerCase().replace(/[^a-z]/g, '');
            const traceback = record.traceback ? `<pre class="traceback">${escapeHtml(record.traceback)}</pre>` : '';
            return (
                `<li class="record level-${level}"><span class="time">${escapeHtml(formatTime(record.time))}</span>` +
                `<span class="level">${escapeHtml(record.level)}</span>` +
                `<span class="text">${escapeHtml(record.message)}</span>${traceback}</li>`
            );
        })
        .join('');
    const body = rows ? `<ul class="log">${rows}</ul>` : '<div class="empty">No log records</div>';
    return (
        `<details class="section" data-section="log"${open ? ' open' : ''}>` +
        `<summary>Log (${(records || []).length})</summary>${body}</details>`
    );
}

/**
 * Render the whole card: the fixed header, the automation's content, the actions and the log.
 *
 * `view` has `automation` (the detail of the automation, or null while it is unknown), `blocks`, `records`,
 * `states`, `images`, `open` ({actions, log}) and `error` (a message shown instead of the card).
 */
export function renderCard(view) {
    if (view.error) return `<div class="card-error">${escapeHtml(view.error)}</div>`;
    if (!view.automation) return '<div class="card-loading">Loading…</div>';
    const open = view.open || {};
    const content = renderContent(view.blocks, view);
    return (
        renderHeader(view.automation) +
        (content ? `<div class="content">${content}</div>` : '') +
        renderActions(view.automation.actions, open.actions) +
        renderLog(view.records, open.log)
    );
}

/**
 * Turn a clicked element's data attributes into the service call it stands for.
 *
 * Returns `{service, data, confirm}`, or null if the element is not a HAAnim control.
 */
export function serviceCall(dataset, automationId) {
    const operation = dataset && dataset.haanim;
    if (operation === 'run') {
        let data = {};
        try {
            data = JSON.parse(dataset.payload || '{}');
        } catch (error) {
            data = {};
        }
        return {
            service: 'run_action',
            data: { automation_id: automationId, action: dataset.action, data },
            confirm: dataset.confirm || null,
        };
    }
    if (CONTROL_SERVICES.has(operation)) {
        return { service: operation, data: { automation_id: automationId }, confirm: null };
    }
    return null;
}

/** Render the panel's list of automations. */
export function renderList(automations) {
    if (!automations || automations.length === 0) {
        return '<div class="empty">No automations yet. Add a folder with a <code>main.py</code> to the automations folder.</div>';
    }
    const rows = automations
        .map((automation) => {
            const state = stateLabel(automation.state, automation.enabled);
            return (
                `<tr class="row" data-open="${escapeHtml(automation.id)}">` +
                `<td class="name">${escapeHtml(automation.name || automation.id)}` +
                `<div class="id">${escapeHtml(automation.id)}</div></td>` +
                `<td><span class="state state-${state.css}">${state.label}</span></td>` +
                `<td>${escapeHtml(automation.version || '')}</td>` +
                `<td class="message">${escapeHtml(automation.message || '')}</td></tr>`
            );
        })
        .join('');
    return (
        '<table class="automations"><thead><tr><th>Automation</th><th>State</th><th>Version</th>' +
        `<th>Status</th></tr></thead><tbody>${rows}</tbody></table>`
    );
}

/** Render what the detail page shows above the card: the metadata and the status of the automation. */
export function renderDetail(automation) {
    const row = (label, value) =>
        value ? `<div class="meta"><span class="label">${label}</span><span>${escapeHtml(value)}</span></div>` : '';
    const failure = automation.last_error
        ? `${automation.last_error.action}: ${automation.last_error.error_type}: ${automation.last_error.message}`
        : '';
    return (
        '<div class="detail">' +
        row('Description', automation.description) +
        row('Author', automation.author) +
        row('Version', automation.version) +
        row('Current action', (automation.running_actions || []).join(', ')) +
        row('Last action', automation.last_action) +
        row('Last action time', formatTime(automation.last_action_time, true)) +
        row('Last started', formatTime(automation.last_run, true)) +
        row('Last error', failure) +
        '</div>'
    );
}

/** Render the integration's configuration: the version and the options. */
export function renderConfig(config) {
    if (!config) return '<div class="empty">Loading…</div>';
    const rows = Object.entries(config.options || {})
        .map(([key, value]) => {
            const shown = Array.isArray(value) ? value.join(', ') : String(value);
            return `<tr><td>${escapeHtml(key.replace(/_/g, ' '))}</td><td>${escapeHtml(shown)}</td></tr>`;
        })
        .join('');
    return (
        `<div class="meta"><span class="label">Version</span><span>${escapeHtml(config.version)}</span></div>` +
        `<table class="config"><tbody>${rows}</tbody></table>` +
        '<div class="hint">Options are changed in Settings → Devices &amp; services → HAAnim → Configure.</div>'
    );
}

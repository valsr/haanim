/**
 * HAAnim rendering: pure functions that turn data into HTML strings.
 *
 * Nothing here touches the DOM, so it runs in the browser and in the unit tests alike. Everything an
 * automation supplies (markdown, labels, values, log messages) is escaped or sanitised here: an automation
 * cannot put markup or scripts into the page.
 */

import { renderGraph } from './haanim-graph.js';

/** The controls of the card header: which service, and for which states it is offered. */
const CONTROLS = [
    { service: 'enable', label: 'Enable', when: (a) => !a.enabled },
    { service: 'disable', label: 'Disable', when: (a) => a.enabled },
    { service: 'start', label: 'Start', when: (a) => a.enabled && (a.state === 'off' || a.state === 'error') },
    { service: 'stop', label: 'Stop', when: (a) => a.state === 'on' },
    { service: 'restart', label: 'Restart', when: (a) => a.state === 'on' },
];

const CONTROL_SERVICES = new Set(['enable', 'disable', 'start', 'stop', 'restart', 'reload']);

/** How many log records are shown. */
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

/**
 * What the state badge says, and how it looks.
 *
 * A running automation shows what it is doing: the name of the action that is executing (the first, and how
 * many more, if there are several), or `Idle` while none is. `@startup` and `@shutdown` are shown as
 * `startup` and `shutdown`. Stopped, disabled, error and unavailable are shown as such.
 * Returns `{label, css}`; the label is text, not HTML.
 */
export function stateLabel(state, enabled, running = []) {
    if (state === 'on') {
        const names = (running || []).map((name) => String(name).replace(/^__(.*)__$/, '$1'));
        if (names.length === 0) return { label: 'Idle', css: 'idle' };
        const more = names.length > 1 ? ` +${names.length - 1}` : '';
        return { label: `${names[0]}${more}`, css: 'running' };
    }
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

/** States in which an entity is not doing anything: its icon is then dimmed and does not turn. */
const INACTIVE_STATES = new Set([
    'off', 'closed', 'idle', 'standby', 'not_home', 'locked', 'docked', 'below_horizon', 'paused', 'disarmed',
    'unavailable', 'unknown', '', '0',
]);

/** Theme colours an icon can be given by name; any other colour is a CSS colour name or a hex value. */
const THEME_COLORS = {
    primary: 'var(--primary-color)',
    accent: 'var(--accent-color)',
    success: 'var(--success-color, #4caf50)',
    warning: 'var(--warning-color, #ff9800)',
    error: 'var(--error-color, #f44336)',
    disabled: 'var(--disabled-color, #9e9e9e)',
};

/** Whether an entity is active (on, open, home, playing, ...), going by its state. */
export function isActive(state) {
    return Boolean(state) && !INACTIVE_STATES.has(String(state.state).toLowerCase());
}

/** Return the CSS value of an icon colour, or null if it is not a colour that may be put into a style. */
export function iconColor(color) {
    const value = String(color ?? '');
    if (Object.hasOwn(THEME_COLORS, value)) return THEME_COLORS[value];
    return /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+(-[a-zA-Z]+)*)$/.test(value) ? value : null;
}

/**
 * Render an icon block.
 *
 * Following an entity, the icon is the entity's own (drawn by Home Assistant's `ha-state-icon`, which the
 * card hands the entity's state) unless the block names one; it is lit and may turn while the entity is
 * active and is dimmed otherwise; the label is the entity's name and its state is shown. Not following, the
 * icon is what the block says.
 */
function renderIcon(block, context, open) {
    const state = block.entity_id ? (context.states || {})[block.entity_id] : null;
    const follows = Boolean(block.follow_entity && block.entity_id);
    const active = follows ? isActive(state) : true;
    const named = /^[a-z0-9-]+:[a-z0-9-]+$/.test(String(block.icon ?? '')) ? block.icon : null;
    const color = iconColor(block.color) || (follows ? 'var(--state-active-color, var(--primary-color))' : null);
    const classes = ['icon', active ? 'active' : 'inactive'];
    if (block.spin && active) classes.push('spin');
    const style = active && color ? ` style="color: ${color}"` : '';
    let picture = '';
    if (named) {
        picture = `<ha-icon icon="${escapeHtml(named)}"></ha-icon>`;
    } else if (follows) {
        picture = `<ha-state-icon data-state-icon="${escapeHtml(block.entity_id)}"></ha-state-icon>`;
    }
    const attributes = (state && state.attributes) || {};
    const label = block.label ?? (follows ? attributes.friendly_name || block.entity_id : '');
    const value = follows ? `<span class="value">${state ? escapeHtml(state.state) : 'unavailable'}</span>` : '';
    // A click on an icon that belongs to an entity opens the entity's own dialog
    const more = block.entity_id ? ` data-more-info="${escapeHtml(block.entity_id)}"` : '';
    return (
        `${open.slice(0, -1)}${more}><span class="${classes.join(' ')}"${style}>${picture}</span>` +
        (label ? `<span class="label">${escapeHtml(label)}</span>` : '') +
        `${value}</div>`
    );
}

/** The length of the dial's arc: half a circle of radius 50. */
const DIAL_LENGTH = Math.PI * 50;

/** A number as a gauge shows it: at most two decimals, and none that are zero. */
export function formatNumber(value) {
    return String(Math.round(value * 100) / 100);
}

/**
 * Render a gauge block: a number within a range, as a progress bar or as a dial.
 *
 * The number is the block's own, or the state of its entity; the entity then also gives the label and the
 * unit unless the block has its own. A state that is not a number leaves the gauge empty and is shown as
 * text. A number outside the range is shown as it is, with the gauge empty or full.
 */
function renderGauge(block, context, open) {
    const state = block.entity_id ? (context.states || {})[block.entity_id] : null;
    const attributes = (state && state.attributes) || {};
    const raw = block.entity_id ? (state ? state.state : 'unavailable') : block.value;
    const number = raw === null || raw === '' || typeof raw === 'boolean' ? NaN : Number(raw);
    const known = Number.isFinite(number);
    const low = Number(block.min);
    const high = Number(block.max);
    const span = high - low;
    const part = known && span > 0 ? Math.min(Math.max((number - low) / span, 0), 1) : 0;
    const label = block.label ?? (block.entity_id ? attributes.friendly_name || block.entity_id : '');
    const unitText = block.unit ?? (block.entity_id ? attributes.unit_of_measurement || '' : '');
    const text = known ? formatNumber(number) : String(raw ?? '');
    const color = iconColor(block.color) || 'var(--primary-color)';
    const more = block.entity_id ? ` data-more-info="${escapeHtml(block.entity_id)}"` : '';
    const start = `${open.slice(0, -1)}${more}>`;
    const range = `role="progressbar" aria-valuemin="${low}" aria-valuemax="${high}"${known ? ` aria-valuenow="${number}"` : ''}`;
    if (block.kind === 'dial') {
        const arc = 'M 10 60 A 50 50 0 0 1 110 60';
        const filled = (part * DIAL_LENGTH).toFixed(2);
        const unit = known && unitText ? `<tspan class="dial-unit"> ${escapeHtml(unitText)}</tspan>` : '';
        return (
            `${start}<svg class="dial" viewBox="0 0 120 70" ${range}>` +
            `<path class="dial-track" d="${arc}"></path>` +
            `<path class="dial-fill" d="${arc}" style="stroke: ${color}"` +
            ` stroke-dasharray="${filled} ${DIAL_LENGTH.toFixed(2)}"></path>` +
            `<text class="dial-value" x="60" y="58" text-anchor="middle">${escapeHtml(text)}${unit}</text></svg>` +
            (label ? `<span class="label">${escapeHtml(label)}</span>` : '') +
            '</div>'
        );
    }
    const unit = known && unitText ? ` <span class="unit">${escapeHtml(unitText)}</span>` : '';
    return (
        `${start}<div class="gauge-head"><span class="label">${escapeHtml(label)}</span>` +
        `<span class="value">${escapeHtml(text)}${unit}</span></div>` +
        `<div class="bar" ${range}><div class="fill" style="width: ${(part * 100).toFixed(1)}%; background: ${color}">` +
        '</div></div></div>'
    );
}

/**
 * Render a badge block: a short text in a coloured pill, with an icon if the block names one.
 *
 * The text is the block's own, or the state of its entity.
 */
function renderBadge(block, context, open) {
    const state = block.entity_id ? (context.states || {})[block.entity_id] : null;
    const text = block.entity_id ? (state ? state.state : 'unavailable') : block.text;
    const named = /^[a-z0-9-]+:[a-z0-9-]+$/.test(String(block.icon ?? '')) ? block.icon : null;
    const color = iconColor(block.color);
    const style = color ? ` style="background: ${color}"` : '';
    const more = block.entity_id ? ` data-more-info="${escapeHtml(block.entity_id)}"` : '';
    return (
        `${open.slice(0, -1)}${more}><span class="badge"${style}>` +
        (named ? `<ha-icon icon="${escapeHtml(named)}"></ha-icon>` : '') +
        `<span class="badge-text">${escapeHtml(text)}</span></span></div>`
    );
}

/** Where an image can be in its row. */
const ALIGNMENTS = new Set(['left', 'center', 'right']);

/** Return a width or height as it may be put into a style (`120px`, `50%`), or null. */
function imageSize(value) {
    return /^[0-9]{1,4}(px|%)$/.test(String(value ?? '')) ? String(value) : null;
}

/**
 * The address of a camera's current picture, or null while the camera has none.
 *
 * Home Assistant gives every camera a picture address that carries its own short-lived token. A stamp makes
 * the address a new one, so that the browser fetches the picture again.
 */
export function cameraUrl(state, stamp = null) {
    const picture = safeUrl(state && state.attributes ? state.attributes.entity_picture : null);
    if (picture === null || stamp === null || stamp === undefined) return picture;
    return `${picture}${picture.includes('?') ? '&' : '?'}t=${encodeURIComponent(stamp)}`;
}

/**
 * Render an image block.
 *
 * The image is drawn at its own size, and never wider than the space it has, unless the block gives a width,
 * a height or both; with both it is fitted into that box and keeps its shape. `align` puts it at the left
 * (the default), in the middle or at the right of its row, and the caption under it goes with it. Until
 * the picture can be shown, its alt text stands in for it.
 *
 * A block with an entity shows the current picture of that camera; `context.stamps` has, by block ID, the
 * stamp of the picture last fetched. A click on it opens the camera's own dialog.
 */
function renderImage(block, context, id) {
    const align = ALIGNMENTS.has(block.align) ? block.align : 'left';
    const camera = block.entity_id ? escapeHtml(block.entity_id) : null;
    const more = camera ? ` data-more-info="${camera}"` : '';
    const open = `<div class="block block-image align-${align}" data-block="${id}"${more}>`;
    const caption = block.caption ? `<div class="caption">${escapeHtml(block.caption)}</div>` : '';
    let source;
    if (camera) {
        source = cameraUrl((context.states || {})[block.entity_id], (context.stamps || {})[block.id]);
    } else {
        source = block.asset ? (context.images || {})[block.url] : safeUrl(block.url);
    }
    if (!source) {
        const standIn = block.alt || (camera ? block.entity_id : '');
        return `${open}<span class="image-pending">${escapeHtml(standIn)}</span>${caption}</div>`;
    }
    const width = imageSize(block.width);
    const height = imageSize(block.height);
    const sizes = [width ? `width: ${width}` : '', height ? `height: ${height}` : ''].filter(Boolean);
    const style = sizes.length ? ` style="${sizes.join('; ')}"` : '';
    const live = camera ? ` data-camera="${id}"` : '';
    return (
        `${open}<img src="${escapeHtml(source)}" alt="${escapeHtml(block.alt || '')}"${live}${style}>` +
        `${caption}</div>`
    );
}

/**
 * Render one content block.
 *
 * `context` has `states` (entity states by ID), `images` (loaded asset URLs), `history` (fetched entity
 * history by graph block ID) and `now`.
 */
export function renderBlock(block, context = {}) {
    const id = escapeHtml(block.id);
    const open = `<div class="block block-${escapeHtml(block.type)}" data-block="${id}">`;
    switch (block.type) {
        case 'text':
            return `${open}${renderMarkdown(block.markdown)}</div>`;
        case 'image':
            return renderImage(block, context, id);
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
        case 'icon':
            return renderIcon(block, context, open);
        case 'gauge':
            return renderGauge(block, context, open);
        case 'badge':
            return renderBadge(block, context, open);
        case 'graph':
            return `${open}${renderGraph(block, context)}</div>`;
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

/** The most cells a row of the layout can have. */
export const MAX_ROW_CELLS = 6;

/**
 * Render the content area: the automation's elements, placed as its layout says.
 *
 * `layout` is a list of rows from the top, each with `cells` (how many cells of equal width the row has) and
 * `elements` (the IDs of the blocks in them, from the left). A row of one cell is the block itself; a row of
 * several is a grid, in which cells nobody filled stay empty. Without a layout every block has a row of its
 * own. A block the layout does not name is not drawn, and neither is a name without a block.
 */
export function renderContent(blocks, context = {}, layout = null) {
    const all = blocks || [];
    if (!Array.isArray(layout)) return all.map((block) => renderBlock(block, context)).join('');
    const byId = new Map(all.map((block) => [block.id, block]));
    return layout
        .map((row) => {
            const cells = Math.min(Math.max(Math.floor(Number(row.cells)) || 1, 1), MAX_ROW_CELLS);
            const drawn = (row.elements || [])
                .slice(0, cells)
                .map((id) => (byId.has(id) ? renderBlock(byId.get(id), context) : ''));
            if (drawn.every((html) => html === '')) return '';
            if (cells === 1) return drawn[0];
            const filled = drawn.map((html) => `<div class="cell">${html}</div>`).join('');
            const empty = '<div class="cell"></div>'.repeat(cells - drawn.length);
            return `<div class="row" style="--cells: ${cells}">${filled}${empty}</div>`;
        })
        .join('');
}

/** The path of the HAAnim panel, and of the pages in it. */
export const PANEL_PATH = '/haanim';

/** The path of an automation's page in the panel; with `logs`, of the log section on it. */
export function automationPath(automationId, logs = false) {
    return `${PANEL_PATH}/automation/${encodeURIComponent(automationId)}${logs ? '/logs' : ''}`;
}

/**
 * Read the part of the address after the panel's own path.
 *
 * Returns `{page, id, section}`: page is `list`, `config` or `detail`; for `detail`, `id` is the automation
 * and `section` is `logs` if the address points at its log.
 */
export function parseRoute(path) {
    const parts = String(path || '')
        .split('/')
        .filter((part) => part !== '');
    if (parts[0] === 'config' && parts.length === 1) return { page: 'config', id: null, section: null };
    if (parts[0] === 'automation' && parts[1]) {
        let id = parts[1];
        try {
            id = decodeURIComponent(parts[1]);
        } catch (error) {
            id = parts[1];
        }
        return { page: 'detail', id, section: parts[2] === 'logs' ? 'logs' : null };
    }
    return { page: 'list', id: null, section: null };
}

/** The fixed parts of the card an automation can hide with `haa.card.configure()`. All are shown by default. */
export const CARD_PARTS = ['title', 'state', 'message', 'actions', 'log'];

/** Whether a fixed part of the card is shown: it is, unless the options say `false` for it. */
function shown(options, part) {
    return !options || options[part] !== false;
}

/**
 * Render the fixed header: the title, the state and the status message, each unless the automation hid it.
 *
 * The title is the one the automation set with `haa.card.set_title()`, else the automation's name. With
 * nothing to show there is no header at all.
 */
export function renderHeader(automation, title = null, options = null) {
    const state = stateLabel(automation.state, automation.enabled, automation.running_actions);
    const name = shown(options, 'title')
        ? `<span class="name">${escapeHtml(title || automation.name || automation.id)}</span>`
        : '';
    const badge = shown(options, 'state')
        ? `<span class="state state-${state.css}">${escapeHtml(state.label)}</span>`
        : '';
    const message =
        shown(options, 'message') && automation.message
            ? `<div class="message">${escapeHtml(automation.message)}</div>`
            : '';
    if (!name && !badge && !message) return '';
    const top = name || badge ? `<div class="title">${name}${badge}</div>` : '';
    return `<div class="header">${top}${message}</div>`;
}

/** Render the controls that apply to the automation's state: enable, disable, start, stop, restart. */
export function renderControls(automation) {
    const controls = CONTROLS.filter((control) => control.when(automation))
        .map((control) => `<button class="control" data-haanim="${control.service}">${control.label}</button>`)
        .join('');
    return `<div class="controls">${controls}</div>`;
}

/** Render the automation's actions as a list, each with a run button. */
export function renderActionList(actions) {
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
    return rows ? `<ul class="actions">${rows}</ul>` : '<div class="empty">No actions</div>';
}

/**
 * Render the buttons at the bottom of the card: one opens the actions, one goes to the log.
 *
 * Each is left out if the automation hid it; with both hidden there is no toolbar.
 */
export function renderToolbar(automation, options = null) {
    const count = (automation.actions || []).length;
    const actions = shown(options, 'actions')
        ? `<button class="tool" data-haanim-ui="actions">Actions (${count})</button>`
        : '';
    const log = shown(options, 'log') ? '<button class="tool" data-haanim-ui="log">Log</button>' : '';
    return actions || log ? `<div class="toolbar">${actions}${log}</div>` : '';
}

/** Render the popup with all actions of the automation. A click outside it, or on Close, closes it. */
export function renderActionsDialog(automation) {
    return (
        '<div class="overlay" data-haanim-ui="close">' +
        '<div class="dialog" role="dialog" aria-modal="true" data-haanim-ui="dialog">' +
        `<div class="dialog-title">${escapeHtml(automation.name || automation.id)}: actions</div>` +
        renderActionList(automation.actions) +
        '<div class="dialog-buttons"><button class="tool" data-haanim-ui="close">Close</button></div>' +
        '</div></div>'
    );
}

/** Render log records, newest last, with the level as a class. Only the latest are drawn. */
export function renderLog(records) {
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
    return rows ? `<ul class="log">${rows}</ul>` : '<div class="empty">No log records</div>';
}

/**
 * Render the whole card: the header, the automation's content, and the buttons for actions and log.
 *
 * `view` has `automation` (the detail of the automation, or null while it is unknown), `title` (the one the
 * automation set, or null), `options` (which fixed parts the automation shows, or null for all), `blocks`,
 * `layout` (the rows the blocks are placed in, or null for one below the other), `states`, `images`, `showActions` (whether the actions popup is open) and `error` (a message shown instead
 * of the card).
 */
export function renderCard(view) {
    if (view.error) return `<div class="card-error">${escapeHtml(view.error)}</div>`;
    if (!view.automation) return '<div class="card-loading">Loading…</div>';
    const header = renderHeader(view.automation, view.title, view.options);
    const content = renderContent(view.blocks, view, view.layout);
    // The line between header and content is only drawn when there is a header
    const contentClass = header ? 'content' : 'content bare';
    return (
        header +
        (content ? `<div class="${contentClass}">${content}</div>` : '') +
        renderToolbar(view.automation, view.options) +
        (view.showActions && shown(view.options, 'actions') ? renderActionsDialog(view.automation) : '')
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
            const state = stateLabel(automation.state, automation.enabled, automation.running_actions);
            return (
                `<tr class="row" data-open="${escapeHtml(automation.id)}">` +
                `<td class="name">${escapeHtml(automation.name || automation.id)}` +
                `<div class="id">${escapeHtml(automation.id)}</div></td>` +
                `<td><span class="state state-${state.css}">${escapeHtml(state.label)}</span></td>` +
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

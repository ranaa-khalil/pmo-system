// PMO System — pmo-app.js
// Assembles the Alpine.js root store from the domain modules.
//
// Each domain module exports a plain object of state/methods taken verbatim
// from the original monolithic pmoApp(). We merge them with property
// descriptors so Alpine getters (computed properties) stay reactive, and
// every method keeps `this` bound to the merged store.
import { core } from './domains/core.js';
import { tasks } from './domains/tasks.js';
import { backlog } from './domains/backlog.js';
import { planning } from './domains/planning.js';
import { projects } from './domains/projects.js';
import { ai } from './domains/ai.js';
import { copilot } from './domains/copilot.js';
import { workflows } from './domains/workflows.js';
import { tenants } from './domains/tenants.js';
import { portal } from './domains/portal.js';
import { fab } from './fab.js';

const DOMAINS = [core, tasks, backlog, planning, projects, ai, copilot, workflows, tenants, portal];

// Merge a domain's properties into a descriptor set.
// - Plain values (state) are copied.
// - Accessors (getters like `get phaseCounts()`) keep their get/set and are
//   bound to the final store so `this` resolves correctly.
function mergeDomain(target, domain, storeRef) {
    for (const key of Object.keys(domain)) {
        if (key in target) {
            console.warn(`[PMO] duplicate property "${key}" while merging domains`);
        }
        const desc = Object.getOwnPropertyDescriptor(domain, key);
        if (desc.get || desc.set) {
            Object.defineProperty(target, key, {
                get() { return desc.get.call(storeRef || target); },
                set(v) { if (desc.set) desc.set.call(storeRef || target, v); },
                enumerable: true,
                configurable: true,
            });
        } else {
            const value = desc.value;
            target[key] = typeof value === 'function' ? value : deepValue(value);
        }
    }
}

// Plain state values (arrays/objects) are shared as-is — Alpine wraps them in
// reactive proxies on the store, same as the original monolith.
function deepValue(v) { return v; }

// The merged store. Getters keep their ORIGINAL unbound `this` so that when
// Alpine wraps the store in its reactive proxy and calls the getter through
// it, internal reads (`this.dashStats`, `this.currentUser`, …) hit the PROXY
// and are tracked by Alpine's reactivity. Binding `this` to the raw store
// object here would make every getter-injected read invisible to Alpine —
// effects would freeze at their init-time value (stat cards stuck at 0,
// canManageUsers never re-evaluated).
function buildStore() {
    const store = {};
    for (const d of DOMAINS) {
        for (const key of Object.keys(d)) {
            if (key in store) {
                console.warn(`[PMO] duplicate property "${key}" while merging domains`);
            }
            const desc = Object.getOwnPropertyDescriptor(d, key);
            if (desc.get || desc.set) {
                // Keep the accessor as-is (do NOT rebind `this`) — Alpine calls
                // it through the reactive proxy, so `this` IS the proxy and
                // dependency tracking works.
                Object.defineProperty(store, key, desc);
            } else {
                const value = desc.value;
                store[key] = typeof value === 'function' ? value : deepValue(value);
            }
        }
    }
    // Getter-to-getter chains (e.g. canManageClients → canManageUsers) resolve
    // `this.<other>` through the proxy at call time, so cross-getter reads are
    // tracked too.
    return store;
}

export function pmoApp() {
    return buildStore();
}

// Register the root store as a proper Alpine component. Alpine 3.13's
// x-data expression evaluator does NOT resolve globals, so the old
// x-data="pmoApp()" produced an empty scope (all views visible, all actions
// dead). x-data="pmoRoot" + Alpine.data() is the robust pattern — a fresh
// name avoids any stale cached component definition from earlier sessions.
function registerPmoApp() {
    if (!window.Alpine) return;
    try {
        // window.pmoApp() (not the direct buildStore reference): it resolves
        // buildStore at CALL time, after every domain module binding is
        // initialized — the direct reference produced a broken store when
        // the callback ran during Alpine's boot.
        window.Alpine.data('pmoRoot', () => window.pmoApp());
    } catch (e) {
        console.error('[PMO] pmoRoot registration failed:', e);
    }
}
if (window.Alpine) {
    registerPmoApp();
} else {
    document.addEventListener('alpine:init', registerPmoApp, { once: true });
}

// Load Alpine ONLY AFTER the registration path is in place — the dynamic
// import guarantees Alpine boots after the listener exists (a static
// <script defer> tag raced the module and broke the store merge).
//
// Retry with backoff: a single truncated download (or a stale 0-byte cache
// entry) leaves the page with every x-cloak element visible and nothing
// interactive. A versioned query forces revalidation so a corrupt cached
// copy is refetched instead of re-served by the browser.
const ALPINE_URL = '/static/alpine.min.js?v=2';
async function loadAlpine(attempt = 1, max = 3) {
    try {
        await import(/* @vite-ignore */ ALPINE_URL);
        if (typeof window.Alpine !== 'undefined') return;
        throw new Error('Alpine global missing after import');
    } catch (e) {
        if (attempt >= max) throw e;
        await new Promise((r) => setTimeout(r, 800 * attempt));
        return loadAlpine(attempt + 1, max);
    }
}
loadAlpine().then(() => {
    registerPmoApp();
    const root = document.querySelector('[x-data="pmoRoot"]');
    if (!root) return;
    // Re-walk ONLY if the store never bound (the boot race). Re-initializing
    // an already-bound tree forks the data scope (two stores on one element)
    // and duplicates every x-for clone — menus duplicated in one view and
    // empty in the other, because the toggle writes to one scope while the
    // other never updates.
    const bound = root._x_dataStack && root._x_dataStack[0] && root._x_dataStack[0].navItems !== undefined;
    if (bound) return;
    try {
        window.Alpine.initTree(root);
    } catch (e) {
        console.error('[PMO] root re-walk failed:', e);
    }
}).catch((e) => {
    // alpine-fallback.js renders a retry screen after 3s — never strip
    // x-cloak (that shows every modal at once).
    console.error('[PMO] Alpine failed to load:', e);
});

// Expose for backward compatibility and manual debugging.
window.pmoApp = pmoApp;
window.fabComponent = fab;

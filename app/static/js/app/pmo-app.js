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
import { fab } from './fab.js';

const DOMAINS = [core, tasks, backlog, planning, projects, ai, copilot, workflows, tenants];

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
import('/static/alpine.min.js').then(() => {
    // Belt-and-braces: if the root component walked before the registration
    // took effect (scheduling edge case at boot), register now and re-walk
    // the root element so the real store data binds.
    const root = document.querySelector('[x-data="pmoRoot"]') || document.body;
    const merged = root._x_dataStack?.some((s) => Object.getOwnPropertyNames(s).some((k) => !k.startsWith('$')));
    if (window.Alpine && !merged) {
        registerPmoApp();
        root.removeAttribute('x-data');
        root.setAttribute('x-data', 'pmoRoot');
        try { window.Alpine.initTree(root); } catch (e) {
            console.error('[PMO] root re-walk failed:', e);
        }
    }
}).catch((e) => {
    console.error('[PMO] Alpine failed to load:', e);
});

// Expose for backward compatibility and manual debugging.
window.pmoApp = pmoApp;
window.fabComponent = fab;

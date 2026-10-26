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

// The merged store. Built in two passes: first pass copies plain data so
// getters evaluated during the second pass see full state.
function buildStore() {
    const store = {};
    for (const d of DOMAINS) mergeDomain(store, d, null);
    // Second pass: rebind accessors to the completed store object identity
    const bound = {};
    for (const key of Object.keys(store)) {
        const desc = Object.getOwnPropertyDescriptor(store, key);
        if (desc.get || desc.set) {
            Object.defineProperty(bound, key, {
                get() { return desc.get.call(store); },
                set(v) { if (desc.set) desc.set.call(store, v); },
                enumerable: true,
                configurable: true,
            });
        } else {
            Object.defineProperty(bound, key, desc);
        }
    }
    // Copy the non-accessor properties back onto the same object identity so
    // `store` and `bound` are one object with correct accessors.
    for (const key of Object.keys(bound)) {
        const desc = Object.getOwnPropertyDescriptor(bound, key);
        if (desc.get || desc.set) {
            Object.defineProperty(store, key, {
                get() { return desc.get.call(store); },
                set(v) { if (desc.set) desc.set.call(store, v); },
                enumerable: true,
                configurable: true,
            });
        }
    }
    return store;
}

export function pmoApp() {
    return buildStore();
}

// Expose for Alpine (loaded with `defer`, so this module must run first —
// the shell loads it as a classic module without defer, Alpine after).
window.pmoApp = pmoApp;
window.fabComponent = fab;

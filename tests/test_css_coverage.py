"""Zero-visual-change guard for the compiled Tailwind artifact (ADR-07, R2 slot one).

The Play CDN (static/tailwind.min.js — a 407KB runtime JIT, Tailwind v3.4.17)
was replaced by a committed compiled stylesheet
(app/static/css/tailwind.compiled.css, built by ``npm run build:css``).
Because the running server may serve the swapped templates immediately,
this suite gates the swap:

1. every Tailwind-owned class token used in app/templates/** (static class
   attributes, Jinja-conditional classes, Alpine ``:class`` bindings and
   ``x-transition:*`` classes) or generated in app/static/js/** (HTML in
   template strings, classList calls, the class-mapping functions) must be
   produced by the compiled artifact — classes defined in the hand-written
   CSS (theme/components/views/utilities + inline <style> blocks) are
   exempt, and a token defined nowhere is a broken style that fails;
2. the content globs in tailwind.config.js must match EVERY template and
   JS file — if a file escapes the globs, its utilities silently vanish
   from the artifact and (1) catches it; this test makes the same point
   directly;
3. the Play CDN script tag is gone from every template, the compiled
   stylesheet is linked with a ?v= cache-bust, and tailwind.min.js stays
   on disk unreferenced for rollback.

Rendered-nothing exemptions — classes that produce NO rule under the
CDN JIT either (same Tailwind v3.4.17, same config), so the
zero-visual-change gate keeps them ungenerated:
- ``brand-*`` colors are tenant-dynamic ``color-mix()/var()`` values;
  Tailwind cannot apply alpha modifiers to unparseable colors, so e.g.
  ``bg-brand-50/30`` renders nothing today (plain ``bg-brand-50`` works);
- ``h-4.5`` / ``w-4.5`` / ``z-5`` — no such step exists in the v3.4.17
  spacing/z-index scales (latent dead classes, unchanged on purpose);
- ``prose-ul:my-0.5`` — a typography-plugin variant with the plugin
  absent and no hand-written rule (views.css defines ``prose-ul:my-1``).
"""

import fnmatch
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO / "app" / "templates"
JS_DIR = REPO / "app" / "static" / "js"
CSS_DIR = REPO / "app" / "static" / "css"
COMPILED = CSS_DIR / "tailwind.compiled.css"
CONFIG = REPO / "tailwind.config.js"
HANDWRITTEN_CSS = ["theme.css", "components.css", "views.css", "utilities.css"]

TOKEN_RE = re.compile(r"^[a-zA-Z0-9_:\[\]().#%/-]+$")

# Tailwind utility family prefixes — gates which JS / :class strings count as classes
FAMILIES = [
    "min-w", "min-h", "max-w", "max-h", "grid-cols", "col-span", "row-span", "space-x", "space-y",
    "gap-x", "gap-y", "ring-offset", "line-clamp", "line-through", "border-t", "border-b", "border-l",
    "border-r", "border-x", "border-y", "bg", "text", "border", "ring", "shadow", "from", "via", "to",
    "rounded", "w", "h", "p", "px", "py", "pt", "pb", "pl", "pr", "m", "mx", "my", "mt", "mb", "ml", "mr",
    "gap", "space", "flex", "grid", "items", "justify", "content", "self", "place", "order", "font",
    "leading", "tracking", "list", "whitespace", "opacity", "z", "top", "bottom", "left", "right", "inset",
    "fixed", "absolute", "relative", "sticky", "static", "hidden", "block", "inline", "overflow", "object",
    "aspect", "columns", "basis", "grow", "shrink", "translate", "rotate", "scale", "skew", "transition",
    "duration", "ease", "animate", "cursor", "select", "resize", "appearance", "pointer-events", "outline",
    "divide", "blur", "brightness", "saturate", "backdrop", "align", "decoration", "underline", "uppercase",
    "lowercase", "capitalize", "normal-case", "italic", "not-italic", "truncate", "break", "tabular", "group",
    "peer", "sr", "transform", "filter", "isolation", "overscroll", "touch", "fill", "stroke", "accent",
    "caret", "scroll", "snap", "float", "clear", "box", "container", "prose", "antialiased", "col", "row",
]
# families that also have a genuine bare utility form (flex, hidden, border, …)
BARE_OK = {
    "flex", "grid", "hidden", "block", "inline", "inline-block", "inline-flex", "fixed", "absolute",
    "relative", "sticky", "static", "truncate", "underline", "uppercase", "lowercase", "capitalize",
    "italic", "not-italic", "normal-case", "container", "antialiased", "border", "rounded", "shadow",
    "ring", "blur", "transform", "filter", "isolate", "content", "grow", "shrink", "transition", "table",
    "contents",
}
# group/peer are marker classes: they generate no CSS by design
MARKER_RE = re.compile(r"^(group|peer)(/.*)?$")
# brand-* alpha modifiers render nothing (see module docstring)
BRAND_ALPHA_RE = re.compile(
    r"^(?:bg|border|ring|from|via|to|shadow|text|divide|fill|stroke|decoration|outline|accent|caret)"
    r"-brand-\d+/"
)
RENDERS_NOTHING = {"h-4.5", "w-4.5", "z-5", "prose-ul:my-0.5", "content-type"}


def _is_utility_shape(token: str) -> bool:
    """True when the token could name a Tailwind utility (not JS state or prose)."""
    if not TOKEN_RE.match(token) or not re.search(r"[a-zA-Z]", token):
        return False
    if token[-1] in "-:/.":
        return False
    stem = token.lstrip("-").split(":")[-1].split("/")[0]
    if stem.startswith("[") or not stem:
        return False
    if stem in BARE_OK:
        return True
    if any(stem == f or stem.startswith(f + "-") or stem.startswith(f + "[") for f in FAMILIES if f in BARE_OK):
        return True
    # families without a bare utility form (list, from, rotate, …) require a compound stem
    if any(
        stem != f and (stem.startswith(f + "-") or stem.startswith(f + "[")) for f in FAMILIES if f not in BARE_OK
    ):
        return True
    return any(
        stem.startswith(f) and len(stem) > len(f) and stem[len(f)] in "-[/:." for f in FAMILIES if "-" in f
    )


def _extract_template_tokens(src: str, out: set, where: dict, rel: str) -> None:
    def add(token: str) -> None:
        if _is_utility_shape(token):
            out.add(token)
            where[token].add(rel)

    for m in re.finditer(r"(?:^|\s)([\w:@-]*class[\w-]*)\s*=\s*('([^']*)'|\"([^\"]*)\")", src, re.S):
        attr, val = m.group(1), (m.group(3) if m.group(3) is not None else m.group(4))
        if attr.startswith(":") or attr.startswith("x-bind"):
            # Alpine binding: quoted strings carry the class names
            for q in re.findall(r"'([^']*)'|\"([^\"]*)\"", val):
                for token in (q[0] or q[1]).split():
                    add(token)
        else:
            static = re.sub(r"\{\{.*?\}\}", " ", val)
            for token in static.split():
                add(token)
            for q in re.findall(r"'([^']*)'|\"([^\"]*)\"", static):
                for token in (q[0] or q[1]).split():
                    add(token)
    for m in re.finditer(r"(?:^|\s)x-transition:[\w-]+\s*=\s*('([^']*)'|\"([^\"]*)\")", src, re.S):
        for token in (m.group(2) or m.group(3)).split():
            add(token)


def _extract_js_tokens(src: str, out: set, where: dict, rel: str) -> None:
    def add(token: str) -> None:
        if _is_utility_shape(token):
            out.add(token)
            where[token].add(rel)

    for m in re.finditer(r"(?:class\s*=\s*|className\s*=\s*)(\"([^\"]*)\"|'([^']*)'|`([^`]*)`)", src, re.S):
        for group in m.groups()[1:]:
            if group:
                for token in group.split():
                    add(token)
    for m in re.finditer(r"classList\.(?:add|remove|toggle)\(([^)]*)\)", src):
        for quoted in re.findall(r"['\"]([^'\"]*)['\"]", m.group(1)):
            for token in quoted.split():
                add(token)
    # class-mapping functions (itemTypeColor, …) return class strings
    for q in re.findall(r"'([^'\\\n]{2,60})'|\"([^\"\\\n]{2,60})\"|`([^`\\\n]{2,120})`", src):
        for token in (q[0] or q[1] or q[2]).split():
            add(token)


def _css_class_names(blob: str) -> set:
    return {part.replace("\\", "") for part in re.findall(r"\.([a-zA-Z0-9_\\:\[\]().#%/-]+)", blob)}


def _used_tokens():
    templates = sorted(TEMPLATE_DIR.rglob("*.html"))
    js_files = sorted(JS_DIR.rglob("*.js"))
    tokens, where = set(), defaultdict(set)
    for path in templates:
        _extract_template_tokens(path.read_text(errors="replace"), tokens, where, str(path.relative_to(REPO)))
    for path in js_files:
        _extract_js_tokens(path.read_text(errors="replace"), tokens, where, str(path.relative_to(REPO)))
    return templates, js_files, tokens, where


def test_config_content_globs_cover_every_source_file():
    """A file outside the globs compiles to nothing — the guard must notice."""
    config_src = CONFIG.read_text()
    m = re.search(r"content:\s*\[(.*?)\]", config_src, re.S)
    assert m, "tailwind.config.js has no content array"
    globs = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
    assert globs, "tailwind.config.js content array is empty"

    def matches(rel: str) -> bool:
        for pattern in globs:
            norm = pattern.lstrip("./")
            if fnmatch.fnmatch(rel, norm) or fnmatch.fnmatch(rel, norm.replace("**/", "**")):
                return True
        return False

    _, js_files, _, _ = _used_tokens()
    sources = [str(p.relative_to(REPO)) for p in sorted(TEMPLATE_DIR.rglob("*.html")) + js_files]
    assert sources, "no source files found under app/templates or app/static/js"
    uncovered = [rel for rel in sources if not matches(rel)]
    assert not uncovered, f"files not matched by tailwind.config.js content globs: {uncovered}"


def test_compiled_artifact_exists_with_preflight():
    assert COMPILED.is_file(), "tailwind.compiled.css is missing — run npm run build:css"
    compiled = COMPILED.read_text()
    assert len(compiled) > 1000, "compiled artifact is suspiciously small"
    assert "box-sizing" in compiled, "preflight (@tailwind base) missing from the artifact"
    assert "@import" not in compiled, "tokens.css was not inlined — the build resolved no @import"


def test_compiled_artifact_covers_every_used_tailwind_class():
    templates, js_files, tokens, where = _used_tokens()
    assert templates and js_files, "extraction found no source files"
    compiled = COMPILED.read_text()
    compiled_norm = compiled.replace("\\", "")
    compiled_classes = _css_class_names(compiled)

    handwritten = set()
    for name in HANDWRITTEN_CSS:
        handwritten |= _css_class_names((CSS_DIR / name).read_text(errors="replace"))
    for path in templates:
        for style in re.findall(r"<style[^>]*>(.*?)</style>", path.read_text(errors="replace"), re.S):
            handwritten |= _css_class_names(style)

    missing = {}
    for token in sorted(tokens):
        if MARKER_RE.match(token) or token in RENDERS_NOTHING or token in handwritten:
            continue
        if BRAND_ALPHA_RE.match(token.split(":")[-1]):
            continue
        boundary = re.compile(r"\." + re.escape(token) + r"(?![a-zA-Z0-9_\\\[\]()#%/.-])")
        if not boundary.search(compiled_norm):
            missing[token] = sorted(where[token])

    # sanity: the classifier actually knows Tailwind classes
    probe = {"bg-emerald-500", "text-[13px]", "hover:bg-ink-50", "rounded-full"}
    assert probe <= tokens, "sanity probe unexpectedly missing from extraction"

    assert not missing, (
        "Tailwind classes used in templates/JS but missing from tailwind.compiled.css "
        "(rebuild with npm run build:css; check the content globs): "
        + "; ".join(f"{tok} <- {files[:2]}" for tok, files in sorted(missing.items())[:20])
    )
    assert len(compiled_classes) > 300, "compiled artifact defines suspiciously few classes"


def test_play_cdn_removed_and_compiled_link_busted():
    for path in sorted(TEMPLATE_DIR.rglob("*.html")):
        src = path.read_text(errors="replace")
        assert "tailwind.min.js" not in src, f"Play CDN script still referenced in {path.name}"
    index = (TEMPLATE_DIR / "index.html").read_text()
    assert re.search(
        r"<link[^>]+href=\"/static/css/tailwind\.compiled\.css\?v=", index
    ), "index.html must link the compiled stylesheet with a ?v= cache-bust"
    # rollback path: the JIT stays on disk, unreferenced
    assert (REPO / "app" / "static" / "tailwind.min.js").is_file(), "tailwind.min.js must stay on disk for rollback"


# Tailwind families whose utilities must never be composed at runtime —
# color/layout families with unambiguous class shapes. Single-letter families
# (p, m, w, h, z) are excluded on purpose: strings like 'p-' + year are
# period keys, not classes.
GUARD_FAMILIES = [
    "bg", "text", "border", "ring", "shadow", "from", "via", "to", "divide",
    "fill", "stroke", "outline", "decoration", "placeholder", "accent", "caret",
    "rounded", "px", "py", "pt", "pb", "pl", "pr", "mx", "my", "mt", "mb",
    "ml", "mr", "gap", "top", "bottom", "left", "right", "inset", "opacity",
    "duration", "delay", "grid-cols", "space-x", "space-y", "translate",
    "scale", "rotate",
]


def test_js_class_tokens_are_literal_strings():
    """Carry-forward guard (ADR-07, Slice 3a): JS classes must be literal.

    A class composed at runtime — ``'bg-' + color``, ``bg-${shade}`` — escapes
    the compiled artifact whenever the composed value has no literal use
    anywhere in the content globs, and the utility silently vanishes from the
    UI. The pattern this codebase uses instead is the literal mapping table
    (itemTypeColor, tagChipClass, avatarColor, workCardBorderColor, …): every
    full class string is written out so ``npm run build:css`` sees it. This
    guard fails on any composed Tailwind class string in app/static/js/**.
    """
    offenders = []
    for path in sorted(JS_DIR.rglob("*.js")):
        src = path.read_text(errors="replace")
        rel = path.relative_to(REPO)
        for fam in GUARD_FAMILIES:
            # 'bg-' + … / "bg-" + … (string concatenation)
            if re.search(r"['\"]" + fam + r"-['\"]\s*\+", src):
                offenders.append(f"{rel}: composes '{fam}-' with +")
            # `bg-${…}` (template literal interpolation)
            if re.search(r"`[^`]*" + fam + r"-\$\{", src):
                offenders.append(f"{rel}: composes '{fam}-' with ${{}}")
    assert not offenders, (
        "Dynamic Tailwind class composition in app/static/js/** — classes must "
        "be literal strings (use a mapping table like itemTypeColor): "
        + "; ".join(offenders[:10])
    )

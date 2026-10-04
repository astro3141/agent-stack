"""The query kind of a model call: one prompt, no tools, an answer in a declared shape (§89).

A harness that pins its prompts to a schema (trading, #62) needs three things of the door that a
task does not: the payload sent byte for byte, no tool round at all, and the answer checked
against the schema it declared — and the check is the door's, after the call, so that it is the
same whichever vendor answered. The ACP path the adapter runs on carries no vendor-side schema
mode (DECISIONS-2026-10-04 §3), so this is where the shape is enforced:

    import query
    text  = query.extract(text)              # the model's text with one JSON fence removed, nothing else
    probs = query.problems(value, schema)    # what the value breaks in the schema; [] when nothing
    bad   = query.unchecked(schema)          # keywords this validator does not check: a schema that
                                             # uses one is refused before the call, never half-checked
    calls, web = query.tool_counts(events)   # tool calls the turn made, and how many were web lookups

What is checked is the JSON Schema subset below (CHECKED) and nothing more. A keyword outside it
would be skipped silently by a general validator's default mode, and an answer called valid on a
half-read schema is worse than a refusal: `unchecked()` names them, and the door refuses the
schema up front. The annotations (ANNOTATIONS) are read by nobody and allowed.
"""
import json, re

# the keywords this validator applies, by the JSON they apply to
CHECKED = {
    "type", "enum", "const",
    "properties", "required", "additionalProperties",
    "items", "minItems", "maxItems",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern",
    "anyOf", "oneOf", "allOf", "$ref", "$defs", "definitions",
}
# read by nobody, allowed anywhere
ANNOTATIONS = {"$schema", "$id", "title", "description", "default", "examples", "$comment", "deprecated"}

# a web lookup, by the names the three vendors give the tool over ACP
WEB_TOOL = re.compile(r"web[_ ]?(search|fetch)", re.I)

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def extract(text):
    """The model's text as the JSON it carries: one surrounding ``` fence removed when the whole
    text is a fence (with or without a language tag), outer whitespace stripped. Nothing else —
    no search for a brace, no repair. What a model wrote around its JSON is its answer too."""
    t = (text or "").strip()
    m = re.fullmatch(r"```[A-Za-z0-9_-]*[ \t]*\r?\n(.*?)\r?\n?```", t, re.S)
    return m.group(1).strip() if m else t


def unchecked(schema):
    """Every keyword in the schema (at any depth) that is neither checked nor an annotation."""
    out = set()

    def walk(s):
        if isinstance(s, dict):
            for k, v in s.items():
                if k not in CHECKED and k not in ANNOTATIONS:
                    out.add(k)
                if k in ("properties", "$defs", "definitions") and isinstance(v, dict):
                    for sub in v.values():
                        walk(sub)
                elif k in ("items", "additionalProperties"):
                    walk(v)
                elif k in ("anyOf", "oneOf", "allOf") and isinstance(v, list):
                    for sub in v:
                        walk(sub)
    walk(schema)
    return sorted(out)


def _resolve(ref, root):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ValueError(f"$ref {ref!r}: only local references (#/$defs/… or #/definitions/…) are read")
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"$ref {ref!r} points at nothing")
        node = node[part]
    return node


def problems(value, schema, root=None, at="$"):
    """What `value` breaks in `schema`, as sentences naming the place; [] when nothing.
    The subset in CHECKED, applied in the order a reader of the schema would."""
    root = schema if root is None else root
    out = []
    if not isinstance(schema, dict):
        return [f"{at}: the schema here is not an object"]
    if "$ref" in schema:
        try:
            return problems(value, _resolve(schema["$ref"], root), root, at)
        except ValueError as e:
            return [f"{at}: {e}"]
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES.get(x, lambda v: False)(value) for x in types):
            out.append(f"{at}: is {_name(value)}, the schema says {' or '.join(map(str, types))}")
            return out                         # the keywords below assume the type
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{at}: {json.dumps(value, ensure_ascii=False)[:60]} is not one of {json.dumps(schema['enum'], ensure_ascii=False)[:120]}")
    if "const" in schema and value != schema["const"]:
        out.append(f"{at}: is not the constant {json.dumps(schema['const'], ensure_ascii=False)[:60]}")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for k in schema.get("required") or []:
            if k not in value:
                out.append(f"{at}: required key {k!r} is missing")
        for k, sub in props.items():
            if k in value:
                out.extend(problems(value[k], sub, root, f"{at}.{k}"))
        ap = schema.get("additionalProperties", True)
        extra = [k for k in value if k not in props]
        if ap is False and extra:
            out.append(f"{at}: keys the schema does not name: {', '.join(sorted(extra))}")
        elif isinstance(ap, dict):
            for k in extra:
                out.extend(problems(value[k], ap, root, f"{at}.{k}"))
    if isinstance(value, list):
        n = len(value)
        if "minItems" in schema and n < schema["minItems"]:
            out.append(f"{at}: {n} items, the schema wants at least {schema['minItems']}")
        if "maxItems" in schema and n > schema["maxItems"]:
            out.append(f"{at}: {n} items, the schema allows at most {schema['maxItems']}")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                out.extend(problems(item, schema["items"], root, f"{at}[{i}]"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for key, bad, word in (("minimum", lambda v, b: v < b, "below the minimum"),
                               ("maximum", lambda v, b: v > b, "above the maximum"),
                               ("exclusiveMinimum", lambda v, b: v <= b, "not above the exclusive minimum"),
                               ("exclusiveMaximum", lambda v, b: v >= b, "not below the exclusive maximum")):
            if key in schema and bad(value, schema[key]):
                out.append(f"{at}: {value} is {word} {schema[key]}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{at}: {len(value)} characters, the schema wants at least {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{at}: {len(value)} characters, the schema allows at most {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{at}: does not match the pattern {schema['pattern']!r}")
    for key in ("allOf", "anyOf", "oneOf"):
        subs = schema.get(key)
        if not isinstance(subs, list) or not subs:
            continue
        results = [problems(value, s, root, at) for s in subs]
        ok = sum(1 for r in results if not r)
        if key == "allOf" and ok < len(subs):
            out.extend(p for r in results for p in r)
        elif key == "anyOf" and ok == 0:
            out.append(f"{at}: matches none of the {len(subs)} alternatives")
        elif key == "oneOf" and ok != 1:
            out.append(f"{at}: matches {ok} of the alternatives, the schema wants exactly one")
    return out


def _name(v):
    return ("null" if v is None else "a boolean" if isinstance(v, bool) else "an integer" if isinstance(v, int)
            else "a number" if isinstance(v, float) else "a string" if isinstance(v, str)
            else "an array" if isinstance(v, list) else "an object" if isinstance(v, dict) else type(v).__name__)


def tool_counts(events_path):
    """(tool calls the turn made, how many of them were web lookups), read from the adapter's
    events.jsonl: one per `tool_call` start (acpx tags a start `tool_call`, its progress
    `tool_call_update`), counted once per tool call id. (0, 0) when there is no file: nothing was
    observed, which for a call that never reached the vendor is the truth."""
    seen, web = {}, set()
    try:
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") != "tool_call" or ev.get("tag") != "tool_call":
                    continue
                cid = ev.get("toolCallId") or f"#{len(seen)}"
                seen[cid] = True
                name = " ".join(str(x) for x in (ev.get("title"), ev.get("text"),
                                                 ((ev.get("rawInput") or {}).get("tool") if isinstance(ev.get("rawInput"), dict) else "")) if x)
                if WEB_TOOL.search(name):
                    web.add(cid)
    except OSError:
        return 0, 0
    return len(seen), len(web)

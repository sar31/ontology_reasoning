"""Display-layer translation of Chinese content to English.

Translates Chinese strings in API responses on the fly, without ever writing
back to Neo4j / MySQL. Translations are cached in-process so repeated requests
(e.g. re-renders of the instance graph) are cheap after the first pass.
"""
import json
import logging
import re
import threading

from llm_client import call_llm

log = logging.getLogger(__name__)

# Matches at least one CJK unified ideograph.
_CJK = re.compile(r"[一-鿿]")

# source Chinese string -> English translation
_cache = {}
_lock = threading.Lock()

TRANSLATE_PROMPT = """You are a professional translator for a military / event knowledge graph.
Translate each Chinese string into natural, concise English. Translate proper nouns (entity names,
places, equipment, events, roles) into their natural English equivalents; keep any already-English
text unchanged. Output ONLY a JSON object of the form:
{"translations": {"<original>": "<translation>", ...}}
Do not add any commentary."""


def _needs_translation(s):
    return isinstance(s, str) and bool(_CJK.search(s))


def translate_batch(strings):
    """Translate a list of strings in bulk, filling the in-process cache.

    Returns the cache dict. Strings already cached or without Chinese characters
    are skipped (no LLM call).
    """
    pending = []
    for s in strings:
        if _needs_translation(s) and s not in _cache:
            pending.append(s)
    # Dedupe, preserving order.
    pending = list(dict.fromkeys(pending))
    if not pending:
        return _cache

    BATCH = 80
    with _lock:
        for i in range(0, len(pending), BATCH):
            chunk = pending[i:i + BATCH]
            try:
                raw = call_llm(
                    TRANSLATE_PROMPT,
                    json.dumps({"strings": chunk}, ensure_ascii=False),
                    temperature=0.0,
                )
                trans = raw.get("translations", {}) if isinstance(raw, dict) else {}
            except Exception as e:
                log.error("translate_batch failed: %s", e)
                trans = {}
            for s in chunk:
                t = trans.get(s)
                # Fall back to the original on a missing / empty translation.
                _cache[s] = t if isinstance(t, str) and t.strip() else s
    return _cache


def translate_value(v):
    """Recursively translate every Chinese string inside ``v``.

    Two passes: first collect all translatable strings (one bulk LLM call), then
    substitute translations back. Dict keys are preserved; only string values are
    translated. Ints, English labels, and already-English strings are unchanged.
    """
    collected = []

    def _collect(x):
        if isinstance(x, str):
            if _needs_translation(x):
                collected.append(x)
        elif isinstance(x, list):
            for item in x:
                _collect(item)
        elif isinstance(x, dict):
            for val in x.values():
                _collect(val)

    _collect(v)
    if collected:
        translate_batch(collected)

    def _apply(x):
        if isinstance(x, str):
            return _cache.get(x, x) if _needs_translation(x) else x
        if isinstance(x, list):
            return [_apply(item) for item in x]
        if isinstance(x, dict):
            return {k: _apply(val) for k, val in x.items()}
        return x

    return _apply(v)

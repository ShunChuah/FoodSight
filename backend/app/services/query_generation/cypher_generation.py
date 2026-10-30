# Schema-aware Cypher generation: question -> one LLM call -> checked Cypher.
# The model's query is untrusted: check_cypher() must accept it before it runs.

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any

from ...contracts import QueryPlan
from ..shared.config import policy
from ..shared.diagnostics import kg_debug, log_timing
from ..shared.llm import LLMServiceError, call_llm, parse_json_object
from .cypher_validation import GraphSchema, SchemaRelationship, validate_cypher
from .proximity import coordinates_from_context, default_radius, explicit_radius_meters

RESTAURANT_DETAILS_FIELD = "restaurant_details"
MAX_GENERATION_SECONDS = 9.0
MIN_GENERATION_SECONDS = 2.5
RESERVED_AFTER_GENERATION_SECONDS = 4.0
MAX_QUERY_LENGTH = 6000
MAX_MATCH_CLAUSES = 10
RESTAURANT_LIMIT = 5
GROUP_LIMIT = 10
# Values the app sets itself; only these are loosened when a search finds nothing.
DEFAULT_RADIUS = "default_radius_m"
DEFAULT_MIN_REVIEWS = "default_min_reviews"
RATED_MINIMUM_REVIEWS = 20
RANKING_METRICS = {
    "Restaurant.average_rating": "highest rt.rating_score (Rating)",
    "Restaurant.review_count": "most rt.total_reviews (Rating)",
    "PriceRange.avg_price": "lowest avg_price (PriceRange)",
    "Location.distance_m": "shortest distance_m (needs the user's position or a named starting place)",
}

ACTIONS = ("query", "clarify", "explain", "decline")
MAX_OPTIONS = 4

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "details": {"type": "boolean"},
        "reply": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "cypher": {"type": "string"},
        "parameters": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"anyOf": [
                    {"type": "string"}, {"type": "number"}, {"type": "boolean"},
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "array", "items": {"type": "number"}},
                    {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                ]},
            },
            "required": ["name", "value"],
            "additionalProperties": False,
        }},
    },
    "required": ["action", "details", "reply", "options", "cypher", "parameters"],
    "additionalProperties": False,
}
TITLED_RESPONSE_SCHEMA = {
    **RESPONSE_SCHEMA,
    "properties": {"chat_title": {"type": "string"}, **RESPONSE_SCHEMA["properties"]},
    "required": ["chat_title", *RESPONSE_SCHEMA["required"]],
}
NO_SECOND_QUESTION = (
    "Your previous reply already asked the user a question. Do not use action clarify now: use sensible defaults."
)
TITLE_RULE = (
    "This chat has no title yet. Also set chat_title, whatever the action: a 2-6 word "
    "Title Case name for the chat that says what the user is looking for (for a follow-up, the whole "
    "conversation's topic), for example \"Halal Japanese Food In SS 2\", "
    "\"McDonald's Competitors\" or \"Cheap Eats Near You\". Never repeat the question word for word."
)

# Fixed prompt text, identical for every question so the provider can cache it.
TASK = """You turn one question about food and drink places in Petaling Jaya into one read-only Neo4j 5 Cypher query.
Use only the graph described below. Read the vocabularies carefully: filters on a categorical property must use its exact values."""

OUTPUT_RULES = """# Output rules
- The query starts with MATCH or OPTIONAL MATCH. Never use CALL, UNION, CREATE, MERGE, SET, DELETE, REMOVE, DETACH, DROP, FOREACH or LOAD CSV.
- Every value taken from the user (names, words, numbers) goes in parameters and is referenced as $name. Vocabulary values may be written inline as quoted strings.
- When rows are restaurants, return one row per restaurant with r.restaurant_id AS restaurant_id, plus only values
  you computed or that explain the match (for example distance_m, a count, or t.name AS competitor_of).
  Do not return names, locations, areas, ratings, prices, cuisines, halal status, facilities or hours:
  the application adds them for every restaurant_id. Use the number of restaurants under Defaults.
  Never return more than {restaurant_limit} restaurants, even if the user asks for more.
- When rows are areas or other groups, return a.name AS area_name (or the group value) plus counts or averages with short
  descriptive aliases. Use LIMIT 5 unless the user asks for a number, up to {group_limit}.
- Always end with a LIMIT, even for a single count or value (LIMIT 1).
- Opening hours are free text, so never filter on them for "open now" or "open late": return the closest or best
  places as usual (with h.is_24_7 = true only when the user wants 24 hours); the app works out which are open now.
- Apply ORDER BY and LIMIT as early as possible (in a WITH) so later matches only touch the kept rows.
- Every condition the user asked for goes in a WHERE right after a MATCH or a WITH, or in a MATCH pattern.
  A WHERE right after OPTIONAL MATCH never removes rows: use OPTIONAL MATCH only for values you display,
  and its WHERE may only mention variables that OPTIONAL MATCH introduces.
- When the query starts from a restaurant the user named (for example its competitors or places near it), return the
  restaurant_id of the result restaurants, plus that starting restaurant's id and name
  (t.restaurant_id AS anchor_id, t.name AS competitor_of or t.name AS near_place).
- Restaurant names the user types rarely match the stored name exactly ("ZUS Coffee SS2" is stored as
  "ZUS Coffee - SS2, Petaling Jaya"). Match them word by word against the name and area together:
  WITH r, toLower(r.name + ' ' + coalesce(a.name, '')) AS label WHERE all(word IN $name_words WHERE label CONTAINS word),
  where $name_words is the user's name in lowercase words (leave out "the", "restaurant", "restoran" and "cafe" unless
  they are the only words). For several named places use $places, a list of word lists, with any(words IN $places ...).
- Meanings: popular or famous = most reviews (total_reviews). Hidden gems = rating_score of at least 4.5 with
  20 to 300 reviews.
  Competition or competitors in an area or cuisine = places of the same kind there; use COMPETES_WITH only when the
  user names one restaurant. Muslim-friendly = halal_status 'halal'.
- Questions about what people say, praise or complain about: query Review (text, sentiment, individual_rating) and
  return r.name AS restaurant, v.sentiment AS sentiment, v.individual_rating AS stars, left(v.text, 300) AS review,
  up to 10 rows. Never return author_name.
- A dish the user names (char kuey teow, roti canai): match the menu and, since many places are named after their
  dish, the restaurant name too:
  WHERE toLower(r.name) CONTAINS $dish OR EXISTS {{ MATCH (r)-[:HAS_DISH]->(d:Dish) WHERE toLower(d.name) CONTAINS $dish }}.
- Distance in metres: point.distance(point({{latitude: l.latitude, longitude: l.longitude}}), point({{latitude: $latitude, longitude: $longitude}})). There is no distance() function.
- avg(), sum(), min(), max() and count() aggregate over rows and skip nulls. Never pass them a list; group with RETURN or WITH instead.
- After RETURN DISTINCT or a RETURN with an aggregation, ORDER BY may only use the returned aliases, never x.property.
- Sort so the most relevant rows come first (for example by rating, review count or distance). Sort descending with coalesce(x, 0) so missing values come last.
- Do not write comments in the query.

# Choosing the action
Write every reply as a friendly local food guide talking to a customer, in plain words: never mention vocabularies,
datasets, properties, queries or the graph. When an action does not use a field, set it to "" or [].
- query (the usual action): write the Cypher. When a vague word in the request changes the results and has a sensible
  default, do not ask: just use the default (for example cheap = budget, or the Defaults above).
  details is true only when the user asks about one particular restaurant they named or referred to (more about it,
  its hours, phone, address, location, halal status or booking); it is false for searches, lists and comparisons.
- clarify: only when the request can mean clearly different things, no default is safe, and the answers would differ
  a lot (for example "BBQ" could mean cooking at the table or barbecued dishes; "coffee shop" could mean a cafe or a
  kopitiam). reply is one short question; options are 2-{max_options} short answers the user can tap, written as
  the user would say them. Ask at most one question. Never ask for something the user already said or that the
  conversation already answered, and never ask for the user's location when their position is available.
- explain: a general food or drink question that needs no particular place (for example what a dish is, or the
  difference between a kopitiam and a mamak). reply is a short, friendly answer of at most 80 words; you may use the
  vocabulary definitions above. Do not name or recommend particular places. Never use explain for questions about
  places, reviews or numbers in Petaling Jaya: query them.
- decline: the question is not about food and drink, or it needs information the graph does not have. If it needs
  a category value that is not in its vocabulary (for example Wi-Fi, parking or a drive-through), never use a different
  value as a stand-in (Dine-in is not Wi-Fi, Curbside Pickup is not a drive-through): decline. reply is one friendly sentence saying what you cannot help with. options may offer up to
  {max_options} food and drink requests you can answer instead, written as the user would ask them; otherwise [].
  When the question is not about food or drink at all, options must be [].
- A place clearly outside Petaling Jaya (for example Kuala Lumpur city centre, Subang Jaya or Shah Alam): decline,
  say you cover Petaling Jaya only, and offer nearby Petaling Jaya areas as options.
Return JSON only."""


@dataclass(frozen=True)
class CypherResult:
    status: str
    plan: QueryPlan | None = None
    reply: str | None = None
    options: tuple[str, ...] = ()
    details: bool = False
    error: str | None = None
    cypher: str | None = None
    chat_title: str | None = None


# Prompt files are read once per process: restart the backend after editing them.
def ontology_path() -> Path:
    path = Path(os.getenv("ONTOLOGY_PATH", "app/knowledge_graph/ontology.json"))
    return path if path.is_absolute() else Path(__file__).resolve().parents[3] / path


@lru_cache(maxsize=1)
def load_ontology() -> dict:
    return json.loads(ontology_path().read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_vocabulary() -> dict:
    source = ontology_path().parent / load_ontology()["vocabulary_source"]
    return json.loads(source.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_examples() -> list[dict]:
    path = ontology_path().parent / os.getenv("CYPHER_EXAMPLES_FILE", "cypher_examples.json")
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["examples"]


@lru_cache(maxsize=1)
def ontology_graph_schema() -> GraphSchema:
    ontology = load_ontology()
    nodes = {label: set(node["properties"]) for label, node in ontology["nodes"].items()}
    relationships = [
        SchemaRelationship(rel["from"], name, rel["to"])
        for name, rel in ontology["relationships"].items()
    ]
    for name, rel in ontology["relationships"].items():
        if rel["pattern"].endswith(f"]-(:{rel['to']})"):
            relationships.append(SchemaRelationship(rel["to"], name, rel["from"]))
    return GraphSchema(nodes=nodes, relationships=relationships)


@lru_cache(maxsize=1)
def vocabulary_bindings() -> dict[tuple[str, str], str]:
    return {
        (label, prop): spec["vocabulary"]
        for label, node in load_ontology()["nodes"].items()
        for prop, spec in node["properties"].items()
        if "vocabulary" in spec
    }


def allowed_values(column: str) -> set[str]:
    return set(load_vocabulary()["columns"][column]["values"])


def normalise_area_patterns(cypher: str, parameters: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(parameters)
    for name in re.findall(r"=~\s*\$(\w+)", cypher):
        pattern = parameters.get(name)
        if isinstance(pattern, str):
            pattern = pattern.replace("\\\\", "\\")
            parameters[name] = re.sub(r"(?<=[A-Za-z])(?=\d)", " ?", pattern)
    areas = set(re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*Area\b", cypher))
    for variable, name in re.findall(r"\b(\w+)\.name\s*\)?\s*CONTAINS\s+(?:toLower\(\s*)?\$(\w+)", cypher,
                                     flags=re.IGNORECASE):
        if variable in areas and isinstance(parameters.get(name), str):
            parameters[name] = re.sub(r"\s*\([^)]*\)\s*", " ", parameters[name]).strip() or parameters[name]
    for name in re.findall(r"[<>]=?\s*\$(\w+)", cypher):
        value = parameters.get(name)
        if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
            parameters[name] = float(value) if "." in value else int(value)
    return parameters


@lru_cache(maxsize=1)
def schema_prompt() -> str:
    ontology = load_ontology()
    columns = load_vocabulary()["columns"]
    lines = [TASK, "", "# Context"]
    lines += [f"- {key.replace('_', ' ')}: {value}" for key, value in ontology["meta"].items()]

    lines += ["", "# Nodes"]
    for label, node in ontology["nodes"].items():
        lines.append(f"## {label}: {node.get('description', '')}".rstrip(": "))
        for prop, spec in node["properties"].items():
            lines.append("- " + _property_line(prop, spec, columns))

    lines += ["", "# Relationships (use exactly these directions)"]
    for rel in ontology["relationships"].values():
        lines.append(f"- {rel['pattern']} [{rel['cardinality']}] {rel['description']}")

    definitions = {k: v for k, v in ontology.get("business_definitions", {}).items() if not k.startswith("_")}
    if definitions:
        lines += ["", "# Business definitions"]
        lines += [f"- {term}: {meaning}" for term, meaning in definitions.items()]
    if ontology.get("query_expansions"):
        lines += ["", "# Query expansions (a generic word means any of these values)"]
        lines += [f"- \"{word}\": {spec['property']} IN {json.dumps(spec['any_of'], ensure_ascii=False)}"
                  for word, spec in ontology["query_expansions"].items()]
    lines += ["", "# Cypher rules"]
    lines += [f"- {rule}" for rule in ontology["cypher_rules"]]
    lines += ["", defaults_prompt()]
    lines += ["", OUTPUT_RULES.format(restaurant_limit=RESTAURANT_LIMIT, group_limit=GROUP_LIMIT, max_options=MAX_OPTIONS)]
    examples = load_examples()
    if examples:
        lines += ["", "# Examples"]
        for example in examples:
            lines += ["", f"Question: {example['question']}"]
            action = example.get("action", "query")
            if action != "query":
                lines.append(f"action: {action}, reply: {example['reply']}"
                             + (f", options: {json.dumps(example['options'], ensure_ascii=False)}" if example.get("options") else ""))
                continue
            if example.get("details"):
                lines.append("details: true")
            lines.append(f"Parameters: {json.dumps(example.get('parameters') or {}, ensure_ascii=False)}")
            lines.append("Cypher:\n" + example["cypher"])
    return "\n".join(lines)


def defaults_prompt() -> str:
    proximity, ranking, results = policy("proximity"), policy("ranking"), policy("results")
    venues = ", ".join(f"{venue} {_km(radius)}" for venue, radius in proximity["venue_radius_meters"].items())
    choices: dict[str, list[str]] = {}
    for word, metric in ranking["choices"].items():
        if metric not in RANKING_METRICS:
            raise ValueError(f"query_assumptions.json ranking choice {word!r} names an unknown metric {metric!r}")
        choices.setdefault(metric, []).append(f'"{word}"')
    nearest = proximity["modes"]["nearest_search"]["default_limit"]
    lines = [
        "# Defaults (what to assume when the user does not say)",
        f"- Only when the user asks for places near them or near a restaurant they named, and gives no distance: "
        f"WHERE distance_m <= ${DEFAULT_RADIUS}. The app sets it (near me {_km(proximity['default_radius_meters'])}, "
        f"{venues}, walking distance {_km(proximity['walking_radius_meters'])}, delivery "
        f"{_km(proximity['delivery_radius_meters'])}). When the user gives a distance, use $radius_m with their value "
        "instead. Never add a distance filter otherwise: a search in an area or in all of Petaling Jaya has none.",
        "- Near a mall, station or landmark (not a restaurant): it has no coordinates, so match restaurants whose name "
        "or area contains it, with the spellings people use (1 Utama: '1 utama', '1utama', 'bandar utama').",
        f"- Nearest or closest: ORDER BY distance_m without a radius filter, LIMIT {nearest} unless the user asks for more.",
        f"- Best, top rated, highly rated or good: highest rt.rating_score among places with "
        f"rt.total_reviews >= ${DEFAULT_MIN_REVIEWS}, ties broken by rt.total_reviews. When the user gives a number "
        "of reviews, use their value in another parameter. No minimum rating unless the user gives one.",
        "- Ranking words: " + "; ".join(f"{', '.join(words)} = {RANKING_METRICS[metric]}"
                                        for metric, words in choices.items()) + ".",
        f"- When the user does not say how to rank places, rank by {RANKING_METRICS[ranking['default_field']]}.",
        f"- Number of restaurants: LIMIT {results['discovery_limit']}; LIMIT {results['default_limit']} when the user "
        f"asks for a few; the number the user asks for, up to {RESTAURANT_LIMIT}.",
        f"- Never put ${DEFAULT_RADIUS} or ${DEFAULT_MIN_REVIEWS} in parameters: the app sets them.",
    ]
    return "\n".join(lines)


def _km(metres: int | float) -> str:
    return f"{metres / 1000:g} km" if metres >= 1000 else f"{metres:g} m"


def _property_line(prop: str, spec: dict, columns: dict) -> str:
    facts = [spec["type"]]
    if spec.get("nullable"):
        facts.append("nullable")
    if spec.get("unique"):
        facts.append("unique")
    if spec.get("match") == "fuzzy":
        facts.append("free text")
    for key in ("format", "unit", "range"):
        if spec.get(key):
            facts.append(f"{key}: {spec[key]}")
    line = f"{prop} ({', '.join(facts)})"
    if spec.get("description"):
        line += f": {spec['description']}"
    column = spec.get("vocabulary")
    if not column:
        return line
    col = columns[column]
    line += f"\n  Vocabulary {column}: {col['meaning']}"
    for value, detail in col["values"].items():
        definition = detail if isinstance(detail, str) else detail.get("definition", "")
        includes = detail.get("includes") if isinstance(detail, dict) else None
        line += f"\n    '{value}': {definition}"
        if includes:
            line += f" Covers: {', '.join(includes)}."
    return line


def question_prompt(
    question: str,
    conversation_context: str,
    location_context: str,
    previous: tuple[str, str] | None = None,
    want_title: bool = False,
    may_clarify: bool = True,
) -> str:
    parts = []
    if conversation_context and conversation_context != "No previous conversation.":
        parts.append("Previous conversation (use it to resolve follow-ups such as 'what about halal ones?'):\n"
                     + conversation_context)
    area = re.search(r"^User location area:\s*(.+)$", location_context or "", flags=re.IGNORECASE | re.MULTILINE)
    if coordinates_from_context(location_context):
        parts.append("The user's position is available as $latitude and $longitude (WGS84). "
                     "Use it for 'near me' or distance questions.")
    elif area:
        parts.append(f"The user said they are in or near this area: {area.group(1).strip()}")
    else:
        parts.append("The user's position is not available: never use $latitude, $longitude or a distance filter.")
    parts.append(f"Question: {question}")
    if not may_clarify:
        parts.append(NO_SECOND_QUESTION)
    if want_title:
        parts.append(TITLE_RULE)
    if previous:
        parts.append("Your previous query was rejected. Return a corrected query.\n"
                     f"Previous query:\n{previous[0]}\nError: {previous[1]}")
    return "\n\n".join(parts)


# Entry point for LLM call 1. Never raises; previous = (rejected query, reason) for the one retry.
def generate_cypher(
    question: str,
    conversation_context: str,
    location_context: str,
    *,
    deadline: float | None = None,
    previous: tuple[str, str] | None = None,
    want_title: bool = False,
    may_clarify: bool = True,
) -> CypherResult:
    started_at = perf_counter()
    result = _generate(question, conversation_context, location_context, deadline, previous, want_title, may_clarify)
    log_timing("cypher.generation", started_at, status=result.status, retry=bool(previous))
    return result


def _generate(question, conversation_context, location_context, deadline, previous, want_title,
              may_clarify=True) -> CypherResult:
    timeout = MAX_GENERATION_SECONDS
    if deadline is not None:
        timeout = min(timeout, deadline - perf_counter() - RESERVED_AFTER_GENERATION_SECONDS)
        if timeout < MIN_GENERATION_SECONDS:
            return CypherResult("skipped_deadline")
    try:
        raw = call_llm(
            question_prompt(question, conversation_context, location_context, previous, want_title, may_clarify),
            schema_prompt(),
            task="query",
            timeout_seconds=timeout,
            response_schema=TITLED_RESPONSE_SCHEMA if want_title else RESPONSE_SCHEMA,
        )
    except LLMServiceError as exc:
        return CypherResult(exc.code or "llm_error", error=str(exc))
    payload = parse_json_object(raw)
    if not payload or not isinstance(payload.get("cypher"), str):
        return CypherResult("invalid_json", error="The model did not return the expected JSON.")
    title = payload.get("chat_title") if want_title and isinstance(payload.get("chat_title"), str) else None
    reply = payload["reply"].strip() if isinstance(payload.get("reply"), str) else ""
    if not payload["cypher"].strip() and re.match(r"(?:OPTIONAL\s+)?MATCH\b", reply, flags=re.IGNORECASE):
        payload["cypher"], reply = reply, ""
    options = tuple(dict.fromkeys(
        " ".join(option.split())[:80] for option in payload.get("options") or []
        if isinstance(option, str) and option.strip()))[:MAX_OPTIONS]
    action = payload.get("action") if payload.get("action") in ACTIONS else "query"
    incomplete = (action == "decline" and not reply) or (action == "explain" and not reply) or \
        (action == "clarify" and (not reply or len(options) < 2))
    if incomplete and payload["cypher"].strip():
        action = "query"
    if action == "clarify" and reply and len(options) >= 2:
        return CypherResult("clarify", reply=reply, options=options, chat_title=title)
    if action == "explain" and reply:
        return CypherResult("explain", reply=reply, chat_title=title)
    if action != "query" or not payload["cypher"].strip():
        return CypherResult("cannot_answer", reply=reply or None, options=options if action == "decline" else (),
                            chat_title=title)

    cypher = repair_cypher(clean_cypher(payload["cypher"]))
    parameters = {
        item["name"].lstrip("$"): item["value"]
        for item in payload.get("parameters") or []
        if isinstance(item, dict) and isinstance(item.get("name"), str)
        and re.fullmatch(r"\$?[A-Za-z_]\w*", item["name"])
    }
    coordinates = coordinates_from_context(location_context)
    if coordinates:
        parameters.update(coordinates)
    cypher, parameters = apply_defaults(cypher, parameters, question, conversation_context)
    if NAME_LABEL.search(payload["cypher"]) or "replace(replace(replace(" in cypher:
        parameters = _apostrophe_free_words(parameters, cypher)
    kg_debug("Cypher (unvalidated)", {"cypher": cypher, "parameters": parameters})

    if not coordinates and re.search(r"\$(?:latitude|longitude)\b", cypher):
        error = ("The user's position is not available, so $latitude and $longitude cannot be used. "
                 "Search the named area (or all of Petaling Jaya) without distances.")
    else:
        error = check_cypher(cypher, parameters)
    if error:
        kg_debug("Cypher rejected", error)
        return CypherResult("rejected_validation", error=error, cypher=cypher, chat_title=title)
    # Fixed after validation, so the check sees the model's own query.
    parameters = normalise_area_patterns(cypher, parameters)
    details = payload.get("details") is True
    return CypherResult("success", plan=build_plan(cypher, parameters, details), cypher=cypher, chat_title=title,
                        details=details)


def apply_defaults(cypher: str, parameters: dict[str, Any], question: str,
                   conversation_context: str = "") -> tuple[str, dict[str, Any]]:
    parameters = {name: value for name, value in parameters.items() if name not in (DEFAULT_RADIUS, DEFAULT_MIN_REVIEWS)}
    stated = explicit_radius_meters(question)
    for name in dict.fromkeys(_radius_parameters(cypher)):
        if stated is not None:
            if name == DEFAULT_RADIUS:
                cypher, name = re.sub(rf"\${DEFAULT_RADIUS}\b", "$radius_m", cypher), "radius_m"
            parameters[name] = stated
        elif name != DEFAULT_RADIUS and parameters.get(name) not in _earlier_radii(conversation_context):
            cypher = re.sub(rf"\${name}\b", f"${DEFAULT_RADIUS}", cypher)
            parameters.pop(name, None)
    if re.search(rf"\${DEFAULT_RADIUS}\b", cypher):
        parameters[DEFAULT_RADIUS] = _default_radius(question, conversation_context)
    if re.search(rf"\${DEFAULT_MIN_REVIEWS}\b", cypher):
        parameters[DEFAULT_MIN_REVIEWS] = policy("ranking").get("rated_minimum_reviews", RATED_MINIMUM_REVIEWS)
    return cypher, parameters


def _radius_parameters(cypher: str) -> list[str]:
    nested = r"\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)"
    return re.findall(rf"distance\w*(?:\.\w+)?\s*(?:{nested})?\s*<=?\s*\$(\w+)", cypher, flags=re.IGNORECASE)


def _user_turns(conversation_context: str) -> list[str]:
    return re.findall(r"^User:\s*(.+)$", conversation_context or "", flags=re.MULTILINE)


def _earlier_radii(conversation_context: str) -> set[int]:
    return {radius for turn in _user_turns(conversation_context)
            if (radius := explicit_radius_meters(turn)) is not None}


def _default_radius(question: str, conversation_context: str) -> int:
    general = policy("proximity")["default_radius_meters"]
    for turn in [question, *reversed(_user_turns(conversation_context))]:
        radius = default_radius(turn)
        if radius is not None and radius != general:
            return radius
    return general


def relaxed_parameters(parameters: dict[str, Any]) -> list[tuple[dict[str, Any], int | None]]:
    settings = policy("alternatives")
    if not settings["enabled"]:
        return []
    attempts, current = [], dict(parameters)
    if current.get(DEFAULT_MIN_REVIEWS):
        current = {**current, DEFAULT_MIN_REVIEWS: 0}
        attempts.append((current, None))
    radius = current.get(DEFAULT_RADIUS)
    if isinstance(radius, (int, float)):
        for step in settings["automatic_radius_steps_meters"]:
            if step > radius:
                current = {**current, DEFAULT_RADIUS: step}
                attempts.append((current, step))
    return attempts[:settings["maximum_attempts"]]


def clean_cypher(cypher: str) -> str:
    if "\n" not in cypher and "\\n" in cypher:
        cypher = cypher.replace("\\n", "\n").replace("\\t", " ")
    cypher = re.sub(r"/\*[\s\S]*?\*/", "", cypher)
    cypher = re.sub(r"//[^\n]*", "", cypher)
    return cypher.strip().rstrip(";").strip()


def build_plan(cypher: str, parameters: dict[str, Any], details: bool = False) -> QueryPlan:
    maximum = RESTAURANT_LIMIT if returns_restaurants(cypher) else GROUP_LIMIT
    limits = [int(value) for value in re.findall(r"\bLIMIT\s+(\d+)\b", cypher, flags=re.IGNORECASE)]
    return QueryPlan(
        cypher=cypher, parameters=parameters,
        result_limit=min([maximum, *limits]),
        requested_fields=(RESTAURANT_DETAILS_FIELD,) if details else (),
    )


def returns_restaurants(cypher: str) -> bool:
    final_return = re.split(r"\bRETURN\b", cypher, flags=re.IGNORECASE)[-1]
    return bool(re.search(r"\bAS\s+restaurant_id\b", final_return, flags=re.IGNORECASE))


def undirected_pattern_issues(cypher: str) -> list[str]:
    relationships = ontology_graph_schema().relationships
    issues = []
    sides = [
        r"(?=\(\s*\w*\s*:\s*([A-Za-z_]\w*)[^)]*\)\s*-\s*\[\s*\w*\s*:\s*([A-Za-z_]\w*)[^\]]*\]\s*-\s*\()",
        r"(?=\)\s*-\s*\[\s*\w*\s*:\s*([A-Za-z_]\w*)[^\]]*\]\s*-\s*\(\s*\w*\s*:\s*([A-Za-z_]\w*))",
    ]
    pairs = re.findall(sides[0], cypher) + [(label, rel) for rel, label in re.findall(sides[1], cypher)]
    for label, rel in pairs:
        if not any(item.type == rel and label in (item.source, item.target) for item in relationships):
            issues.append(f"{label} has no {rel} relationship; check the relationship list.")
    return list(dict.fromkeys(issues))


def aggregate_issues(cypher: str) -> list[str]:
    collected = set(re.findall(r"\bcollect\s*\([^)]*\)\s+AS\s+([A-Za-z_]\w*)", cypher, flags=re.IGNORECASE))
    misused = sorted({name for name in collected if re.search(
        rf"\b(?:avg|sum|stDev|stDevP|min|max|percentileCont|percentileDisc)\s*\(\s*(?:\[\s*)?"
        rf"(?:\w+\s+IN\s+)?{re.escape(name)}\b", cypher, flags=re.IGNORECASE)})
    if not misused:
        return []
    return [f"{', '.join(misused)} is a list from collect(); avg(), sum(), min(), max() and stDev() take rows, not a list. "
            "Aggregate the values directly in the same WITH or RETURN, for example avg(rt.rating_score)."]


def parameter_issues(cypher: str, parameters: dict[str, Any]) -> list[str]:
    issues = []
    # Only the user's real position may be used as coordinates; places are found by name, never by guessed coordinates.
    invented = sorted(name for name in re.findall(r"\$(\w*(?:lat|lon|lng)\w*)", cypher, flags=re.IGNORECASE)
                      if name not in ("latitude", "longitude"))
    if invented:
        issues.append(f"Do not invent coordinates (${', $'.join(invented)}). Use only $latitude and $longitude, the "
                      "user's position; to search a named area, filter on the Area name instead.")
    for name in re.findall(r"\ball\s*\(\s*\w+\s+IN\s+\$(\w+)", cypher, flags=re.IGNORECASE):
        value = parameters.get(name)
        if isinstance(value, list) and any(isinstance(item, list) for item in value):
            issues.append(f"${name} is a list of word lists. For several places use "
                          f"any(words IN ${name} WHERE all(word IN words WHERE label CONTAINS word)).")
    return issues


def repair_cypher(cypher: str) -> str:
    cypher = re.sub(r"(?<=[A-Za-z])''(?=[A-Za-z])", r"\\'", cypher)
    cypher = re.sub(r"\s+NULLS\s+(?:LAST|FIRST)\b", "", cypher, flags=re.IGNORECASE)
    cypher = _nulls_last(cypher)
    cypher = _bounded_limit(cypher)
    cypher = _without_junk_patterns(cypher)
    cypher = _apostrophe_free_labels(cypher)
    required = required_optional_matches(cypher)
    if required != cypher:
        kg_debug("Cypher repaired (OPTIONAL MATCH with a filter became MATCH)", required)
        cypher = required
    if not (returns_restaurants(cypher) and order_by_issues(cypher)):
        return cypher
    *head, final = re.split(r"(\bRETURN\b)", cypher, flags=re.IGNORECASE)
    if re.search(r"\b(?:count|collect|avg|sum|min|max)\s*\(", final, flags=re.IGNORECASE):
        return cypher
    repaired = "".join(head) + re.sub(r"^\s*DISTINCT\b", "", final, count=1, flags=re.IGNORECASE)
    kg_debug("Cypher repaired (removed RETURN DISTINCT)", repaired)
    return repaired


# Junk the model leaves on a pattern ("-[]-()"), which silently removes rows.
JUNK_PATTERN = re.compile(r"\s*<?-\[\s*:?\s*\??\s*\]-?>?\s*\(\s*\)|\s*-\[:\w*\]\?<?-\(\s*\)")
DOUBLED_VARIABLE = re.compile(r"\b([A-Za-z_]\w*)\s+\1(?=\s+(?:RETURN|WITH|ORDER|WHERE|MATCH|OPTIONAL|UNWIND)\b)")


REPEATED_RELATIONSHIP = re.compile(r"(-\[:(\w+)\]->?\([^()]*\))\s*<?-\[:\2\]->?\(\s*\)")


def _without_junk_patterns(cypher: str) -> str:
    cypher = REPEATED_RELATIONSHIP.sub(r"\1", JUNK_PATTERN.sub("", cypher))
    return DOUBLED_VARIABLE.sub(r"\1", cypher)


NAME_LABEL = re.compile(r"toLower\(\s*(\w+\.name\s*\+\s*' '\s*\+\s*coalesce\(\s*\w+\.name\s*,\s*''\s*\))\s*\)")
APOSTROPHES = ("'", "\u2019", " ")


def _apostrophe_free_labels(cypher: str) -> str:
    return NAME_LABEL.sub(
        lambda m: f"toLower(replace(replace(replace({m.group(1)}, \"'\", ''), '\u2019', ''), ' ', ''))", cypher)


LABEL_WORDS = re.compile(r"\b\w+\s+IN\s+\$(\w+)\s+WHERE\s+(?:label\s+CONTAINS|all\s*\()", re.IGNORECASE)


def _apostrophe_free_words(parameters: dict[str, Any], cypher: str) -> dict[str, Any]:
    names = set(LABEL_WORDS.findall(cypher))

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            for mark in APOSTROPHES:
                value = value.replace(mark, "")
            return value
        return [clean(item) for item in value] if isinstance(value, list) else value
    return {name: clean(value) if name in names and isinstance(value, list) else value
            for name, value in parameters.items()}


# `ORDER BY rt.rating_score DESC` puts places without a rating first in Neo4j; coalesce puts them last.
def _nulls_last(cypher: str) -> str:
    def fix(match: re.Match) -> str:
        items = re.split(r",(?![^()]*\))", match.group(2))
        fixed = [re.sub(r"^(\s*)([A-Za-z_]\w*\.[A-Za-z_]\w*)(\s+DESC(?:ENDING)?\b)", r"\1coalesce(\2, -1)\3", item,
                        flags=re.IGNORECASE) for item in items]
        return match.group(1) + ",".join(fixed)
    return re.sub(r"(\bORDER\s+BY\b)(.*?)(?=\bLIMIT\b|\bSKIP\b|\bRETURN\b|\bWITH\b|\bMATCH\b|\bOPTIONAL\b|$)",
                  fix, cypher, flags=re.IGNORECASE | re.DOTALL)


def _bounded_limit(cypher: str) -> str:
    maximum = RESTAURANT_LIMIT if returns_restaurants(cypher) else GROUP_LIMIT
    cypher = re.sub(r"\bLIMIT\s+(\d+)\b", lambda m: f"LIMIT {min(int(m.group(1)), maximum)}", cypher,
                    flags=re.IGNORECASE)
    if not re.search(r"\bLIMIT\s+\d+\s*$", cypher, flags=re.IGNORECASE) and \
            not re.search(r"\bLIMIT\b", re.split(r"\bRETURN\b", cypher, flags=re.IGNORECASE)[-1], flags=re.IGNORECASE):
        cypher = f"{cypher.rstrip()}\nLIMIT {maximum}"
    return cypher


def order_by_issues(cypher: str) -> list[str]:
    final = re.split(r"\bRETURN\b", cypher, flags=re.IGNORECASE)[-1]
    parts = re.split(r"\bORDER\s+BY\b", final, maxsplit=1, flags=re.IGNORECASE)
    projection, ordering = parts[0], parts[1] if len(parts) > 1 else ""
    if not ordering:
        return []
    distinct = re.match(r"\s*DISTINCT\b", projection, flags=re.IGNORECASE)
    aggregated = re.search(r"\b(?:count|collect|avg|sum|min|max)\s*\(", projection, flags=re.IGNORECASE)
    if (distinct or aggregated) and re.search(r"\b[A-Za-z_]\w*\.[A-Za-z_]\w*", re.sub(QUOTED, "''", ordering)):
        return ["After RETURN DISTINCT or an aggregation, ORDER BY can only use the returned aliases: "
                "return the value with an alias (for example rt.total_reviews AS reviews) and order by that alias."]
    return []


def limit_issues(cypher: str) -> list[str]:
    restaurants = returns_restaurants(cypher)
    maximum = RESTAURANT_LIMIT if restaurants else GROUP_LIMIT
    too_high = [int(value) for value in re.findall(r"\bLIMIT\s+(\d+)\b", cypher, flags=re.IGNORECASE)
                if int(value) > maximum]
    if not too_high:
        return []
    kind = "restaurants" if restaurants else "rows"
    return [f"Return at most {maximum} {kind}: use LIMIT {RESTAURANT_LIMIT if restaurants else 5} or less."]


def check_cypher(cypher: str, parameters: dict[str, Any]) -> str | None:
    started_at = perf_counter()
    valid, error = validate_cypher(cypher, ontology_graph_schema(), parameters)
    if not valid and re.search(r"\bUNION\b", cypher, flags=re.IGNORECASE):
        error = ("UNION is not allowed. Return one row with several columns instead "
                 "(for example RETURN chains, independents, total).")
    if valid and "`" in cypher:
        valid, error = False, "Do not use backticks: write labels, relationship types and properties as plain names."
    if valid and re.search(r"\bRETURN\s+(?:DISTINCT\s+)?-?\d+(?:\.\d+)?\s*(?:LIMIT\b|$)",
                           re.split(r"(?=\bRETURN\b)", cypher, flags=re.IGNORECASE)[-1], flags=re.IGNORECASE):
        valid, error = False, "RETURN named columns (for example a.name AS area_name, count(r) AS places), not a number."
    if valid and (len(cypher) > MAX_QUERY_LENGTH
                  or len(re.findall(r"\bMATCH\b", cypher, re.IGNORECASE)) > MAX_MATCH_CLAUSES):
        valid, error = False, "The query exceeds the allowed complexity."
    if valid:
        issues = (limit_issues(cypher) + order_by_issues(cypher) + optional_match_filter_issues(cypher)
                  + vocabulary_issues(cypher, parameters) + aggregate_issues(cypher) + undirected_pattern_issues(cypher)
                  + parameter_issues(cypher, parameters))
        if issues:
            valid, error = False, " ".join(issues)
    log_timing("cypher.validation", started_at, status="success" if valid else "invalid")
    return None if valid else error


QUOTED = r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\""
CLAUSE = re.compile(r"\b(OPTIONAL\s+MATCH|MATCH|WHERE|WITH|RETURN|UNWIND|ORDER\s+BY|LIMIT|SKIP)\b", re.IGNORECASE)


# A WHERE after OPTIONAL MATCH that mentions earlier variables never removes rows: the condition is silently ignored.
def optional_match_filter_issues(cypher: str) -> list[str]:
    return [f"The WHERE after OPTIONAL MATCH mentions {', '.join(earlier)}, which an earlier clause matched; "
            "it will not remove any rows. Move that condition to a WHERE after MATCH or WITH."
            for _, earlier in _filtering_optional_matches(cypher)]


def required_optional_matches(cypher: str) -> str:
    starts = {start for start, _ in _filtering_optional_matches(cypher)} | set(_unused_optional_filters(cypher))
    for start in sorted(starts, reverse=True):
        cypher = cypher[:start] + re.sub(r"^OPTIONAL\s+", "", cypher[start:], flags=re.IGNORECASE)
    return cypher


def _unused_optional_filters(cypher: str) -> list[int]:
    text = re.sub(QUOTED, lambda match: "'" + " " * (len(match.group()) - 2) + "'", cypher)
    keywords = list(CLAUSE.finditer(text))
    bound: set[str] = set()
    found = []
    for index, match in enumerate(keywords):
        keyword = " ".join(match.group(1).upper().split())
        body = text[match.end():keywords[index + 1].start() if index + 1 < len(keywords) else len(text)]
        if keyword in {"MATCH", "OPTIONAL MATCH"}:
            names = set(re.findall(r"[(\[]\s*([A-Za-z_]\w*)", body))
            introduced = names - bound
            bound |= names
            following = keywords[index + 1] if index + 1 < len(keywords) else None
            if keyword == "OPTIONAL MATCH" and introduced and following and following.group(1).upper() == "WHERE":
                where_end = keywords[index + 2].start() if index + 2 < len(keywords) else len(text)
                condition, rest = text[following.end():where_end], text[where_end:]
                if any(re.search(rf"\b{name}\b", condition) for name in introduced) and \
                        not any(re.search(rf"\b{name}\b", rest) for name in introduced):
                    found.append(match.start())
        elif keyword in {"WITH", "UNWIND"}:
            bound |= set(re.findall(r"\bAS\s+([A-Za-z_]\w*)", body, flags=re.IGNORECASE))
    return found


def _filtering_optional_matches(cypher: str) -> list[tuple[int, list[str]]]:
    text = re.sub(QUOTED, lambda match: "'" + " " * (len(match.group()) - 2) + "'", cypher)
    keywords = list(CLAUSE.finditer(text))
    bound: set[str] = set()
    found = []
    previous, previous_start, introduced = "", 0, set()
    for index, match in enumerate(keywords):
        keyword = " ".join(match.group(1).upper().split())
        body = text[match.end():keywords[index + 1].start() if index + 1 < len(keywords) else len(text)]
        if keyword in {"MATCH", "OPTIONAL MATCH"}:
            names = set(re.findall(r"[(\[]\s*([A-Za-z_]\w*)", body))
            introduced = names - bound
            bound |= names
        elif keyword == "WHERE" and previous == "OPTIONAL MATCH":
            mentioned = set(re.findall(r"\b([A-Za-z_]\w*)\s*\.", body)) | set(
                re.findall(r"\b([A-Za-z_]\w*)\s+IS\s+(?:NOT\s+)?NULL\b", body, flags=re.IGNORECASE))
            earlier = sorted(name for name in mentioned & bound if name not in introduced)
            if earlier:
                found.append((previous_start, earlier))
        elif keyword in {"WITH", "UNWIND"}:
            bound |= set(re.findall(r"\bAS\s+([A-Za-z_]\w*)", body, flags=re.IGNORECASE))
        if keyword != "WHERE":
            previous, previous_start = keyword, match.start()
    return found


def vocabulary_issues(cypher: str, parameters: dict[str, Any]) -> list[str]:
    bindings = vocabulary_bindings()
    variables = dict(re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)", cypher))
    used: list[tuple[str, str, Any]] = []

    def add(variable: str, prop: str, value: Any) -> None:
        label = variables.get(variable)
        if label and (label, prop) in bindings:
            used.append((label, prop, value))

    def literals(text: str) -> list[str]:
        return [a if a else b for a, b in re.findall(QUOTED, text)]

    for variable, prop, single, double in re.findall(
            rf"\b(\w+)\.(\w+)\s*(?:=|<>)\s*(?:{QUOTED})", cypher):
        add(variable, prop, single or double)
    for variable, prop, items in re.findall(r"\b(\w+)\.(\w+)\s+IN\s+\[([^\]]*)\]", cypher, flags=re.IGNORECASE):
        for value in literals(items):
            add(variable, prop, value)
    for variable, prop, name in re.findall(r"\b(\w+)\.(\w+)\s*(?:=|<>|\bIN\b)\s*\$(\w+)", cypher, flags=re.IGNORECASE):
        add(variable, prop, parameters.get(name))
    for single, double, variable, prop in re.findall(
            rf"(?:{QUOTED})\s+IN\s+split\(\s*(\w+)\.(\w+)", cypher, flags=re.IGNORECASE):
        add(variable, prop, single or double)
    for name, variable, prop in re.findall(r"\$(\w+)\s+IN\s+split\(\s*(\w+)\.(\w+)", cypher, flags=re.IGNORECASE):
        add(variable, prop, parameters.get(name))
    for variable, label, body in re.findall(r"\(\s*(\w*)\s*:\s*(\w+)\s*\{([^}]*)\}", cypher):
        for prop, single, double, name in re.findall(rf"(\w+)\s*:\s*(?:(?:{QUOTED})|\$(\w+))", body):
            if (label, prop) in bindings:
                used.append((label, prop, parameters.get(name) if name else single or double))

    issues = []
    for label, prop, value in used:
        column = bindings[(label, prop)]
        allowed = allowed_values(column)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and item not in allowed:
                issues.append(f"{label}.{prop} has no value '{item}'. Allowed values: "
                              + ", ".join(f"'{v}'" for v in sorted(allowed)) + ". If the user asked for something "
                              "that is not in this list, do not use another value instead: use action decline.")
    return list(dict.fromkeys(issues))

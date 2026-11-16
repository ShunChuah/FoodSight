# Schema-aware Cypher generation: question -> one LLM call -> checked Cypher.
# The model's query is untrusted: check_cypher() must accept it before it runs.

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any

from ...contracts import QueryPlan
from ..shared.cache import QUERY_REPLIES
from ..shared.config import app_timezone, policy
from ..shared.diagnostics import kg_debug, log_timing
from ..shared.llm import LLMServiceError, call_llm, parse_json_object
from .cypher_validation import GraphSchema, SchemaRelationship, validate_cypher
from .proximity import coordinates_from_context, default_radius, explicit_radius_meters

RESTAURANT_DETAILS_FIELD = "restaurant_details"
MIN_GENERATION_SECONDS = 2.5
RESERVED_AFTER_GENERATION_SECONDS = 2.5
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
    "PriceRange.avg_meal_price": "lowest p.avg_meal_price (PriceRange)",
    "Location.distance_m": "shortest distance_m (needs the user's position or a named starting place)",
}

ACTIONS = ("query", "clarify", "explain", "decline")
MAX_OPTIONS = 4
RECOMMENDATION = policy("recommendation")
STUDY_OBJECTIVES = ["balanced", *policy("market_study")["objectives"]]
PRICE_POSITIONS = ["none", "budget", "mid", "premium"]
ANSWER_SHAPES = ("list", "pick_one")
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
RANKING_CHOICES = ("relevance", "rating", "popularity", "price", "distance")
# The intent used when a reply has none.
INTENT_DEFAULTS = {"category": "none", "preferences": [], "budget": False, "location_study": False, "areas": [],
                   "objective": "balanced", "price_position": "none", "meal": False, "answer": "list",
                   "day": "today", "time": "", "ranking": "relevance", "best": False, "target_price": 0,
                   "customer_focus": False}

# What a restaurant search is after, named by the model so the app can rank by it.
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": [*RECOMMENDATION["categories"], "none"]},
        "preferences": {"type": "array", "items": {"type": "string", "enum": list(RECOMMENDATION["preferences"])}},
        "budget": {"type": "boolean"},
        "location_study": {"type": "boolean"},
        "areas": {"type": "array", "items": {"type": "string"}},
        "objective": {"type": "string", "enum": STUDY_OBJECTIVES},
        "price_position": {"type": "string", "enum": PRICE_POSITIONS},
        "meal": {"type": "boolean"},
        "answer": {"type": "string", "enum": list(ANSWER_SHAPES)},
        "day": {"type": "string", "enum": ["today", *WEEKDAY_NAMES]},
        "time": {"type": "string"},
        "ranking": {"type": "string", "enum": list(RANKING_CHOICES)},
        "best": {"type": "boolean"},
        "target_price": {"type": "number"},
        "customer_focus": {"type": "boolean"},
    },
    "required": ["category", "preferences", "budget", "location_study", "areas", "objective", "price_position",
                 "meal", "answer", "day", "time", "ranking", "best", "target_price", "customer_focus"],
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "details": {"type": "boolean"},
        "business": {"type": "boolean"},
        "intent": INTENT_SCHEMA,
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
    "required": ["action", "details", "business", "intent", "reply", "options", "cypher", "parameters"],
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
NO_TITLE_RULE = "This chat already has a title: set chat_title to \"\"."

# Fixed prompt text, identical for every question so the provider can cache it.
TASK = """You turn one question about food and drink places in Petaling Jaya into one read-only Neo4j 5 Cypher query.
Use only the graph described below. Read the vocabularies carefully: filters on a categorical property must use its exact values."""

OUTPUT_RULES = """# Writing the Cypher
- Every value taken from the user (names, words, numbers) goes in parameters and is referenced as $name. Vocabulary
  values may be written inline as quoted strings.
- Every condition goes in a WHERE right after a MATCH or a WITH, or in a MATCH pattern.
- avg(), sum(), min(), max() and count() aggregate over rows and skip nulls; never pass them a list. After RETURN
  DISTINCT or an aggregation, ORDER BY may only use the returned aliases. Several groups come from one query, one row
  per group; never UNION.
- A restaurant the user names rarely matches the stored name exactly ("ZUS Coffee SS2" is stored as "ZUS Coffee -
  SS2, Petaling Jaya"). Match it word by word against the name and area together:
  WITH r, toLower(r.name + ' ' + coalesce(a.name, '')) AS label WHERE all(word IN $name_words WHERE label CONTAINS word),
  with $name_words the name in lowercase words (leave out "the", "restaurant", "restoran" and "cafe" unless they are
  the only words). For several named places use $places, a list of word lists, with any(words IN $places ...).
- A dish (roti canai, char kuey teow): menus are not recorded. Match the cuisine whose Covers list names it or the
  restaurant name: WHERE EXISTS {{ MATCH (r)-[:SERVES]->(:Cuisine {{name: 'Indian Muslim'}}) }} OR
  toLower(r.name) CONTAINS $dish.
- Meanings: popular or famous = most reviews. Hidden gems = rating_score of at least 4.5 with 20 to 300 reviews.
  Competition in an area or cuisine = places of the same kind there; COMPETES_WITH only when the user names one
  restaurant.
- Location studies (location_study true): return only the concept's direct competitors, every active restaurant
  matching its cuisine, kind and halal requirement, as RETURN DISTINCT r.restaurant_id AS restaurant_id with no ORDER
  BY and LIMIT 5 (the app reads them all and compares the areas itself). Never use Area, counts, shares or price,
  customer or atmosphere filters for these, even for one named area.
- Other business questions (competition, gaps, shares, segments) return area or group rows of counts, shares and
  averages, not lists of places. Match every active restaurant first and count the kind with
  count(DISTINCT CASE WHEN ... THEN r END) in the same WITH, so totals, shares and zero counts are right; a cuisine is
  CASE WHEN EXISTS {{ (r)-[:SERVES]->(:Cuisine {{name: 'Thai'}}) }}. Saturated or crowded: compare the area's share
  with PJ's, returning PJ's own figures under the same aliases with a pj_ prefix (cafes and pj_cafes). Cuisines
  missing from an area: start from (c:Cuisine) and OPTIONAL MATCH the restaurants. Pricing a planned outlet: one row
  with its competitors' count and lowest, average and highest price there, the area's average price and the kind's
  average across PJ. Areas ranked by an average need at least 10 restaurants. Areas the user names: only those, one
  row each. Sentiment over time: count each sentiment per period.
- What people say, praise or complain about: query Review and return r.name AS restaurant, v.sentiment AS
  sentiment, v.individual_rating AS stars, left(v.text, 300) AS review, up to 10 rows. Never return author_name.

# Choosing the action
Write every reply as a friendly local food guide in plain English, whatever language the user writes in: never
mention vocabularies, datasets, properties, queries or the graph. A field an action does not use is "" or [].
- query (the usual action): the Cypher goes in cypher, never in reply. A vague word with a sensible default needs
  no question: use the default. details is true only when the user asks about one restaurant they named or referred
  to (more about it, its hours, phone, address, halal status or booking); then return only r.restaurant_id, since
  the app adds everything else. business is true when the user asks as an owner, operator or analyst (opening or
  running a place, competitors, pricing, market research), also in a follow-up; a plain count with no business
  context ("how many Korean restaurants are in Uptown?") is a diner's question.
- clarify: only when the request can mean clearly different things, no default is safe and the answers would differ
  a lot ("BBQ" could be cooking at the table or barbecued dishes), when it asks for things one place cannot all be
  (cheap and expensive at once; "Japanese Chinese" with no "and" or "or"), or when a business question is about
  the user's own place and you cannot identify it. A restaurant or brand the user names, with or without its area,
  is never a reason to ask: query it with details true. reply is one short question that names the choices in plain
  words ("Do you mean cheap eats, fine dining or one of each?"), never lettered or numbered. options are 2 to
  {max_options} short answers the user can tap (2 to 5 words, no brackets), one for every sensible reading on its own
  and any mix of them, each leading to a different search ("Cheap eats", "Fine dining", "One of each"). Ask at most one
  question, and never for something already said, answered, or the user's position when it is available.
- explain: a general food or drink question needing no particular place (what a dish is, a kopitiam versus a
  mamak): reply in at most 80 words, naming no places. Questions about places, reviews or numbers in Petaling Jaya
  are always queries.
- decline: the question is not about food and drink, or needs information that is not recorded. A value missing from
  a vocabulary (Wi-Fi, a drive-through) is never replaced by another one: decline. reply is one friendly sentence; for
  a business question add what you can compare instead. options may offer up to {max_options} food and drink requests
  you can answer instead, or [] when the question is not about food or drink.
- A place clearly outside Petaling Jaya (Kuala Lumpur city centre, Subang Jaya, Shah Alam): decline, say you cover
  Petaling Jaya only, and offer the request in nearby Petaling Jaya areas as options ("Nasi lemak in SS 2"). Never
  search such a place as an Area.
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


NOT_SHOWN = "Not in chatbot_schema.json."


@lru_cache(maxsize=1)
def load_chatbot_schema() -> dict:
    path = ontology_path().parent / os.getenv("CHATBOT_SCHEMA_FILE", "chatbot_schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_vocabulary() -> dict:
    source = ontology_path().parent / load_chatbot_schema()["vocabulary_source"]
    return json.loads(source.read_text(encoding="utf-8"))


# ontology.json (the data pipeline's structure) merged with chatbot_schema.json (what the query model is shown).
@lru_cache(maxsize=1)
def load_ontology() -> dict:
    structure = json.loads(ontology_path().read_text(encoding="utf-8"))
    return merge_schema(structure, load_chatbot_schema(), load_vocabulary()["columns"])


# Anything chatbot_schema.json does not list is hidden; a vocabulary defaults to the column <table>.<property>.
def merge_schema(structure: dict, chatbot: dict, columns: dict) -> dict:
    unknown = [label for label in chatbot["nodes"] if label not in structure["nodes"]]
    unknown += [name for name in chatbot["relationships"] if name not in structure["relationships"]]
    nodes = {}
    for label, node in structure["nodes"].items():
        described = chatbot["nodes"].get(label)
        names = [node["key"], *node["properties"], *node.get("points", {}), *node.get("derived", {})]
        specs = (described or {}).get("properties", {})
        unknown += [f"{label}.{name}" for name in specs if name not in names]
        properties = {}
        for name in names:
            spec = dict(specs.get(name) or {"hide_from_prompt": NOT_SHOWN})
            if "vocabulary" not in spec and f"{node.get('table')}.{name}" in columns:
                spec["vocabulary"] = f"{node['table']}.{name}"
            properties[name] = spec
        extra = {"description": described["description"]} if described and described.get("description") else {}
        nodes[label] = {**node, **extra, **({} if described else {"hide_from_prompt": NOT_SHOWN}),
                        "properties": properties}
    if unknown:
        raise ValueError(f"chatbot_schema.json names what ontology.json does not have: {', '.join(unknown)}")
    relationships = {name: {**rel, **chatbot["relationships"].get(name, {"hide_from_prompt": NOT_SHOWN})}
                     for name, rel in structure["relationships"].items()}
    rules = {key: value for key, value in chatbot.items() if key not in ("description", "nodes", "relationships")}
    return {**rules, "nodes": nodes, "relationships": relationships}


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
        if rel.get("undirected"):
            relationships.append(SchemaRelationship(rel["to"], name, rel["from"]))
    return GraphSchema(nodes=nodes, relationships=relationships)


def relationship_pattern(name: str, rel: dict) -> str:
    return f"(:{rel['from']})-[:{name}]-{'' if rel.get('undirected') else '>'}(:{rel['to']})"


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


# PJ stores sections in Malay: "Section 17" is "Seksyen 17"; SS, PJU and PJS stay as written.
SECTION = re.compile(r"\b(?:section|sec\.?|seksyen)\s*\??\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)


def normalise_area_patterns(cypher: str, parameters: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(parameters)
    for name in [*re.findall(r"=~\s*\$(\w+)", cypher),
                 *re.findall(r"CONTAINS\s+(?:toLower\(\s*)?\$(\w+)", cypher, flags=re.IGNORECASE)]:
        if isinstance(parameters.get(name), str):
            parameters[name] = SECTION.sub(r"Seksyen \1", parameters[name])
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


# Cuisine nodes hold source labels; each counts as the categories.json value whose Covers list names it.
CUISINE_NAMES, CUISINE_CATEGORIES = "cuisine_names", "cuisine_categories"
CUISINE_MAP = re.compile(r"\(\s*(\w*)\s*:\s*Cuisine\s*\{([^}]*)\}\s*\)")
MAP_ENTRY = re.compile(r"(\w+)\s*:\s*('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\$\w+|[^,]+)")
PATH_START = re.compile(r"\(\s*\w+\s*(?::\s*\w+\s*)?\)\s*<?-\s*\[[^\]]*\]\s*->?\s*$")
SUBQUERY = re.compile(r"\b(?:EXISTS|COUNT|COLLECT)\s*\{", re.IGNORECASE)


@lru_cache(maxsize=1)
def cuisine_labels() -> dict[str, dict[str, str]]:
    names, categories = {}, {}
    for value, detail in load_vocabulary()["columns"]["cuisine.name"]["values"].items():
        for label in (value, *detail.get("includes", [])):
            names.setdefault(label.lower(), value)
            categories.setdefault(label.lower(), detail.get("category"))
    return {CUISINE_NAMES: names, CUISINE_CATEGORIES: categories}


def translate_cuisines(cypher: str, parameters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not re.search(r":\s*Cuisine\b", cypher):
        return cypher, parameters
    parts, done = [], 0
    for number, match in enumerate(CUISINE_MAP.finditer(cypher), 1):
        before = cypher[:match.start()]
        clauses = [" ".join(m.group(1).upper().split()) for m in CLAUSE.finditer(before)]
        subquery = max((m.end() for m in SUBQUERY.finditer(before)), default=-1) > before.rfind("}")
        # Only a MATCH pattern may name a new node; elsewhere a pattern is wrapped in EXISTS { MATCH ... }.
        expression = not subquery and (not clauses or clauses[-1] not in ("MATCH", "OPTIONAL MATCH"))
        path = PATH_START.search(before) if expression else None
        if expression and not path:
            continue
        variable = match.group(1) or f"cuisine_{number}"
        conditions = " AND ".join(f"{variable}.{prop} = {value.strip()}" for prop, value in MAP_ENTRY.findall(match.group(2)))
        node = f"({variable}:Cuisine WHERE {conditions})"
        parts += [cypher[done:path.start() if path else match.start()],
                  f"EXISTS {{ MATCH {path.group(0)}{node} }}" if path else node]
        done = match.end()
    rewritten = "".join(parts) + cypher[done:]
    variables = set(re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*Cuisine\b", rewritten))
    if not variables:
        return rewritten, parameters
    names = "|".join(map(re.escape, variables))
    rewritten = re.sub(rf"\b({names})\.(name|category)\b", lambda m: (
        f"coalesce(${CUISINE_NAMES if m.group(2) == 'name' else CUISINE_CATEGORIES}[toLower({m.group(1)}.name)], "
        f"{m.group(1)}.{m.group(2)})"), rewritten)
    return rewritten, {**parameters, **cuisine_labels()}


@lru_cache(maxsize=1)
def schema_prompt() -> str:
    ontology = load_ontology()
    columns = load_vocabulary()["columns"]
    lines = [TASK, "", "# Context"]
    lines += [f"- {key.replace('_', ' ')}: {value}" for key, value in ontology["meta"].items()]

    lines += ["", "# Nodes"]
    for label, node in ontology["nodes"].items():
        if node.get("hide_from_prompt"):
            continue
        lines.append(f"## {label}: {node.get('description', '')}".rstrip(": "))
        for prop, spec in node["properties"].items():
            if not spec.get("hide_from_prompt"):
                lines.append("- " + _property_line(prop, spec, columns, node))

    lines += ["", "# Relationships (use exactly these directions)"]
    for name, rel in ontology["relationships"].items():
        if name not in hidden_relationships():
            extra = f" Properties: {', '.join(rel['properties'])}." if rel.get("properties") else ""
            lines.append(f"- {relationship_pattern(name, rel)} [{rel['cardinality']}] {rel['description']}{extra}")

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
            if example.get("intent"):
                lines.append("intent: " + json.dumps(example["intent"], ensure_ascii=False))
            lines.append(f"Parameters: {json.dumps(example.get('parameters') or {}, ensure_ascii=False)}")
            lines.append("Cypher:\n" + example["cypher"])
    return "\n".join(lines)


def defaults_prompt() -> str:
    proximity, results = policy("proximity"), policy("results")
    venues = ", ".join(f"{venue} {_km(radius)}" for venue, radius in proximity["venue_radius_meters"].items())
    nearest = proximity["modes"]["nearest_search"]["default_limit"]
    preferences = "; ".join(f"{name} ({', '.join(entry['terms'][:3])})"
                            for name, entry in RECOMMENDATION["preferences"].items())
    lines = [
        "# Requirements go in the Cypher, wishes go in intent",
        "- The Cypher keeps only what the user requires: a named area, place or distance, a cuisine or dish, a kind of "
        "place they name, halal (only when they ask for halal, Muslim-friendly or no pork), a price they give as a "
        "number, and a facility, atmosphere or customer group they make a must (\"must have a kids menu\", \"only with "
        "outdoor seating\"). Everything else is a wish and goes in intent: moods and occasions, cheap or premium "
        "without a number, best or popular, opening times and the day. The app ranks by the wishes, checks opening "
        "hours and keeps meal places itself, so never write them as Cypher conditions. A long message still gets one "
        "short query for its main question.",
        "",
        "# intent (fields that do not apply keep these defaults: category none, preferences [], budget false, "
        "location_study false, areas [], objective balanced, price_position none, meal false, answer list, day today, "
        "time \"\", ranking relevance, best false, target_price 0, customer_focus false)",
        "Read every field from the whole question and the conversation, in any wording or language.",
        "- category: a kind of place the user names (" + ", ".join(RECOMMENDATION["categories"]) + "); none for "
        "restaurants, food or places in general. preferences: moods, occasions and who it suits, only those the user "
        "mentions, from " + preferences + ".",
        "- budget: true for cheap or affordable. meal: true when they want a proper meal (eat, food, hungry, makan, "
        "lunch, dinner, a restaurant), false when they also or only want drinks, desserts, snacks or pastries; for a "
        "business, true when the concept serves meals.",
        "- time: \"\" unless they ask about opening times, since it removes places closed then: \"now\" for open now, "
        "\"late\" for supper or late night, their time as HH:MM (\"after 10pm\" = \"22:00\"), \"later\" for a meal or "
        "part of the day that is not now (breakfast, dinner, tonight). day: today unless they name another day, worked "
        "out from today's weekday given with the question.",
        "- ranking: rating for top or highest rated, popularity for most popular or famous, price for cheapest, distance "
        "for nearest or closest, otherwise relevance (also for best, good and near me). best: true when they want the "
        "best or top places.",
        f"- answer: pick_one when they want one place chosen from places already shown (which is cheapest, which one "
        f"is closest); otherwise list. For pick_one, return all those places by the restaurant_id values in the "
        f"conversation (never ids from the examples), in the order asked, LIMIT {RESTAURANT_LIMIT}.",
        "- location_study: true when they ask where to open an F&B outlet, which area suits a concept, has the least "
        "competition or the strongest market for it, or whether named areas suit it. Then areas are the areas they "
        "named as written ([] for all of PJ); objective is exposure (more customers, visibility), low_competition or "
        "strongest_market, otherwise balanced; price_position is budget, mid or premium when they say so; "
        "target_price is the price per person they name (RM15 = 15); customer_focus is true when they name who the "
        "outlet is for.",
        "",
        "# Locations",
        f"- Near the user or a restaurant they named, with no distance given: WHERE distance_m <= ${DEFAULT_RADIUS} (the "
        f"app sets it: near me {_km(proximity['default_radius_meters'])}, {venues}, walking distance "
        f"{_km(proximity['walking_radius_meters'])}, delivery {_km(proximity['delivery_radius_meters'])}). A distance "
        f"the user gives: $radius_m. Nearest or closest: ORDER BY distance_m, LIMIT {nearest}, no radius. A search in "
        "an area or in all of Petaling Jaya has no distance.",
        "- Near a named mall, school, university, hospital, hotel or office: (r)-[n:NEAR]->(np:NearbyPlace) WHERE "
        "toLower(np.name) CONTAINS toLower($place), nearest first by n.distance_m. Near a named train station: "
        "(r)-[s:NEAREST_STATION]->(st:NearbyPlace) WHERE toLower(st.name) CONTAINS toLower($place) AND s.distance_m "
        f"<= ${DEFAULT_RADIUS}. Any other landmark has no pin: match restaurants whose name or area contains it, with "
        "the spellings people use (1 Utama: '1 utama', '1utama', 'bandar utama').",
        f"- Never put ${DEFAULT_RADIUS} or ${DEFAULT_MIN_REVIEWS} in parameters: the app sets them.",
        "",
        "# Results",
        f"- Restaurants: one row each, r.restaurant_id AS restaurant_id plus only values you computed (distance_m, a "
        f"count, t.name AS competitor_of); the app adds names, ratings, prices, hours and the rest. LIMIT "
        f"{results['discovery_limit']}, {results['default_limit']} for a few, or the number asked up to "
        f"{RESTAURANT_LIMIT}. Order by rt.rating_score unless the user asks for another order.",
        f"- Areas or other groups: a.name AS area_name (or the group value) plus counts or averages with short "
        f"aliases, LIMIT 5, or the number asked up to {GROUP_LIMIT}.",
    ]
    return "\n".join(lines)


def _km(metres: int | float) -> str:
    return f"{metres / 1000:g} km" if metres >= 1000 else f"{metres:g} m"


DEFINED_VOCABULARIES = {"price_range.tier", "business_profile.halal_status"}


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def _property_line(prop: str, spec: dict, columns: dict, node: dict) -> str:
    facts = [spec["type"]]
    if prop == node.get("key"):
        facts.append("unique")
    elif prop not in node.get("required", []) and prop not in node.get("derived", {}):
        facts.append("nullable")
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
    line += f"\n  Vocabulary {column}: {_first_sentence(col['meaning'])}"
    values = col["values"]
    if column not in DEFINED_VOCABULARIES and not any(isinstance(d, dict) and d.get("includes") for d in values.values()):
        return line + "\n    " + ", ".join(f"'{value}'" for value in values)
    for value, detail in values.items():
        line += f"\n    '{value}'"
        if column in DEFINED_VOCABULARIES:
            line += f": {detail if isinstance(detail, str) else detail.get('definition', '')}"
        includes = detail.get("includes") if isinstance(detail, dict) else None
        if includes:
            line += f" Covers: {', '.join(includes)}."
    return line


# Questions that read like "where should I open ..." get a reminder of the short competitor query, so the first
# attempt is right; long business briefs otherwise tend to come back as one large aggregate query.
LOCATION_STUDY = re.compile(
    r"\b(?:where (?:should|can|could|do|would) (?:i|we) (?:open|start|set up|put)"
    r"|which (?:area|location|part of pj)s? (?:is|would|should|offers?|suits?|has the (?:least|fewest|lowest) compet)"
    r"|(?:best|good|right) (?:area|location|spot) (?:to|for)|least competition|(?:fewer|less|fewest) competit"
    r"|strongest .{0,30}market|suitable for (?:a|an|my|our)\b|open(?:ing)? (?:a|an|my|our|first|new)\b"
    r".{0,80}\b(?:cafe|café|restaurant|shop|stall|outlet|kiosk|bakery|eatery))",
    re.IGNORECASE)
# "Who would I compete with if I open ..." asks for the competitors themselves, not an area comparison.
COMPETITOR_LIST = re.compile(r"\bwho (?:would|will|do|does|should) (?:i|we) compete\b|\bcompete with\b", re.IGNORECASE)
# "Is SS2 saturated with cafes?", "how many ..." or "what share ...": the figures of an area, not a comparison of areas.
AREA_FIGURES = re.compile(r"\b(?:saturated|crowded|oversupplied|how many|what share|what percentage|proportion of)\b",
                          re.IGNORECASE)
NOT_LOCATION_STUDY_HINT = (
    "This is not a location study: set intent location_study false and answer it as one of the other business "
    "questions, with the competitors as a list of places, or the area's counts and shares with PJ's own figures "
    "alongside.")
LOCATION_STUDY_HINT = (
    "This reads like a location study: set intent location_study true and return only the concept's direct "
    "competitors, filtered on hard requirements (cuisine, kind of place, halal), never on customers, price, "
    "atmosphere or area. Everything else in the message goes in intent.")


def question_prompt(
    question: str,
    conversation_context: str,
    location_context: str,
    previous: tuple[str, str] | None = None,
    want_title: bool = False,
    may_clarify: bool = True,
    chat_state: str = "",
) -> str:
    parts = []
    if conversation_context and conversation_context != "No previous conversation.":
        parts.append("Previous conversation (use it to resolve follow-ups such as 'what about halal ones?'):\n"
                     + conversation_context)
    if chat_state:
        parts.append(chat_state)
    area = re.search(r"^User location area:\s*(.+)$", location_context or "", flags=re.IGNORECASE | re.MULTILINE)
    if coordinates_from_context(location_context):
        parts.append("The user's position is available as $latitude and $longitude (WGS84). "
                     "Use it for 'near me' or distance questions.")
    elif area:
        parts.append(f"The user said they are in or near this area: {area.group(1).strip()}")
    else:
        parts.append("The user's position is not available: never use $latitude, $longitude or a distance filter.")
    # The day only, so a cached reply lasts the whole day.
    parts.append(f"Today is {WEEKDAY_NAMES[datetime.now(app_timezone()).weekday()].capitalize()}.")
    parts.append(f"Question: {question}")
    if COMPETITOR_LIST.search(question) or AREA_FIGURES.search(question):
        parts.append(NOT_LOCATION_STUDY_HINT)
    elif LOCATION_STUDY.search(question):
        parts.append(LOCATION_STUDY_HINT)
    if not may_clarify:
        parts.append(NO_SECOND_QUESTION)
    parts.append(TITLE_RULE if want_title else NO_TITLE_RULE)
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
    chat_state: str = "",
) -> CypherResult:
    started_at = perf_counter()
    result = _generate(question, conversation_context, location_context, deadline, previous, want_title, may_clarify,
                       chat_state)
    log_timing("cypher.generation", started_at, status=result.status, retry=bool(previous))
    return result


CACHED_STATUSES = ("success", "clarify", "explain", "cannot_answer")


def _generate(question, conversation_context, location_context, deadline, previous, want_title,
              may_clarify=True, chat_state="") -> CypherResult:
    prompt = question_prompt(question, conversation_context, location_context, previous, want_title, may_clarify,
                             chat_state)
    # Only first attempts are cached: a retry's prompt carries the rejected query.
    raw = QUERY_REPLIES.get(prompt, want_title) if not previous else None
    if raw is None:
        # LLM_QUERY_TIMEOUT_SECONDS caps the call; the answer's deadline can only shorten it.
        timeout = None
        if deadline is not None:
            timeout = deadline - perf_counter() - RESERVED_AFTER_GENERATION_SECONDS
            if timeout < MIN_GENERATION_SECONDS:
                return CypherResult("skipped_deadline")
        try:
            raw = call_llm(prompt, schema_prompt(), task="query", timeout_seconds=timeout,
                           # One response format for every call, so all questions share one prompt cache.
                           response_schema=TITLED_RESPONSE_SCHEMA)
        except LLMServiceError as exc:
            return CypherResult(exc.code or "llm_error", error=str(exc))
        result = _read_reply(raw, question, conversation_context, location_context, want_title)
        if not previous and result.status in CACHED_STATUSES:
            QUERY_REPLIES.set(raw, prompt, want_title)
        return result
    return _read_reply(raw, question, conversation_context, location_context, want_title)


# Choice labels such as "(A)" or "B)" in a clarifying question, or "1." before an option, duplicate the buttons.
OPTION_LABEL = re.compile(r"(?:(?<=\s)|^)(?:\(\s*[A-Da-d1-4]\s*\)|[A-D]\)(?=\s))\s*")
OPTION_PREFIX = re.compile(r"^\s*(?:\(\s*[A-Da-d1-9]\s*\)|[A-Da-d1-9][.)])\s+")


# A button is the short choice: "One of each (1 cheap, 1 expensive)" becomes "One of each".
def _option_text(option: str) -> str:
    text = OPTION_LABEL.sub("", OPTION_PREFIX.sub("", option))
    short = re.sub(r"\s*\([^)]*\)", "", text)
    return " ".join((short if short.strip() else text).split())[:80]


def _read_reply(raw, question, conversation_context, location_context, want_title) -> CypherResult:
    payload = parse_json_object(raw)
    if not payload or not isinstance(payload.get("cypher"), str):
        return CypherResult("invalid_json", error="The model did not return the expected JSON.")
    title = payload.get("chat_title") if want_title and isinstance(payload.get("chat_title"), str) else None
    reply = payload["reply"].strip() if isinstance(payload.get("reply"), str) else ""
    if not payload["cypher"].strip() and re.match(r"(?:OPTIONAL\s+)?MATCH\b", reply, flags=re.IGNORECASE):
        payload["cypher"], reply = reply, ""
    options = tuple(dict.fromkeys(
        text for text in (_option_text(option) for option in payload.get("options") or [] if isinstance(option, str))
        if text))[:MAX_OPTIONS]
    action = payload.get("action") if payload.get("action") in ACTIONS else "query"
    # Only a clarifying question loses its choice labels; an explanation keeps its own wording and line breaks.
    if action == "clarify":
        reply = " ".join(OPTION_LABEL.sub("", reply).split())
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
    repaired = without_contradictions(cypher)
    if repaired != cypher:
        kg_debug("Dropped conditions that can never help", {"before": cypher, "after": repaired})
        cypher = repaired

    if not coordinates and re.search(r"\$(?:latitude|longitude)\b", cypher):
        error = ("The user's position is not available, so $latitude and $longitude cannot be used. "
                 "Search the named area (or all of Petaling Jaya) without distances.")
    else:
        error = check_cypher(cypher, parameters) or contradiction_error(cypher)
    if error:
        kg_debug("Cypher rejected", error)
        return CypherResult("rejected_validation", error=error, cypher=cypher, chat_title=title)
    # Fixed after validation, so the check sees the model's own query.
    parameters = normalise_area_patterns(cypher, parameters)
    details = payload.get("details") is True
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else None
    if normalised_intent(intent)["answer"] == "pick_one":
        cypher = every_shown_place(cypher)
    plan = build_plan(cypher, parameters, details, business=payload.get("business") is True, intent=intent)
    return CypherResult("success", plan=plan, cypher=cypher, chat_title=title,
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
    return _without_unasked_24_7(cypher, question), parameters


TWENTY_FOUR_HOURS = re.compile(r"\b24\s*(?:/\s*7|[- ]?h(?:ou)?rs?\b|h\b)|round[- ]the[- ]clock|all[- ]night|non[- ]?stop",
                               re.IGNORECASE)


def _without_unasked_24_7(cypher: str, question: str) -> str:
    if "is_24_7" not in cypher or TWENTY_FOUR_HOURS.search(question or ""):
        return cypher
    flag = r"\w+\.is_24_7\s*=\s*true\b"
    cypher = re.sub(r"\s*\{\s*is_24_7\s*:\s*true\s*\}|,\s*is_24_7\s*:\s*true\b|\bis_24_7\s*:\s*true\s*,\s*", "", cypher,
                    flags=re.IGNORECASE)
    cypher = re.sub(rf"\bWHERE\s+{flag}\s+AND\s+", "WHERE ", cypher, flags=re.IGNORECASE)
    cypher = re.sub(rf"\s+AND\s+{flag}", "", cypher, flags=re.IGNORECASE)
    return re.sub(rf"\s*\bWHERE\s+{flag}(?!\s*(?:OR|AND)\b)", "", cypher, flags=re.IGNORECASE)


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


def build_plan(cypher: str, parameters: dict[str, Any], details: bool = False, business: bool = False,
               intent: dict[str, Any] | None = None) -> QueryPlan:
    maximum = RESTAURANT_LIMIT if returns_restaurants(cypher) else GROUP_LIMIT
    limits = [int(value) for value in re.findall(r"\bLIMIT\s+(\d+)\b", cypher, flags=re.IGNORECASE)]
    return QueryPlan(
        cypher=cypher, parameters=parameters,
        result_limit=min([maximum, *limits]),
        requested_fields=(RESTAURANT_DETAILS_FIELD,) if details else (),
        business=business,
        intent=normalised_intent(intent),
    )


CLOCK_VALUE = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
# Conditions that can never help: a membership test compared with a boolean, an empty list, always true or false.
CONTRADICTIONS = re.compile(
    r"'[^']*'\s+IN\s+(?:coalesce\([^)]*\)|\[[^\]]*\]|\w+\.\w+)\s*=\s*(?:false|true)\b"
    r"|\)\s*=\s*false\b|\bIN\s*\[\s*\]|\bIS\s+(?:NOT\s+)?NULL\s+OR\s+true\b|\btrue\s*=\s*false\b",
    re.IGNORECASE)


# The same conditions as whole expressions, dropped by the app instead of a second model call.
DROPPABLE = re.compile(
    r"\(\s*[^()]*?\)\s*=\s*false\b"
    r"|'[^']*'\s+IN\s+(?:coalesce\([^)]*\)|\[[^\]]*\]|\w+\.\w+)\s*=\s*(?:false|true)\b"
    r"|(?:'[^']*'|\b\w+(?:\.\w+)?)\s+IN\s*\[\s*\]"
    r"|(?:'[^']*'|\b\w+(?:\.\w+)?)\s+IS\s+(?:NOT\s+)?NULL\s+OR\s+true\b"
    r"|\btrue\s*=\s*false\b",
    re.IGNORECASE)


def without_contradictions(cypher: str) -> str:
    return DROPPABLE.sub("true", cypher)


def contradiction_error(cypher: str) -> str | None:
    found = CONTRADICTIONS.search(cypher)
    if not found:
        return None
    return (f"The condition near \"{found.group(0)}\" can never help: it is always true, always false or tests an "
            "empty list. Leave a preference out of the Cypher (it goes in intent), and write a requirement plainly, "
            "for example 'quiet' IN coalesce(bp.ambiance, []).")
SHOWN_IDS = re.compile(r"\.restaurant_id\s+IN\s+\[([^\]]*)\]", re.IGNORECASE)


# A pick-one query keeps every shown place, so a tie or the true closest is never cut.
def every_shown_place(cypher: str) -> str:
    shown = SHOWN_IDS.search(cypher)
    if not shown:
        return cypher
    count = len([value for value in shown.group(1).split(",") if value.strip()])
    return re.sub(r"\bLIMIT\s+(\d+)\s*$", lambda match: f"LIMIT {max(int(match.group(1)), min(count, RESTAURANT_LIMIT))}",
                  cypher.rstrip(), flags=re.IGNORECASE)


# Every intent field present and valid.
def normalised_intent(intent: dict[str, Any] | None) -> dict[str, Any]:
    intent = {**INTENT_DEFAULTS, **(intent if isinstance(intent, dict) else {})}
    choices = {"answer": ANSWER_SHAPES, "day": ("today", *WEEKDAY_NAMES), "ranking": RANKING_CHOICES}
    for name, allowed in choices.items():
        value = str(intent.get(name) or "").strip().lower()
        intent[name] = value if value in allowed else INTENT_DEFAULTS[name]
    # Today's weekday from the model means today.
    if intent["day"] == WEEKDAY_NAMES[datetime.now(app_timezone()).weekday()]:
        intent["day"] = "today"
    time = str(intent.get("time") or "").strip().lower()
    clock = CLOCK_VALUE.fullmatch(time)
    intent["time"] = (f"{int(clock[1]):02d}:{clock[2]}" if clock else time if time in ("now", "late", "later") else "")
    for name in ("meal", "budget", "location_study", "customer_focus", "best"):
        intent[name] = intent.get(name) is True
    price = intent.get("target_price")
    intent["target_price"] = float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0 else 0
    return intent


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
    cypher = _optional_rating(cypher)
    if not (returns_restaurants(cypher) and order_by_issues(cypher)):
        return cypher
    *head, final = re.split(r"(\bRETURN\b)", cypher, flags=re.IGNORECASE)
    if re.search(r"\b(?:count|collect|avg|sum|min|max)\s*\(", final, flags=re.IGNORECASE):
        return cypher
    repaired = "".join(head) + re.sub(r"^\s*DISTINCT\b", "", final, count=1, flags=re.IGNORECASE)
    kg_debug("Cypher repaired (removed RETURN DISTINCT)", repaired)
    return repaired


RATING_MATCH = re.compile(r"(?<!OPTIONAL )\bMATCH\s+\((\w+)\)-\[:HAS_RATING\]->\((\w+):Rating\)(?=\s)")


# A rating used only to sort or show is optional: a required one silently drops every place without a rating.
def _optional_rating(cypher: str) -> str:
    match = RATING_MATCH.search(cypher)
    if not match or re.search(rf"\b{match[2]}\.\w+\s*(?:>=|<=|<>|=|>|<|IS\b|IN\b)", cypher):
        return cypher
    return cypher[:match.start()] + "OPTIONAL " + cypher[match.start():]


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
        error = ("UNION is not allowed. For figures, return one row with several columns (for example RETURN "
                 "chains, independents, total). For restaurants from two groups, return one row per restaurant: "
                 "WITH tier, collect(r)[0..1] AS picks UNWIND picks AS r RETURN r.restaurant_id AS restaurant_id, "
                 "tier.")
    if valid and "`" in cypher:
        valid, error = False, "Do not use backticks: write labels, relationship types and properties as plain names."
    if valid and re.search(r"::\s*\w", re.sub(QUOTED, "''", cypher)):
        valid, error = False, "Cypher has no :: casts. Compare the value directly (is_24_7 = true) or use toString()."
    if valid and re.search(r"\bRETURN\s+(?:DISTINCT\s+)?-?\d+(?:\.\d+)?\s*(?:LIMIT\b|$)",
                           re.split(r"(?=\bRETURN\b)", cypher, flags=re.IGNORECASE)[-1], flags=re.IGNORECASE):
        valid, error = False, "RETURN named columns (for example a.name AS area_name, count(r) AS places), not a number."
    if valid and (len(cypher) > MAX_QUERY_LENGTH
                  or len(re.findall(r"\bMATCH\b", cypher, re.IGNORECASE)) > MAX_MATCH_CLAUSES):
        valid, error = False, "The query exceeds the allowed complexity."
    if valid:
        issues = (limit_issues(cypher) + order_by_issues(cypher) + optional_match_filter_issues(cypher)
                  + vocabulary_issues(cypher, parameters) + aggregate_issues(cypher) + undirected_pattern_issues(cypher)
                  + parameter_issues(cypher, parameters) + hidden_property_issues(cypher))
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


@lru_cache(maxsize=1)
def hidden_labels() -> set[str]:
    return {label for label, node in load_ontology()["nodes"].items() if node.get("hide_from_prompt")}


@lru_cache(maxsize=1)
def hidden_relationships() -> set[str]:
    return {name for name, rel in load_ontology()["relationships"].items()
            if rel.get("hide_from_prompt") or rel["from"] in hidden_labels() or rel["to"] in hidden_labels()}


@lru_cache(maxsize=1)
def hidden_properties() -> set[tuple[str, str]]:
    return {(label, prop) for label, node in load_ontology()["nodes"].items()
            for prop, spec in node["properties"].items() if spec.get("hide_from_prompt")}


def hidden_property_issues(cypher: str) -> list[str]:
    variables = dict(re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)", cypher))
    used = {(variables.get(variable), prop) for variable, prop in re.findall(r"\b(\w+)\.(\w+)", cypher)}
    used |= {(label, prop) for label, body in re.findall(r"\(\s*\w*\s*:\s*(\w+)\s*\{([^}]*)\}", cypher)
             for prop in re.findall(r"(\w+)\s*:", body)}
    names = sorted(f"{label}.{prop}" for label, prop in used if (label, prop) in hidden_properties())
    names += sorted(set(re.findall(r":\s*(\w+)", cypher)) & (hidden_labels() | hidden_relationships()))
    return [f"{', '.join(names)} cannot be used in a query: leave it out."] if names else []


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
            rf"(?:{QUOTED})\s+IN\s+(\w+)\.(\w+)", cypher, flags=re.IGNORECASE):
        add(variable, prop, single or double)
    for name, variable, prop in re.findall(r"\$(\w+)\s+IN\s+(\w+)\.(\w+)", cypher, flags=re.IGNORECASE):
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

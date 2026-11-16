import re
from dataclasses import replace
from functools import partial
from typing import Any, Callable

from . import opening_hours
from ...contracts import QueryPlan, RetrievalResult
from ..maps.answer_map import answer_map, study_map
from ..query_generation.coverage import outside_coverage
from ..query_generation.cypher_generation import (
    CUISINE_NAMES,
    CypherResult,
    RESTAURANT_DETAILS_FIELD,
    cuisine_labels,
    generate_cypher,
    returns_restaurants,
)
from ..query_generation.scope import about_food
from ..shared.config import policy
from ..shared.diagnostics import kg_debug, note_turn
from ..shared.messages import response
from ..shared.neo4j import execution_enabled
from ..shared import progress
from .answer_checks import asked_dish, serves_dish
from .answer_text import TECHNICAL_WORDS
from .graph_reads import (
    _anchor_question,
    _dish_places,
    _plain,
    _query_time,
    _relax,
    _run,
    _unknown_area_question,
    _with_restaurant_details,
)
from .market_study import settings as market_settings, study
from .opening_hours import _yesterday, open_now, time_asked
from .ranking import candidate_pool, rank_for_intent, recommendation_intent, without_soft_filters


# LLM call 1 and the Neo4j query; replies collects the chat title and quick replies.
def query_graph(
    user_query: str,
    conversation_context: str,
    location_context: str,
    *,
    deadline: float | None = None,
    replies: dict | None = None,
    want_title: bool = False,
    may_clarify: bool = True,
    chat_state: str = "",
) -> RetrievalResult:
    replies = replies if replies is not None else {}
    generate = partial(generate_cypher, user_query, conversation_context, location_context, deadline=deadline,
                       chat_state=chat_state)
    generated = generate(want_title=want_title, may_clarify=may_clarify)
    if want_title and generated.chat_title:
        replies["chat_title"] = generated.chat_title
    if generated.status == "clarify" and (not may_clarify or _already_said(user_query, generated.options)):
        retry = generate(previous=("", NO_SECOND_QUESTION_ERROR), may_clarify=False)
        generated = retry if retry.status != "skipped_deadline" else generated
    elif generated.status == "clarify" and _same_options(generated.options):
        kg_debug("Clarifying options mean the same thing", generated.options)
        retry = generate(previous=("", SAME_OPTIONS_ERROR), may_clarify=may_clarify)
        if retry.status == "clarify" and _same_options(retry.options):
            retry = generate(previous=("", NO_SECOND_QUESTION_ERROR), may_clarify=False)
        generated = retry if retry.status != "skipped_deadline" else generated
    if generated.status == "rejected_validation":
        retry = generate(previous=(generated.cypher or "", generated.error or ""), may_clarify=may_clarify)
        generated = _keep_details(retry, generated) if retry.status != "skipped_deadline" else generated
    note_turn(outcome=OUTCOMES.get(generated.status, generated.status))
    if generated.status == "clarify":
        return _clarification(replies, generated.reply or "", generated.options)
    if generated.status == "explain":
        return RetrievalResult(status="success", query_plan=QueryPlan(),
                               message=generated.reply)
    if generated.status == "cannot_answer":
        coverage = outside_coverage(user_query, conversation_context, anywhere=_about_coverage(generated.reply))
        if coverage:
            replies["quick_replies"] = list(coverage.suggestions)
            return RetrievalResult(status="unsupported", query_plan=QueryPlan(), message=coverage.message)
        reason = _friendly_reason(generated.reply)
        replies["quick_replies"] = [option for option in generated.options if about_food(option)] \
            if reason != UNSUPPORTED_REQUEST else []
        return RetrievalResult(status="unsupported", query_plan=QueryPlan(), message=reason)
    if generated.status != "success" or not generated.plan:
        status = "invalid_query" if generated.status == "rejected_validation" else "execution_error"
        return RetrievalResult(status=status, query_plan=QueryPlan(),
                               message=response("errors.validation" if status == "invalid_query" else "errors.retrieval"),
                               failure=None if status == "invalid_query" else _model_failure(generated.status))

    plan = generated.plan
    if not execution_enabled():
        return RetrievalResult(status="preview", query_plan=plan)
    progress.report_stage(progress.UNDERSTOOD, question_summary(plan, user_query))
    progress.report_stage(progress.COMPARING if plan.intent.get("location_study") is True else progress.SEARCHING)
    if plan.intent.get("location_study") is True:
        studied = _market_study(plan, generate, user_query, deadline)
        if studied is not None:
            return studied
    wanted = time_asked(user_query, opening_hours.now_local())
    best = _asks_best_rated(user_query, plan)
    intent = recommendation_intent(user_query, plan.intent, plan.cypher) if _discovery(plan) else None
    rank = bool(intent and intent.active)
    if rank:
        plan = replace(plan, cypher=without_soft_filters(plan.cypher, intent, user_query))
    # An explicit ranking (most popular, cheapest) keeps its order.
    prefer_open = not wanted and not (intent and intent.explicit) and _prefers_open(user_query, plan)
    meal = _meal_only(user_query, plan, intent)
    widen = bool(wanted or best or prefer_open or rank or meal)
    candidates = candidate_pool() if rank else None
    execution = _run(plan, deadline, more_candidates=widen and returns_restaurants(plan.cypher),
                     pool=candidates)
    if execution.status == "error" and execution.detail:
        retry = _keep_details(generate(previous=(plan.cypher, execution.detail)), generated)
        if retry.status == "success" and retry.plan:
            plan = retry.plan
            # Same wider pool, or filtering by hours can leave nothing.
            execution = _run(plan, deadline, more_candidates=widen and returns_restaurants(plan.cypher),
                     pool=candidates)
    note_turn(business=plan.business, cypher=plan.cypher, rows=len(execution.records),
              parameters={key: value for key, value in plan.parameters.items() if key not in ("latitude", "longitude")})
    if execution.status != "success":
        return RetrievalResult(status="execution_error", query_plan=plan, message=execution.message,
                               failure=_search_failure(execution.status))
    widened = None
    if not execution.records:
        # Nothing found: loosen only the app's own defaults, never the user's values.
        relaxed = _relax(plan, deadline)
        if relaxed:
            plan, execution, widened = relaxed

    rows = [{key: _plain(value) for key, value in row.items()} for row in execution.records]
    branches = _anchor_question(rows, deadline)
    if branches:
        return _clarification(replies, *branches)
    if rows and returns_restaurants(plan.cypher):
        pool = plan.result_limit * (OPEN_FIRST_POOL if prefer_open else 1)
        rows = _with_restaurant_details(rows if wanted or best or rank or meal else rows[:pool], deadline)
        rows = _whole_word_matches(rows, plan)
        if meal:
            rows = _serves_meals(rows)
        if plan.business and COMPETITOR_WORDS.search(user_query) and RESTAURANT_CONCEPT.search(user_query):
            rows = _meal_competitors(rows)
        if best:
            rows = _well_reviewed(rows)
        if rank:
            rows = rank_for_intent(rows, intent)
        if meal:
            rows = _meal_places_first(rows)
        if wanted:
            rows = [row for row in rows
                    if open_now(row.get("hours_today"), wanted, _yesterday(row.get("weekly_hours"), wanted)) is True]
            if not rows:
                return RetrievalResult(status="no_results", query_plan=plan, message=NOT_OPEN_THEN)
        elif prefer_open:
            rows = sorted(rows[:pool], key=_open_first_ranked if rank else _open_first)
        rows = rows[:plan.result_limit]
    dish_message = None
    if returns_restaurants(plan.cypher) and not plan.business and RESTAURANT_DETAILS_FIELD not in plan.requested_fields:
        rows, dish_message = _dish_matches(rows, plan, user_query, deadline, wanted)
    map_rows = rows
    kg_debug("Cypher rows", rows)
    if not rows:
        unknown_area = _unknown_area_question(plan, deadline, user_query, conversation_context)
        if unknown_area:
            return _clarification(replies, *unknown_area)
        if re.search(r"COMPETES_WITH", plan.cypher):
            return RetrievalResult(status="no_results", query_plan=plan, message=NO_COMPETITORS)
        if filters_on_area(plan.cypher):
            replies["quick_replies"] = [SEARCH_ALL_PJ]
            return RetrievalResult(status="no_results", query_plan=plan,
                                   message=NO_MATCHES_IN_AREA if plan.business else NO_RESULTS_IN_AREA)
        return RetrievalResult(status="no_results", query_plan=plan, message=NO_RESULTS)
    notes = [_widened_note(widened)] if widened else []
    if dish_message:
        notes.append(dish_message)
    missing = _missing_places(rows, named_places(plan.parameters), user_query)
    if missing:
        notes.append(f"I couldn't find {_join(missing)}, so I can't include {'it' if len(missing) == 1 else 'them'}.")
    if few_area_matches(plan, rows):
        replies["quick_replies"] = [SEARCH_ALL_PJ]
    return RetrievalResult(
        status="success",
        query_plan=plan,
        records=rows,
        map_result=answer_map(plan, map_rows, area_filter=filters_on_area(plan.cypher),
                              timeout_seconds=_query_time(deadline)),
        message=" ".join(notes) or None,
    )


FEW_RESULTS = 3


# The query model gave no usable query: it ran out of time, or the AI service failed or answered nonsense.
def _model_failure(status: str) -> str:
    return "timeout" if status in ("timeout", "skipped_deadline") else "model"


def _search_failure(status: str) -> str:
    return "timeout" if status == "timeout" else "search"
TIER_SUMMARY = {"budget": "budget", "mid": "mid-range", "upscale": "upscale", "luxury": "fine dining"}


def _quoted(cypher: str, field: str) -> list[str]:
    single = re.findall(rf"\b{field}\s*(?::|=)\s*'([^']+)'", cypher)
    listed = [value for group in re.findall(rf"\b{field}\s+IN\s*\[([^\]]*)\]", cypher)
              for value in re.findall(r"'([^']+)'", group)]
    return single + listed


# The area the query filters on, readable: a study's named areas, or "(?i)^SS ?2\b.*" read as "SS 2".
def _area_name(plan: QueryPlan) -> str | None:
    areas = [area for area in plan.intent.get("areas") or [] if isinstance(area, str)]
    if areas:
        return ", ".join(areas[:2])
    pattern = _area_pattern(plan)
    if not pattern:
        match = re.search(r"\(\s*(\w+)\s*:\s*Area\b", plan.cypher)
        contains = match and re.search(rf"\b{match.group(1)}\.name\s*\)?\s*CONTAINS\s+(?:toLower\(\s*)?\$(\w+)",
                                       plan.cypher)
        value = plan.parameters.get(contains.group(1)) if contains else None
        return value if isinstance(value, str) else None
    text = re.sub(r"\(\?i\)|\\b|\.\*|[\^$]", "", pattern).replace(" ?", " ").replace("\\", "")
    return text.strip() or None


def _plural(kind: str) -> str:
    words = kind.replace("_", " ")
    return words if words.endswith("s") else words + "s"


# What the app understood, in a few words for the processing card ("competition, SS 2, cafes").
def question_summary(plan: QueryPlan, user_query: str) -> list[str]:
    words: list[str] = []
    if plan.intent.get("location_study") is True:
        words.append("where to open")
    elif plan.business:
        words.append("competition" if COMPETITOR_WORDS.search(user_query) or "COMPETES_WITH" in plan.cypher
                     else "market analysis")
    elif RESTAURANT_DETAILS_FIELD in plan.requested_fields:
        words.append("restaurant details")
    place = progress.place() or _area_name(plan)
    if place:
        words.append(place)
    elif "distance_m" in plan.cypher and isinstance(plan.parameters.get("latitude"), (int, float)):
        words.append("near you")
    words += re.findall(r"Cuisine\s*\{\s*name\s*:\s*'([^']+)'", plan.cypher)
    words += [value for key, value in plan.parameters.items() if "cuisine" in key and isinstance(value, str)]
    words += [_plural(kind) for kind in _quoted(plan.cypher, "restaurant_type")]
    tiers = [TIER_SUMMARY.get(tier, tier) for tier in _quoted(plan.cypher, "tier")]
    words += tiers or (["budget"] if plan.intent.get("budget") is True else [])
    if time_asked(user_query, opening_hours.now_local()):
        words.append("opening hours")
    return progress.summary_words(words)
OUTCOMES = {"success": "query", "cannot_answer": "decline"}


# A named dish outranks soft filters such as price: when no result clearly offers it, search for the dish itself.
def _dish_matches(rows: list[dict[str, Any]], plan: QueryPlan, user_query: str, deadline: float | None,
                  wanted: Any = None) -> tuple[list[dict[str, Any]], str | None]:
    dish = asked_dish(user_query, plan.parameters)
    if not dish or any(serves_dish(row, dish) for row in rows):
        return rows, None
    budget = bool(plan.intent.get("budget")) or plan.intent.get("price_position") == "budget"
    # A wider pool when the places must also be open at the time asked.
    limit = plan.result_limit * (OPEN_FIRST_POOL if wanted else 1)
    found = _dish_places(dish, cuisine_labels()[CUISINE_NAMES].get(dish), _area_pattern(plan), budget,
                         limit, deadline, _search_circle(plan))
    found = _with_restaurant_details(found, deadline) if found else []
    if wanted:
        found = [row for row in found
                 if open_now(row.get("hours_today"), wanted, _yesterday(row.get("weekly_hours"), wanted)) is True]
    found = found[:plan.result_limit]
    if not found:
        return rows, None
    kg_debug("Dish search replaced the results", {"dish": dish, "rows": len(found)})
    if budget and not any(row.get("price_tier") == "budget" for row in found):
        return found, f"I couldn't find a budget {dish} place, so these are the closest matches, cheapest first."
    return found, None


def _area_pattern(plan: QueryPlan) -> str | None:
    for variable in re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*Area\b", plan.cypher):
        match = re.search(rf"\b{re.escape(variable)}\.name\s*=~\s*\$(\w+)", plan.cypher)
        if match and isinstance(plan.parameters.get(match.group(1)), str):
            return plan.parameters[match.group(1)]
    return None


# The user's position and search radius when the query keeps to a distance ("near me"), so the dish search does too.
def _search_circle(plan: QueryPlan) -> tuple[float, float, float] | None:
    match = re.search(r"\bdistance_m\s*<=\s*\$(\w+)", plan.cypher)
    values = [plan.parameters.get(name) for name in ("latitude", "longitude", match.group(1) if match else "")]
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return values[0], values[1], values[2]
    return None


NO_STUDY_AREAS = ("I couldn't find enough restaurants in those areas to compare. Try another area, or ask about all "
                  "of Petaling Jaya.")


STUDY_QUERY = ("This is a location study: return only the concept's direct competitors across all of Petaling Jaya, "
               "as RETURN DISTINCT r.restaurant_id AS restaurant_id, filtered on the concept's cuisine or kind (and "
               "halal only if the user asked), with no Area, IN_AREA, price, customer or atmosphere filter, counts, "
               "shares or other aggregation. The app compares the areas and judges price and customers itself.")
AREA_WORK = re.compile(r"\bIN_AREA\b|:Area\b|\bPRICED_AT\b|:PriceRange\b|\b(?:target_segment|ambiance)\b"
                       r"|\b(?:count|collect|sum|avg)\s*\(", re.IGNORECASE)
ANY_CUISINE = re.compile(r"\(\s*(\w*)\s*:Cuisine\s*\)")


# A location study needs the plain list of competitors: an area or price filter or an aggregate would skew every
# figure, and a Cuisine that names no cuisine counts every restaurant as a competitor.
def _competitor_query_issue(cypher: str) -> str | None:
    if not returns_restaurants(cypher) or AREA_WORK.search(cypher):
        return STUDY_QUERY
    for match in ANY_CUISINE.finditer(cypher):
        if not match[1] or not re.search(rf"\b{match[1]}\.(?:name|category)\b", cypher):
            return STUDY_QUERY + " Name the cuisine, for example (:Cuisine {name: 'Japanese'})."
    return None


# "Where to open": the generated Cypher lists competitors, then one aggregate query ranks every area.
# None falls back to an ordinary business answer.
def _market_study(plan: QueryPlan, generate: Callable[..., CypherResult], user_query: str,
                  deadline: float | None) -> RetrievalResult | None:
    issue = _competitor_query_issue(plan.cypher)
    if issue:
        retry = generate(previous=(plan.cypher, issue))
        if retry.status != "success" or not retry.plan or _competitor_query_issue(retry.plan.cypher):
            return None
        plan = replace(retry.plan, intent=retry.plan.intent or plan.intent)
    limit = market_settings()["max_competitors"]
    execution = _run(plan, deadline, more_candidates=True, pool=limit)
    if execution.status == "error" and execution.detail:
        retry = generate(previous=(plan.cypher, execution.detail))
        if retry.status == "success" and retry.plan:
            plan = replace(retry.plan, intent=retry.plan.intent or plan.intent)
            execution = _run(plan, deadline, more_candidates=True, pool=limit)
    note_turn(business=True, cypher=plan.cypher, rows=len(execution.records), study=plan.intent)
    if execution.status != "success":
        return RetrievalResult(status="execution_error", query_plan=plan, message=execution.message,
                               failure=_search_failure(execution.status))
    competitors = list(dict.fromkeys(row["restaurant_id"] for row in execution.records
                                     if row.get("restaurant_id") is not None))
    found = study(competitors, plan.intent, user_query, timeout_seconds=_query_time(deadline))
    if found is None:
        return RetrievalResult(status="execution_error", query_plan=plan, message=response("errors.retrieval"),
                               failure="search")
    areas, places = found
    plan = replace(plan, business=True)
    if not areas:
        return RetrievalResult(status="no_results", query_plan=plan, message=NO_STUDY_AREAS)
    # The study keeps only the figures it compares, so the map's place cards read the full details.
    places = _with_restaurant_details(places, deadline) or places
    return RetrievalResult(status="success", query_plan=plan, records=areas,
                           map_result=study_map(areas, competitors, places, timeout_seconds=_query_time(deadline)))


BEST_RATED = re.compile(r"\b(?:best|top[- ]rated|highest[- ]rated|best[- ]rated|highly[- ]rated)\b", re.IGNORECASE)


def _asks_best_rated(question: str, plan: QueryPlan) -> bool:
    return bool(BEST_RATED.search(question) and returns_restaurants(plan.cypher)
                and re.search(r"ORDER\s+BY[^\n]*rating_score", plan.cypher, re.IGNORECASE)
                and not re.search(r"total_reviews\s*>=?", plan.cypher, re.IGNORECASE))


def _discovery(plan: QueryPlan) -> bool:
    return (returns_restaurants(plan.cypher) and not plan.business
            and RESTAURANT_DETAILS_FIELD not in plan.requested_fields and not named_places(plan.parameters))


def _well_reviewed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    minimum = policy("ranking").get("rated_minimum_reviews", 0)
    kept = [row for row in rows if isinstance(row.get("review_count"), int) and row["review_count"] >= minimum]
    return kept or rows


def _keep_details(retry: CypherResult, first: CypherResult) -> CypherResult:
    if not retry.plan:
        return retry
    if first.plan and first.plan.business and not retry.plan.business:
        retry = replace(retry, plan=replace(retry.plan, business=True))
    if not first.details or retry.details:
        return retry
    plan = replace(retry.plan, requested_fields=(*retry.plan.requested_fields, RESTAURANT_DETAILS_FIELD))
    return replace(retry, plan=plan, details=True)


# Prefer whole-word name matches: "gem" is Restoran Gem, not Restoran Gembira.
def _whole_word_matches(rows: list[dict[str, Any]], plan: QueryPlan) -> list[dict[str, Any]]:
    names = re.findall(r"\ball\s*\(\s*\w+\s+IN\s+\$(\w+)", plan.cypher, flags=re.IGNORECASE)
    words = next((plan.parameters[name] for name in names if isinstance(plan.parameters.get(name), list)
                  and all(isinstance(word, str) for word in plan.parameters[name])), None)
    if not words or len(rows) < 2:
        return rows

    def whole(row: dict[str, Any]) -> bool:
        label = re.sub(r"['\u2019]", "", f"{row.get('restaurant_name', '')} {row.get('area', '')}".casefold())
        # Section codes as users type them: "SS 2" reads "ss2", so "ss2" matches SS 2 but not SS 24.
        label = re.sub(r"\b([a-z]+) (\d)", r"\1\2", label)
        return all(re.search(rf"(?<![a-z0-9]){re.escape(word.casefold())}(?![a-z0-9])", label) for word in words)

    exact = [row for row in rows if whole(row)]
    return exact or rows


def named_places(parameters: dict[str, Any] | None) -> list[list[str]]:
    for value in (parameters or {}).values():
        if isinstance(value, list) and len(value) >= 2 and all(
                isinstance(words, list) and words and all(isinstance(word, str) for word in words) for words in value):
            return value
    return []


def _missing_places(rows: list[dict[str, Any]], places: list[list[str]], question: str) -> list[str]:
    labels = [f"{row.get('restaurant_name', '')} {row.get('area', '')}".casefold() for row in rows]
    missing = []
    for words in places:
        if not any(all(word.casefold() in label for word in words) for label in labels):
            typed = re.search(r"\W*".join(re.escape(word) for word in words), question, re.IGNORECASE)
            if typed:
                missing.append(typed.group(0))
    return missing


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def few_area_matches(plan: QueryPlan, rows: list[dict[str, Any]]) -> bool:
    return (0 < len(rows) < min(FEW_RESULTS, plan.result_limit) and returns_restaurants(plan.cypher) and filters_on_area(plan.cypher)
            and RESTAURANT_DETAILS_FIELD not in plan.requested_fields and not named_places(plan.parameters))


def _widened_note(radius: int) -> str:
    distance = f"{radius / 1000:g} km" if radius >= 1000 else f"{radius} m"
    return f"There wasn't anything close by, so I looked a little further out, up to {distance}."


SEARCH_ALL_PJ = "Search all of Petaling Jaya"
NO_RESULTS_IN_AREA = ("Sorry, I couldn't find anything that matches in that area. Would you like me to look across "
                      "Petaling Jaya instead?")
NO_MATCHES_IN_AREA = ("The available records show no matching places in that area, so a new outlet there would have "
                      "no direct competitors yet. Would you like me to look across Petaling Jaya instead?")
NO_COMPETITORS = ("I couldn't find any direct competitors recorded for that place yet. Ask me about places of the "
                  "same cuisine or price in its area instead.")
NO_RESULTS = ("Sorry, I couldn't find anything that matches. You could try a different cuisine, a wider budget "
              "or another area.")


def filters_on_area(cypher: str) -> bool:
    for variable in re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*Area\b", cypher):
        v = re.escape(variable)
        if re.search(rf"\(\s*{v}\s*:\s*Area\s*\{{|\b{v}\.name\s*(?:=~|=|CONTAINS|STARTS\s+WITH)"
                     rf"|toLower\(\s*{v}\.name\s*\)\s*(?:=|CONTAINS|STARTS\s+WITH)", cypher, flags=re.IGNORECASE):
            return True
    return False


NO_SECOND_QUESTION_ERROR ="You asked the user a question again. Choose another action and use sensible defaults."
FILLER_WORDS = {"the", "a", "an", "one", "branch", "outlet", "in", "at", "yes", "no", "please", "that"}


# A clarification whose option the question already names ("ZUS Coffee SS2") is not worth asking.
def _already_said(question: str, options: tuple[str, ...] | list[str]) -> bool:
    asked = re.sub(r"[^a-z0-9]", "", question.lower())
    for option in options or ():
        words = [word for word in re.findall(r"[a-z0-9]+", option.lower()) if word not in FILLER_WORDS]
        if len(words) >= 2 and all(word in asked for word in words):
            return True
    return False


SAME_OPTIONS_ERROR = ("Your options meant the same thing in different words. Offer readings that lead to different "
                      "searches, or use a sensible default and query.")
OPTION_WORDS = {"i", "mean", "want", "option", "options", "place", "places", "restaurant", "restaurants", "one",
                "each", "a", "an", "the", "and", "or", "for", "of", "to", "with", "food", "please", "just", "both"}
SAME_MEANING = {"budget": "cheap", "affordable": "cheap", "inexpensive": "cheap", "cheaper": "cheap",
                "premium": "expensive", "pricey": "expensive", "luxury": "expensive", "upscale": "expensive",
                "fine": "expensive", "dining": "", "high": "expensive", "end": ""}


# Options whose key words match after common synonyms ("one cheap and one expensive" and "one budget and one
# premium option") give the user no real choice.
def _same_options(options: tuple[str, ...] | list[str]) -> bool:
    keys = []
    for option in options or ():
        words = {SAME_MEANING.get(word, word) for word in re.findall(r"[a-z]+", option.lower())}
        keys.append(frozenset(words - OPTION_WORDS - {""}))
    return any(keys[i] and keys[i] == keys[j] for i in range(len(keys)) for j in range(i + 1, len(keys)))


def _clarification(replies: dict, question: str, options: tuple[str, ...] | list[str]) -> RetrievalResult:
    replies["quick_replies"] = list(options)
    return RetrievalResult(status="clarification_required", query_plan=QueryPlan(),
                           message=question)


SYSTEM_PHRASES = ((re.compile(r"\s+(?:in|from) (?:the|this|my|our) (?:database|dataset|data)\b", re.IGNORECASE), ""),
                  (re.compile(r"\b(?:the|this|my|our) (?:database|dataset|data)\b", re.IGNORECASE), "my information"),
                  (re.compile(r"\bqueries\b", re.IGNORECASE), "searches"),
                  (re.compile(r"\bquery\b", re.IGNORECASE), "search"))
UNSUPPORTED_REQUEST = ("Sorry, I don't have that information yet, so I can't search by it. I can help with cuisines, "
                       "prices, ratings, opening hours, halal status, and services like delivery or reservations.")


def _about_coverage(reason: str | None) -> bool:
    city = re.escape(policy("coverage")["city"])
    return bool(reason and re.search(rf"\b(?:{city}|PJ)\b", reason, re.IGNORECASE))


def _friendly_reason(reason: str | None) -> str:
    if not reason:
        return response("errors.outside")
    if TECHNICAL_WORDS.search(reason):
        return UNSUPPORTED_REQUEST
    for pattern, replacement in SYSTEM_PHRASES:
        reason = pattern.sub(replacement, reason)
    return reason


NOT_OPEN_THEN = ("None of the places I found are open at that time by their regular hours. Try a 24-hour place, "
                 "or ask me for places open late.")


OPEN_FIRST_POOL = 2
OPEN_FIRST = {True: 0, None: 1, False: 2}


def _open_first(row: dict[str, Any]) -> int:
    return OPEN_FIRST.get(row.get("open_now"), 1)


# Ranked places: only those open now move up, and never above an exact match.
def _open_first_ranked(row: dict[str, Any]) -> tuple[bool, bool]:
    return bool(row.get("alternative")), row.get("open_now") is not True


PLANNING_WORDS = re.compile(
    r"\b(?:breakfast|brunch|lunch|dinner|tea ?time|morning|afternoon|evening|tonight|tomorrow|weekends?|later|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b", re.IGNORECASE)


def _prefers_open(question: str, plan: QueryPlan) -> bool:
    return not (PLANNING_WORDS.search(question or "") or RESTAURANT_DETAILS_FIELD in plan.requested_fields
                or len(named_places(plan.parameters)) >= 2)


COMPETITOR_WORDS = re.compile(r"\bcompet\w*|\brivals?\b", re.IGNORECASE)
RESTAURANT_CONCEPT = re.compile(r"\brestaurants?\b", re.IGNORECASE)


def _meal_words() -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(re.escape(term) for term in policy("meals")["terms"]) + r")\b",
                      re.IGNORECASE)


# Dinner, lunch or a restaurant asks for a meal, so dessert, drinks and bakery places are left out, unless the user
# asked for one of those kinds (policy "meals").
def _meal_only(user_query: str, plan: QueryPlan, intent: Any) -> bool:
    settings = policy("meals")
    if plan.business or RESTAURANT_DETAILS_FIELD in plan.requested_fields or not returns_restaurants(plan.cypher):
        return False
    if not _meal_words().search(user_query or ""):
        return False
    if intent is not None and intent.category in settings["unless_category"]:
        return False
    return not any(f"'{kind}'" in plan.cypher for kind in settings["not_meals"])


def _serves_meals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = set(policy("meals")["not_meals"])
    kept = [row for row in rows if row.get("restaurant_type") not in excluded]
    if len(kept) < len(rows):
        kg_debug("Left out places that do not serve meals", [row.get("restaurant_name") for row in rows
                                                             if row not in kept])
    return kept


# Cafes come after the other meal places, so a coffee chain never leads a dinner list; the order is kept otherwise.
def _meal_places_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    later = set(policy("meals")["only_if_needed"])
    return sorted(rows, key=lambda row: row.get("restaurant_type") in later)


# A Korean restaurant does not compete with a drinks shop that also carries the Korean tag.
def _meal_competitors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = set(market_settings()["not_restaurant_competitors"])
    kept = [row for row in rows if row.get("restaurant_type") not in excluded]
    return kept or rows

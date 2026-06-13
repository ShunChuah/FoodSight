import json
import math
import os
import re
import socket
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()


TITLE_SYSTEM_PROMPT = """
Create a short plain-text chat title from the user's first query.

Rules:
- Use 3 to 7 words only.
- Use letters, numbers, and spaces only.
- Do not use emojis, symbols, markdown, quotation marks, brackets, slashes, hyphens, or punctuation.
- Preserve important place names.
- Do not add explanations.
- Return only the title text.
""".strip()

class LLMServiceError(Exception):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


def generate_chat_title(first_query: str) -> str:
    try:
        title = call_llm(first_query, TITLE_SYSTEM_PROMPT)
    except LLMServiceError:
        title = None
    return title[:160] if title else _fallback_title(first_query)


def call_llm(prompt: str, instructions: str | None = None) -> str | None:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    url = _get_llm_url()
    if not api_key or not url:
        print("LLM call skipped: LLM_API_KEY or LLM_API_URL is missing.", flush=True)
        raise LLMServiceError(
            "The LLM service is not configured. Please check the backend "
            "LLM configuration."
        )

    full_prompt = f"{instructions}\n\n{prompt}" if instructions else prompt
    payload, headers = _build_llm_request(full_prompt)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"LLM HTTP error {exc.code}: {error_body[:500]}", flush=True)
        raise LLMServiceError(_http_error_message(exc.code, error_body)) from exc
    except (TimeoutError, socket.timeout) as exc:
        print(f"LLM call timed out: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service timed out. Please try again later."
        ) from exc
    except urllib.error.URLError as exc:
        if _is_timeout_error(exc.reason):
            print(f"LLM call timed out: {exc}", flush=True)
            raise LLMServiceError(
                "The LLM service timed out. Please try again later."
            ) from exc
        print(f"LLM URL error: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service could not be reached. Please try again later."
        ) from exc
    except ConnectionError as exc:
        print(f"LLM connection error: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service could not be reached. Please try again later."
        ) from exc
    except json.JSONDecodeError as exc:
        print(f"LLM response was not valid JSON: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service returned an invalid response. Please try again."
        ) from exc

    text = _extract_llm_text(data)
    if not text:
        print(f"LLM returned no text: {json.dumps(data)[:500]}", flush=True)
    return text


def generate_graph_query_response(
    schema_context: str,
    understanding_context: str,
    location_context: str,
) -> str | None:
    generated = call_llm(
        _build_cypher_prompt(
            schema_context,
            understanding_context,
            location_context,
        )
    )
    return generated


def _build_cypher_prompt(
    schema_context: str,
    understanding_context: str,
    location_context: str,
) -> str:
    return f"""
Generate one read-only Neo4j Cypher query for FoodSight.

Rules:
1. Output only `CYPHER | ` followed by one query.
2. Use structured query understanding as the source of truth.
3. Use only the supplied schema. Do not invent labels, relationships, or
   properties.
4. Every non-empty filter must affect the query. For customer/lookup queries,
   use MATCH/WHERE. For analyst area metrics, use business filters in the
   matching_competitors CASE so total_restaurants still counts the full area.
5. If a filter cannot be represented with the supplied schema, ignore only that
   filter. Do not add optional matches for unused filters.
6. Required filter paths:
   Restaurant -> (r:Restaurant)
   Dish -> (r)-[:HAS_DISH]->(d:Dish)
   Cuisine -> (r)-[:SERVES]->(c:Cuisine)
   PriceRange -> (r)-[:HAS_PRICE_RANGE]->(p:PriceRange)
   BusinessProfile -> (r)-[:HAS_PROFILE]->(bp:BusinessProfile)
   Facility -> (r)-[:HAS_FACILITY]->(f:Facility)
   Promotion -> (r)-[:HAS_PROMOTION]->(promo:Promotion)
   Location -> (r)-[:LOCATED_AT]->(loc:Location)
   Area -> (loc)-[:LOCATED_IN]->(a:Area)
   City -> (a)-[:PART_OF]->(city:City)
   Cluster -> (r)-[:BELONGS_TO_CLUSTER]->(cl:Cluster)
7. For list values, match any value with case-insensitive equality or CONTAINS.
8. Do not replace Dish/Cuisine filters with BusinessProfile filters.
9. With browser coordinates, rank or filter by distance from Location. Never use
   exact latitude/longitude equality.
10. If scope is fnb_analyst and analysis.mode is area_opportunity,
   competitor_density, or market_gap, return aggregate area metrics instead of
   only matching restaurants. Include candidate area, total_restaurants,
   matching_competitors, saturation ratio, and available density/rating signals.
   Use aliases: candidate_area, total_restaurants, matching_competitors,
   saturation_ratio, avg_area_rating, avg_area_review_count, avg_density_score.
   Do not calculate final opportunity_score, risk_score, or gap_score in
   Cypher; Python analysis calculates final scores from these raw metrics.
11. For analyst matching_competitors, count restaurants matching the business
    type through Restaurant, Cuisine, or Dish filters with
    count(DISTINCT CASE WHEN ... THEN r END). total_restaurants must count all
    restaurants in the candidate area.
12. If analysis.mode is pricing_analysis, return pricing evidence instead of
    restaurant rows: item/category, sample_count, min_price, avg_price,
    max_price, and available restaurant PriceRange signals. Use Dish.price for
    menu-item pricing and PriceRange for restaurant-level pricing.
    Use aliases: item_category, sample_count, min_price, avg_price, max_price,
    avg_restaurant_price_range.
13. If analysis.mode is customer_segment_analysis, aggregate BusinessProfile
    signals by target segment, dining experience, business style, or ambiance.
    Use aliases: segment, restaurant_count, avg_rating, avg_review_count.
14. If analysis.mode is location_risk_analysis, return area risk metrics from
    Restaurant, Area, and Cluster. Use aliases: candidate_area,
    total_restaurants, matching_competitors, saturation_ratio, avg_area_rating,
    avg_area_review_count, avg_density_score.
15. If analysis.mode is menu_gap_analysis, aggregate Dish, MenuCategory, and
    Cuisine signals to find underrepresented menu categories or dishes. Use
    aliases: item_category, dish_count, restaurant_count, avg_price,
    avg_rating, avg_review_count.
16. For area_opportunity without location.value, rank all candidate areas. If
    location.value exists, filter/analyze that named area.
17. The Location section is authoritative when it contains an area or browser
    coordinates.
18. Apply sort and LIMIT. Default LIMIT 3.
19. Allowed clauses: MATCH, OPTIONAL MATCH, WHERE, WITH, RETURN, ORDER BY, SKIP,
    LIMIT. Never use write clauses, CALL, UNION, USE, subqueries, procedures,
    APOC, or plugins.
   
Structured query understanding:
{understanding_context}

Schema:
{schema_context}

Location:
{location_context}
""".strip()


def _get_llm_url() -> str | None:
    url = os.getenv("LLM_API_URL", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    return url.replace("{model}", model) if url else None


def _get_llm_style() -> str:
    return os.getenv("LLM_API_STYLE", "content").strip().lower()


def _build_llm_request(prompt: str) -> tuple[dict, dict[str, str]]:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    style = _get_llm_style()
    headers = {"Content-Type": "application/json"}

    if style == "content":
        headers["x-goog-api-key"] = api_key
        return {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, headers
    if style == "responses":
        headers["Authorization"] = f"Bearer {api_key}"
        return {"model": model, "input": prompt}, headers

    headers["Authorization"] = f"Bearer {api_key}"
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }, headers


def _extract_llm_text(data: dict) -> str | None:
    style = _get_llm_style()
    if style == "content":
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts") if candidates else []
        text = "\n".join(part.get("text", "") for part in parts or [])
        return text.strip() or None
    if style == "responses":
        if data.get("output_text"):
            return str(data["output_text"]).strip() or None
        text_parts = [
            content["text"]
            for output in data.get("output") or []
            for content in output.get("content") or []
            if content.get("text")
        ]
        return "\n".join(text_parts).strip() or None

    choices = data.get("choices") or []
    content = choices[0].get("message", {}).get("content") if choices else None
    return content.strip() if isinstance(content, str) and content.strip() else None


def _http_error_message(status_code: int, error_body: str) -> str:
    if status_code == 429:
        retry_match = re.search(
            r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)s",
            error_body,
            flags=re.IGNORECASE,
        )
        if retry_match:
            retry_seconds = max(1, math.ceil(float(retry_match.group(1))))
            return (
                "The LLM service rate limit has been reached. Please try again "
                f"in about {retry_seconds} seconds."
            )
        return (
            "The LLM service rate limit has been reached. Please try again shortly."
        )
    return (
        f"The LLM service returned HTTP error {status_code}. "
        "Please try again later."
    )


def _is_timeout_error(error: object) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return "timed out" in str(error).lower()


def _fallback_title(message: str) -> str:
    clean_message = " ".join(message.strip().split())
    return f"{clean_message[:35]}..." if len(clean_message) > 35 else clean_message

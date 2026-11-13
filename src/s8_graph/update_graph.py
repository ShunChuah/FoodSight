"""
FoodSight — Knowledge Graph Update (UC21)
Updates Neo4j with only the PostgreSQL rows that changed, instead of copying
everything again (that is the full build, python run_8_graph.py --fresh).

Step 1 — Read the stage 8 to-do list, data/state/graph_todo.json, written by
          run_7_loading.py: every row it added, updated or deleted, grouped as
          restaurants (everything that belongs to one restaurant, by
          restaurant_id), areas, city, nearby_places, cuisines and facilities,
          each change with its value before and now.

Step 2 — Take those records from the graph data run_8_graph.py has just
          extracted from PostgreSQL and validated (UC18, UC19, UC22). For a
          restaurant that is its node, the nodes that belong to it alone (its
          location, hours, price, profile, rating, nearby counts and
          reviews) and the relationships that start at them.

Step 3 — Write them in ONE Neo4j transaction, so an error changes nothing:
          - a node that is new is created, one whose properties differ is
            updated (MERGE), one that is the same is left alone;
          - each listed restaurant's relationships are made the same as in
            PostgreSQL: missing ones are added, ones PostgreSQL no longer has
            are removed (a dropped cuisine, a deleted school, a moved station);
          - a node PostgreSQL deleted is removed with its relationships (a
            nearby place gone from OSM, a rating the restaurant lost);
          - the clusters are rebuilt, as every load numbers them again:
            Cluster nodes, IN_CLUSTER, SPANS and COMPETES_WITH.

Step 4 — Conflicts (UC21's exception flow): before a property is changed, the
          graph's value is compared with the value PostgreSQL had before the
          load (the to-do list's "before"; for a property PostgreSQL did not
          change, its current value). When the graph holds something else, it
          was changed outside the pipeline (by hand in Neo4j Browser, for
          example): the PostgreSQL value, the most recent, is written anyway,
          and the conflict is logged (into the day's log, data/logs/).

Step 5 — Log the summary (added, updated, removed), then empty the to-do list.
          A load that ran in the meantime keeps its entries.
"""

import hashlib
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

from src.cache_saving import save_json
from src.s7_loader.load_data import TODO_FILE
from src.s8_graph.build_graph import (connect, create_constraints_and_indexes, load_nodes,
                                      load_relationships, _set_points)
from src.s8_graph.extract_entities import _split_list

logger = logging.getLogger(__name__)

# The to-do list's groups of shared rows and their node labels
GROUP_LABELS = {
    "areas": "Area",
    "city": "City",
    "nearby_places": "NearbyPlace",
    "cuisines": "Cuisine",
    "facilities": "Facility",
}
# A restaurant's location belongs to it alone (restaurant.location_id is
# UNIQUE), like the rows that carry its restaurant_id (hours, rating, ...).
OWNED_BY_FK = {"LOCATED_IN"}
CONFLICTS_SHOWN = 20  # conflict lines written to the log before a count only


# ---------------------------------------------------------------------------
# The to-do list
# ---------------------------------------------------------------------------


def read_todo(path=TODO_FILE):
    """The stage 8 to-do list, or None when there is none."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def todo_is_empty(todo):
    return not todo or (not todo.get("rebuild_clusters")
                        and not any((todo.get("changes") or {}).values()))


def empty_todo(applied, path=TODO_FILE):
    """Remove from the to-do list what has been applied. An entry that a load
    added or changed in the meantime stays for the next run."""
    current = read_todo(path)
    if current is None:
        return
    changes = current.get("changes") or {}
    for group, entries in ((applied or {}).get("changes") or {}).items():
        for key, entry in entries.items():
            if changes.get(group, {}).get(key) == entry:
                del changes[group][key]
    newer_load = (applied or {}).get("updated_at") != current.get("updated_at")
    save_json(path, {
        **current,
        "rebuild_clusters": bool(current.get("rebuild_clusters") and newer_load),
        "changes": {group: entries for group, entries in changes.items() if entries},
        "emptied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# Comparing graph values with PostgreSQL values
# ---------------------------------------------------------------------------


def _native(v):
    """A Neo4j date-time as a Python one."""
    return v.to_native() if hasattr(v, "to_native") else v


def _as_time(v):
    v = _native(v)
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _equal(a, b):
    """True when two values are the same: numbers within a millionth, times as
    instants (a time can be a string from the to-do list), lists item by item."""
    a, b = _native(a), _native(b)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, datetime) or isinstance(b, datetime):
        ta, tb = _as_time(a), _as_time(b)
        return ta is not None and ta == tb
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-6
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def _matches_todo(graph_value, todo_value, is_list):
    """The graph value against a value from the to-do list, where a long text
    is written as its sha256 and a list property as its comma text."""
    if isinstance(todo_value, str) and todo_value.startswith("sha256:") and isinstance(graph_value, str):
        return "sha256:" + hashlib.sha256(graph_value.encode("utf-8")).hexdigest() == todo_value
    if is_list and isinstance(todo_value, str):
        todo_value = _split_list(todo_value)
    return _equal(graph_value, todo_value)


def _short(v):
    v = _native(v)
    if isinstance(v, str) and len(v) > 200:
        return "(outline)"
    text = repr(v.isoformat() if isinstance(v, datetime) else v)
    return text if len(text) <= 60 else text[:57] + "..."


# ---------------------------------------------------------------------------
# The update
# ---------------------------------------------------------------------------


class _Update:
    """One graph update: the ontology, the validated PostgreSQL data, the
    counts for the summary and the conflicts found."""

    def __init__(self, ontology, nodes, relationships):
        self.ontology = ontology
        self.specs = ontology["nodes"]
        self.rels = ontology["relationships"]
        self.key_of = {label: spec["key"] for label, spec in self.specs.items()}
        self.label_of_table = {spec["table"]: label for label, spec in self.specs.items()}
        self.rows = {label: {n[self.key_of[label]]: n for n in items} for label, items in nodes.items()}
        # relationship type -> from key -> {to key: properties}
        self.by_from = {t: defaultdict(dict) for t in self.rels}
        for rel_type, items in relationships.items():
            for rel in items:
                self.by_from[rel_type][rel["from"]][rel["to"]] = rel.get("props") or {}
        self.relationships = relationships
        rebuilt = {label for label, spec in self.specs.items() if spec.get("rebuild")}
        # Rebuilt with the clusters: the rebuilt types and every type touching a rebuilt label
        self.cluster_types = [t for t, s in self.rels.items()
                              if s.get("rebuild") or s["from"] in rebuilt or s["to"] in rebuilt]
        self.rebuilt_labels = sorted(rebuilt)
        # The relationships from a restaurant to the nodes that belong to it alone
        self.owned_types = [t for t, s in self.rels.items()
                            if s["from"] == "Restaurant" and t not in self.cluster_types
                            and (s.get("table") == self.specs[s["to"]]["table"] or t in OWNED_BY_FK)]
        self.nodes = Counter()  # (label, "added" | "updated" | "removed") -> n
        self.links = Counter()  # (type, "added" | "removed" | "updated") -> n
        self.conflicts = []
        self.missing_ends = Counter()
        self.detached = 0  # relationships removed together with a removed node
        self.graph_types = set()  # relationship types the graph has, read when the update starts

    # -- nodes ----------------------------------------------------------------

    def graph_props(self, tx, label, keys):
        key = self.key_of[label]
        return {rec["k"]: dict(rec["p"]) for rec in tx.run(
            f"MATCH (n:`{label}`) WHERE n.`{key}` IN $keys RETURN n.`{key}` AS k, properties(n) AS p",
            keys=list(keys))}

    def write_nodes(self, tx, label, keys, expected=None):
        """Create the nodes that are missing and update the ones whose
        properties differ, checking each change for a conflict. `expected`:
        {key: {column: value PostgreSQL had before}} from the to-do list."""
        if not keys:
            return
        spec = self.specs[label]
        points = set(spec.get("points", {}))
        lists = set(spec.get("list_properties", []))
        derived = set(spec.get("derived", {}))
        in_graph = self.graph_props(tx, label, keys)
        to_write = []
        for key in keys:
            row = self.rows[label][key]
            graph = in_graph.get(key)
            if graph is None:
                self.nodes[(label, "added")] += 1
                to_write.append(row)
                continue
            differ = [p for p in (set(graph) | set(row)) - points if not _equal(graph.get(p), row.get(p))]
            if not differ:
                continue
            self.nodes[(label, "updated")] += 1
            to_write.append(row)
            before = (expected or {}).get(key, {})
            for prop in sorted(differ):
                if prop in before:
                    # changed by the load: the graph should still hold the value before it
                    if not (_matches_todo(graph.get(prop), before[prop], prop in lists)
                            or _equal(graph.get(prop), row.get(prop))):
                        self.conflict(label, key, prop, graph.get(prop), before[prop], row.get(prop))
                elif prop in derived or isinstance(_native(graph.get(prop)), datetime) \
                        or isinstance(row.get(prop), datetime):
                    # worked out from other values (counted_as_open), or a fetch time
                    # written along with its row: it changes with them, never on its own
                    continue
                else:
                    # PostgreSQL did not change it, so the graph should hold the same value
                    self.conflict(label, key, prop, graph.get(prop), row.get(prop), row.get(prop))
        if to_write:
            tx.run(f"UNWIND $rows AS row MERGE (n:`{label}` {{`{self.key_of[label]}`: row.`{self.key_of[label]}`}}) "
                   f"SET n = row{_set_points(spec)}", rows=to_write).consume()

    def conflict(self, label, key, prop, graph_value, expected, new_value):
        self.conflicts.append((label, key, prop))
        if len(self.conflicts) <= CONFLICTS_SHOWN:
            logger.warning("  Conflict: %s %s %s: the graph had %s, expected %s; set to %s from PostgreSQL",
                           label, key, prop, _short(graph_value), _short(expected), _short(new_value))

    def remove_nodes(self, tx, label, keys):
        if not keys:
            return
        key = self.key_of[label]
        counters = tx.run(f"MATCH (n:`{label}`) WHERE n.`{key}` IN $keys DETACH DELETE n",
                          keys=list(keys)).consume().counters
        self.nodes[(label, "removed")] += counters.nodes_deleted
        self.detached += counters.relationships_deleted

    def remove_restaurants(self, tx, ids):
        """A restaurant deleted from PostgreSQL goes with the nodes that belong to it alone."""
        if not ids:
            return
        found = tx.run("MATCH (r:Restaurant) WHERE r.restaurant_id IN $ids RETURN count(r) AS c",
                       ids=list(ids)).single()["c"]
        owned = "|".join(f"`{t}`" for t in self.owned_types)
        counters = tx.run(f"MATCH (r:Restaurant) WHERE r.restaurant_id IN $ids "
                          f"OPTIONAL MATCH (r)-[:{owned}]->(o) "
                          f"WITH r, collect(o) AS mine "
                          f"FOREACH (x IN mine | DETACH DELETE x) "
                          f"DETACH DELETE r",
                          ids=list(ids)).consume().counters
        self.nodes[("Restaurant", "removed")] += found
        self.nodes[("its own nodes", "removed")] += max(counters.nodes_deleted - found, 0)
        self.detached += counters.relationships_deleted

    # -- relationships ---------------------------------------------------------

    def sync_relationships(self, tx, rel_type, start_keys):
        """Make the relationships of this type that start at these nodes the
        same as in PostgreSQL. Returns the end keys that lost their link."""
        if not start_keys:
            return set()
        spec = self.rels[rel_type]
        fk, tk = self.key_of[spec["from"]], self.key_of[spec["to"]]
        want = {(f, t): props for f in start_keys for t, props in self.by_from[rel_type].get(f, {}).items()}
        if not want and rel_type not in self.graph_types:
            return set()  # none in PostgreSQL or in the graph (a type whose table is still empty)
        have = {(rec["f"], rec["t"]): dict(rec["p"]) for rec in tx.run(
            f"MATCH (a:`{spec['from']}`)-[r:`{rel_type}`]->(b:`{spec['to']}`) WHERE a.`{fk}` IN $keys "
            f"RETURN a.`{fk}` AS f, b.`{tk}` AS t, properties(r) AS p", keys=list(start_keys))}
        gone = have.keys() - want.keys()
        new = want.keys() - have.keys()
        moved = [k for k in want.keys() & have.keys()
                 if any(not _equal(have[k].get(p), want[k].get(p)) for p in set(have[k]) | set(want[k]))]
        if gone:
            tx.run(f"UNWIND $rows AS row MATCH (a:`{spec['from']}` {{`{fk}`: row.f}})"
                   f"-[r:`{rel_type}`]->(b:`{spec['to']}` {{`{tk}`: row.t}}) DELETE r",
                   rows=[{"f": f, "t": t} for f, t in gone]).consume()
        if new:
            created = tx.run(f"UNWIND $rows AS row MATCH (a:`{spec['from']}` {{`{fk}`: row.f}}) "
                             f"MATCH (b:`{spec['to']}` {{`{tk}`: row.t}}) "
                             f"MERGE (a)-[r:`{rel_type}`]->(b) SET r = row.props",
                             rows=[{"f": f, "t": t, "props": want[(f, t)]} for f, t in new]
                             ).consume().counters.relationships_created
            if created < len(new):
                self.missing_ends[rel_type] += len(new) - created
            self.links[(rel_type, "added")] += created
        if moved:
            tx.run(f"UNWIND $rows AS row MATCH (a:`{spec['from']}` {{`{fk}`: row.f}})"
                   f"-[r:`{rel_type}`]->(b:`{spec['to']}` {{`{tk}`: row.t}}) SET r = row.props",
                   rows=[{"f": f, "t": t, "props": want[(f, t)]} for f, t in moved]).consume()
        self.links[(rel_type, "removed")] += len(gone)
        self.links[(rel_type, "updated")] += len(moved)
        still_linked = {t for _, t in want}
        return {t for _, t in gone if t not in still_linked}

    def rebuild_clusters(self, tx):
        """As in the full build: every Cluster node (with its IN_CLUSTER and
        SPANS) and every COMPETES_WITH is deleted and made again."""
        node_summary = load_nodes(tx, self.ontology, {label: list(self.rows[label].values())
                                                      for label in self.rebuilt_labels})
        rel_summary = load_relationships(tx, self.ontology, {t: self.relationships[t]
                                                             for t in self.cluster_types})
        return node_summary, rel_summary


def update_graph(ontology, nodes, relationships, todo, in_postgres):
    """Apply the to-do list (see the module text). `nodes` and `relationships`
    are the validated data of all of PostgreSQL; `in_postgres` is {label: set
    of keys} before validation, to tell a deleted row from an invalid one."""
    u = _Update(ontology, nodes, relationships)
    groups = todo.get("changes") or {}

    # Which restaurants: in PostgreSQL and valid -> synced; gone -> removed
    listed = {int(k): entry for k, entry in (groups.get("restaurants") or {}).items()}
    removed = {rid for rid, entry in listed.items()
               if entry.get("action") == "deleted" or rid not in in_postgres.get("Restaurant", set())}
    synced = sorted(rid for rid in listed if rid not in removed and rid in u.rows["Restaurant"])
    invalid = sorted(set(listed) - removed - set(synced))
    if invalid:
        logger.warning("  %d listed restaurants failed the ontology check and keep their old graph data "
                       "(see data/review/graph_invalid.json): %s", len(invalid), invalid[:10])

    # The nodes that belong to each synced restaurant, and what the to-do list
    # says each property was before the load
    owned = defaultdict(set)  # label -> keys
    expected = defaultdict(lambda: defaultdict(dict))  # label -> key -> {column: before}
    for rid in synced:
        fields = listed[rid].get("changes") or {}
        mine = {"Restaurant": {rid}}
        for rel_type in u.owned_types:
            label = u.rels[rel_type]["to"]
            keys = set(u.by_from[rel_type].get(rid, {}))
            owned[label] |= keys
            mine.setdefault(label, set()).update(keys)
        for field, (before, _now) in fields.items():
            table, _, column = field.partition(".")
            label = u.label_of_table.get(table)
            if column and label in mine:
                for key in mine[label]:
                    expected[label][key][column] = before

    shared_write, shared_remove = defaultdict(set), defaultdict(set)
    for group, label in GROUP_LABELS.items():
        for k, entry in (groups.get(group) or {}).items():
            key = int(k)
            if entry.get("action") == "deleted" or key not in in_postgres.get(label, set()):
                shared_remove[label].add(key)
            elif key in u.rows[label]:
                shared_write[label].add(key)
                for field, (before, _now) in (entry.get("changes") or {}).items():
                    table, _, column = field.partition(".")
                    if column and u.label_of_table.get(table) == label:
                        expected[label][key][column] = before

    logger.info("  To-do list: %d restaurants (%d to update, %d to remove), %s; clusters %s",
                len(listed), len(synced), len(removed),
                ", ".join(f"{len(v)} {g}" for g, v in groups.items() if g != "restaurants" and v) or "nothing else",
                "rebuilt" if todo.get("rebuild_clusters") else "unchanged")

    driver = connect()
    try:
        with driver.session() as session:
            # Schema statements cannot share a transaction with data changes
            create_constraints_and_indexes(session, ontology)
            with session.begin_transaction() as tx:
                u.graph_types = set(tx.run("CALL db.relationshipTypes() YIELD relationshipType "
                                           "RETURN relationshipType").value())
                # 1. removals
                u.remove_restaurants(tx, removed)
                for label, keys in shared_remove.items():
                    u.remove_nodes(tx, label, keys)
                # 2. nodes: shared ones first, so the relationships find both ends
                for label, keys in shared_write.items():
                    u.write_nodes(tx, label, sorted(keys), expected[label])
                u.write_nodes(tx, "Restaurant", synced, expected["Restaurant"])
                for label, keys in owned.items():
                    u.write_nodes(tx, label, sorted(keys), expected[label])
                # 3. relationships that start at a listed node
                gone_owned = defaultdict(set)
                for rel_type, spec in u.rels.items():
                    if rel_type in u.cluster_types:
                        continue
                    if spec["from"] == "Restaurant":
                        starts = set(synced)
                    elif spec["from"] in owned:  # Location -[:IN_AREA]->
                        starts = owned[spec["from"]]
                    else:  # Area -[:IN_CITY]->
                        starts = shared_write.get(spec["from"], set())
                    lost = u.sync_relationships(tx, rel_type, starts)
                    if rel_type in u.owned_types:
                        gone_owned[spec["to"]] |= lost
                # 4. a node that belonged to a restaurant alone and lost its link
                for label, keys in gone_owned.items():
                    u.remove_nodes(tx, label, keys - set(u.rows.get(label, {})))
                # 5. clusters
                cluster_summary = u.rebuild_clusters(tx) if todo.get("rebuild_clusters") else None
                tx.commit()
            total_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            total_rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    finally:
        driver.close()

    # Summary (UC21 step 6)
    labels = sorted({label for label, _ in u.nodes})
    if labels:
        logger.info("  %-16s %6s %8s %8s", "NODE", "added", "updated", "removed")
        for label in labels:
            logger.info("  %-16s %6d %8d %8d", label, u.nodes[(label, "added")],
                        u.nodes[(label, "updated")], u.nodes[(label, "removed")])
    types = sorted({t for t, _ in u.links if sum(u.links[(t, a)] for a in ("added", "removed", "updated"))})
    if types:
        logger.info("  %-16s %6s %8s %8s", "RELATIONSHIP", "added", "removed", "updated")
        for rel_type in types:
            logger.info("  %-16s %6d %8d %8d", rel_type, u.links[(rel_type, "added")],
                        u.links[(rel_type, "removed")], u.links[(rel_type, "updated")])
    if u.detached:
        logger.info("  %d relationships removed together with the removed nodes", u.detached)
    if not labels and not types:
        logger.info("  No node or relationship of the listed rows differed from PostgreSQL.")
    if cluster_summary:
        node_summary, rel_summary = cluster_summary
        logger.info("  Clusters rebuilt: %s", ", ".join(
            [f"{sent} {label}" for label, (sent, _) in node_summary.items()]
            + [f"{sent} {t}" for t, (sent, _) in rel_summary.items()]))
    for rel_type, n in u.missing_ends.items():
        logger.warning("  %d %s relationships were not added: an end node is missing in the graph. "
                       "Run python run_8_graph.py --fresh.", n, rel_type)
    if u.conflicts:
        logger.warning("  Conflicts: %d (the graph had been changed outside the pipeline; "
                       "PostgreSQL's values were written)%s", len(u.conflicts),
                       f", first {CONFLICTS_SHOWN} listed above" if len(u.conflicts) > CONFLICTS_SHOWN else "")
    else:
        logger.info("  Conflicts: 0")
    logger.info("  Graph now holds %d nodes and %d relationships.", total_nodes, total_rels)

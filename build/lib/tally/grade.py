"""Grade the engine against the answer key.

The grader is the only component that reads ``answer_key.csv`` and ``expected_links.csv``.
It reads them from the generated world directory, never from the warehouse.

Metrics
  per class     precision, recall, F1 from exact matches of (class, set of records involved)
  links         precision and recall of the pairings the engine made
  false alarms  how many benign look-alikes the engine wrongly raised as errors
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from tally.synth.classes import DEFECT_CLASSES
from tally.warehouse import Warehouse

Entities = frozenset  # frozenset[tuple[str, str]]


def _entities(text: str) -> Entities:
    return frozenset((e["source"], e["id"]) for e in json.loads(text))


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 1.0


def _f1(p: float, r: float) -> float:
    return round(2 * p * r / (p + r), 4) if (p + r) else 0.0


@dataclass
class ClassScore:
    name: str
    category: str
    support: int
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        return _f1(self.precision, self.recall)

    def as_dict(self) -> dict:
        return {
            "class": self.name, "category": self.category, "support": self.support,
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": self.precision, "recall": self.recall, "f1": self.f1,
        }  # fmt: skip


@dataclass
class Scorecard:
    classes: list[ClassScore] = field(default_factory=list)
    links: dict[str, dict] = field(default_factory=dict)
    benign_total: int = 0
    benign_false_alarms: int = 0
    unexplained_error_findings: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def benign_false_alarm_rate(self) -> float:
        return round(self.benign_false_alarms / self.benign_total, 4) if self.benign_total else 0.0

    def error_classes(self) -> list[ClassScore]:
        return [c for c in self.classes if c.category == "error"]

    def to_dict(self) -> dict:
        errs = self.error_classes()
        tp = sum(c.tp for c in errs)
        fp = sum(c.fp for c in errs)
        fn = sum(c.fn for c in errs)
        return {
            "meta": self.meta,
            "summary": {
                "error_micro_precision": _ratio(tp, tp + fp),
                "error_micro_recall": _ratio(tp, tp + fn),
                "benign_false_alarm_rate": self.benign_false_alarm_rate,
                "benign_defects": self.benign_total,
                "benign_false_alarms": self.benign_false_alarms,
                "error_findings_matching_no_defect": self.unexplained_error_findings,
            },
            "classes": [c.as_dict() for c in self.classes],
            "links": self.links,
        }


def load_key(world: Path) -> list[dict]:
    with (world / "answer_key.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_links(world: Path) -> set[tuple[str, str, str]]:
    with (world / "expected_links.csv").open(newline="", encoding="utf-8") as f:
        return {(r["link_type"], r["left_id"], r["right_id"]) for r in csv.DictReader(f)}


def grade(wh: Warehouse, world: Path) -> Scorecard:
    key = load_key(world)
    expected: dict[str, set[Entities]] = {}
    category: dict[str, str] = {k: v[0] for k, v in DEFECT_CLASSES.items()}
    for d in key:
        expected.setdefault(d["class"], set()).add(_entities(d["entities"]))

    found: dict[str, set[Entities]] = {}
    error_findings: list[tuple[str, Entities]] = []
    rows = wh.con.execute("SELECT class, category, entities FROM recon.findings").fetchall()
    for cls, cat, ents in rows:
        found.setdefault(cls, set()).add(_entities(ents))
        category.setdefault(cls, cat)
        if cat == "error":
            error_findings.append((cls, _entities(ents)))

    card = Scorecard()
    for cls in sorted(set(expected) | set(found) | set(DEFECT_CLASSES)):
        e, f = expected.get(cls, set()), found.get(cls, set())
        card.classes.append(
            ClassScore(cls, category[cls], len(e), len(e & f), len(f - e), len(e - f))
        )

    # Benign look-alikes the engine wrongly raised as errors. Only a *false positive* error
    # finding counts: a correct error on a record that also carries a benign quirk is not an alarm.
    benign = [(d["class"], _entities(d["entities"])) for d in key if d["category"] == "benign"]
    entity_to_benign: dict[tuple[str, str], list[int]] = {}
    for i, (_, ents) in enumerate(benign):
        for e in ents:
            entity_to_benign.setdefault(e, []).append(i)
    alarmed: set[int] = set()
    all_key_entities = {e for d in key for e in _entities(d["entities"])}
    unexplained = 0
    for cls, ents in error_findings:
        if ents in expected.get(cls, set()):
            continue  # a true positive
        for e in ents:
            alarmed.update(entity_to_benign.get(e, []))
        if not ents & all_key_entities:
            unexplained += 1
    card.benign_total = len(benign)
    card.benign_false_alarms = len(alarmed)
    card.unexplained_error_findings = unexplained

    exp_links = load_links(world)
    got_links = {
        tuple(r)
        for r in wh.con.execute("SELECT link_type, left_id, right_id FROM recon.links").fetchall()
    }
    for kind in ("ledger_txn", "payout_bank", "all"):
        e = {x for x in exp_links if kind == "all" or x[0] == kind}
        g = {x for x in got_links if kind == "all" or x[0] == kind}
        tp = len(e & g)
        p, r = _ratio(tp, len(g)), _ratio(tp, len(e))
        card.links[kind] = {
            "expected": len(e), "found": len(g), "tp": tp,
            "precision": p, "recall": r, "f1": _f1(p, r),
        }  # fmt: skip
    return card


def render_markdown(card: Scorecard) -> str:
    d = card.to_dict()
    meta = d["meta"]
    lines = ["# TrueUp scorecard", ""]
    if meta:
        lines += [", ".join(f"{k}: {v}" for k, v in meta.items()), ""]
    s = d["summary"]
    lines += [
        "## Summary",
        "",
        f"- Real errors: micro precision **{s['error_micro_precision']:.3f}**, "
        f"micro recall **{s['error_micro_recall']:.3f}**",
        f"- Benign look-alikes wrongly raised as errors: **{s['benign_false_alarms']} of "
        f"{s['benign_defects']}** ({s['benign_false_alarm_rate']:.2%})",
        f"- Error findings that match no injected defect: {s['error_findings_matching_no_defect']}",
        f"- Link accuracy: precision **{d['links']['all']['precision']:.4f}**, "
        f"recall **{d['links']['all']['recall']:.4f}**",
        "",
        "## By class",
        "",
        "| Class | Kind | Cases | Found right | Missed | False alarms | Precision | Recall | F1 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in d["classes"]:
        if c["support"] == 0 and c["fp"] == 0:
            continue
        lines.append(
            f"| `{c['class']}` | {c['category']} | {c['support']} | {c['tp']} | {c['fn']} | "
            f"{c['fp']} | {c['precision']:.3f} | {c['recall']:.3f} | {c['f1']:.3f} |"
        )
    lines += [
        "",
        "## Links",
        "",
        "| Kind | Expected | Found | Precision | Recall |",
        "|---|---:|---:|---:|---:|",
    ]
    for kind, v in d["links"].items():
        lines.append(
            f"| {kind} | {v['expected']} | {v['found']} "
            f"| {v['precision']:.4f} | {v['recall']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def check_floors(card: Scorecard, floors: dict) -> list[str]:
    """Return a list of failures; empty means every floor holds.

    Per-class floors apply only to classes with at least ``min_support`` cases, because one miss
    in a class of twenty moves recall by five points and says little on its own.
    """
    failures: list[str] = []
    d = card.to_dict()["summary"]
    if d["error_micro_precision"] < floors["micro_precision_min"]:
        failures.append(
            f"error precision {d['error_micro_precision']:.4f} < {floors['micro_precision_min']}"
        )
    if d["error_micro_recall"] < floors["micro_recall_min"]:
        failures.append(
            f"error recall {d['error_micro_recall']:.4f} < {floors['micro_recall_min']}"
        )
    for c in card.error_classes():
        if c.support < floors["min_support"]:
            continue
        if c.recall < floors["class_recall_min"]:
            failures.append(f"{c.name}: recall {c.recall:.3f} < {floors['class_recall_min']}")
        if c.precision < floors["class_precision_min"]:
            failures.append(
                f"{c.name}: precision {c.precision:.3f} < {floors['class_precision_min']}"
            )
    for kind in ("ledger_txn", "payout_bank"):
        link, floor = card.links[kind], floors[f"link_{kind}_min"]
        for metric in ("precision", "recall"):
            if link[metric] < floor:
                failures.append(f"links/{kind}: {metric} {link[metric]:.4f} < {floor}")
    if card.benign_false_alarm_rate > floors["benign_false_alarm_max"]:
        failures.append(
            f"benign false-alarm rate {card.benign_false_alarm_rate:.2%} "
            f"> {floors['benign_false_alarm_max']:.2%}"
        )
    for c in card.classes:  # a class the answer key never injects must not appear as an error
        if c.support == 0 and c.fp > 0 and c.category == "error":
            failures.append(
                f"{c.name}: {c.fp} error finding(s) of a class with no injected defects"
            )
    return failures

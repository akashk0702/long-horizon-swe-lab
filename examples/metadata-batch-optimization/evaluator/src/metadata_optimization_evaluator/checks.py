"""Assertions depend only on public outputs, errors, and collaborator invocations."""

import importlib
import json
import unittest
from collections import Counter
from copy import deepcopy
from typing import Any, Protocol


class EncodedRepository(Protocol):
    def get_encoded(self, profile_id: str) -> str: ...


def encoded(category: str = "events", version: int = 1, **changes: object) -> str:
    value = {
        "category": category,
        "version": version,
        "labels": ["ready", "café"],
        "required_fields": ["amount"],
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False)


class CountingRepository:
    def __init__(self, backing: EncodedRepository) -> None:
        self.backing = backing
        self.calls: list[str] = []

    def get_encoded(self, profile_id: str) -> str:
        self.calls.append(profile_id)
        return self.backing.get_encoded(profile_id)


class CountingDecoder:
    def __init__(self, backing: Any) -> None:
        self.backing = backing
        self.calls: list[str] = []

    def decode(self, profile_id: str, value: str) -> Any:
        self.calls.append(profile_id)
        return self.backing.decode(profile_id, value)


class MetadataContract(unittest.TestCase):
    def setUp(self) -> None:
        self.api = importlib.import_module("metadata_pipeline")
        self.backing = self.api.InMemoryProfileRepository(
            {
                "p": encoded(),
                "q": encoded("archive", 2),
            }
        )
        self.repository = CountingRepository(self.backing)
        self.decoder = CountingDecoder(self.api.JsonProfileDecoder())
        self.processor = self.api.BatchProcessor(self.repository, self.decoder)

    def record(self, key: str = "r", profile: str = "p", amount: int = 1) -> Any:
        return self.api.InputRecord(key, profile, {"amount": amount, "nested": {"items": [amount]}})

    def assert_record(self, actual: Any, record: Any, category: str, version: int) -> None:
        self.assertEqual(actual.record_id, record.record_id)
        self.assertEqual(actual.profile_id, record.profile_id)
        self.assertEqual(actual.payload, record.payload)
        self.assertEqual(actual.category, category)
        self.assertEqual(actual.version, version)
        self.assertEqual(actual.labels, ["ready", "café"])

    def test_functional_empty(self) -> None:
        self.assertEqual(self.processor.enrich([]), [])
        self.assertEqual(self.repository.calls, [])
        self.assertEqual(self.decoder.calls, [])

    def test_functional_single(self) -> None:
        record = self.record()
        output = self.processor.enrich([record])
        self.assertEqual(len(output), 1)
        self.assert_record(output[0], record, "events", 1)
        self.backing.set_encoded("p", encoded(" spaced ", labels=["x", "x"]))
        nullable = self.api.InputRecord("nullable", "p", {"amount": None})
        preserved = self.processor.enrich([nullable])[0]
        self.assertEqual(preserved.payload, {"amount": None})
        self.assertEqual((preserved.category, preserved.labels), (" spaced ", ["x", "x"]))
        self.backing.set_encoded("p", encoded(labels=[], required_fields=[]))
        empty = self.processor.enrich([self.api.InputRecord("empty", "p", {})])[0]
        self.assertEqual((empty.payload, empty.labels), ({}, []))

    def test_functional_repeated_profile(self) -> None:
        records = [self.record(str(i), amount=i) for i in range(11)]
        output = self.processor.enrich(records)
        self.assertEqual(len(output), len(records))
        for actual, record in zip(output, records, strict=True):
            self.assert_record(actual, record, "events", 1)

    def test_functional_interleaved_order(self) -> None:
        records = [self.record(str(i), "p" if i % 2 else "q", i) for i in range(9)]
        output = self.processor.enrich(records)
        self.assertEqual(len(output), len(records))
        for actual, record in zip(output, records, strict=True):
            category, version = ("events", 1) if record.profile_id == "p" else ("archive", 2)
            self.assert_record(actual, record, category, version)

    def test_functional_independent_payloads(self) -> None:
        first, second = self.record("a", amount=3), self.record("b", amount=8)
        output = self.processor.enrich([first, second])
        self.assert_record(output[0], first, "events", 1)
        self.assert_record(output[1], second, "events", 1)

    def test_functional_missing_profile(self) -> None:
        with self.assertRaises(self.api.MissingProfileError) as caught:
            self.processor.enrich([self.record(profile="absent")])
        self.assertEqual(caught.exception.profile_id, "absent")
        self.assertEqual(str(caught.exception), "Profile not found: absent")

    def test_functional_malformed_json(self) -> None:
        self.backing.set_encoded("p", "{")
        with self.assertRaises(self.api.ProfileDecodeError) as caught:
            self.processor.enrich([self.record()])
        self.assertEqual(caught.exception.profile_id, "p")
        self.assertEqual(str(caught.exception), "Invalid JSON for profile: p")

    def test_functional_invalid_structure(self) -> None:
        variants = [
            ("[]", "expected object"),
            ("{}", "expected category, version, labels, required_fields"),
            (encoded(category=" "), "category must be a nonblank string"),
            (encoded(version=True), "version must be a positive integer"),
            (encoded(version=0), "version must be a positive integer"),
            (encoded(labels=[4]), "labels must be a list of nonblank strings"),
            (
                encoded(required_fields="amount"),
                "required_fields must be a list of nonblank strings",
            ),
        ]
        for value, reason in variants:
            with self.subTest(reason=reason, value=value):
                self.backing.set_encoded("p", value)
                with self.assertRaises(self.api.ProfileValidationError) as caught:
                    self.processor.enrich([self.record()])
                self.assertEqual(caught.exception.profile_id, "p")
                self.assertEqual(caught.exception.reason, reason)
                self.assertEqual(str(caught.exception), f"Invalid profile p: {reason}")

    def test_functional_input_immutability(self) -> None:
        records = [self.record("a"), self.record("b", "q")]
        before = deepcopy(records)
        self.processor.enrich(records)
        self.assertEqual(records, before)

    def test_functional_repeated_calls(self) -> None:
        records = [self.record(), self.record("s", "q")]
        first = self.processor.enrich(records)
        self.assertEqual(first, self.processor.enrich(records))
        self.assertEqual(self.processor.enrich([]), [])
        self.assertEqual(first, self.processor.enrich(records))

    def test_functional_freshness_between_calls(self) -> None:
        for version in (1, 3, 2):
            self.backing.set_encoded("p", encoded("updated", version))
            output = self.processor.enrich([self.record(), self.record("s")])
            for actual in output:
                self.assertEqual((actual.category, actual.version), ("updated", version))
        self.backing.remove("p")
        with self.assertRaises(self.api.MissingProfileError):
            self.processor.enrich([self.record()])

    def test_functional_duplicate_ids(self) -> None:
        records = [
            self.record("same", "p", 2),
            self.record("same", "q", 7),
            self.record("same", "p", 9),
        ]
        output = self.processor.enrich(records)
        self.assertEqual([item.payload["amount"] for item in output], [2, 7, 9])
        self.assertEqual([item.category for item in output], ["events", "archive", "events"])

    def test_functional_outputs_own_mutable_data(self) -> None:
        record = self.record()
        first, second = self.processor.enrich([record, record])
        first.payload["nested"]["items"].append(9)
        first.labels.append("new")
        self.assertEqual(record.payload["nested"], {"items": [1]})
        self.assertEqual(second.payload["nested"], {"items": [1]})
        self.assertEqual(second.labels, ["ready", "café"])
        self.assertEqual(self.processor.enrich([record])[0].labels, ["ready", "café"])

    def test_functional_first_record_error_stops_later_resolution(self) -> None:
        self.backing.set_encoded("p", encoded(required_fields=["z", "a"]))
        bad = self.api.InputRecord("bad", "p", {})
        with self.assertRaises(self.api.RecordValidationError) as caught:
            self.processor.enrich([bad, self.record(profile="absent")])
        self.assertEqual(caught.exception.record_id, "bad")
        self.assertEqual(caught.exception.missing_fields, ("z", "a"))
        self.assertEqual(str(caught.exception), "Record bad missing fields: z, a")
        self.assertEqual(self.repository.calls, ["p"])
        self.assertEqual(self.decoder.calls, ["p"])
        self.assertEqual(bad.payload, {})

    def test_functional_first_profile_error_stops_later_resolution(self) -> None:
        self.backing.set_encoded("p", "{")
        with self.assertRaises(self.api.MissingProfileError):
            self.processor.enrich([self.record(profile="absent"), self.record()])
        self.assertEqual(self.repository.calls, ["absent"])
        self.assertEqual(self.decoder.calls, [])

    def test_functional_injected_decoder_is_authoritative(self) -> None:
        api = self.api

        class CustomDecoder:
            def decode(self, profile_id: str, value: str) -> Any:
                return api.MetadataProfile(profile_id, "custom", 12, (value,), ())

        repository = CountingRepository(api.InMemoryProfileRepository({"p": "opaque"}))
        decoder = CountingDecoder(CustomDecoder())
        output = api.BatchProcessor(repository, decoder).enrich([self.record()])
        self.assertEqual(
            (output[0].category, output[0].version, output[0].labels), ("custom", 12, ["opaque"])
        )
        self.assertEqual(repository.calls, ["p"])
        self.assertEqual(decoder.calls, ["p"])

    def large_batch(self, size: int, distinct: int) -> None:
        self.repository.calls.clear()
        self.decoder.calls.clear()
        for i in range(distinct):
            self.backing.set_encoded(f"p{i}", encoded(f"group-{i}", i + 1))
        records = [self.record(f"r{i}", f"p{i % distinct}", i) for i in range(size)]
        output = self.processor.enrich(records)
        self.assertEqual(len(output), size)
        for i, (actual, record) in enumerate(zip(output, records, strict=True)):
            self.assert_record(actual, record, f"group-{i % distinct}", i % distinct + 1)

    def test_efficiency_retrieval_per_distinct_profile(self) -> None:
        for size, distinct in ((1, 1), (19, 3), (1000, 8), (23, 23)):
            with self.subTest(size=size, distinct=distinct):
                self.large_batch(size, distinct)
                self.assertEqual(
                    Counter(self.repository.calls), Counter({f"p{i}": 1 for i in range(distinct)})
                )

    def test_efficiency_decode_per_distinct_profile(self) -> None:
        for size, distinct in ((1, 1), (19, 3), (1000, 8), (23, 23)):
            with self.subTest(size=size, distinct=distinct):
                self.large_batch(size, distinct)
                self.assertEqual(
                    Counter(self.decoder.calls), Counter({f"p{i}": 1 for i in range(distinct)})
                )

    def test_efficiency_prefix_before_error(self) -> None:
        bad = self.api.InputRecord("bad", "p", {})
        with self.assertRaises(self.api.RecordValidationError):
            self.processor.enrich(
                [self.record("a"), self.record("b"), bad, self.record(profile="q")]
            )
        self.assertEqual(self.repository.calls, ["p"])
        self.assertEqual(self.decoder.calls, ["p"])

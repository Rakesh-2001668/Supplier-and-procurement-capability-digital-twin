"""Property-based tests (TD §17 test layers, hypothesis): money rounding, GST arithmetic and HSN prefix matching, rule band
selection, MRP lot sizing/netting arithmetic, field-mapping and crypto invariants. They need no database."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st

from app.pic.platform import crypto, field_mapping, money, passwords, preconditions, rules
from app.pic.services import gst, planning, policy_sim

FAST = settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
paise = st.integers(min_value=0, max_value=10**13)
qty = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000000"), places=3, allow_nan=False, allow_infinity=False)
rate = st.sampled_from([Decimal(r) for r in ("0", "0.25", "3", "5", "12", "18", "28")])


# ---------------------------------------------------------------- money rounding
@FAST
@given(q=st.integers(min_value=1, max_value=10**6), price=paise)
def test_integer_quantities_are_exact(q, price):
    assert money.line_amount(q, price) == q * price


@FAST
@given(q=qty, price=paise)
def test_line_amount_is_half_up_within_half_a_paisa(q, price):
    exact = q * Decimal(price)
    got = money.line_amount(q, price)
    assert abs(Decimal(got) - exact) <= Decimal("0.5")
    assert got == int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@FAST
@given(a=qty, b=qty, price=paise)
def test_line_amount_is_monotonic_in_quantity(a, b, price):
    lo, hi = sorted((a, b))
    assert money.line_amount(lo, price) <= money.line_amount(hi, price)


@FAST
@given(rupees=st.decimals(min_value=0, max_value=10**9, places=2, allow_nan=False, allow_infinity=False))
def test_rupee_to_paise_round_trip(rupees):
    assert money.from_minor(money.to_minor(rupees)) == rupees


@FAST
@given(minor=st.integers(min_value=-10**12, max_value=10**12))
def test_inr_formatting_round_trips_to_the_amount(minor):
    text = money.fmt_inr(minor)
    digits = text.replace("₹", "").replace(",", "").replace("-", "")
    assert Decimal(digits) == abs(money.from_minor(minor)) and text.startswith("-") == (minor < 0)


# ---------------------------------------------------------------- GST arithmetic and HSN matching
@FAST
@given(net=paise, r=rate)
def test_gst_is_within_half_a_paisa_and_split_halves_differ_by_at_most_two_paise(net, r):
    total = money.tax_amount(net, r)
    assert abs(Decimal(total) - Decimal(net) * r / 100) <= Decimal("0.5")
    half = money.tax_amount(net, r / 2)  # CGST = SGST = half the rate on an intra-state supply
    assert abs(total - 2 * half) <= 1


@FAST
@given(net=paise, extra=st.integers(min_value=0, max_value=10**9), r=rate)
def test_gst_is_monotonic_in_the_net_amount(net, extra, r):
    assert money.tax_amount(net, r) <= money.tax_amount(net + extra, r)


@FAST
@given(code=st.text(alphabet="0123456789", min_size=2, max_size=8), prefixes=st.lists(st.text(alphabet="0123456789", min_size=2, max_size=8), min_size=1, max_size=4))
def test_hsn_match_length_is_the_longest_matching_prefix_and_excludes_win(code, prefixes):
    entry = gst.Entry(tuple(prefixes), (), "GOODS", Decimal(18), "d", "r", "n")
    expected = max((len(p) for p in prefixes if code.startswith(p)), default=0)
    assert entry.match_length(code) == expected
    excluded = gst.Entry(tuple(prefixes), (code[:2],), "GOODS", Decimal(18), "d", "r", "n")
    assert excluded.match_length(code) == 0


@given(text=st.text(max_size=30))
def test_digits_of_keeps_only_digits(text):
    assert gst.digits_of(text) == "".join(c for c in text if c.isdigit())


# ---------------------------------------------------------------- rule band selection
@st.composite
def band_tables(draw):
    edges = sorted(draw(st.lists(st.integers(min_value=1, max_value=10**10), min_size=1, max_size=6, unique=True)))
    bands = [{"upTo": e, "chain": [f"R{i}"]} for i, e in enumerate(edges)]
    bands.append({"upTo": None, "chain": [f"R{len(edges)}"]})
    return bands


@FAST
@given(bands=band_tables(), value=st.integers(min_value=0, max_value=2 * 10**10))
def test_band_selection_is_the_first_band_that_contains_the_value(bands, value):
    rule = rules.Rule("DMN-01", "t", {"bands": bands})
    expected = next(i for i, b in enumerate(bands) if b["upTo"] is None or value <= b["upTo"])
    assert rules.band_chain(rule, value) == bands[expected]["chain"]
    assert rules.requisition_chain(rule, value, "OTHER", None, "STOCK") == bands[expected]["chain"]
    assert policy_sim._band(rule, value)[0] == expected


@FAST
@given(bands=band_tables())
def test_an_edge_value_belongs_to_the_lower_band_and_one_more_to_the_next(bands):
    rule = rules.Rule("DMN-01", "t", {"bands": bands})
    for index, band in enumerate(bands[:-1]):
        assert policy_sim._band(rule, band["upTo"])[0] == index
        assert policy_sim._band(rule, band["upTo"] + 1)[0] == index + 1


@FAST
@given(bands=band_tables(), a=st.integers(min_value=0, max_value=2 * 10**10), b=st.integers(min_value=0, max_value=2 * 10**10))
def test_band_index_never_decreases_as_the_value_grows(bands, a, b):
    rule = rules.Rule("DMN-01", "t", {"bands": bands})
    lo, hi = sorted((a, b))
    assert policy_sim._band(rule, lo)[0] <= policy_sim._band(rule, hi)[0]


# ---------------------------------------------------------------- MRP lot sizing (the arithmetic the netting hands its net requirement to)
def _material(**over):
    base = dict(lot_size_policy="LOTFORLOT", lot_size_qty=None, annual_demand=None, ordering_cost_minor=None, holding_rate=None,
                standard_price_minor=None, max_lot=None, min_lot=None, pack_size=None)
    base.update(over)
    return SimpleNamespace(**base)


@FAST
@given(net=qty, pack=st.one_of(st.none(), st.sampled_from([Decimal(x) for x in (1, 5, 12, 25, 100)])),
       minimum=st.one_of(st.none(), st.sampled_from([Decimal(x) for x in (1, 10, 50)])))
def test_lot_for_lot_covers_the_net_requirement_and_respects_minimum_and_pack_size(net, pack, minimum):
    material = _material(min_lot=minimum, pack_size=pack)
    ordered = planning.lot_size(material, net)
    assert ordered >= net
    if minimum:
        assert ordered >= minimum
    if pack:
        assert ordered % pack == 0


@FAST
@given(net=qty, fixed=st.sampled_from([Decimal(x) for x in (10, 25, 40, 100)]))
def test_fixed_lot_is_the_smallest_multiple_covering_the_net(net, fixed):
    ordered = planning.lot_size(_material(lot_size_policy="FIXED", lot_size_qty=fixed), net)
    assert ordered % fixed == 0 and ordered >= net and ordered - fixed < net


@FAST
@given(net=qty, projected=st.decimals(min_value=0, max_value=500, places=1), maximum=st.decimals(min_value=1, max_value=2000, places=0))
def test_min_max_orders_up_to_the_maximum(net, projected, maximum):
    ordered = planning.lot_size(_material(lot_size_policy="MINMAX", max_lot=maximum), net, projected=projected)
    assert ordered >= net and ordered >= maximum - projected


# ---------------------------------------------------------------- field mapping and crypto invariants
json_scalars = st.one_of(st.none(), st.booleans(), st.integers(-10**6, 10**6), st.text(max_size=12))
payloads = st.dictionaries(st.from_regex(r"[a-z][a-zA-Z0-9]{0,8}", fullmatch=True), json_scalars, max_size=8)


@FAST
@given(payload=payloads)
def test_no_rules_is_the_identity_and_the_input_is_never_modified(payload):
    snapshot = dict(payload)
    assert field_mapping.apply([], payload) == payload
    if payload:
        key = next(iter(payload))
        field_mapping.apply([{"op": "drop", "field": key}, {"op": "constant", "to": "extra", "value": 1}], payload)
    assert payload == snapshot


@FAST
@given(payload=payloads.filter(lambda p: len(p) > 0), new=st.from_regex(r"[A-Z][A-Za-z0-9]{0,8}", fullmatch=True))
def test_rename_preserves_the_value_and_removes_the_old_key(payload, new):
    old = next(iter(payload))
    assume(new not in payload)
    out = field_mapping.apply([{"op": "rename", "from": old, "to": new}], payload)
    assert out[new] == payload[old] and old not in out and len(out) == len(payload)


@FAST
@given(minor=st.integers(min_value=0, max_value=10**12))
def test_minor_to_major_formats_exactly_two_decimals(minor):
    out = field_mapping.apply([{"op": "format", "field": "v", "kind": "minor_to_major", "decimals": 2}], {"v": minor})
    assert Decimal(out["v"]) * 100 == minor and len(out["v"].split(".")[1]) == 2


@FAST
@given(plaintext=st.text(min_size=1, max_size=60), purpose=st.sampled_from(["bank", "gstin", "bid:1"]))
def test_encryption_round_trips_under_the_active_key_and_is_not_deterministic(plaintext, purpose):
    import uuid
    tenant = uuid.UUID(int=7)
    a, b = crypto.encrypt(tenant, purpose, plaintext), crypto.encrypt(tenant, purpose, plaintext)
    assert crypto.decrypt(tenant, purpose, a) == plaintext and a != b
    assert crypto.key_id_of(a) == crypto.active_key_id()


@FAST
@given(version=st.integers(1, 10**6), tags=st.lists(st.integers(1, 10**6), min_size=1, max_size=4))
def test_if_match_parsing_accepts_quoted_weak_and_listed_tags(version, tags):
    header = ", ".join(f'W/"{t}"' if i % 2 else f'"{t}"' for i, t in enumerate(tags))
    assert preconditions.parse(header) == [str(t) for t in tags]


@FAST
@given(extra=st.text(alphabet="!@#$%^&*", min_size=1, max_size=3))
def test_a_listed_password_stays_refused_with_suffixes_and_substitutions(extra):
    assert passwords.is_common("password" + extra) and passwords.is_common("P@ssw0rd" + extra) and passwords.is_common("Welcome1" + extra)


def test_the_date_used_by_documentation_examples_is_a_real_date():
    assert date(2026, 10, 30).isoformat() == "2026-10-30"

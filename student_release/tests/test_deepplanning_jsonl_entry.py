from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


EXPECTED_SHARED_POLICY = (
    "Build a cart that satisfies the shopper's requested items, quantities, "
    "and any stated delivery requirements. If the request leaves details "
    "such as size or gender unspecified, use the shopper's profile to "
    "choose suitable products. Before finishing, verify the final cart "
    "with get_cart_info and report its contents and total."
)


def _load_entry():
    spec = importlib.util.spec_from_file_location(
        "deepplanning_jsonl_entry_under_test",
        ROOT / "public_runner" / "envs" / "deepplanning_jsonl_entry.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_deepplanning_entry_parses_public_shopping_case_id():
    module = _load_entry()

    parsed = module.parse_shopping_case_id("shopping/level_1/case_12")

    assert parsed.level == 1
    assert parsed.sample_id == "12"
    assert parsed.case_dir_name == "case_12"


def test_deepplanning_entry_rejects_non_shopping_case_id():
    module = _load_entry()

    try:
        module.parse_shopping_case_id("travel/level_1/case_12")
    except ValueError as exc:
        assert "shopping/level_<1|2|3>/case_<id>" in str(exc)
    else:
        raise AssertionError("expected ValueError")


@pytest.mark.parametrize(
    ("level", "query", "expected_policy"),
    [
        (
            1,
            "  Please buy two blue shirts.\n",
            EXPECTED_SHARED_POLICY + "\n\n" + (
                "Choose the cart with the lowest total price that meets "
                "the shopper's requirements."
            ),
        ),
        (
            2,
            "  Please buy two blue shirts. My budget is between 100 and 200.\n",
            EXPECTED_SHARED_POLICY + "\n\n" + (
                "Choose the cart with the lowest total price that meets the "
                "shopper's requirements and stated budget. Respect both bounds "
                "if a budget range is given. If the item requirements can be met "
                "but no cart fits the budget, explain this and describe the "
                "lowest-priced cart that meets the other requirements, including "
                "its total."
            ),
        ),
        (
            3,
            "  Please buy two blue shirts. My budget is 200.\n",
            EXPECTED_SHARED_POLICY + "\n\n" + (
                "Compare product and coupon combinations together, including "
                "carts with no coupons. Choose the cart with the lowest final "
                "total after discounts that meets the shopper's requirements and "
                "any stated budget. Respect both bounds if a budget range is "
                "given. Use get_user_info to check which coupons the shopper "
                "owns and in what quantities. Use the shopping tools' results "
                "to determine coupon eligibility, stacking, and final prices. "
                "Apply the chosen coupons to the cart and report the coupons "
                "used and their quantities. If the item requirements can be "
                "met but no cart fits the budget, explain this and describe "
                "the cheapest cart that meets the other requirements, including "
                "its total after eligible discounts."
            ),
        ),
    ],
    ids=["level_1", "level_2", "level_3"],
)
def test_deepplanning_entry_preserves_level_policy_query_and_cart(
    tmp_path, monkeypatch, level, query, expected_policy
):
    module = _load_entry()
    benchmark_root = tmp_path / "shoppingplanning"
    data_dir = benchmark_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / f"level_{level}_query_meta.json").write_text(
        json.dumps([{"id": "12", "query": query}]), encoding="utf-8"
    )
    case_dir = benchmark_root / f"database_level{level}" / "case_12"
    case_dir.mkdir(parents=True)
    cart = {
        "items": [{"product_id": "shirt", "quantity": 2}],
        "used_coupons": [],
    }
    (case_dir / "cart.json").write_text(json.dumps(cart), encoding="utf-8")
    monkeypatch.setattr(module.DeepPlanningShoppingSession, "_load_tool_schema", lambda self: [])
    monkeypatch.setattr(
        module.DeepPlanningShoppingSession, "_load_tool_instances", lambda self, case_dir: {}
    )
    session = module.DeepPlanningShoppingSession(benchmark_root, tmp_path / "work")

    started = session.start(f"shopping/level_{level}/case_12")
    observed = session.observe()

    for observation in (started, observed):
        assert observation["domain_policy"] == expected_policy
        assert observation["query"] == query
        assert observation["cart"] == cart

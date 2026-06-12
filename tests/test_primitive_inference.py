"""Tests for primitive inference."""

from rosclaw_darwin.sources.primitive_inference import (
    enrich_objects,
    infer_object_affordances,
    infer_primitives,
)
from rosclaw_darwin.tdl.schema import ObjectSpec


class TestPrimitiveInference:
    def test_infer_pick_and_place_from_name(self):
        primitives = infer_primitives(name="Pick and place the red cube", objects=[ObjectSpec(name="cube")])
        names = [p.name for p in primitives]
        assert "Pick" in names
        assert "Place" in names

    def test_infer_open_fridge(self):
        primitives = infer_primitives(
            name="Open the fridge",
            objects=[ObjectSpec(name="fridge")],
        )
        assert any(p.name == "Open" for p in primitives)

    def test_object_affordances(self):
        assert "graspable" in infer_object_affordances("milk_bottle")
        assert "openable" in infer_object_affordances("fridge")
        assert "pressable" in infer_object_affordances("button")
        assert "surface" in infer_object_affordances("table")

    def test_enrich_objects(self):
        objs = [ObjectSpec(name="bowl"), ObjectSpec(name="door")]
        enriched = enrich_objects(objs)
        assert any("container" in str(a) for a in enriched[0].affordances)
        assert any("openable" in str(a) for a in enriched[1].affordances)

    def test_fallback_pick_place_when_objects_present(self):
        primitives = infer_primitives(name="prepare tea", objects=[ObjectSpec(name="teabag")])
        names = [p.name for p in primitives]
        assert "Pick" in names
        assert "Place" in names

    def test_bddl_like_success_conditions(self):
        primitives = infer_primitives(
            name="store groceries",
            success_conditions=["(inside ?cereal ?cabinet)", "(ontop ?milk ?counter)"],
            objects=[ObjectSpec(name="cereal"), ObjectSpec(name="cabinet")],
        )
        assert any(p.name == "Place" for p in primitives)

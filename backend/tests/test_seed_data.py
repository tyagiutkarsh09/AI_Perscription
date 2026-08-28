from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import AllergyClass, Base, BrandCatalog, Formulary, Interaction
from app.seed import ALLERGY_CLASSES, BRANDS, FORMULARY, INTERACTIONS, load_reference_data


def test_seed_reference_data_is_self_consistent():
    ingredient_names = [row["ingredient_name"] for row in FORMULARY]
    ingredients = set(ingredient_names)

    assert len(ingredient_names) == len(ingredients) == 20
    assert all(
        row["source"] or "clinician verification required" in row["notes"].lower()
        for row in FORMULARY
    )
    assert all(
        row["max_single_dose"] is not None
        or "clinician verification required" in row["notes"].lower()
        for row in FORMULARY
    )
    assert {row["ingredient"] for row in BRANDS} <= ingredients
    assert all(
        row["ingredient_a"] in ingredients
        and row["ingredient_b"] in ingredients
        and row["ingredient_a"] != row["ingredient_b"]
        for row in INTERACTIONS
    )
    assert any(
        row["class_name"] == "penicillins" and "amoxicillin" in row["members"]
        for row in ALLERGY_CLASSES
    )


def test_seed_loader_is_idempotent():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        load_reference_data(session)
        session.commit()
        load_reference_data(session)
        session.commit()

        assert {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Formulary, BrandCatalog, Interaction, AllergyClass)
        } == {
            "formulary": 20,
            "brand_catalog": 2,
            "interactions": 1,
            "allergy_classes": 1,
        }

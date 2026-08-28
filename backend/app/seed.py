from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select

from .models import AllergyClass, BrandCatalog, Formulary, Interaction


def ref_id(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"ai-prescription-tool:{kind}:{key}"))


DAILYMED = "https://dailymed.nlm.nih.gov/dailymed/search.cfm?query="
VERIFY = "Clinician verification required before use as pilot safety data."

FORMULARY = [
    {
        "ingredient_name": "paracetamol",
        "atc_class": "N02BE01",
        "max_single_dose": 1000,
        "max_daily_dose": 4000,
        "mg_per_kg": None,
        "min_age": 12,
        "max_age": None,
        "forms": ["tablet"],
        "notes": f"Adult oral label ceiling only. {VERIFY}",
        "verified_by": None,
        "verified_at": None,
        "source": (
            "FDA acetaminophen adult daily maximum: "
            "https://www.fda.gov/drugs/safe-use-over-counter-pain-relievers-and-fever-reducers/acetaminophen; "
            "DailyMed 500 mg directions (2 tablets per dose): "
            "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=14bcbaf9-76b6-f8ba-e063-6294a90a91f6"
        ),
    },
    *[
        {
            "ingredient_name": name,
            "atc_class": atc,
            "max_single_dose": None,
            "max_daily_dose": None,
            "mg_per_kg": None,
            "min_age": None,
            "max_age": None,
            "forms": forms,
            "notes": VERIFY,
            "verified_by": None,
            "verified_at": None,
            "source": f"DailyMed official-label index: {DAILYMED}{name.replace(' ', '+')}",
        }
        for name, atc, forms in [
            ("ibuprofen", "M01AE01", ["tablet", "suspension"]),
            ("amoxicillin", "J01CA04", ["capsule", "tablet", "suspension"]),
            ("azithromycin", "J01FA10", ["tablet", "suspension"]),
            ("doxycycline", "J01AA02", ["capsule", "tablet"]),
            ("cefixime", "J01DD08", ["tablet", "suspension"]),
            ("cetirizine", "R06AE07", ["tablet", "syrup"]),
            ("levocetirizine", "R06AE09", ["tablet", "solution"]),
            ("loratadine", "R06AX13", ["tablet", "syrup"]),
            ("omeprazole", "A02BC01", ["capsule", "tablet"]),
            ("pantoprazole", "A02BC02", ["tablet"]),
            ("metformin", "A10BA02", ["tablet"]),
            ("amlodipine", "C08CA01", ["tablet"]),
            ("losartan", "C09CA01", ["tablet"]),
            ("salbutamol", "R03AC02", ["inhaler", "tablet", "syrup"]),
            ("budesonide", "R03BA02", ["inhaler", "nebuliser suspension"]),
            ("montelukast", "R03DC03", ["tablet"]),
            ("ondansetron", "A04AA01", ["tablet", "solution"]),
            ("diclofenac", "M01AB05", ["tablet", "gel"]),
            ("warfarin", "B01AA03", ["tablet"]),
        ]
    ],
]

BRANDS = [
    {
        "brand_name": "Dolo-650",
        "ingredient": "paracetamol",
        "strength": "650 mg",
        "form": "tablet",
        "manufacturer": "Micro Labs Limited",
        "source": "https://www.microlabsltd.com/therapy/fever-pain-management",
    },
    {
        "brand_name": "Crocin 650",
        "ingredient": "paracetamol",
        "strength": "650 mg",
        "form": "tablet",
        "manufacturer": "Haleon",
        "source": "https://www.haleonhealthpartner.com/en-in/pain-relief/brands/crocin/products/crocin-650/",
    },
]

INTERACTIONS = [
    {
        "ingredient_a": "warfarin",
        "ingredient_b": "ibuprofen",
        "severity": "severe",
        "description": "Warfarin with an NSAID can increase bleeding risk.",
        "management": "Avoid unless specifically assessed; monitor closely if used.",
        "source": "https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=25146c2b-91dc-452a-8628-23eacd5a9f79&type=pdf",
    }
]

ALLERGY_CLASSES = [
    {
        "class_name": "penicillins",
        "members": ["amoxicillin"],
        "source": "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=13bd4214-9b7f-425b-af5f-fc1ddc678230",
    }
]


def load_reference_data(session) -> None:
    ingredient_ids = {
        row["ingredient_name"]: ref_id("ingredient", row["ingredient_name"])
        for row in FORMULARY
    }

    for row in FORMULARY:
        session.merge(Formulary(id=ingredient_ids[row["ingredient_name"]], **row))
    for row in BRANDS:
        data = {key: value for key, value in row.items() if key != "ingredient"}
        session.merge(
            BrandCatalog(
                id=ref_id("brand", row["brand_name"]),
                ingredient_id=ingredient_ids[row["ingredient"]],
                **data,
            )
        )
    for row in INTERACTIONS:
        data = {
            key: value
            for key, value in row.items()
            if key not in {"ingredient_a", "ingredient_b"}
        }
        pair = f"{row['ingredient_a']}:{row['ingredient_b']}"
        session.merge(
            Interaction(
                id=ref_id("interaction", pair),
                ingredient_a=ingredient_ids[row["ingredient_a"]],
                ingredient_b=ingredient_ids[row["ingredient_b"]],
                **data,
            )
        )
    for row in ALLERGY_CLASSES:
        session.merge(
            AllergyClass(
                id=ref_id("allergy-class", row["class_name"]),
                class_name=row["class_name"],
                member_ingredient_ids=[ingredient_ids[name] for name in row["members"]],
            )
        )


def main() -> None:
    from .database import SessionLocal

    with SessionLocal.begin() as session:
        load_reference_data(session)

    with SessionLocal() as session:
        for model in (Formulary, BrandCatalog, Interaction, AllergyClass):
            count = session.scalar(select(func.count()).select_from(model))
            print(f"{model.__tablename__}: {count}")


if __name__ == "__main__":
    main()

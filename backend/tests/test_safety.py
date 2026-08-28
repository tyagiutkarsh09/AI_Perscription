from app.safety import (
    DoseLimits,
    InteractionRule,
    Medicine,
    PatientFacts,
    evaluate,
)


PARACETAMOL_LIMITS = DoseLimits(max_single_mg=1000, max_daily_mg=4000)


def events_of_type(medicines, patient, event_type):
    return [event for event in evaluate(medicines, patient) if event.type == event_type]


def test_1300_mg_paracetamol_single_dose_is_severe():
    medicine = Medicine("paracetamol", dose_mg=1300, doses_per_day=1, limits=PARACETAMOL_LIMITS)

    events = events_of_type([medicine], PatientFacts(age=28), "dose")

    assert [(event.severity, event.medicine, event.must_acknowledge) for event in events] == [
        ("severe", "paracetamol", True)
    ]
    assert "Max 1000 mg per dose; this is 1300 mg" in events[0].message


def test_650_mg_paracetamol_twice_daily_is_under_separate_daily_limit():
    medicine = Medicine("paracetamol", dose_mg=650, doses_per_day=2, limits=PARACETAMOL_LIMITS)

    assert events_of_type([medicine], PatientFacts(age=28), "dose") == []


def test_penicillin_class_allergy_conflicts_with_amoxicillin():
    medicine = Medicine("amoxicillin", allergy_classes=("penicillins",))

    events = events_of_type(
        [medicine], PatientFacts(age=35, allergies=("penicillins",)), "allergy"
    )

    assert [(event.severity, event.medicine, event.must_acknowledge) for event in events] == [
        ("severe", "amoxicillin", True)
    ]
    assert "penicillins" in events[0].message


def test_warfarin_and_ibuprofen_have_severe_pairwise_interaction():
    medicines = [
        Medicine(
            "warfarin",
            interactions=(
                InteractionRule(
                    other="ibuprofen",
                    severity="severe",
                    description="Warfarin with an NSAID can increase bleeding risk.",
                ),
            ),
        ),
        Medicine("ibuprofen"),
    ]

    events = events_of_type(medicines, PatientFacts(age=70), "interaction")

    assert len(events) == 1
    assert events[0].severity == "severe"
    assert events[0].medicine == "warfarin + ibuprofen"
    assert events[0].must_acknowledge is True


def test_uncovered_drug_requires_manual_verification_and_never_passes():
    events = events_of_type(
        [Medicine("mysterydrug", covered=False)], PatientFacts(age=30), "uncovered"
    )

    assert len(events) == 1
    assert events[0].severity == "warning"
    assert events[0].message == "Not in safety database — verify manually."
    assert events[0].must_acknowledge is True


def test_weight_based_single_dose_limit_is_applied_when_weight_is_known():
    medicine = Medicine(
        "weightmed",
        dose_mg=600,
        limits=DoseLimits(max_mg_per_kg=10),
    )

    events = events_of_type(
        [medicine], PatientFacts(age=10, weight_kg=50), "dose"
    )

    assert len(events) == 1
    assert "500 mg weight-based limit" in events[0].message


def test_age_outside_curated_range_requires_acknowledgment():
    medicine = Medicine("agemed", limits=DoseLimits(min_age=12, max_age=65))

    events = events_of_type([medicine], PatientFacts(age=8), "age")

    assert len(events) == 1
    assert events[0].severity == "warning"
    assert events[0].must_acknowledge is True

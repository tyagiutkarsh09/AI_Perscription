from dataclasses import dataclass, field


Severity = str


@dataclass(frozen=True)
class DoseLimits:
    max_single_mg: float | None = None
    max_daily_mg: float | None = None
    max_mg_per_kg: float | None = None
    min_age: int | None = None
    max_age: int | None = None


@dataclass(frozen=True)
class InteractionRule:
    other: str
    severity: Severity
    description: str


@dataclass(frozen=True)
class Medicine:
    name: str
    dose_mg: float | None = None
    doses_per_day: float | None = None
    covered: bool = True
    limits: DoseLimits = field(default_factory=DoseLimits)
    allergy_classes: tuple[str, ...] = ()
    interactions: tuple[InteractionRule, ...] = ()


@dataclass(frozen=True)
class PatientFacts:
    age: int | None = None
    weight_kg: float | None = None
    allergies: tuple[str, ...] = ()


@dataclass(frozen=True)
class SafetyEvent:
    type: str
    severity: Severity
    message: str
    medicine: str
    must_acknowledge: bool = True


def _number(value: float) -> str:
    return f"{value:g}"


def evaluate(medicines: list[Medicine], patient: PatientFacts) -> list[SafetyEvent]:
    events: list[SafetyEvent] = []
    allergies = {allergy.casefold() for allergy in patient.allergies}

    for medicine in medicines:
        if not medicine.covered:
            events.append(
                SafetyEvent(
                    "uncovered",
                    "warning",
                    "Not in safety database — verify manually.",
                    medicine.name,
                )
            )
            continue

        limits = medicine.limits
        if medicine.dose_mg is not None:
            if limits.max_single_mg is not None and medicine.dose_mg > limits.max_single_mg:
                events.append(
                    SafetyEvent(
                        "dose",
                        "severe",
                        "Dose above usual range. "
                        f"Max {_number(limits.max_single_mg)} mg per dose; "
                        f"this is {_number(medicine.dose_mg)} mg. Reduce or acknowledge.",
                        medicine.name,
                    )
                )
            if limits.max_daily_mg is not None and medicine.doses_per_day is not None:
                daily_mg = medicine.dose_mg * medicine.doses_per_day
                if daily_mg > limits.max_daily_mg:
                    events.append(
                        SafetyEvent(
                            "dose",
                            "severe",
                            "Daily dose above usual range. "
                            f"Max {_number(limits.max_daily_mg)} mg per day; "
                            f"this is {_number(daily_mg)} mg/day. Reduce or acknowledge.",
                            medicine.name,
                        )
                    )
            if limits.max_mg_per_kg is not None and patient.weight_kg is not None:
                weight_limit = limits.max_mg_per_kg * patient.weight_kg
                if medicine.dose_mg > weight_limit:
                    events.append(
                        SafetyEvent(
                            "dose",
                            "severe",
                            "Dose above weight-based range. "
                            f"Max {_number(weight_limit)} mg weight-based limit; "
                            f"this is {_number(medicine.dose_mg)} mg. Reduce or acknowledge.",
                            medicine.name,
                        )
                    )

        if patient.age is not None and (
            (limits.min_age is not None and patient.age < limits.min_age)
            or (limits.max_age is not None and patient.age > limits.max_age)
        ):
            age_range = (
                f"{limits.min_age}+"
                if limits.max_age is None
                else f"{limits.min_age or 0}–{limits.max_age}"
            )
            events.append(
                SafetyEvent(
                    "age",
                    "warning",
                    f"Age outside curated range ({age_range} years). Verify or acknowledge.",
                    medicine.name,
                )
            )

        conflicting_class = next(
            (name for name in medicine.allergy_classes if name.casefold() in allergies),
            None,
        )
        if medicine.name.casefold() in allergies or conflicting_class:
            conflict = conflicting_class or medicine.name
            events.append(
                SafetyEvent(
                    "allergy",
                    "severe",
                    f"Allergy conflict: {medicine.name} is in {conflict}. Change or acknowledge.",
                    medicine.name,
                )
            )

    names = {medicine.name.casefold(): medicine for medicine in medicines if medicine.covered}
    seen_pairs: set[frozenset[str]] = set()
    for medicine in medicines:
        for rule in medicine.interactions:
            other = names.get(rule.other.casefold())
            pair = frozenset((medicine.name.casefold(), rule.other.casefold()))
            if other is None or pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            events.append(
                SafetyEvent(
                    "interaction",
                    rule.severity,
                    f"{rule.description} Review or acknowledge.",
                    f"{medicine.name} + {other.name}",
                )
            )

    return events

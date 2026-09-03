import { useEffect, useMemo, useRef, useState } from "react";

const emptyPatient = {
  name: "",
  age: "",
  sex: "",
  weight_kg: "",
  contact: "",
  patient_id: "",
};

const emptyDoctor = {
  name: "",
  registration_no: "",
};

const emptyMed = {
  brand: "",
  generic: "",
  strength: "",
  form: "",
  route: "oral",
  dose: "",
  frequency: "",
  duration: "",
  instructions: "",
};

const safetyLabels = {
  interaction: "Interaction",
  allergy: "Allergy",
  dose: "Dose",
  age: "Age",
};

const rowOrder = ["interaction", "allergy", "dose", "age"];

function formatTimestamp(value) {
  if (!value) {
    return "Pending";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    day: "2-digit",
    month: "short",
  }).format(date);
}

function getSeverityRank(severity) {
  if (severity === "severe") {
    return 3;
  }
  if (severity === "warning" || severity === "warn") {
    return 2;
  }
  if (severity === "unknown" || severity === "uncovered") {
    return 1;
  }
  return 0;
}

function getRowState(events) {
  if (!events.length) {
    return {
      tone: "safe",
      icon: "✓",
      heading: "PASS",
      summary: "No issues flagged",
      detail: "Checked in current draft",
    };
  }

  const unresolved = events.filter((event) => !event.acknowledged);
  const acknowledged = events.filter((event) => event.acknowledged);
  const highest = [...unresolved, ...acknowledged].sort(
    (left, right) => getSeverityRank(right.severity) - getSeverityRank(left.severity),
  )[0];
  const tone = highest?.severity === "severe"
    ? "severe"
    : highest?.severity === "unknown" || highest?.severity === "uncovered"
      ? "unknown"
      : "warn";

  if (unresolved.length) {
    return {
      tone,
      icon: tone === "severe" ? "!" : tone === "unknown" ? "?" : "▲",
      heading: tone === "severe" ? "SEVERE" : tone === "unknown" ? "UNCOVERED" : "WARNING",
      summary: unresolved.length === 1 ? "1 unresolved" : `${unresolved.length} unresolved`,
      detail: unresolved[0].message,
    };
  }

  const latest = acknowledged[acknowledged.length - 1];
  return {
    tone: "unknown",
    icon: "✓",
    heading: "ACKNOWLEDGED",
    summary: `Acknowledged by ${latest.acknowledged_by || "doctor"}`,
    detail: latest.acknowledged_reason
      ? `${formatTimestamp(latest.acknowledged_at)} · ${latest.acknowledged_reason}`
      : formatTimestamp(latest.acknowledged_at),
  };
}

function normalizeEvent(event) {
  return {
    ...event,
    severity: event.severity || event.type || "warning",
    acknowledged_by: event.acknowledged_by || event.doctor_name || "",
    acknowledged_at: event.acknowledged_at || event.updated_at || "",
    acknowledged_reason: event.acknowledged_reason || event.reason || "",
  };
}

function Field({ label, value, mono = false, wash = false }) {
  return (
    <div className={`field ${wash ? "field--wash" : ""}`}>
      <span className="field-label">{label}</span>
      <span className={mono ? "field-value field-value--mono" : "field-value"}>{value}</span>
    </div>
  );
}

function MedicineCard({ medicine, locked, onChange, brands }) {
  const uncovered = !medicine.ingredient;

  const input = (label, field, mono = false) => (
    field === "brand" ? (
      <label className="field field--editable" key={field}>
        <span className="field-label">{label}</span>
        <select value={medicine.brand || ""} onChange={(event) => onChange(field, event.target.value)} disabled={locked}>
          <option value="">Generic only</option>
          {brands.map((brand) => <option key={brand.brand_name} value={brand.brand_name}>{brand.brand_name}</option>)}
        </select>
      </label>
    ) : (
    <label className={`field field--editable ${mono ? "field--mono" : ""}`}>
      <span className="field-label">{label}</span>
      <input
        value={medicine[field] || ""}
        onChange={(event) => onChange(field, event.target.value)}
        disabled={locked}
      />
    </label>
    )
  );

  return (
    <article className="rx-card">
      <div className="rx-card__topline">
        <span className="eyebrow">Rx item</span>
        <span className={`rx-flag ${uncovered ? "rx-flag--unknown" : "rx-flag--accent"}`}>
          {uncovered ? "Needs manual verification" : "AI-staged"}
        </span>
      </div>
      <div className="rx-grid">
        {input("Ingredient", "ingredient", !uncovered)}
        {input("Brand", "brand")}
        {input("Strength", "strength", true)}
        {input("Form", "form")}
        {input("Route", "route")}
        {input("Dose", "dose", true)}
        {input("Frequency", "frequency", true)}
        {input("Duration", "duration", true)}
        <Field label="Single dose" value={medicine.single_dose_mg ? `${medicine.single_dose_mg} mg` : "Not calculated"} mono />
        <Field label="Daily total" value={medicine.daily_dose_mg ? `${medicine.daily_dose_mg} mg/day` : "Not calculated"} mono />
      </div>
      <div className="rx-instructions">
        <span className="field-label">Instructions</span>
        <textarea
          rows="2"
          value={medicine.instructions || ""}
          onChange={(event) => onChange("instructions", event.target.value)}
          disabled={locked}
          placeholder="No patient instructions captured."
        />
      </div>
      <div className="rx-card__footer">
        <span className="rx-evidence">{locked ? "Locked signed item" : "Evidence link pending transcript integration"}</span>
        {uncovered ? (
          <span className="inline-banner inline-banner--unknown">Not in safety DB - verify manually.</span>
        ) : null}
      </div>
    </article>
  );
}

export default function App() {
  const [mode, setMode] = useState("manual");
  const [catalog, setCatalog] = useState({ brands: [], generics: [] });
  const [manualMeds, setManualMeds] = useState([{ ...emptyMed }]);
  const [patient, setPatient] = useState(emptyPatient);
  const [doctor, setDoctor] = useState(emptyDoctor);
  const [dictation, setDictation] = useState("");
  const [diagnosis, setDiagnosis] = useState("");
  const [draft, setDraft] = useState(null);
  const [events, setEvents] = useState([]);
  const [isDrafting, setIsDrafting] = useState(false);
  const [isAcknowledging, setIsAcknowledging] = useState(false);
  const [isSigning, setIsSigning] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [showAckSheet, setShowAckSheet] = useState(false);
  const [ackReason, setAckReason] = useState("");
  const [selectedEventIds, setSelectedEventIds] = useState([]);
  const [statusMessage, setStatusMessage] = useState("Ready for dictation review.");
  const [errorMessage, setErrorMessage] = useState("");
  const ackHeadingRef = useRef(null);
  const recorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  const unresolvedEvents = useMemo(
    () => events.filter((event) => event.must_acknowledge && !event.acknowledged),
    [events],
  );

  const groupedRows = useMemo(() => {
    const grouped = Object.fromEntries(rowOrder.map((key) => [key, []]));
    events.forEach((event) => {
      const key = rowOrder.includes(event.type) ? event.type : "dose";
      grouped[key].push(event);
    });
    return rowOrder.map((key) => ({
      key,
      label: safetyLabels[key],
      events: grouped[key],
      row: getRowState(grouped[key]),
    }));
  }, [events]);

  const coverage = useMemo(() => {
    const medicines = draft?.medicines || [];
    if (!medicines.length) {
      return { total: 0, linked: 0, label: "0 of 0 medicines linked", percent: 0, warn: false };
    }
    return {
      total: medicines.length,
      linked: 0,
      label: `0 of ${medicines.length} linked · ${medicines.length} missing context`,
      percent: 0,
      warn: true,
    };
  }, [draft]);

  useEffect(() => {
    if (showAckSheet) {
      ackHeadingRef.current?.focus();
    }
  }, [showAckSheet]);

  useEffect(() => {
    fetch("/api/catalog")
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => data && setCatalog(data))
      .catch(() => {});
  }, []);

  function updatePatient(field, value) {
    setPatient((current) => ({ ...current, [field]: value }));
  }

  function updateDoctor(field, value) {
    setDoctor((current) => ({ ...current, [field]: value }));
  }

  function updateMed(index, changes) {
    setManualMeds((current) =>
      current.map((row, position) => (position === index ? { ...row, ...changes } : row)),
    );
  }

  function selectBrand(index, brandName) {
    const brand = catalog.brands.find((entry) => entry.brand_name === brandName);
    updateMed(
      index,
      brand
        ? { brand: brand.brand_name, generic: brand.ingredient, strength: brand.strength, form: brand.form }
        : { brand: "" },
    );
  }

  function addMed() {
    setManualMeds((current) => [...current, { ...emptyMed }]);
  }

  function removeMed(index) {
    setManualMeds((current) =>
      current.length === 1 ? current : current.filter((_, position) => position !== index),
    );
  }

  function applyDraft(data, fallbackDiagnosis = "") {
    setDraft(data);
    setPatient(data.patient || patient);
    setDiagnosis(data.diagnosis || fallbackDiagnosis);
    setEvents((data.safety_events || []).map(normalizeEvent));
    setSelectedEventIds([]);
    setAckReason("");
    setShowAckSheet(false);
    setIsDirty(false);
    setStatusMessage("Draft staged. Review required before signing.");
  }

  async function saveEditedDraft() {
    if (!draft?.prescription_id || locked || !isDirty) return true;
    setIsSaving(true);
    try {
      const response = await fetch(`/api/prescriptions/${draft.prescription_id}/draft`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          diagnosis,
          medicines: draft.medicines.map(({ id, ...medicine }) => ({
            id,
            brand: medicine.brand || null,
            generic: medicine.ingredient || null,
            strength: medicine.strength || null,
            form: medicine.form || null,
            route: medicine.route || null,
            dose: medicine.dose || null,
            frequency: medicine.frequency || null,
            duration: medicine.duration || null,
            instructions: medicine.instructions || null,
          })),
        }),
      });
      if (!response.ok) throw new Error(`Save draft failed (${response.status})`);
      applyDraft(await response.json(), diagnosis);
      setStatusMessage("Draft saved and safety rechecked.");
      return true;
    } catch (error) {
      setErrorMessage(error.message || "Draft could not be saved.");
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  function updateStagedMedicine(index, field, value) {
    setDraft((current) => ({
      ...current,
      medicines: current.medicines.map((medicine, position) =>
        position === index ? { ...medicine, [field]: value } : medicine,
      ),
    }));
    setIsDirty(true);
  }

  async function finishRecording() {
    if (!recorderRef.current) return;
    recorderRef.current.stop();
    setIsRecording(false);
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setErrorMessage("Audio recording is unavailable. Paste the transcript instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => event.data.size && audioChunksRef.current.push(event.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        setIsDrafting(true);
        setErrorMessage("");
        try {
          const body = new FormData();
          body.append("audio", new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" }), "dictation.webm");
          body.append("patient", JSON.stringify(patient));
          body.append("doctor", JSON.stringify(doctor));
          const response = await fetch("/api/mode2/audio-draft", { method: "POST", body });
          if (!response.ok) throw new Error(`Audio draft failed (${response.status})`);
          applyDraft(await response.json());
        } catch (error) {
          setErrorMessage(error.message || "Audio could not be transcribed. Paste the transcript instead.");
        } finally {
          setIsDrafting(false);
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
      setStatusMessage("Recording dictation...");
    } catch (error) {
      setErrorMessage(error.message || "Microphone access was not granted. Paste the transcript instead.");
    }
  }

  async function createManualDraft(event) {
    event.preventDefault();
    setIsDrafting(true);
    setErrorMessage("");
    setStatusMessage("Running safety checks on the generic ingredients.");

    try {
      const response = await fetch("/api/manual/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          diagnosis,
          patient,
          doctor,
          medicines: manualMeds.map((row) => ({
            ...row,
            brand: row.brand || null,
            generic: row.generic || null,
          })),
        }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(
          detail?.detail
            ? `Draft rejected: ${JSON.stringify(detail.detail)}`
            : `Draft request failed (${response.status})`,
        );
      }
      const data = await response.json();
      applyDraft(data, diagnosis);
    } catch (error) {
      setErrorMessage(error.message || "Draft could not be created.");
      setStatusMessage("Draft failed.");
    } finally {
      setIsDrafting(false);
    }
  }

  async function createDraft(event) {
    event.preventDefault();
    setIsDrafting(true);
    setErrorMessage("");
    setStatusMessage("Reviewing dictation and building the draft.");

    try {
      const response = await fetch("/api/mode2/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: dictation,
          patient,
          doctor,
        }),
      });
      if (!response.ok) {
        throw new Error(`Draft request failed (${response.status})`);
      }
      const data = await response.json();
      applyDraft(data);
    } catch (error) {
      setErrorMessage(error.message || "Draft could not be created.");
      setStatusMessage("Draft failed.");
    } finally {
      setIsDrafting(false);
    }
  }

  async function signPrescription() {
    if (!draft?.prescription_id) {
      setErrorMessage("Create a draft before signing.");
      return;
    }

    if (!(await saveEditedDraft())) return;
    setIsSigning(true);
    setErrorMessage("");

    try {
      const response = await fetch(`/api/prescriptions/${draft.prescription_id}/sign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          doctor_name: doctor.name,
          registration_no: doctor.registration_no,
        }),
      });

      if (response.status === 409) {
        const data = await response.json();
        const nextEvents = (data.safety_events || []).map(normalizeEvent);
        setEvents(nextEvents);
        setSelectedEventIds(nextEvents.filter((item) => item.must_acknowledge && !item.acknowledged).map((item) => item.id));
        setShowAckSheet(true);
        setStatusMessage("Acknowledgment required before signing proceeds.");
        return;
      }

      if (!response.ok) {
        throw new Error(`Sign request failed (${response.status})`);
      }

      const data = await response.json();
      setDraft((current) => ({
        ...current,
        signed: data.signed,
        signed_at: data.signed_at,
        pdf_url: data.pdf_url,
      }));
      setShowAckSheet(false);
      setStatusMessage("Prescription signed.");
    } catch (error) {
      setErrorMessage(error.message || "Prescription could not be signed.");
    } finally {
      setIsSigning(false);
    }
  }

  async function acknowledgeWarnings() {
    if (!draft?.prescription_id || !selectedEventIds.length || !ackReason.trim()) {
      setErrorMessage("Select warnings and enter a reason.");
      return;
    }

    setIsAcknowledging(true);
    setErrorMessage("");

    try {
      const response = await fetch(`/api/prescriptions/${draft.prescription_id}/acknowledge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_ids: selectedEventIds,
          doctor_name: doctor.name,
          registration_no: doctor.registration_no,
          reason: ackReason.trim(),
        }),
      });
      if (!response.ok) {
        throw new Error(`Acknowledge request failed (${response.status})`);
      }
      const data = await response.json();
      setEvents((data.safety_events || []).map(normalizeEvent));
      setStatusMessage("Warnings acknowledged. You can sign now.");
      setShowAckSheet(false);
      setAckReason("");
      setSelectedEventIds([]);
    } catch (error) {
      setErrorMessage(error.message || "Warnings could not be acknowledged.");
    } finally {
      setIsAcknowledging(false);
    }
  }

  function toggleEvent(eventId) {
    setSelectedEventIds((current) =>
      current.includes(eventId) ? current.filter((id) => id !== eventId) : [...current, eventId],
    );
  }

  const locked = Boolean(draft?.signed);

  return (
    <main className="app-shell">
      <section className="top-banner" aria-live="polite">
        <span className="top-banner__status">{statusMessage}</span>
        {errorMessage ? <span className="top-banner__error">{errorMessage}</span> : null}
      </section>

      <div className="console-layout">
        <aside className="left-rail">
          <div className="panel">
            <span className="eyebrow">Mode</span>
            <div className="mode-switch" role="group" aria-label="Prescribing mode">
              <button
                type="button"
                className={`mode-tab ${mode === "manual" ? "mode-tab--active" : ""}`}
                aria-pressed={mode === "manual"}
                onClick={() => setMode("manual")}
                disabled={locked}
              >
                Manual
              </button>
              <button
                type="button"
                className={`mode-tab ${mode === "voice" ? "mode-tab--active" : ""}`}
                aria-pressed={mode === "voice"}
                onClick={() => setMode("voice")}
                disabled={locked}
              >
                Voice
              </button>
            </div>
            <p className="muted">
              {mode === "manual"
                ? "Hand-enter the prescription. Safety runs on the resolved generic."
                : "Paste transcript. Extraction stages a draft you review before signing."}
            </p>
          </div>

          <div className="panel">
            <span className="eyebrow">Patient</span>
            <div className="form-grid">
              {Object.entries(emptyPatient).map(([field]) => (
                <label key={field} className="input-group">
                  <span>{field.replace("_kg", " (kg)").replace("_id", " ID").replace(/_/g, " ")}</span>
                  <input
                    value={patient[field]}
                    onChange={(event) => updatePatient(field, event.target.value)}
                    disabled={locked}
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="panel">
            <span className="eyebrow">Doctor</span>
            <div className="form-grid">
              <label className="input-group">
                <span>Name</span>
                <input value={doctor.name} onChange={(event) => updateDoctor("name", event.target.value)} disabled={locked} />
              </label>
              <label className="input-group">
                <span>Registration no</span>
                <input
                  value={doctor.registration_no}
                  onChange={(event) => updateDoctor("registration_no", event.target.value)}
                  disabled={locked}
                />
              </label>
            </div>
          </div>
        </aside>

        <section className="center-column">
          <header className="panel patient-header">
            <div>
              <span className="eyebrow">Encounter</span>
              <h1>{patient.name || "Patient name pending"}</h1>
            </div>
            <div className="header-meta">
              <span>{patient.age || "--"} y</span>
              <span>{patient.sex || "--"}</span>
              <span>{patient.weight_kg || "--"} kg</span>
              <span>{draft?.encounter_id || "ENC pending"}</span>
              <span>{draft?.signed_at ? formatTimestamp(draft.signed_at) : "Unsigned"}</span>
            </div>
          </header>

          {mode === "voice" ? (
            <form className="panel dictation-panel" onSubmit={createDraft}>
              <span className="eyebrow">Dictation</span>
              <label className="input-group">
                <span>Clinical text</span>
                <textarea
                  rows="7"
                  value={dictation}
                  onChange={(event) => setDictation(event.target.value)}
                  placeholder="Patient has a headache; prescribe the selected brand twice daily for 3 days."
                  disabled={locked}
                />
              </label>
              <div className="dictation-actions">
                <button className="button button--accent" type="button" onClick={isRecording ? finishRecording : startRecording} disabled={isDrafting || locked}>
                  {isRecording ? "Stop recording" : "Record dictation"}
                </button>
                <button className="button button--ghost" type="submit" disabled={isDrafting || locked}>
                {isDrafting ? "Building draft..." : "Create draft"}
                </button>
              </div>
            </form>
          ) : (
            <form className="panel manual-panel" onSubmit={createManualDraft}>
              <span className="eyebrow">Manual entry</span>
              <label className="input-group">
                <span>Diagnosis</span>
                <input
                  value={diagnosis}
                  onChange={(event) => setDiagnosis(event.target.value)}
                  placeholder="e.g. viral fever"
                  disabled={locked}
                />
              </label>

              {manualMeds.map((row, index) => (
                <fieldset key={index} className="manual-med" disabled={locked}>
                  <legend>
                    Medicine {index + 1}
                    {manualMeds.length > 1 ? (
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => removeMed(index)}
                        aria-label={`Remove medicine ${index + 1}`}
                      >
                        Remove
                      </button>
                    ) : null}
                  </legend>
                  <div className="form-grid">
                    <label className="input-group">
                      <span>Brand (from catalog)</span>
                      <select value={row.brand} onChange={(event) => selectBrand(index, event.target.value)}>
                        <option value="">— generic only —</option>
                        {catalog.brands.map((brand) => (
                          <option key={brand.brand_name} value={brand.brand_name}>
                            {brand.brand_name} · {brand.ingredient}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="input-group">
                      <span>Generic ingredient</span>
                      <input
                        list="generic-options"
                        value={row.generic}
                        onChange={(event) => updateMed(index, { generic: event.target.value })}
                        placeholder="resolved for safety"
                      />
                    </label>
                    <label className="input-group">
                      <span>Strength</span>
                      <input value={row.strength} onChange={(event) => updateMed(index, { strength: event.target.value })} />
                    </label>
                    <label className="input-group">
                      <span>Form</span>
                      <input value={row.form} onChange={(event) => updateMed(index, { form: event.target.value })} />
                    </label>
                    <label className="input-group">
                      <span>Route</span>
                      <input value={row.route} onChange={(event) => updateMed(index, { route: event.target.value })} />
                    </label>
                    <label className="input-group">
                      <span>Dose</span>
                      <input
                        value={row.dose}
                        onChange={(event) => updateMed(index, { dose: event.target.value })}
                        placeholder="1 tablet / 650 mg"
                      />
                    </label>
                    <label className="input-group">
                      <span>Frequency</span>
                      <input
                        value={row.frequency}
                        onChange={(event) => updateMed(index, { frequency: event.target.value })}
                        placeholder="twice daily"
                      />
                    </label>
                    <label className="input-group">
                      <span>Duration</span>
                      <input
                        value={row.duration}
                        onChange={(event) => updateMed(index, { duration: event.target.value })}
                        placeholder="3 days"
                      />
                    </label>
                    <label className="input-group manual-med__wide">
                      <span>Instructions</span>
                      <input value={row.instructions} onChange={(event) => updateMed(index, { instructions: event.target.value })} />
                    </label>
                  </div>
                </fieldset>
              ))}

              <div className="manual-actions">
                <button className="button button--ghost" type="button" onClick={addMed} disabled={locked}>
                  Add medicine
                </button>
                <button className="button button--accent" type="submit" disabled={isDrafting || locked}>
                  {isDrafting ? "Checking safety..." : "Create draft"}
                </button>
              </div>
              <datalist id="generic-options">
                {catalog.generics.map((generic) => (
                  <option key={generic} value={generic} />
                ))}
              </datalist>
            </form>
          )}

          {mode === "voice" ? (
            <section className="panel">
              <span className="eyebrow">Diagnosis</span>
              <textarea
                rows="3"
                value={diagnosis}
                onChange={(event) => { setDiagnosis(event.target.value); setIsDirty(true); }}
                placeholder="Editable diagnosis appears here."
                disabled={locked || !draft}
              />
            </section>
          ) : null}

          <section className="panel">
            <div className="section-header">
              <div>
                <span className="eyebrow">Prescription</span>
                <h2>AI-staged draft</h2>
              </div>
              {coverage.total ? (
                <div className="coverage">
                  <span className={`coverage__label ${coverage.warn ? "coverage__label--warn" : ""}`}>{coverage.label}</span>
                  <div className="coverage__track" aria-hidden="true">
                    <span className="coverage__fill" style={{ width: `${coverage.percent}%` }} />
                  </div>
                </div>
              ) : null}
            </div>

            {draft?.medicines?.length ? (
              <div className="rx-list">
                {draft.medicines.map((medicine, index) => (
                  <MedicineCard
                    key={medicine.id || `${medicine.brand}-${medicine.ingredient}`}
                    medicine={medicine}
                    locked={locked}
                    brands={catalog.brands}
                    onChange={(field, value) => updateStagedMedicine(index, field, value)}
                  />
                ))}
              </div>
            ) : (
              <p className="muted">No prescription items yet.</p>
            )}
          </section>
        </section>

        <aside className="right-rail">
          <section className="panel safety-panel">
            <div className="section-header">
              <div>
                <span className="eyebrow">Safety rail</span>
                <h2>Review before signature</h2>
              </div>
              <span className="safety-count">{unresolvedEvents.length} open</span>
            </div>
            <div className="safety-list">
              {groupedRows.map(({ key, label, events: rowEvents, row }) => (
                <article key={key} className={`safety-row safety-row--${row.tone}`}>
                  <div className="safety-row__main">
                    <span className="safety-icon" aria-hidden="true">{row.icon}</span>
                    <div>
                      <div className="safety-row__line">
                        <span className="safety-label">{label}</span>
                        <span className="safety-state">{row.heading}</span>
                      </div>
                      <p>{row.summary}</p>
                      <p className="muted">{row.detail}</p>
                    </div>
                  </div>
                  {rowEvents.filter((item) => !item.acknowledged).map((item) => (
                    <div key={item.id} className="safety-detail">
                      <p>{item.message}</p>
                      <button className="button button--ghost" type="button" onClick={() => setShowAckSheet(true)}>
                        Acknowledge
                      </button>
                    </div>
                  ))}
                </article>
              ))}
            </div>
          </section>
        </aside>
      </div>

      <div className="sign-bar">
        <div className="sign-bar__copy">
          <span className="sign-bar__icon" aria-hidden="true">⛨</span>
          <span>AI-staged draft · Review required. You are in control.</span>
        </div>
        <div className="sign-bar__actions">
          {draft?.pdf_url ? (
            <a className="button button--ghost" href={draft.pdf_url} target="_blank" rel="noreferrer">
              Open PDF
            </a>
          ) : (
            <button className="button button--ghost" type="button" onClick={saveEditedDraft} disabled={locked || isSaving || !draft}>
              {isSaving ? "Saving..." : "Save draft"}
            </button>
          )}
          <button className="button button--accent" type="button" onClick={signPrescription} disabled={isSigning}>
            {locked ? "Signed" : isSigning ? "Signing..." : "Approve & Sign"}
          </button>
        </div>
      </div>

      {showAckSheet ? (
        <div className="ack-sheet" role="dialog" aria-modal="true" aria-labelledby="ack-title">
          <div className="ack-sheet__card">
            <h2 id="ack-title" tabIndex="-1" ref={ackHeadingRef}>Acknowledgment required</h2>
            <p className="muted">Signing stays enabled. Record acknowledgment for each warning.</p>
            <div className="ack-list">
              {unresolvedEvents.map((item) => (
                <label key={item.id} className="ack-item">
                  <input
                    type="checkbox"
                    checked={selectedEventIds.includes(item.id)}
                    onChange={() => toggleEvent(item.id)}
                  />
                  <span>{item.message}</span>
                </label>
              ))}
            </div>
            <label className="input-group">
              <span>Reason</span>
              <textarea rows="3" value={ackReason} onChange={(event) => setAckReason(event.target.value)} />
            </label>
            <div className="ack-actions">
              <button className="button button--ghost" type="button" onClick={() => setShowAckSheet(false)}>
                Close
              </button>
              <button className="button button--accent" type="button" onClick={acknowledgeWarnings} disabled={isAcknowledging}>
                {isAcknowledging ? "Recording..." : "Acknowledge"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

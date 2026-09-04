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

function MedicineFields({ row, brands, onBrand, onChange, missing = [] }) {
  const cell = (label, field, placeholder = "") => (
    <label className={`input-group ${missing.includes(field) ? "input-group--missing" : ""}`} key={field}>
      <span>{label}{missing.includes(field) ? " · required" : ""}</span>
      <input
        value={row[field] || ""}
        onChange={(event) => onChange({ [field]: event.target.value })}
        placeholder={placeholder}
      />
    </label>
  );

  return (
    <div className="form-grid">
      <label className="input-group">
        <span>Brand (from catalog)</span>
        <select value={row.brand || ""} onChange={(event) => onBrand(event.target.value)}>
          <option value="">— generic only —</option>
          {brands.map((brand) => (
            <option key={brand.brand_name} value={brand.brand_name}>
              {brand.brand_name} · {brand.ingredient}
            </option>
          ))}
        </select>
      </label>
      <label className={`input-group ${missing.includes("name") ? "input-group--missing" : ""}`}>
        <span>Generic ingredient{missing.includes("name") ? " · required" : ""}</span>
        <input
          list="generic-options"
          value={row.generic || ""}
          onChange={(event) => onChange({ generic: event.target.value })}
          placeholder="resolved for safety"
        />
      </label>
      {cell("Strength", "strength")}
      {cell("Form", "form")}
      {cell("Route", "route")}
      {cell("Dose", "dose", "1 tablet / 650 mg")}
      {cell("Frequency", "frequency", "twice daily")}
      {cell("Duration", "duration", "3 days")}
      <label className="input-group manual-med__wide">
        <span>Instructions</span>
        <input
          value={row.instructions || ""}
          onChange={(event) => onChange({ instructions: event.target.value })}
        />
      </label>
    </div>
  );
}

function MedicineCard({ medicine, locked, onChange, brands }) {
  const uncovered = !medicine.ingredient;
  const evidenceIds = medicine.evidence_segment_ids || [];
  const missingContext = medicine.evidence_status === "missing_context";

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
        {medicine.evidence_status ? (
          missingContext ? (
            <span className="inline-banner inline-banner--warn">Missing context — no transcript evidence. Verify before signing.</span>
          ) : (
            <span className="rx-evidence rx-evidence--linked">Evidence: transcript {evidenceIds.join(", ")}</span>
          )
        ) : (
          <span className="rx-evidence">{locked ? "Locked signed item" : "Doctor-entered"}</span>
        )}
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
  const [recordingTarget, setRecordingTarget] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [showAckSheet, setShowAckSheet] = useState(false);
  const [ackReason, setAckReason] = useState("");
  const [selectedEventIds, setSelectedEventIds] = useState([]);
  const [statusMessage, setStatusMessage] = useState("Ready for dictation review.");
  const [errorMessage, setErrorMessage] = useState("");
  const [consentGiven, setConsentGiven] = useState(false);
  const [encounterId, setEncounterId] = useState(null);
  const [transcript, setTranscript] = useState([]);
  const [convoInput, setConvoInput] = useState("");
  const [staged, setStaged] = useState(null);
  const [missingRequired, setMissingRequired] = useState([]);
  const [commandText, setCommandText] = useState("");
  const [appliedLog, setAppliedLog] = useState([]);
  const ackHeadingRef = useRef(null);
  const stagedPayloadRef = useRef(null);
  const recorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const wsRef = useRef(null);

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
    // Evidence coverage is a Mode 3 concept — the backend sends it only for ambient drafts.
    if (draft?.coverage) {
      const { total, linked, missing, label } = draft.coverage;
      return { total, linked, label, percent: total ? Math.round((linked / total) * 100) : 0, warn: missing > 0 };
    }
    return { total: 0, linked: 0, label: "", percent: 0, warn: false };
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

  // ── hybrid voice: short commands stage fields now, dictation stages one draft at Review ──

  function stagedPayload() {
    const text = (value) => (value === "" || value === undefined ? null : value);
    const number = (value) => (value === "" || value === null || value === undefined ? null : Number(value));
    return {
      patient: {
        name: text(patient.name),
        patient_id: text(patient.patient_id),
        age: number(patient.age),
        sex: text(patient.sex),
        weight_kg: number(patient.weight_kg),
        contact: text(patient.contact),
        allergies: staged?.patient?.allergies || [],
      },
      diagnosis: text(diagnosis),
      medicines: staged?.medicines || [],
    };
  }
  stagedPayloadRef.current = stagedPayload;

  function applyStaged(data) {
    const next = data.draft;
    setStaged(next);
    setMissingRequired(data.missing_required || []);
    setDiagnosis(next.diagnosis || "");
    setPatient((current) => ({
      ...current,
      name: next.patient.name ?? "",
      patient_id: next.patient.patient_id ?? "",
      age: next.patient.age ?? "",
      sex: next.patient.sex ?? "",
      weight_kg: next.patient.weight_kg ?? "",
      contact: next.patient.contact ?? "",
    }));
    if (data.applied?.length) {
      setAppliedLog((log) => [...data.applied, ...log].slice(0, 6));
    }
    setStatusMessage(
      data.note || (data.applied?.length ? `Staged: ${data.applied.join("; ")}` : "Nothing changed."),
    );
  }

  async function postStaging(url, body) {
    setErrorMessage("");
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Voice request failed (${response.status})`);
    return response.json();
  }

  async function reviewPrescription(draftOverride) {
    setIsDrafting(true);
    try {
      const data = await postStaging("/api/voice/review", {
        draft: draftOverride || stagedPayload(),
        doctor: { name: doctor.name || null, registration_no: doctor.registration_no || null },
      });
      if (!data.ready) {
        applyStaged(data);
        setStatusMessage("Fill the marked required fields before signing.");
        return;
      }
      setStaged(null);
      setMissingRequired([]);
      applyDraft(data, diagnosis);
    } catch (error) {
      setErrorMessage(error.message || "The prescription could not be reviewed.");
    } finally {
      setIsDrafting(false);
    }
  }

  async function sendCommand(utterance) {
    if (!utterance.trim()) return;
    try {
      const data = await postStaging("/api/voice/command", {
        utterance,
        draft: stagedPayload(),
      });
      applyStaged(data);
      setCommandText("");
      if (data.action === "review") await reviewPrescription(data.draft);
    } catch (error) {
      setErrorMessage(error.message || "The command could not be applied.");
    }
  }

  async function sendDictation() {
    if (!dictation.trim()) return;
    setIsDrafting(true);
    try {
      applyStaged(await postStaging("/api/voice/dictation", { text: dictation, draft: stagedPayload() }));
      setStatusMessage("Dictation extracted. Review before signing.");
    } catch (error) {
      setErrorMessage(error.message || "The dictation could not be extracted.");
    } finally {
      setIsDrafting(false);
    }
  }

  function updateStagedField(index, changes) {
    setStaged((current) => ({
      ...current,
      medicines: current.medicines.map((row, position) =>
        position === index ? { ...row, ...changes } : row,
      ),
    }));
  }

  function selectStagedBrand(index, brandName) {
    const brand = catalog.brands.find((entry) => entry.brand_name === brandName);
    updateStagedField(
      index,
      brand
        ? { brand: brand.brand_name, generic: null, strength: brand.strength, form: brand.form }
        : { brand: null },
    );
  }

  function removeStagedMedicine(index) {
    setStaged((current) => ({
      ...current,
      medicines: current.medicines.filter((_, position) => position !== index),
    }));
  }

  function missingFieldsFor(index) {
    const prefix = `medicine ${index + 1}.`;
    return missingRequired
      .filter((entry) => entry.startsWith(prefix))
      .map((entry) => entry.slice(prefix.length));
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
    setRecordingTarget(null);
  }

  async function startRecording(target) {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setErrorMessage("Audio recording is unavailable. Type the command or transcript instead.");
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
          body.append("audio", new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" }), "utterance.webm");
          body.append("draft", JSON.stringify(stagedPayloadRef.current()));
          const url = target === "command" ? "/api/voice/audio-command" : "/api/voice/audio-dictation";
          const response = await fetch(url, { method: "POST", body });
          if (!response.ok) throw new Error(`Audio ${target} failed (${response.status})`);
          const data = await response.json();
          applyStaged(data);
          if (data.transcript) {
            setDictation((current) => (current ? `${current}\n${data.transcript}` : data.transcript));
          }
          if (data.action === "review") await reviewPrescription(data.draft);
        } catch (error) {
          setErrorMessage(error.message || "Audio could not be transcribed. Type it instead.");
        } finally {
          setIsDrafting(false);
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecordingTarget(target);
      setStatusMessage(target === "command" ? "Listening for a command..." : "Recording dictation...");
    } catch (error) {
      setErrorMessage(error.message || "Microphone access was not granted. Type it instead.");
    }
  }

  function openStream(id) {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${window.location.host}/api/mode3/encounters/${id}/stream`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.segment) {
        setTranscript((current) => [...current, data.segment]);
      } else if (data.error === "consent_required") {
        setErrorMessage("Recording blocked — consent is required.");
      }
    };
    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null;
    };
    wsRef.current = ws;
  }

  async function startAmbient() {
    if (!consentGiven) {
      setErrorMessage("Capture patient consent before recording.");
      return;
    }
    setErrorMessage("");
    try {
      const response = await fetch("/api/mode3/consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient, doctor, consent: true }),
      });
      if (!response.ok) throw new Error(`Consent could not be captured (${response.status})`);
      const data = await response.json();
      setEncounterId(data.encounter_id);
      setTranscript([]);
      setDraft(null);
      setEvents([]);
      openStream(data.encounter_id);
      setStatusMessage("Consent captured. Recording — transcript streaming live.");
    } catch (error) {
      setErrorMessage(error.message || "Could not start the ambient encounter.");
    }
  }

  function streamConversation() {
    const ws = wsRef.current;
    if (!ws) {
      setErrorMessage("Start the encounter before streaming the conversation.");
      return;
    }
    const lines = convoInput.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!lines.length) return;
    const send = () => lines.forEach((line) => ws.send(line));
    if (ws.readyState === WebSocket.OPEN) send();
    else ws.addEventListener("open", send, { once: true });
    setConvoInput("");
  }

  async function endEncounter() {
    if (!encounterId) return;
    wsRef.current?.close();
    setIsDrafting(true);
    setErrorMessage("");
    setStatusMessage("Extracting the prescription from the full conversation.");
    try {
      const response = await fetch(`/api/mode3/encounters/${encounterId}/end`, { method: "POST" });
      if (!response.ok) throw new Error(`End encounter failed (${response.status})`);
      applyDraft(await response.json());
    } catch (error) {
      setErrorMessage(error.message || "Could not extract the prescription.");
    } finally {
      setIsDrafting(false);
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
      <datalist id="generic-options">
        {catalog.generics.map((generic) => (
          <option key={generic} value={generic} />
        ))}
      </datalist>
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
              <button
                type="button"
                className={`mode-tab ${mode === "ambient" ? "mode-tab--active" : ""}`}
                aria-pressed={mode === "ambient"}
                onClick={() => setMode("ambient")}
                disabled={locked}
              >
                Ambient
              </button>
            </div>
            <p className="muted">
              {mode === "manual"
                ? "Hand-enter the prescription. Safety runs on the resolved generic."
                : mode === "ambient"
                  ? "Record the consented visit. Extraction links every medicine to the transcript."
                  : "Paste transcript. Extraction stages a draft you review before signing."}
            </p>
          </div>

          {mode === "ambient" ? (
            <div className="panel">
              <span className="eyebrow">Live transcript</span>
              {transcript.length ? (
                <div className="transcript">
                  {transcript.map((seg) => (
                    <p key={seg.id} className={`transcript-line transcript-line--${(seg.speaker || "speaker").toLowerCase()}`}>
                      <span className="transcript-speaker">{seg.speaker}</span>
                      <span>{seg.text}</span>
                    </p>
                  ))}
                </div>
              ) : (
                <p className="muted">
                  {encounterId ? "Listening — stream the conversation." : "Consent required before recording can start."}
                </p>
              )}
            </div>
          ) : null}

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
            <section className="panel dictation-panel">
              <span className="eyebrow">Voice</span>
              <p className="muted">
                Short commands update the draft as you speak. Or dictate the whole encounter and
                review one extracted draft at the end — say <code>Review prescription</code>.
              </p>
              <label className="input-group">
                <span>Command</span>
                <input
                  value={commandText}
                  onChange={(event) => setCommandText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      sendCommand(commandText);
                    }
                  }}
                  placeholder='"Add penicillin allergy." · "Change duration to 7 days." · "Review prescription."'
                  disabled={locked}
                />
              </label>
              <div className="dictation-actions">
                <button
                  className="button button--accent"
                  type="button"
                  onClick={() => (recordingTarget === "command" ? finishRecording() : startRecording("command"))}
                  disabled={isDrafting || locked || recordingTarget === "dictation"}
                >
                  {recordingTarget === "command" ? "Stop" : "Speak command"}
                </button>
                <button
                  className="button button--ghost"
                  type="button"
                  onClick={() => sendCommand(commandText)}
                  disabled={locked || !commandText.trim()}
                >
                  Apply command
                </button>
              </div>

              <label className="input-group">
                <span>Dictation</span>
                <textarea
                  rows="6"
                  value={dictation}
                  onChange={(event) => setDictation(event.target.value)}
                  placeholder="Patient name Ramesh Kumar, male, 42 years old. Diagnosis: acute pharyngitis. Prescribe the brand, one tablet twice daily for 5 days after food."
                  disabled={locked}
                />
              </label>
              <div className="dictation-actions">
                <button
                  className="button button--accent"
                  type="button"
                  onClick={() => (recordingTarget === "dictation" ? finishRecording() : startRecording("dictation"))}
                  disabled={isDrafting || locked || recordingTarget === "command"}
                >
                  {recordingTarget === "dictation" ? "Stop recording" : "Record dictation"}
                </button>
                <button
                  className="button button--ghost"
                  type="button"
                  onClick={sendDictation}
                  disabled={isDrafting || locked || !dictation.trim()}
                >
                  {isDrafting ? "Extracting..." : "Extract dictation"}
                </button>
                <button
                  className="button button--ghost"
                  type="button"
                  onClick={() => reviewPrescription()}
                  disabled={isDrafting || locked}
                >
                  End &amp; review prescription
                </button>
              </div>
              {appliedLog.length ? <p className="muted">Last changes: {appliedLog.join(" · ")}</p> : null}
            </section>
          ) : mode === "ambient" ? (
            <section className="panel ambient-panel">
              <span className="eyebrow">Ambient encounter</span>
              {encounterId ? (
                <>
                  <p className="muted">
                    Recording. Enter the conversation as it happens — one utterance per line, prefixed
                    <code> Doctor: </code>/<code> Patient: </code> — or wire a live mic to the same stream.
                  </p>
                  <label className="input-group">
                    <span>Conversation</span>
                    <textarea
                      rows="6"
                      value={convoInput}
                      onChange={(event) => setConvoInput(event.target.value)}
                      placeholder={"Doctor: Let's start Dolo 650 twice daily for 3 days.\nPatient: Okay doctor."}
                      disabled={locked}
                    />
                  </label>
                  <div className="dictation-actions">
                    <button className="button button--ghost" type="button" onClick={streamConversation} disabled={locked || !convoInput.trim()}>
                      Stream to transcript
                    </button>
                    <button className="button button--accent" type="button" onClick={endEncounter} disabled={isDrafting || locked}>
                      {isDrafting ? "Extracting draft..." : "End encounter"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p className="muted">Recording cannot start until per-encounter consent is captured.</p>
                  <label className="ack-item">
                    <input type="checkbox" checked={consentGiven} onChange={(event) => setConsentGiven(event.target.checked)} />
                    <span>Patient has consented to this visit being recorded.</span>
                  </label>
                  <div className="dictation-actions">
                    <button
                      className="button button--accent"
                      type="button"
                      onClick={startAmbient}
                      disabled={!consentGiven || !patient.name || !doctor.name || !doctor.registration_no}
                    >
                      Start encounter
                    </button>
                  </div>
                </>
              )}
            </section>
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
                  <MedicineFields
                    row={row}
                    brands={catalog.brands}
                    onBrand={(brandName) => selectBrand(index, brandName)}
                    onChange={(changes) => updateMed(index, changes)}
                  />
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
            </form>
          )}

          {mode !== "manual" ? (
            <section className="panel">
              <span className="eyebrow">Diagnosis</span>
              <textarea
                className={missingRequired.includes("diagnosis") ? "input--missing" : ""}
                rows="3"
                value={diagnosis}
                onChange={(event) => { setDiagnosis(event.target.value); setIsDirty(true); }}
                placeholder="Editable diagnosis appears here."
                disabled={locked || !(draft || staged)}
              />
            </section>
          ) : null}

          {staged && !draft ? (
            <section className="panel">
              <div className="section-header">
                <div>
                  <span className="eyebrow">Staged by voice</span>
                  <h2>AI-staged draft · not safety-checked yet</h2>
                </div>
                <span className="safety-count">{missingRequired.length} required missing</span>
              </div>
              <p className="muted">
                Allergies: {staged.patient.allergies?.length ? staged.patient.allergies.join(", ") : "none recorded"}
              </p>
              {missingRequired.length ? (
                <p className="inline-banner inline-banner--warn">
                  Required before signing: {missingRequired.join(", ")}
                </p>
              ) : null}
              {staged.medicines.map((row, index) => (
                <fieldset key={index} className="manual-med" disabled={locked}>
                  <legend>
                    Medicine {index + 1}
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => removeStagedMedicine(index)}
                      aria-label={`Remove medicine ${index + 1}`}
                    >
                      Remove
                    </button>
                  </legend>
                  <MedicineFields
                    row={row}
                    brands={catalog.brands}
                    missing={missingFieldsFor(index)}
                    onBrand={(brandName) => selectStagedBrand(index, brandName)}
                    onChange={(changes) => updateStagedField(index, changes)}
                  />
                </fieldset>
              ))}
              <p className="muted">
                Review resolves each brand to its generic and runs the deterministic safety checks.
                Nothing is signed until you approve it.
              </p>
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

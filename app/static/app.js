"use strict";

// All text from reports and models is inserted with textContent, never innerHTML,
// so nothing an engineer types (or a model writes) can run as markup.

const POLL_MS = 1500;
const READING_FIELDS = ["wind_knots", "temp_c", "fuel_pct"];
const TEXT_FIELDS = ["engineer_name", "station", "note"];

const state = { reports: [], selectedId: null, detail: null };

const form = document.getElementById("report-form");
const formStatus = document.getElementById("form-status");
const listEl = document.getElementById("report-list");
const listEmpty = document.getElementById("list-empty");
const detailEl = document.getElementById("detail");

// --- small helpers ---

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.class) node.className = options.class;
  if (options.text !== undefined) node.textContent = options.text;
  for (const [name, value] of Object.entries(options.attrs || {})) node.setAttribute(name, value);
  for (const child of [].concat(children)) if (child) node.append(child);
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function formatCost(value) {
  return `$${Number(value).toFixed(6)}`;
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function verdictBadge(verdict) {
  const noGo = verdict === "no_go";
  return el("span", { class: `badge ${noGo ? "badge-nogo" : "badge-go"}`, text: noGo ? "NO-GO" : "GO" });
}

function chip(text, kind = "") {
  return el("span", { class: `chip ${kind}`.trim(), text });
}

// --- filing a report ---

function clearErrors() {
  form.querySelectorAll(".field-error").forEach((node) => (node.textContent = ""));
  form.querySelectorAll(".invalid").forEach((node) => node.classList.remove("invalid"));
}

function showErrors(errors) {
  for (const { field, message } of errors) {
    const slot = form.querySelector(`[data-error-for="${CSS.escape(field)}"]`) ||
      form.querySelector('[data-error-for="body"]');
    slot.textContent = message;
    const input = form.elements[field];
    if (input) input.classList.add("invalid");
  }
}

function readForm() {
  const payload = {};
  for (const field of TEXT_FIELDS) payload[field] = form.elements[field].value;
  for (const field of READING_FIELDS) {
    // Send a real number, or null when empty or not numeric so the server
    // answers "must be a number" for that field.
    const raw = form.elements[field].value.trim();
    payload[field] = raw === "" || Number.isNaN(Number(raw)) ? null : Number(raw);
  }
  return payload;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearErrors();
  formStatus.textContent = "";
  const button = document.getElementById("submit-button");
  button.disabled = true;
  try {
    const { ok, status, body } = await api("/api/reports", {
      method: "POST",
      body: JSON.stringify(readForm()),
    });
    if (ok) {
      form.reset();
      formStatus.textContent = `Report #${body.id} filed.`;
      state.selectedId = body.id;
      await refresh();
    } else if (status === 422 && body.errors) {
      showErrors(body.errors);
      formStatus.textContent = "Report not filed. Fix the highlighted fields.";
    } else {
      formStatus.textContent = `Report not filed (error ${status}).`;
    }
  } catch {
    formStatus.textContent = "Report not filed: the server could not be reached.";
  } finally {
    button.disabled = false;
  }
});

// --- reports list ---

function renderList() {
  listEmpty.hidden = state.reports.length > 0;
  listEl.replaceChildren(
    ...state.reports.map((report) => {
      const meta = [
        `#${report.id}`,
        report.station,
        report.engineer_name,
        formatTime(report.created_at),
      ].join(" · ");
      const chips = [verdictBadge(report.verdict)];
      if (report.severity_final) chips.push(chip(report.severity_final, `sev-${report.severity_final}`));
      if (report.brief_by_minutes) chips.push(chip(`brief in ${report.brief_by_minutes} min`));
      chips.push(chip(report.status, `status-${report.status}`));
      if (report.needs_review) chips.push(chip("needs review", "chip-review"));

      const button = el("button", { class: "report-row", attrs: { type: "button" } }, [
        el("span", { class: "row-meta", text: meta }),
        el("span", { class: "row-chips" }, chips),
      ]);
      if (report.id === state.selectedId) button.classList.add("selected");
      button.addEventListener("click", () => select(report.id));
      return el("li", {}, button);
    }),
  );
}

// --- report detail ---

function flagRow(label, flag) {
  if (!flag) return null;
  return el("li", { class: flag.flagged ? "flag flag-on" : "flag" }, [
    el("strong", { text: `${label}: ${flag.flagged ? "flagged" : "clear"}` }),
    el("span", { text: flag.reason ? ` — ${flag.reason}` : "" }),
  ]);
}

function traceCard(step) {
  const title = el("div", { class: "trace-title" }, [
    el("span", { class: "trace-seq", text: String(step.seq) }),
    el("strong", { text: step.name }),
    chip(step.kind, `kind-${step.kind}`),
    step.fallback_used ? chip("fallback used", "chip-review") : null,
  ]);
  const facts = step.kind === "model"
    ? [
        `model: ${step.model || "no reply"}`,
        `tokens in: ${step.input_tokens}`,
        `tokens out: ${step.output_tokens}`,
        `cost: ${formatCost(step.cost_usd)}`,
        `latency: ${step.latency_ms} ms`,
      ]
    : ["plain code", "tokens in: 0", "tokens out: 0", `cost: ${formatCost(0)}`];
  facts.push(`started: ${formatTime(step.started_at)}`);

  const card = el("li", { class: `trace-card ${step.fallback_used ? "trace-fallback" : ""}`.trim() }, [
    title,
    el("div", { class: "trace-facts" }, facts.map((fact) => el("span", { text: fact }))),
  ]);
  if (step.error) card.append(el("p", { class: "trace-error", text: step.error }));
  if (step.output !== null && step.output !== undefined) {
    card.append(
      el("details", {}, [
        el("summary", { text: "Output" }),
        el("pre", { text: JSON.stringify(step.output, null, 2) }),
      ]),
    );
  }
  return card;
}

function approvalSection(report) {
  if (report.status === "approved") {
    return el("p", {
      class: "approved-line",
      text: `Approved by ${report.approved_by} at ${formatTime(report.approved_at)}.`,
    });
  }
  if (report.status === "processing") {
    return el("p", { class: "muted", text: "Pipeline running… the briefing will appear here." });
  }
  if (report.status === "failed") {
    const button = el("button", { text: "Re-run pipeline", attrs: { type: "button" } });
    button.addEventListener("click", async () => {
      button.disabled = true;
      await api(`/api/reports/${report.id}/rerun`, { method: "POST" });
      await refresh();
    });
    return el("div", { class: "approve-box" }, [
      el("p", { class: "trace-error", text: `Pipeline failed: ${report.error || "unknown error"}` }),
      button,
    ]);
  }

  // pending: only a person can approve
  const input = el("input", {
    attrs: { type: "text", maxlength: "80", placeholder: "Flight Director name", "aria-label": "Approver name" },
  });
  const error = el("span", { class: "field-error" });
  const button = el("button", { text: "Approve briefing", attrs: { type: "submit" } });
  const approveForm = el("form", { class: "approve-box" }, [
    report.needs_review
      ? el("p", { class: "review-warning", text: "This report needs review before approval. Read the reasons above." })
      : null,
    el("div", { class: "approve-row" }, [input, button]),
    error,
  ]);
  approveForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    button.disabled = true;
    const { ok, status, body } = await api(`/api/reports/${report.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approver_name: input.value }),
    });
    if (!ok) {
      error.textContent = status === 422 ? body.errors[0].message : body.detail || `Error ${status}`;
      button.disabled = false;
      return;
    }
    input.blur(); // let the detail panel re-render with the approved state
    await refresh();
  });
  return approveForm;
}

function renderDetail() {
  const report = state.detail;
  if (!report) return;
  const active = document.activeElement;
  if (active && detailEl.contains(active) && active.tagName === "INPUT") return; // don't wipe typing

  const openOutputs = new Set(
    [...detailEl.querySelectorAll(".trace-card")]
      .map((card, index) => (card.querySelector("details[open]") ? index : null))
      .filter((index) => index !== null),
  );

  const flags = report.flags || {};
  const sections = [
    el("div", { class: "detail-head" }, [
      verdictBadge(report.verdict),
      el("span", { class: "detail-title", text: `Report #${report.id} · ${report.station} · ${report.engineer_name}` }),
      chip(report.status, `status-${report.status}`),
    ]),
    flags.injection && flags.injection.flagged
      ? el("p", { class: "injection-badge", text: "Possible injected instructions — review" })
      : null,

    el("h3", { text: "Verdict (from code)" }),
    el("pre", { class: "header-block", text: report.briefing_header }),
    el("p", {
      class: "muted",
      text: `Readings: wind ${report.wind_knots} kn · temp ${report.temp_c} °C · fuel ${report.fuel_pct} %`,
    }),

    report.review_reasons.length
      ? el("div", { class: "review-reasons" }, [
          el("strong", { text: "Needs review:" }),
          el("ul", {}, report.review_reasons.map((reason) => el("li", { text: reason }))),
        ])
      : null,

    el("h3", { text: "Checks" }),
    Object.keys(flags).length
      ? el("ul", { class: "flags" }, [
          flagRow("Hidden instructions", flags.injection),
          flagRow("Missing details", flags.missing_details),
          flagRow("Panic in tone", flags.panic),
        ])
      : el("p", { class: "muted", text: "Not run yet." }),

    el("h3", { text: "Briefing summary (drafted by model)" }),
    report.briefing
      ? el("p", { class: "briefing-body", text: report.briefing })
      : el("p", { class: "muted", text: "No briefing yet." }),
    report.review_rounds
      ? el("p", { class: "muted", text: `Draft/review rounds used: ${report.review_rounds} of 3` })
      : null,

    el("h3", { text: "Engineer's note" }),
    el("p", { class: "note-body", text: report.note }),

    el("h3", { text: "Approval" }),
    approvalSection(report),

    el("h3", { text: "Trace" }),
    el("p", { class: "cost-total" }, [
      el("span", { text: "Total cost for this report: " }),
      el("strong", { text: formatCost(report.total_cost_usd) }),
      el("span", { class: "muted", text: `  (${report.trace.length} steps)` }),
    ]),
    el("ol", { class: "trace" }, report.trace.map(traceCard)),
  ];
  detailEl.replaceChildren(...sections.filter(Boolean));
  detailEl.querySelectorAll(".trace-card").forEach((card, index) => {
    const details = card.querySelector("details");
    if (details && openOutputs.has(index)) details.open = true;
  });
}

// --- loading and polling ---

async function select(id) {
  state.selectedId = id;
  if (document.activeElement) document.activeElement.blur();
  await refresh();
}

async function refresh() {
  const list = await api("/api/reports");
  if (list.ok) state.reports = list.body;
  if (state.selectedId !== null) {
    const detail = await api(`/api/reports/${state.selectedId}`);
    state.detail = detail.ok ? detail.body : null;
  }
  renderList();
  renderDetail();
}

async function poll() {
  // Keep polling only while something is still being processed.
  if (state.reports.some((report) => report.status === "processing")) {
    await refresh().catch(() => {});
  }
  setTimeout(poll, POLL_MS);
}

async function start() {
  const health = await api("/api/health").catch(() => null);
  if (health && health.ok && health.body.llm_mode === "fake") {
    document.getElementById("fake-banner").hidden = false;
  }
  await refresh();
  poll();
}

start();

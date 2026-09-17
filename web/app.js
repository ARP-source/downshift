/* Dashboard rendering.
 *
 * Charts are hand-built inline SVG: three data points per chart do not justify
 * a library, and this keeps the page dependency-free and instant to load.
 *
 * Colour rules followed here:
 *   - one axis per chart; cost and quality are different scales, so they are
 *     two charts rather than one chart with two y-axes
 *   - colour follows the entity (an arm keeps its hue everywhere)
 *   - every bar carries a visible value label, which is required because the
 *     aqua slot sits below 3:1 contrast on the light surface
 */

const ARM_COLOR = {
  router: "var(--router)",
  flagship: "var(--flagship)",
  cheapest: "var(--cheapest)",
};
const ARM_LABEL = {
  router: "Router",
  flagship: "All flagship",
  cheapest: "All cheapest",
};
const ARM_ORDER = ["flagship", "router", "cheapest"];

const CHAOS_LABEL = {
  off: "Healthy",
  flagship_down: "Flagship down (503)",
  flagship_rate_limited: "Flagship rate limited (429)",
  flagship_slow: "Flagship timing out",
  top_two_down: "Top two tiers down",
};

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );
const usd = (v) => "$" + Number(v).toFixed(v < 0.01 ? 5 : 4);
const pct = (v) => (v == null ? "—" : (Number(v) * 100).toFixed(1) + "%");
const pct100 = (v) => (v == null ? "—" : Number(v).toFixed(1) + "%");

let STATE = null;

/* ---------- charts ---------------------------------------------------- */

function barChart(host, rows, format) {
  if (!host) return;
  const width = Math.max(280, host.clientWidth || 420);
  const rowH = 40;
  const padL = 104;
  const padR = 72;
  const height = rows.length * rowH + 8;
  const max = Math.max(...rows.map((r) => r.value)) || 1;
  const span = width - padL - padR;

  const parts = rows.map((r, i) => {
    // The 14px bar inside a 40px row leaves a clear gap between neighbours.
    const y = i * rowH + 11;
    const w = Math.max(2, (r.value / max) * span);
    return `
      <g>
        <title>${esc(r.name)}: ${esc(format(r.value))}</title>
        <text class="bar-name" x="${padL - 10}" y="${y + 11}" text-anchor="end">${esc(r.name)}</text>
        <rect x="${padL}" y="${y}" width="${w}" height="14" rx="4" fill="${r.color}"></rect>
        <text class="bar-label" x="${padL + w + 8}" y="${y + 11}">${esc(format(r.value))}</text>
      </g>`;
  });

  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img">
      <line class="axis" x1="${padL}" y1="2" x2="${padL}" y2="${height - 4}"></line>
      ${parts.join("")}
    </svg>`;
}

function lineChart(host, points) {
  if (!host) return;
  if (!points || points.length < 2) {
    host.innerHTML = '<p class="empty">Run the benchmark to see the policy learn.</p>';
    return;
  }
  const width = Math.max(300, host.clientWidth || 640);
  const height = 210;
  const padL = 48;
  const padR = 24;
  const padT = 18;
  const padB = 36;
  const values = points.map((p) => p.savings_pct);
  const lo = Math.max(0, Math.min(...values) - 6);
  const hi = Math.min(100, Math.max(...values) + 6);
  const x = (i) => padL + (i / (points.length - 1)) * (width - padL - padR);
  const y = (v) => padT + (1 - (v - lo) / (hi - lo || 1)) * (height - padT - padB);

  const grid = [0, 0.5, 1]
    .map((t) => {
      const v = lo + t * (hi - lo);
      return `<line class="gridline" x1="${padL}" y1="${y(v)}" x2="${width - padR}" y2="${y(v)}"></line>
              <text class="tick" x="${padL - 8}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(0)}%</text>`;
    })
    .join("");

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.savings_pct)}`).join(" ");

  const marks = points
    .map((p, i) => {
      // Quality is annotated per point rather than drawn as a second series,
      // so the chart keeps one axis and one meaning.
      const q = p.quality == null ? "—" : pct(p.quality);
      return `<g>
          <title>Pass ${p.epoch}: ${p.savings_pct}% cheaper, quality ${q}</title>
          <circle cx="${x(i)}" cy="${y(p.savings_pct)}" r="5" fill="var(--router)"
                  stroke="var(--surface-1)" stroke-width="2"></circle>
          <text class="bar-label" x="${x(i)}" y="${y(p.savings_pct) - 12}" text-anchor="middle">${p.savings_pct}%</text>
          <text class="tick" x="${x(i)}" y="${height - 15}" text-anchor="middle">pass ${p.epoch}</text>
          <text class="tick" x="${x(i)}" y="${height - 3}" text-anchor="middle">quality ${q}</text>
        </g>`;
    })
    .join("");

  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img">
      ${grid}
      <path d="${path}" fill="none" stroke="var(--router)" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round"></path>
      ${marks}
    </svg>`;
}

/* ---------- sections --------------------------------------------------- */

function renderChaos(s) {
  const modes = s.chaos_modes || ["off"];
  const active = s.chaos_mode || "off";
  $("chaos-controls").innerHTML = modes
    .map(
      (m) =>
        `<button class="${m === "off" ? "" : "danger "}${m === active ? "active" : ""}"
                 data-mode="${esc(m)}">${esc(CHAOS_LABEL[m] || m)}</button>`
    )
    .join("");
  $("chaos-controls")
    .querySelectorAll("button")
    .forEach((b) =>
      b.addEventListener("click", async () => {
        await fetch("/api/chaos", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: b.dataset.mode }),
        });
        await refresh();
      })
    );
}

function renderMode(s) {
  const badge = $("mode-badge");
  const live = s.mode === "live";
  badge.className = "badge " + (live ? "live" : "mock");
  badge.textContent = live ? "live models" : "mock provider";

  if (s.chaos_mode && s.chaos_mode !== "off") {
    const banner = document.createElement("div");
    banner.className = "chaos-on";
    banner.textContent =
      "Failure injected: " +
      (CHAOS_LABEL[s.chaos_mode] || s.chaos_mode) +
      ". Requests below are being served around it.";
    const host = $("mode-banner");
    host.insertAdjacentElement("afterend", banner);
    // Remove any earlier copy so repeated refreshes do not stack banners.
    let prev = banner.nextElementSibling;
    while (prev) {
      const next = prev.nextElementSibling;
      if (prev.classList && prev.classList.contains("chaos-on")) prev.remove();
      prev = next;
    }
  } else {
    document.querySelectorAll(".chaos-on").forEach((e) => e.remove());
  }

  const degraded = (s.degraded || []).length
    ? ` Unavailable request features were dropped automatically: ${s.degraded.join(", ")}.`
    : "";

  // A price table nobody has checked makes every number downstream fiction.
  // Say so louder than the mode itself.
  if (s.rates_verified === false) {
    $("mode-banner").innerHTML =
      `<strong>Rate card not verified.</strong> The ${esc(s.ladder_name)} ladder is using
       placeholder prices, so every cost figure on this page is a placeholder too.
       Set <code>FEATHERLESS_RATES</code> to the rates from the model pages before
       quoting any of these numbers.`;
    return;
  }

  // Live was asked for but not achieved: say so loudly rather than quietly
  // serving simulated numbers under a live badge.
  if (!live && s.requested_live) {
    $("mode-banner").innerHTML =
      `<strong>Live mode was requested but is not active.</strong> MOCK=0 is set, but no
       usable API key was found, so the deterministic mock provider is running and every
       number below is simulated. Put a key in <code>.env</code> and restart.`;
    return;
  }

  $("mode-banner").innerHTML = live
    ? `<strong>Live mode.</strong> Every number below comes from real API calls and measured token counts.${esc(degraded)}`
    : `<strong>Mock provider &mdash; these numbers exercise the machinery, not the model.</strong>
       Correctness is simulated from the same difficulty score the router uses, so mock results
       cannot tell you whether that score predicts real model capability. What they do verify,
       end to end, is the routing, escalation, accounting and reliability paths. Set an API key
       and <code>MOCK=0</code> to measure the real thing.`;
}

function renderLadder(s) {
  $("ladder").innerHTML = s.ladder
    .map((t) => {
      const color =
        t.tier === 2 ? "var(--flagship)" : t.tier === 1 ? "var(--router)" : "var(--cheapest)";
      const rel =
        t.relative_cost === 1
          ? "the baseline price"
          : `${(1 / t.relative_cost).toFixed(1)}x cheaper than flagship`;
      return `<div class="tier">
          <div class="name"><span class="dot" style="background:${color}"></span>${esc(t.label)}</div>
          <div class="price">$${t.input_per_mtok.toFixed(2)} in / $${t.output_per_mtok.toFixed(
        2
      )} out per 1M tokens</div>
          <div class="rel">${esc(rel)}</div>
        </div>`;
    })
    .join("");
}

function renderKPIs(s) {
  const r = s.report;
  const host = $("kpis");
  if (!r) {
    const live = s.live;
    host.innerHTML = `
      <div class="kpi"><div class="label">Requests routed</div><div class="value">${live.requests}</div>
        <div class="foot">this session, not the benchmark</div></div>
      <div class="kpi"><div class="label">Spent</div><div class="value">${usd(live.total_cost_usd)}</div>
        <div class="foot">against ${usd(live.baseline_cost_usd)} at flagship prices</div></div>
      <div class="kpi"><div class="label">Saved so far</div><div class="value">${pct100(
        live.savings_pct
      )}</div>
        <div class="foot">run the benchmark for a measured comparison</div></div>`;
    return;
  }
  const c = r.comparison;
  host.innerHTML = `
    <div class="kpi"><div class="label">Cost vs all-flagship</div>
      <div class="value" style="color:var(--router)">−${pct100(c.cost_saving_vs_flagship_pct)}</div>
      <div class="foot">measured on ${r.items} items, both arms</div></div>
    <div class="kpi"><div class="label">Quality retained</div>
      <div class="value">${pct100(c.quality_retained_pct)}</div>
      <div class="foot">${pct(c.quality_router)} correct vs ${pct(c.quality_flagship)} flagship</div></div>
    <div class="kpi"><div class="label">p50 latency</div>
      <div class="value">−${pct100(c.latency_p50_change_pct)}</div>
      <div class="foot">cheaper tiers answer faster</div></div>
    <div class="kpi"><div class="label">At 1M requests/month</div>
      <div class="value">$${Number(c.projected_monthly_savings_usd).toLocaleString(undefined, {
        maximumFractionDigits: 0,
      })}</div>
      <div class="foot">extrapolated from the measured per-request delta</div></div>`;
}

function renderBench(s) {
  const r = s.report;
  const note = $("bench-note");
  if (!r) {
    note.textContent = "No benchmark run yet.";
    $("chart-cost").innerHTML = '<p class="empty">No data.</p>';
    $("chart-quality").innerHTML = '<p class="empty">No data.</p>';
    $("arm-table").innerHTML = "";
    lineChart($("chart-learn"), null);
    $("adaptations").innerHTML = "";
    return;
  }
  const c = r.comparison;
  note.innerHTML = `${r.items} items, ${r.dataset.checkable} of them graded automatically.
    The router ran ${c.router_epochs} passes so the policy had evidence to learn from;
    the baselines ran once. ${r.simulated ? "Simulated provider." : "Live models."}`;

  barChart(
    $("chart-cost"),
    ARM_ORDER.map((a) => ({
      name: ARM_LABEL[a],
      color: ARM_COLOR[a],
      value: r.arms[a].metrics.total_cost_usd,
    })),
    usd
  );

  barChart(
    $("chart-quality"),
    ARM_ORDER.map((a) => ({
      name: ARM_LABEL[a],
      color: ARM_COLOR[a],
      value: r.arms[a].metrics.quality || 0,
    })),
    pct
  );

  $("arm-table").innerHTML = `
    <thead><tr><th>Arm</th><th>Cost</th><th>Quality</th><th>p50</th><th>p95</th>
      <th>Calls</th><th>Unanswered</th></tr></thead>
    <tbody>${ARM_ORDER.map((a) => {
      const m = r.arms[a].metrics;
      return `<tr>
        <td><span class="swatch" style="background:${ARM_COLOR[a]}"></span>${ARM_LABEL[a]}</td>
        <td>${usd(m.total_cost_usd)}</td><td>${pct(m.quality)}</td>
        <td>${Math.round(m.p50_latency_ms)} ms</td><td>${Math.round(m.p95_latency_ms)} ms</td>
        <td>${m.calls}</td><td>${m.unresolved}</td></tr>`;
    }).join("")}</tbody>`;

  lineChart($("chart-learn"), c.learning_curve);

  const adapts = r.arms.router.adaptations || [];
  $("adaptations").innerHTML = adapts.length
    ? adapts
        .map(
          (a) =>
            `<div class="adapt">Difficulty ${esc(a.bucket_label)} moved
             <strong>${a.direction}</strong> from tier ${a.from} to ${a.to}
             <span class="why">&mdash; ${esc(a.why)}</span></div>`
        )
        .join("")
    : '<p class="empty">The policy did not need to move: its starting prior already matched the evidence.</p>';
}

const SCENARIO_LABEL = {
  off: "Healthy",
  flagship_down: "Flagship down",
  top_two_down: "Top two down",
};

function renderBrownout(s) {
  const b = s.brownout;
  if (!b) {
    $("chart-brownout").innerHTML = '<p class="empty">Not run yet.</p>';
    $("brownout-table").innerHTML = "";
    return;
  }
  const rows = b.scenarios.map((x) => ({
    name: `${SCENARIO_LABEL[x.mode] || x.mode} � ${x.arm === "router" ? "Router" : "All flagship"}`,
    color: x.arm === "router" ? ARM_COLOR.router : ARM_COLOR.flagship,
    value: x.answered_pct,
  }));
  barChart($("chart-brownout"), rows, (v) => v.toFixed(1) + "%");

  $("brownout-table").innerHTML = `
    <thead><tr><th>Scenario</th><th>Arm</th><th>Answered</th><th>Quality</th>
      <th>Cost</th><th>Failovers</th></tr></thead>
    <tbody>${b.scenarios
      .map(
        (x) => `<tr>
        <td>${esc(SCENARIO_LABEL[x.mode] || x.mode)}</td>
        <td><span class="swatch" style="background:${
          x.arm === "router" ? ARM_COLOR.router : ARM_COLOR.flagship
        }"></span>${x.arm === "router" ? "Router" : "All flagship"}</td>
        <td>${x.answered}/${x.requests} (${x.answered_pct}%)</td>
        <td>${pct(x.quality)}</td>
        <td>${usd(x.cost_usd)}</td>
        <td>${x.failovers}</td></tr>`
      )
      .join("")}</tbody>`;
}

function renderPolicy(s) {
  // Prefer the policy the benchmark actually trained. The dashboard keeps its
  // own long-lived router for the ask box, and showing that one after a
  // benchmark run would display an untrained prior next to trained results.
  const trained = s.report && s.report.arms && s.report.arms.router;
  const rows = (trained && trained.policy) || s.policy || [];
  const source = trained && trained.policy ? "benchmark" : "live";
  const caption = $("policy-source");
  if (caption) {
    caption.textContent =
      source === "benchmark"
        ? "Learned during the benchmark run, across all four passes."
        : "The live session policy. Run the benchmark or send requests to give it evidence.";
  }
  const tiers = rows.length ? Object.keys(rows[0].tiers) : [];
  $("policy-table").innerHTML = `
    <thead><tr><th>Difficulty</th><th>Starts on</th>${tiers
      .map((t) => `<th>${esc(t)}</th>`)
      .join("")}</tr></thead>
    <tbody>${rows
      .map(
        (r) => `<tr><td>${esc(r.bucket_label)}</td><td>${esc(r.start_model)}</td>${tiers
          .map((t) => {
            const cell = r.tiers[t];
            return `<td>${
              cell.attempts
                ? `${pct(cell.success_rate)} <span class="why">n=${cell.attempts}</span>`
                : "—"
            }</td>`;
          })
          .join("")}</tr>`
      )
      .join("")}</tbody>`;
}

function renderFeed(s) {
  const feed = s.feed || [];
  if (!feed.length) {
    $("feed").innerHTML = "";
    return;
  }
  $("feed").innerHTML = `
    <thead><tr><th>Request</th><th>Difficulty</th><th>Served by</th><th>Cost</th>
      <th>Flagship</th><th>Latency</th></tr></thead>
    <tbody>${feed
      .map((f) => {
        const climbed = f.escalations + f.failovers;
        const tail = climbed
          ? ` <span class="why">after ${climbed} step${climbed > 1 ? "s" : ""} up</span>`
          : "";
        return `<tr>
          <td>${esc(f.prompt.slice(0, 64))}${f.prompt.length > 64 ? "…" : ""}
              <div class="why">${esc(f.decision_reason)}</div></td>
          <td>${f.difficulty.toFixed(3)}</td>
          <td>${esc(f.final_label || "unanswered")}${tail}</td>
          <td>${usd(f.cost_usd)}</td>
          <td>${usd(f.baseline_cost_usd)}</td>
          <td>${Math.round(f.latency_ms)} ms</td></tr>`;
      })
      .join("")}</tbody>`;
}

function render(s) {
  STATE = s;
  renderChaos(s);
  renderMode(s);
  renderLadder(s);
  renderKPIs(s);
  renderBench(s);
  renderBrownout(s);
  renderPolicy(s);
  renderFeed(s);
}

function renderCompare(data) {
  const host = $("compare");
  if (!data) {
    host.innerHTML = "";
    return;
  }
  const f = data.features;
  const d = data.decision;
  const saving =
    data.saving_pct == null
      ? ""
      : ` and costs <strong>${data.saving_pct}% less</strong> than the flagship answer beside it`;

  const cards = data.tiers
    .map((t) => {
      const verdict = t.usable
        ? '<span class="verdict pass">passes the gate</span>'
        : `<span class="verdict fail">fails the gate &mdash; ${esc(t.gate_reason)}</span>`;
      const body = t.ok
        ? esc(t.text || "(empty)")
        : `<em>${esc(t.error || "call failed")}</em>`;
      return `<div class="cmp${t.would_route_here ? " picked" : ""}">
          <div class="top">
            <span class="model">${esc(t.label)}</span>
            ${t.would_route_here ? '<span class="tag">router picks</span>' : ""}
          </div>
          <div class="answer">${body}</div>
          <div class="meta">${usd(t.cost_usd)} &middot; ${Math.round(t.latency_ms)} ms &middot;
            ${t.input_tokens} in / ${t.output_tokens} out</div>
          ${verdict}
        </div>`;
    })
    .join("");

  // Without this, an exploration probe looks like the router contradicting its
  // own policy table, which reads as a bug to anyone watching.
  const why = d.explored
    ? ` This one is an <strong>exploration probe</strong>: the policy would normally
        start a band this hard higher up, and 20% of requests deliberately try one
        tier cheaper to find out whether that is wasted money.`
    : "";

  host.innerHTML = `
    <div class="cmp-head">
      Difficulty <strong>${f.difficulty.toFixed(3)}</strong>
      &mdash; ${esc(f.reasons.join("; "))}.
      The router would send this to <strong>${esc(d.label)}</strong>${saving}.${why}
    </div>
    <div class="cmp-grid">${cards}</div>`;
}

/* ---------- wiring ----------------------------------------------------- */

async function refresh() {
  const res = await fetch("/api/state");
  render(await res.json());
}

async function loadSamples() {
  const res = await fetch("/api/samples");
  const items = await res.json();
  $("samples").innerHTML = items
    .map(
      (i) =>
        `<span class="chip" data-prompt="${esc(i.prompt)}">${esc(i.prompt.slice(0, 46))}${
          i.prompt.length > 46 ? "…" : ""
        }</span>`
    )
    .join("");
  $("samples")
    .querySelectorAll(".chip")
    .forEach((chip) => {
      chip.addEventListener("click", () => {
        $("ask-input").value = chip.dataset.prompt;
        $("ask-form").requestSubmit();
      });
    });
}

$("compare-btn").addEventListener("click", async () => {
  const prompt = $("ask-input").value.trim();
  if (!prompt) return;
  const btn = $("compare-btn");
  btn.disabled = true;
  btn.textContent = "Asking every tier�";
  try {
    const res = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    renderCompare(await res.json());
  } finally {
    btn.disabled = false;
    btn.textContent = "Compare all tiers";
  }
});

$("run-brownout").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Breaking things�";
  try {
    await fetch("/api/brownout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 30 }),
    });
    await refresh();
  } finally {
    btn.disabled = false;
    btn.textContent = "Run outage test";
  }
});

$("run-bench").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    await fetch("/api/bench", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    await refresh();
  } finally {
    btn.disabled = false;
    btn.textContent = "Run benchmark";
  }
});

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("ask-input");
  const prompt = input.value.trim();
  if (!prompt) return;
  const btn = $("ask-btn");
  btn.disabled = true;
  try {
    await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    input.value = "";
    await refresh();
  } finally {
    btn.disabled = false;
  }
});

window.addEventListener("resize", () => {
  if (STATE) render(STATE);
});

loadSamples();
refresh();

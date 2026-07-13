// App shell: mission lifecycle, PTT -> /api/transmit, WebSocket pushes,
// coach panel, comms log, debrief.

const App = {
  brief: null,
  ws: null,
  facilityKhz: {},
  busy: false,

  async start() {
    const callsign = document.getElementById("callsign-input").value.trim() || "N67525";
    const coach = document.getElementById("coach-check").checked;
    const startBtn = document.getElementById("start-btn");
    const startStatus = document.getElementById("start-status");
    startBtn.disabled = true;
    startStatus.textContent = "Checking local services…";

    try {
      const readiness = await fetch("/api/readiness").then((r) => r.json());
      this.showReadiness(readiness);

      const r = await fetch("/api/mission/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callsign, coach }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || "Could not start the mission.");
      this.brief = body;
    } catch (e) {
      startStatus.textContent = e.message || "Could not reach Ground Control.";
      startStatus.classList.add("degraded");
      startBtn.disabled = false;
      return;
    }

    for (const [fac, mhz] of Object.entries(this.brief.freqs)) {
      this.facilityKhz[fac] = Math.round(parseFloat(mhz) * 1000);
    }

    document.getElementById("start-overlay").hidden = true;
    document.getElementById("game").hidden = false;
    document.getElementById("hdr-callsign").textContent = this.brief.callsign;
    document.getElementById("mission-text").textContent = this.brief.mission;
    document.getElementById("atis-text").textContent = this.brief.atis_display || "";
    this.renderChartInfo();
    if (!this.brief.coach) {
      document.getElementById("coach-panel").style.display = "none";
      document.getElementById("atis-details").style.display = "none";
    }
    this.setCoach(this.brief.coach_hint);

    Radio.init();
    GameMap.init(document.getElementById("map"), this.brief);
    GameMap.setView("ground");
    let atisLoaded = false;
    try {
      await RadioAudio.init();
      Radio.onActiveChange = (khz) => RadioAudio.setAtis(khz === this.facilityKhz.atis);
      atisLoaded = await RadioAudio.loadAtis();
    } catch {
      atisLoaded = false;
    }
    if (atisLoaded) {
      RadioAudio.setAtis(Radio.activeKhz === this.facilityKhz.atis);
    } else {
      const details = document.getElementById("atis-details");
      details.style.display = "";
      details.open = true;
      this.setStatus("ATIS audio unavailable — use the displayed ATIS text.");
    }

    this.connectWs();
    this.wirePtt();
    this.wireTextForm();
    this.wireChartInfo();
  },

  showReadiness(readiness) {
    const unavailable = readiness.degraded || [];
    const text = unavailable.length
      ? `Degraded mode · unavailable: ${unavailable.join(", ")}`
      : "Local voice services ready";
    for (const id of ["start-status", "service-status"]) {
      const el = document.getElementById(id);
      el.textContent = text;
      el.classList.toggle("degraded", unavailable.length > 0);
    }
  },

  // ---- chart info drawer -----------------------------------------------------

  renderChartInfo() {
    const ci = this.brief.chart_info;
    if (!ci) return;

    document.getElementById("ci-freqs").innerHTML = (ci.frequencies || [])
      .map((f) => `<span><b>${f.label}</b> ${f.value}</span>`)
      .join("");

    const field = ci.field || {};
    let html = "";
    if (field.elevation_ft != null) {
      html += `<div class="ci-field-row"><span>Field elevation</span><span>${field.elevation_ft} ft</span></div>`;
    }
    if (field.pattern_altitude_ft_agl != null) {
      html += `<div class="ci-field-row"><span>Pattern altitude</span><span>${field.pattern_altitude_ft_agl} ft AGL</span></div>`;
    }
    for (const rw of ci.runways || []) {
      html += `<div class="ci-runway">
        <div class="ci-runway-id">RWY ${rw.id}</div>
        <div class="ci-runway-detail">${rw.dimensions_ft} ft</div>
        <div class="ci-runway-detail">${rw.pavement_rating}</div>
        <div class="ci-runway-detail">${rw.strength}</div>
      </div>`;
    }
    document.getElementById("ci-field").innerHTML = html;

    document.getElementById("ci-notes").innerHTML = (ci.notes || [])
      .map((n) => `<li>${n}</li>`)
      .join("");
  },

  toggleChartInfo(force) {
    const panel = document.getElementById("map-panel");
    const tab = document.getElementById("chart-info-tab");
    const open = force !== undefined ? force : !panel.classList.contains("drawer-open");
    panel.classList.toggle("drawer-open", open);
    tab.setAttribute("aria-expanded", String(open));
  },

  wireChartInfo() {
    const tab = document.getElementById("chart-info-tab");
    tab.addEventListener("click", () => this.toggleChartInfo());
    window.addEventListener("keydown", (e) => {
      if (e.key !== "i" && e.key !== "I") return;
      if (e.ctrlKey || e.metaKey || e.altKey) return; // don't hijack Ctrl/Cmd+I
      if (/INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
      this.toggleChartInfo();
    });
  },

  connectWs() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${scheme}://${location.host}/ws`);
    this.ws.onopen = () => this.setStatus(" ");
    this.ws.onmessage = (e) => this.onPush(JSON.parse(e.data));
    this.ws.onclose = () => {
      this.setStatus("Connection lost — reconnecting…");
      setTimeout(() => this.connectWs(), 1500);
    };
  },

  sendLegComplete(leg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "leg_complete", leg }));
    }
  },

  onPush(msg) {
    if (msg.type === "debrief_narrative") {
      document.getElementById("debrief-narrative").textContent = msg.text;
      return;
    }
    if (msg.type !== "push") return;

    if (msg.atc) {
      const khz = this.facilityKhz[msg.atc.facility];
      if (Radio.activeKhz === khz) {
        if (msg.atc.audio_b64) {
          RadioAudio.playAtc(msg.atc.audio_b64, msg.atc.delay_ms);
        } else {
          this.setStatus("ATC audio unavailable — transmission shown in the log.");
        }
        this.addLog("atc", msg.atc.facility, msg.atc.display);
      } else {
        this.addLog("info", "", `You missed a call on ${(khz / 1000).toFixed(2)} — check your frequency.`);
      }
    }
    if (msg.coach) this.setCoach(msg.coach);
    if (msg.complete) this.showDebrief(msg.debrief);
  },

  // ---- transmitting ---------------------------------------------------------

  wirePtt() {
    const ptt = document.getElementById("ptt");
    const down = async (e) => {
      e.preventDefault();
      if (this.busy || RadioAudio.keyed) return;
      if (!(await RadioAudio.ensureMic())) {
        this.setStatus("Mic unavailable — use the text box below.");
        return;
      }
      ptt.classList.add("keyed");
      this.setStatus("TRANSMITTING…");
      RadioAudio.keyDown();
    };
    const up = (e) => {
      e.preventDefault();
      if (!RadioAudio.keyed) return;
      ptt.classList.remove("keyed");
      const wav = RadioAudio.keyUp();
      if (!wav || wav.size < 4000) {
        this.setStatus("Too short — hold while you speak.");
        return;
      }
      this.transmit({ audio: wav });
    };

    ptt.addEventListener("pointerdown", down);
    ptt.addEventListener("pointerup", up);
    ptt.addEventListener("pointerleave", (e) => RadioAudio.keyed && up(e));
    window.addEventListener("keydown", (e) => {
      if (e.code !== "Space" || e.repeat) return;
      if (/INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
      down(e);
    });
    window.addEventListener("keyup", (e) => {
      if (e.code !== "Space") return;
      if (/INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
      up(e);
    });
  },

  wireTextForm() {
    document.getElementById("text-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = document.getElementById("text-input");
      const text = input.value.trim();
      if (!text || this.busy) return;
      input.value = "";
      this.transmit({ text });
    });
  },

  async transmit({ audio, text }) {
    this.busy = true;
    this.setStatus(audio ? "Transcribing…" : "Sending…");
    const fd = new FormData();
    fd.append("freq_khz", Radio.activeKhz);
    fd.append("xpdr_code", Radio.xpdrCodeStr);
    fd.append("xpdr_mode", Radio.xpdrMode);
    if (audio) fd.append("audio", audio, "call.wav");
    if (text) fd.append("text", text);

    try {
      const r = await fetch("/api/transmit", { method: "POST", body: fd });
      const res = await r.json();
      if (!r.ok) throw new Error(res.error || "Transmission failed.");
      this.handleResult(res);
    } catch (e) {
      this.setStatus(e.message || "Server error — try again.");
    } finally {
      this.busy = false;
    }
  },

  handleResult(res) {
    this.setStatus(" ");
    if (res.transcript) {
      this.addLog("pilot", Radio.fmt(Radio.activeKhz), res.transcript);
    }
    if (!res.heard && !res.atc) {
      this.addLog("info", "", "…static…");
    }
    if (res.atc) {
      if (res.atc.audio_b64) {
        RadioAudio.playAtc(res.atc.audio_b64, res.atc.delay_ms);
      } else {
        this.setStatus("ATC audio unavailable — transmission shown in the log.");
      }
      this.addLog("atc", res.atc.facility, res.atc.display);
    }
    if (res.coach) this.setCoach(res.coach);
    if (res.actions && res.actions.length) {
      GameMap.runActions(res.actions, (leg) => this.sendLegComplete(leg))
        .catch((error) => {
          console.error("movement stopped", error);
          this.setStatus(error.message || "Aircraft movement stopped.");
          this.addLog("info", "", error.message || "Aircraft movement stopped.");
        });
    }
  },

  // ---- UI helpers -------------------------------------------------------------

  setStatus(t) {
    document.getElementById("tx-status").textContent = t;
  },

  setCoach(t) {
    const el = document.getElementById("coach-text");
    // highlight the ideal-call quote if present
    const m = t && t.match(/“([^”]+)”/);
    if (m) {
      const [before] = t.split("“");
      el.innerHTML = "";
      el.append(before);
      const q = document.createElement("span");
      q.className = "ideal";
      q.textContent = `“${m[1]}”`;
      el.appendChild(q);
    } else {
      el.textContent = t || "—";
    }
  },

  addLog(kind, tag, text) {
    const log = document.getElementById("log");
    const div = document.createElement("div");
    div.className = `log-entry ${kind}`;
    if (kind === "info") {
      div.textContent = text;
    } else {
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = kind === "pilot" ? `YOU · ${tag}` : `ATC · ${tag.toUpperCase()}`;
      div.appendChild(who);
      div.append(text);
    }
    log.prepend(div);
    log.scrollTop = 0;
  },

  showDebrief(d) {
    document.getElementById("debrief-total").textContent =
      `Overall score: ${d.total}/100 · ${d.duration_min} minutes`;
    const tbody = document.querySelector("#debrief-table tbody");
    tbody.innerHTML = "";
    for (const s of d.steps) {
      const tr = document.createElement("tr");
      const cls = s.score >= 90 ? "score-good" : s.score >= 60 ? "score-mid" : "score-bad";
      tr.innerHTML =
        `<td>${s.name}</td><td class="${cls}">${s.score}</td>` +
        `<td>${s.attempts}</td><td>${(s.missed || []).join(", ") || "—"}</td>`;
      tbody.appendChild(tr);
    }
    document.getElementById("debrief-overlay").hidden = false;
  },
};

document.getElementById("start-btn").addEventListener("click", () => App.start());

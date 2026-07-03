// COM radio (KX-155 style: active/standby + flip-flop) and transponder (KT-76A).
// State lives here; app.js reads Radio.active / Radio.xpdr* when transmitting.

const Radio = {
  activeKhz: 118000,
  standbyKhz: 132650,
  xpdrCode: [1, 2, 0, 0],
  xpdrModes: ["OFF", "SBY", "ALT"],
  xpdrModeIdx: 1,
  onActiveChange: null, // set by app.js (drives ATIS loop)

  init() {
    document.getElementById("com-swap").addEventListener("click", () => {
      [this.activeKhz, this.standbyKhz] = [this.standbyKhz, this.activeKhz];
      this.render();
      if (this.onActiveChange) this.onActiveChange(this.activeKhz);
    });

    document.querySelectorAll("[data-knob]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const dir = parseInt(btn.dataset.dir, 10);
        let mhz = Math.floor(this.standbyKhz / 1000);
        let khz = this.standbyKhz % 1000;
        if (btn.dataset.knob === "mhz") {
          mhz += dir;
          if (mhz > 136) mhz = 118;
          if (mhz < 118) mhz = 136;
        } else {
          khz += dir * 25;
          if (khz >= 1000) khz = 0;
          if (khz < 0) khz = 975;
        }
        this.standbyKhz = mhz * 1000 + khz;
        this.render();
      });
    });

    const digitsEl = document.getElementById("xpdr-digits");
    this.xpdrCode.forEach((_, i) => {
      const col = document.createElement("div");
      col.className = "xpdr-digit";
      const up = document.createElement("button");
      up.textContent = "▲";
      const d = document.createElement("div");
      d.className = "d";
      const down = document.createElement("button");
      down.textContent = "▼";
      up.addEventListener("click", () => this.bumpDigit(i, 1));
      down.addEventListener("click", () => this.bumpDigit(i, -1));
      col.append(up, d, down);
      digitsEl.appendChild(col);
    });

    document.getElementById("xpdr-mode").addEventListener("click", () => {
      this.xpdrModeIdx = (this.xpdrModeIdx + 1) % this.xpdrModes.length;
      this.render();
    });

    this.render();
  },

  bumpDigit(i, dir) {
    this.xpdrCode[i] = (this.xpdrCode[i] + dir + 8) % 8; // transponder digits are 0-7
    this.render();
  },

  fmt(khz) {
    // real radios truncate the third kHz digit: 132.675 shows as 132.67
    return (Math.floor(khz / 10) / 100).toFixed(2);
  },

  get xpdrCodeStr() {
    return this.xpdrCode.join("");
  },

  get xpdrMode() {
    return this.xpdrModes[this.xpdrModeIdx];
  },

  render() {
    document.getElementById("com-active").textContent = this.fmt(this.activeKhz);
    document.getElementById("com-standby").textContent = this.fmt(this.standbyKhz);
    document.querySelectorAll("#xpdr-digits .d").forEach((el, i) => {
      el.textContent = this.xpdrCode[i];
    });
    const modeBtn = document.getElementById("xpdr-mode");
    modeBtn.textContent = this.xpdrMode;
    modeBtn.className = this.xpdrMode === "ALT" ? "alt" : this.xpdrMode === "OFF" ? "off" : "";
  },
};

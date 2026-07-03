// Map rendering. The ground view is the FAA airport diagram inlined as vector
// SVG (assets/ksba-diagram.svg — cropped and rotated for widescreen); the
// airborne legs use a stylized coastal scene built from SVG shapes. The
// aircraft is a first-class SVG marker moved over the map. Server coordinates
// are normalized 0..1 and mapped into whichever view's viewBox is active.

const SVGNS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};

// Aircraft silhouette in local units (nose at 0,-1); scaled/rotated per frame.
const PLANE_PATH =
  "M0,-1 L0.22,-0.25 L1,0.15 L0.2,0.2 L0.35,0.85 L0,0.7 " +
  "L-0.35,0.85 L-0.2,0.2 L-1,0.15 L-0.22,-0.25 Z";

const GameMap = {
  svg: null,
  chartLayer: null,   // <g> holding the current scene (chart or coastal)
  planeEl: null,      // <path> aircraft marker (drawn above the scene)
  view: "ground",
  plane: { x: 0.445, y: 0.366, heading: 0 },
  patternPoints: {},
  anim: null, // {pts:[{x,y}], seg, t, speed, resolve}
  SPEEDS: { taxi: 40, roll: 150, fly: 65 }, // units/sec vs a 900-unit reference

  // Ground viewBox is read from the chart SVG on load; the coastal view uses a
  // fixed widescreen viewBox. Both render with uniform (meet) scaling so the
  // aircraft marker never distorts.
  groundVB: { w: 504.4, h: 351.3 },
  patternVB: { w: 1000, h: 700 },
  chartReady: false,

  init(svg, brief) {
    this.svg = svg;
    this.patternPoints = brief.pattern_points || {};
    this.plane.x = brief.plane.pos[0];
    this.plane.y = brief.plane.pos[1];

    this.chartLayer = el("g");
    this.planeEl = el("path", {
      d: PLANE_PATH,
      fill: "#f5a623",
      stroke: "#332200",
      "stroke-width": 0.35,
      "stroke-linejoin": "round",
    });
    this.svg.append(this.chartLayer, this.planeEl);

    this.loadChart(); // async; applies the ground scene once ready
    this.applyScene();

    let last = performance.now();
    const loop = (now) => {
      this.tick((now - last) / 1000);
      last = now;
      this.render();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  },

  async loadChart() {
    try {
      const txt = await (await fetch("assets/ksba-diagram.svg")).text();
      const doc = new DOMParser().parseFromString(txt, "image/svg+xml");
      const root = doc.documentElement;
      const vb = (root.getAttribute("viewBox") || "0 0 504.4 351.3")
        .split(/[\s,]+/).map(Number);
      this.groundVB = { w: vb[2], h: vb[3] };
      this.chartNodes = Array.from(root.childNodes)
        .filter((n) => n.nodeType === 1)
        .map((n) => document.importNode(n, true));
      this.chartReady = true;
      if (this.view === "ground") this.applyScene();
    } catch (e) {
      // fall back to the raster twin so the ground view still shows the chart
      console.error("chart svg load failed, using png fallback", e);
      this.chartFallback = true;
      if (this.view === "ground") this.applyScene();
    }
  },

  setView(v) {
    // label update is idempotent — do it before the guard so the initial
    // "AIRPORT DIAGRAM" caption shows even when the scene is already applied.
    document.getElementById("view-label").textContent =
      v === "ground" ? "AIRPORT DIAGRAM" : "AREA · SANTA BARBARA COASTLINE";
    if (v === this.view && this.sceneApplied) return;
    this.view = v;
    this.applyScene();
  },

  vb() {
    return this.view === "ground" ? this.groundVB : this.patternVB;
  },

  applyScene() {
    const vb = this.vb();
    this.svg.setAttribute("viewBox", `0 0 ${vb.w} ${vb.h}`);
    this.chartLayer.replaceChildren();
    if (this.view === "ground") {
      // the FAA chart assumes paper-white; back it so it reads on the dark panel
      this.chartLayer.append(el("rect", {
        x: 0, y: 0, width: vb.w, height: vb.h, fill: "#ffffff",
      }));
      if (this.chartReady) {
        this.chartLayer.append(...this.chartNodes);
      } else if (this.chartFallback) {
        this.chartLayer.append(el("image", {
          href: "assets/ksba-diagram.png", x: 0, y: 0, width: vb.w, height: vb.h,
        }));
      }
    } else {
      this.buildPattern(this.chartLayer);
    }
    this.sceneApplied = true;
  },

  // ---- coordinate mapping -------------------------------------------------

  toPx(nx, ny) {
    const vb = this.vb();
    return [nx * vb.w, ny * vb.h];
  },

  // ---- animation (unchanged engine; operates in normalized space) ---------

  runActions(actions, onLeg) {
    let p = Promise.resolve();
    for (const a of actions) {
      if (a.type !== "move") continue;
      p = p.then(() => {
        this.setView(a.view);
        if (!a.path || a.path.length < 2) {
          if (a.path && a.path.length) {
            this.plane.x = a.path[a.path.length - 1][0];
            this.plane.y = a.path[a.path.length - 1][1];
          }
          if (a.leg && onLeg) onLeg(a.leg);
          return;
        }
        // teleport to path start (view switches between ground/pattern spaces)
        this.plane.x = a.path[0][0];
        this.plane.y = a.path[0][1];
        return this.animatePath(a.path, a.speed).then(() => {
          if (a.leg && onLeg) onLeg(a.leg);
        });
      });
    }
    return p;
  },

  animatePath(path, speed) {
    return new Promise((resolve) => {
      this.anim = {
        pts: path.map(([x, y]) => ({ x, y })),
        seg: 0,
        t: 0, // fraction along current segment
        speed: this.SPEEDS[speed] || 60,
        resolve,
      };
    });
  },

  tick(dt) {
    const a = this.anim;
    if (!a) return;
    // speed is defined against a 900-unit-tall reference view
    let travel = a.speed * (this.vb().h / 900) * dt;

    while (a.seg < a.pts.length - 1) {
      const p0 = a.pts[a.seg], p1 = a.pts[a.seg + 1];
      const [x0, y0] = this.toPx(p0.x, p0.y);
      const [x1, y1] = this.toPx(p1.x, p1.y);
      const segLen = Math.max(Math.hypot(x1 - x0, y1 - y0), 1e-6);
      if (segLen > 1) {
        this.plane.heading = Math.atan2(y1 - y0, x1 - x0);
      }
      const remain = segLen * (1 - a.t);
      if (travel < remain) {
        a.t += travel / segLen;
        this.plane.x = p0.x + (p1.x - p0.x) * a.t;
        this.plane.y = p0.y + (p1.y - p0.y) * a.t;
        return;
      }
      travel -= remain;
      a.seg += 1;
      a.t = 0;
    }

    const end = a.pts[a.pts.length - 1];
    this.plane.x = end.x;
    this.plane.y = end.y;
    this.anim = null;
    a.resolve();
  },

  // ---- drawing ------------------------------------------------------------

  render() {
    const [px, py] = this.toPx(this.plane.x, this.plane.y);
    const deg = this.plane.heading * 180 / Math.PI + 90; // nose (−y) -> heading
    const s = (this.view === "ground" ? 0.020 : 0.024) * this.vb().h;
    this.planeEl.setAttribute(
      "transform", `translate(${px} ${py}) rotate(${deg}) scale(${s})`);
  },

  buildPattern(g) {
    const { w: W, h: H } = this.patternVB;
    const line = (H * 0.0025);
    g.append(el("rect", { x: 0, y: 0, width: W, height: H, fill: "#233140" }));

    // ocean below the coastline
    const coast = `M 0 ${H * 0.82} C ${W * 0.3} ${H * 0.77}, ${W * 0.6} ${H * 0.83}, ${W} ${H * 0.79}`;
    g.append(el("path", { d: `${coast} L ${W} ${H} L 0 ${H} Z`, fill: "#0f3552" }));
    g.append(el("path", { d: coast, fill: "none", stroke: "#5b7f9c", "stroke-width": line * 2 }));

    const label = (x, y, t, fill, size = H * 0.02, anchor = "start") => {
      const n = el("text", {
        x, y, fill, "font-size": size, "text-anchor": anchor,
        "font-family": "ui-monospace, Menlo, monospace",
      });
      n.textContent = t;
      g.append(n);
    };
    label(W * 0.42, H * 0.93, "PACIFIC OCEAN", "#5b7f9c");

    // airport symbol: the two runway orientations
    const ap = this.patternPoints.airport || [0.24, 0.58];
    const [ax, ay] = [ap[0] * W, ap[1] * H];
    const L = H * 0.03;
    g.append(el("line", {
      x1: ax - L, y1: ay + L * 0.25, x2: ax + L, y2: ay - L * 0.25,
      stroke: "#c8d4e0", "stroke-width": line * 5,
    }));
    g.append(el("line", {
      x1: ax - L * 0.3, y1: ay - L * 0.7, x2: ax + L * 0.3, y2: ay + L * 0.7,
      stroke: "#c8d4e0", "stroke-width": line * 3,
    }));
    label(ax - L, ay - L, "KSBA", "#c8d4e0");

    // 10-mile east reference
    const e10 = this.patternPoints.east_10mi || [0.86, 0.70];
    const [ex, ey] = [e10[0] * W, e10[1] * H];
    g.append(el("circle", {
      cx: ex, cy: ey, r: H * 0.012, fill: "none", stroke: "#5b7f9c", "stroke-width": line,
    }));
    label(ex, ey + H * 0.045, "10 NM EAST", "#5b7f9c", H * 0.02, "middle");
  },
};

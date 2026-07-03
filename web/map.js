// Map rendering: the FAA airport diagram for ground ops, a stylized coastal
// view for the airborne legs. Coordinates from the server are normalized 0..1.

const GameMap = {
  canvas: null,
  ctx: null,
  img: null,
  view: "ground",
  plane: { x: 0.378, y: 0.547, heading: -Math.PI / 2 },
  patternPoints: {},
  anim: null, // {pts:[{x,y}], seg, segT, speed, resolve}
  SPEEDS: { taxi: 40, roll: 150, fly: 65 }, // px/sec against a 900px reference height

  init(canvas, brief) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.patternPoints = brief.pattern_points || {};
    this.plane.x = brief.plane.pos[0];
    this.plane.y = brief.plane.pos[1];

    this.img = new Image();
    this.img.src = "assets/ksba-diagram.png";

    const fit = () => {
      const r = canvas.parentElement.getBoundingClientRect();
      canvas.width = r.width * devicePixelRatio;
      canvas.height = r.height * devicePixelRatio;
    };
    new ResizeObserver(fit).observe(canvas.parentElement);
    fit();

    let last = performance.now();
    const loop = (now) => {
      this.tick((now - last) / 1000);
      last = now;
      this.draw();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  },

  setView(v) {
    this.view = v;
    document.getElementById("view-label").textContent =
      v === "ground" ? "AIRPORT DIAGRAM" : "AREA · SANTA BARBARA COASTLINE";
  },

  // ---- coordinate mapping -------------------------------------------------

  groundRect() {
    // contain-fit the diagram image
    const cw = this.canvas.width, ch = this.canvas.height;
    if (!this.img.naturalWidth) return { x: 0, y: 0, w: cw, h: ch };
    const s = Math.min(cw / this.img.naturalWidth, ch / this.img.naturalHeight);
    const w = this.img.naturalWidth * s, h = this.img.naturalHeight * s;
    return { x: (cw - w) / 2, y: (ch - h) / 2, w, h };
  },

  toPx(nx, ny) {
    if (this.view === "ground") {
      const r = this.groundRect();
      return [r.x + nx * r.w, r.y + ny * r.h];
    }
    return [nx * this.canvas.width, ny * this.canvas.height];
  },

  // ---- animation ----------------------------------------------------------

  runActions(actions, onLeg) {
    // sequentially run move actions; call onLeg(legId) as each named leg finishes
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
    // speed is defined against a 900px-tall reference view
    let travelPx = a.speed * (this.canvas.height / 900) * dt;

    while (a.seg < a.pts.length - 1) {
      const p0 = a.pts[a.seg], p1 = a.pts[a.seg + 1];
      const [x0, y0] = this.toPx(p0.x, p0.y);
      const [x1, y1] = this.toPx(p1.x, p1.y);
      const segLenPx = Math.max(Math.hypot(x1 - x0, y1 - y0), 1e-6);
      if (segLenPx > 1) {
        this.plane.heading = Math.atan2(y1 - y0, x1 - x0);
      }
      const remainPx = segLenPx * (1 - a.t);
      if (travelPx < remainPx) {
        a.t += travelPx / segLenPx;
        this.plane.x = p0.x + (p1.x - p0.x) * a.t;
        this.plane.y = p0.y + (p1.y - p0.y) * a.t;
        return;
      }
      travelPx -= remainPx;
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

  draw() {
    const { ctx, canvas } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (this.view === "ground") this.drawGround();
    else this.drawPattern();
    this.drawPlane();
  },

  drawGround() {
    const { ctx } = this;
    const r = this.groundRect();
    ctx.fillStyle = "#e9e6df";
    ctx.fillRect(r.x, r.y, r.w, r.h);
    if (this.img.naturalWidth) ctx.drawImage(this.img, r.x, r.y, r.w, r.h);
  },

  drawPattern() {
    const { ctx, canvas } = this;
    const W = canvas.width, H = canvas.height;

    // sky / land
    ctx.fillStyle = "#233140";
    ctx.fillRect(0, 0, W, H);
    // ocean below the coastline
    const coastY = 0.80;
    ctx.fillStyle = "#0f3552";
    ctx.beginPath();
    ctx.moveTo(0, H * (coastY + 0.02));
    ctx.bezierCurveTo(W * 0.3, H * (coastY - 0.03), W * 0.6, H * (coastY + 0.03), W, H * (coastY - 0.01));
    ctx.lineTo(W, H);
    ctx.lineTo(0, H);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "#5b7f9c";
    ctx.lineWidth = 2 * devicePixelRatio;
    ctx.beginPath();
    ctx.moveTo(0, H * (coastY + 0.02));
    ctx.bezierCurveTo(W * 0.3, H * (coastY - 0.03), W * 0.6, H * (coastY + 0.03), W, H * (coastY - 0.01));
    ctx.stroke();

    ctx.font = `${12 * devicePixelRatio}px ui-monospace, Menlo, monospace`;
    ctx.fillStyle = "#5b7f9c";
    ctx.fillText("PACIFIC OCEAN", W * 0.42, H * 0.93);

    // airport symbol: the two runway orientations
    const ap = this.patternPoints.airport || [0.24, 0.58];
    const [ax, ay] = this.toPx(ap[0], ap[1]);
    const L = 22 * devicePixelRatio;
    ctx.strokeStyle = "#c8d4e0";
    ctx.lineWidth = 5 * devicePixelRatio;
    ctx.beginPath(); // 7-25: roughly ENE-WSW
    ctx.moveTo(ax - L, ay + L * 0.25);
    ctx.lineTo(ax + L, ay - L * 0.25);
    ctx.stroke();
    ctx.lineWidth = 3 * devicePixelRatio;
    ctx.beginPath(); // 15-33
    ctx.moveTo(ax - L * 0.3, ay - L * 0.7);
    ctx.lineTo(ax + L * 0.3, ay + L * 0.7);
    ctx.stroke();
    ctx.fillStyle = "#c8d4e0";
    ctx.fillText("KSBA", ax - L, ay - L);

    // 10-mile east reference
    const e10 = this.patternPoints.east_10mi || [0.86, 0.70];
    const [ex, ey] = this.toPx(e10[0], e10[1]);
    ctx.strokeStyle = "#5b7f9c";
    ctx.lineWidth = devicePixelRatio;
    ctx.beginPath();
    ctx.arc(ex, ey, 6 * devicePixelRatio, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#5b7f9c";
    ctx.fillText("10 NM EAST", ex - 34 * devicePixelRatio, ey + 22 * devicePixelRatio);
  },

  drawPlane() {
    const { ctx } = this;
    const [px, py] = this.toPx(this.plane.x, this.plane.y);
    const s = (this.view === "ground" ? 9 : 12) * devicePixelRatio;
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(this.plane.heading + Math.PI / 2);
    ctx.beginPath(); // simple aircraft silhouette
    ctx.moveTo(0, -s);           // nose
    ctx.lineTo(s * 0.22, -s * 0.25);
    ctx.lineTo(s, s * 0.15);     // right wing
    ctx.lineTo(s * 0.2, s * 0.2);
    ctx.lineTo(s * 0.35, s * 0.85); // right tail
    ctx.lineTo(0, s * 0.7);
    ctx.lineTo(-s * 0.35, s * 0.85);
    ctx.lineTo(-s * 0.2, s * 0.2);
    ctx.lineTo(-s, s * 0.15);    // left wing
    ctx.lineTo(-s * 0.22, -s * 0.25);
    ctx.closePath();
    ctx.fillStyle = "#f5a623";
    ctx.strokeStyle = "#332200";
    ctx.lineWidth = devicePixelRatio;
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  },
};

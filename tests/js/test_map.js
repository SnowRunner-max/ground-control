"use strict";

const assert = require("node:assert/strict");
const { beforeEach, test } = require("node:test");

global.document = {
  createElementNS: () => ({
    setAttribute() {},
  }),
  getElementById: () => ({ textContent: "" }),
};
global.performance = { now: () => 0 };
global.requestAnimationFrame = () => {};

const { GameMap } = require("../../web/map.js");

const original = {
  setView: GameMap.setView,
  loadChart: GameMap.loadChart,
  applyScene: GameMap.applyScene,
  animatePath: GameMap.animatePath,
};

beforeEach(() => {
  GameMap.view = "ground";
  GameMap.plane = { x: 0.2, y: 0.3, heading: 0 };
  GameMap.anim = null;
  GameMap.actionQueue = Promise.resolve();
  GameMap.sceneApplied = true;
  GameMap.groundVB = { w: 504.4, h: 351.3 };
  GameMap.patternVB = { w: 1000, h: 700 };
  GameMap.setView = original.setView;
  GameMap.loadChart = original.loadChart;
  GameMap.applyScene = original.applyScene;
  GameMap.animatePath = original.animatePath;
});

test("mission brief is the only initial aircraft position", () => {
  assert.throws(
    () => GameMap.init({}, { plane: { view: "ground" } }),
    /missing a valid aircraft position/,
  );

  GameMap.loadChart = () => {};
  GameMap.applyScene = () => {};
  const svg = { append() {} };
  GameMap.init(svg, {
    plane: { view: "ground", pos: [0.684, 0.237] },
    pattern_points: {},
  });
  assert.equal(GameMap.plane.x, 0.684);
  assert.equal(GameMap.plane.y, 0.237);
});

test("same-view action accepts a continuous start without repositioning", () => {
  GameMap.setView = function setView(view) { this.view = view; };
  const path = [[0.2, 0.3], [0.25, 0.3]];
  assert.equal(GameMap.prepareMove({ view: "ground", path }), path);
  assert.equal(GameMap.plane.x, 0.2);
  assert.equal(GameMap.plane.y, 0.3);
});

test("same-view action rejects a discontinuity", () => {
  GameMap.setView = function setView(view) { this.view = view; };
  assert.throws(
    () => GameMap.prepareMove({
      view: "ground",
      path: [[0.4, 0.5], [0.45, 0.5]],
    }),
    /Movement discontinuity in ground view/,
  );
  assert.deepEqual(GameMap.plane, { x: 0.2, y: 0.3, heading: 0 });
});

test("a rejected movement does not acknowledge its leg", async () => {
  GameMap.setView = function setView(view) { this.view = view; };
  const legs = [];
  await assert.rejects(
    GameMap.runActions([{
      type: "move",
      view: "ground",
      path: [[0.5, 0.5], [0.6, 0.5]],
      leg: "bad-leg",
    }], (leg) => legs.push(leg)),
    /Movement discontinuity/,
  );
  assert.deepEqual(legs, []);
});

test("view transition explicitly repositions into the new coordinate space", () => {
  GameMap.setView = function setView(view) { this.view = view; };
  const path = [[0.8, 0.7], [0.7, 0.6]];
  GameMap.prepareMove({ view: "pattern", path });
  assert.equal(GameMap.view, "pattern");
  assert.equal(GameMap.plane.x, 0.8);
  assert.equal(GameMap.plane.y, 0.7);
});

test("action batches serialize and acknowledge legs after movement", async () => {
  GameMap.setView = function setView(view) { this.view = view; };
  GameMap.animatePath = async function animatePath(path) {
    const end = path[path.length - 1];
    this.plane.x = end[0];
    this.plane.y = end[1];
  };
  const legs = [];
  await GameMap.runActions([
    { type: "move", view: "ground", path: [[0.2, 0.3], [0.3, 0.3]], leg: "one" },
    { type: "move", view: "ground", path: [[0.3, 0.3], [0.4, 0.3]], leg: "two" },
  ], (leg) => legs.push(leg));
  assert.deepEqual(legs, ["one", "two"]);
  assert.equal(GameMap.plane.x, 0.4);
});

test("taxi speed advances in pixels and heading follows the segment", async () => {
  GameMap.plane = { x: 0, y: 0, heading: 99 };
  const finished = GameMap.animatePath([[0, 0], [0.2, 0]], "taxi");
  GameMap.tick(1);

  const expectedTravelPx = 40 * (351.3 / 900);
  assert.ok(Math.abs(GameMap.plane.x - expectedTravelPx / 504.4) < 1e-9);
  assert.equal(GameMap.plane.y, 0);
  assert.equal(GameMap.plane.heading, 0);

  GameMap.tick(100);
  await finished;
  assert.equal(GameMap.plane.x, 0.2);
  assert.equal(GameMap.anim, null);
});

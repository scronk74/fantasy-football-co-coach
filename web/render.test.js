import { test } from "node:test";
import assert from "node:assert/strict";
import { ping } from "./render.js";

test("module loading works", () => {
  assert.equal(ping(), "pong");
});

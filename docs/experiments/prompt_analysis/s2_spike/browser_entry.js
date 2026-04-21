// Entry point for bundle-size measurement.
// Mirrors what a v1 PoC would expose: patterns + entropy.
// Validators are excluded by S2 scope (projected, not measured).
export { patterns } from "./patterns.js";
export { shannonEntropy } from "./entropy.js";

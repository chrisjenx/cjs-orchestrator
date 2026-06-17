// Minimal Zig build file — Zig is intentionally NOT in the support matrix, so this
// fixture exercises graceful degradation for an unrecognised ecosystem.
const std = @import("std");

pub fn build(b: *std.Build) void {
    const t = b.standardTargetOptions(.{});
    _ = t;
}

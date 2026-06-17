# fixture-unknown-stack

An intentionally unrecognised stack (Zig), with **no CI file**. Detection can't match it to
the support matrix, so it must degrade gracefully: mine this README for any real commands,
then ask the user for the rest and log what it couldn't detect.

## Building and testing

```
zig build         # build
zig build test    # run tests
```

There is no configured linter, type-checker, or coverage tool.

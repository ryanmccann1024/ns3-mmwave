# util/

## Scope
Generic string, path, and INI helpers. Standard library only: no ns-3, no `domain/` types.

## Files
- **ini-parser.h/cc** -- `IniMap`, `parseIni()`, `iniGet()`, `iniGetBool()`
- **string-utils.h/cc** -- `trimStr()`, `splitTab()`, `toIso8601()`, `resolvePath()`, `dirOf()`, `parseSeedList()`

## Behavior to preserve
- `parseIni` strips `#` and `;` comments before parsing, so values cannot contain
  either character. It throws `std::runtime_error` if the file cannot be opened.
- `iniGetBool` is true only for `true`/`1`/`yes` (case-insensitive); any other
  present value is false, with no error.
- `parseSeedList` calls `std::exit(1)` on a bad token; it does not throw.
- `toIso8601` uses POSIX `gmtime_r` and always outputs UTC.
- `resolvePath` returns empty or absolute inputs unchanged.
- `splitTab` has no callers in `src/` today.

## Changing a helper
Both `.cc` files are listed in the root `CMakeLists.txt` and in the Makefiles of
the `config`, `config-rules`, `io-cli`, `loader` and `query` unit suites; a new
`.cc` here must be added to all of them. There is no `util/` suite of its own:
`tests/unit/loader` tests `parseIni`, `iniGet`, `iniGetBool`, `toIso8601` and
`dirOf`; `tests/unit/config` tests `parseSeedList`; `tests/unit/io-cli` tests
`trimStr`.

## Dependencies
- Depends on: standard library only
- Depended on by: `config/` (`config-loader.cc`, `rl-control.cc`, `query-config.h`), `cli/` (`cli-parser.cc`), `io/` (`metrics-writer.cc`, `run-logger.h`), and the unit suites above

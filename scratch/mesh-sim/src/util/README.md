@page src_util src/util

@brief Standard-library string, path, and INI helpers shared by config, cli, and io.

These files have no ns-3 or `domain/` dependency. `parseIni` reads `run.ini` into
a two-level map (section, then key) that `ConfigLoader` queries to fill
`SimConfig`. The string helpers trim whitespace, split on tabs, format UTC
timestamps, resolve relative paths, and parse comma-separated seed lists.

## 1\. Module layout

| File | Role |
|------|------|
| `ini-parser.h` | `IniMap` alias and declarations for `parseIni`, `iniGet`, `iniGetBool`. |
| `ini-parser.cc` | Line-by-line INI parser: comment stripping, section headers, key-value split. |
| `string-utils.h` | Declarations for `trimStr`, `splitTab`, `toIso8601`, `resolvePath`, `dirOf`, `parseSeedList`. |
| `string-utils.cc` | Implementations of the string and path helpers. |

## 2\. Run

Nothing runs on its own; the files are compiled into the simulator. There is no
`util/` suite of its own; other suites test the helpers. Run from
`scratch/mesh-sim/`:

```bash
make -C tests/unit/loader test   # parseIni, iniGet, iniGetBool, toIso8601, dirOf
make -C tests/unit/config test   # parseSeedList
make -C tests/unit/io-cli test   # trimStr
```

## 3\. Output

Nothing is written to disk. Every function returns its result to the caller.

## 4\. Conventions

- **Comments in INI files.** `parseIni` drops everything from the first `#` or `;`
  on a line, so values cannot contain either character.
- **Keys before any section.** They are stored under the empty section name `""`.
- **Booleans.** `iniGetBool` is true for `true`, `1`, `yes` (any case). Any other
  present value is false, with no error.
- **Time.** `toIso8601` uses POSIX `gmtime_r` and returns UTC as
  `YYYY-MM-DDTHH:MM:SSZ`. It is not portable to Windows.
- **Unused helper.** `splitTab` has no callers in `src/` today.
- **Paths.** `resolvePath` returns empty or absolute paths unchanged and never
  checks that the file exists.
- **Error handling.** `parseIni` throws `std::runtime_error` for an unreadable
  file. `parseSeedList` prints `Error: ...` and calls `std::exit(1)` on a bad token.
- **Comments.** Headers use Doxygen `/** */` blocks with `@fn`, `@brief`,
  `@param`, `@return`.

## 5\. Dependencies

- C++17 standard library (`<filesystem>`, `<chrono>`); no third-party packages.
- POSIX `gmtime_r` for `toIso8601`.

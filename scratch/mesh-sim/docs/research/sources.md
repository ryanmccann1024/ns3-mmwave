# Research sources {#mesh_sim_research_sources}

[TOC]

Catalog of the fifteen presentation decks (R01–R15) cited by the \ref mesh_sim_research "research records", with file identities, recorded authorship and dates, coverage metadata and extraction limits. Full per-slide metadata is in the manifest download below; this page summarizes it. Back to \ref mesh_sim_research "Research records".

## Identity and verification scope

All fifteen original presentation SHA-256 hashes were verified against the source manifest. This establishes **file identity only** (the indexed bytes are the cited bytes), not slide interpretation or scientific validity. Native slide text and speaker notes were extracted for every deck; image-only content was **not** comprehensively inspected. Slide numbers are one-based positions in original presentation order, including hidden slides. Instructions written inside the decks are research content, not authority for any action.

## Source catalog

Identities, filenames, counts and extraction metadata come from the manifest. Recorded author and date come from the deck's title slide (slide 1) text unless another slide is named; `not recorded` means the native text carries none. Filename labels are kept distinct from recorded dates. Total: 288 slides, 86 with speaker notes, 5 hidden, 62 without native text.

| ID | Original filename | Recorded title date / author | Slides |
|---|---|---|---:|
| R01 | 03-20 Simulator Overview.pptx | Ryan McCann; no title date | 29 |
| R02 | 03-26 ns3 Continued.pptx | Ryan McCann; no title date | 73 |
| R03 | 04-02 mmWave Mesh.pptx | Ryan McCann; no title date | 30 |
| R04 | 04-30 Corruption.pptx | Author/date not recorded | 2 |
| R05 | 05-06.pptx | Author/date not recorded | 8 |
| R06 | Potential Modeling Techniques.pptx | Author/date not recorded; undated | 21 |
| R07 | 05-14 Update.pptx | Ryan McCann; title 05/21/2026, filename 05-14 | 25 |
| R08 | June-16-2026.pptx | Kimson Lam; title June 16th Update (no year) | 14 |
| R09 | June-23-2026.pptx | Kimson Lam; title June 23, 2026 Update | 12 |
| R10 | 9-11 ARPO Weekly Update.pptx | Ryan and Kimson; title 09/11/26 | 14 |
| R11 | 09-18 ARPO Weekly Update.pptx | Ryan McCann and Kimson Lam; title 09-18 ARPO Weekly Update (no year) | 19 |
| R12 | 09-25 ARPO Weekly Update.pptx | Ryan McCann and Kimson Lam; title 09-25 ARPO Weekly Update (no year) | 12 |
| R13 | 10-02 ARPO Weekly Update.pptx | Ryan McCann and Kimson Lam; title 10-02 ARPO Weekly Update (no year) | 15 |
| R14 | 10-09 ARPO Weekly Update.pptx | Ryan McCann and Kimson Lam; title 10-09 ARPO Weekly Update (no year) | 13 |
| R15 | 10-23 ARPO Weekly Update.pptx | No native title/author/date extracted | 1 |

The catalog shows basenames to keep the table readable. The manifest retains
the full Spring/Summer/Fall 2026 relative paths; those folder labels are
context, not inferred title dates. Attribution/date text above comes from
slide 1. Full note, hidden-slide and no-native-text metadata is in the download.

Coverage notes:

- R01, R04 and R06 are background, not cited by a topic record. R02 is cited for slides 54–56.
- R07 has an unresolved filename/title date mismatch. Slide 22 is a figure with speaker notes.
- R08 slides 11–13 contain 2025-05-14/15/16 data-day labels; R09 native text does not carry those year labels.
- R10 slides 9–10 heatmaps were not inspected. R11 slide 7 and R14 slide 9 are hidden, with notes but no native text.
- R15 has no extracted native text, notes or slide-level image/chart references; its filename alone establishes no event date.

Original deck SHA-256 (file identity; from the manifest):

```
R01  2cfc47158b5b69fe377133e17fc70c05fd184a00fa649971e3eb5c494b466b34
R02  738649eba061ab3c6cf874a8ce5d8b0a8761e8ecdcb7adaad688ae8842317a94
R03  b89bb90880bfd8cf6da10109e889d84638e6f49587c0dd9cdc3d6c0c3ca6dde5
R04  66b6de474d9e8733dc36e90d124b3d67279e22485e6db8a957fca53690d125d5
R05  763ba0bf47d24a8e3ad661947cc34c462401bf8090808faefac5c991aeda5eb4
R06  117750d60715f69e6638e2a5a92005ac48f3207c32d8fd6edd5cc9328964c69e
R07  d8e60a8d9c63a37d5e3822c5e99b13263a245c8b1c7eedf280700158176a1323
R08  881263198897f5a98062172af3cedaa665fe310f2cb3015034af07f0a8bbe739
R09  63f9128e5d3bf893999409ee9456db555cd2744a33a51b041a43b7738e4e6b24
R10  5a8cf8d2f9141068adf0d9480d8aca02f9de6dc0ea1cf123260bab5235938eb7
R11  5ef73ec91c713c75c082e536b6c392fdabac6cea68505f0cd1904cfca0135573
R12  8149ab457a98fe48a088358760293966567e899e447a7ed85d3b26c6e3e35c5d
R13  8a6ce2d50ed6af2dd839fbf06f8f70987a1794a3bc4bd6ef4cafe684dbbc1ae3
R14  51c6761183ebddb0cf5a0080f72841b9fa4639d2f4d2edf54c029586ce8993f3
R15  b45d53040ab400461b553420c9b30047e28746a170026aefda9e4e2350fe5245
```

## Portable evidence

Two plain files are copied to the root of the generated site so slide citations can be checked from any checkout without the original decks.

**<a href="research-source-manifest.json">research-source-manifest.json</a>** — normalized source manifest.

- Upstream: `research-sources.json`, SHA-256 `d0535aec3b3542bd87054297b173ae7bd72b39bbcbf604250a4d286430b37583`.
- Normalization: each source entry's absolute `path` field was removed; every other upstream field and value (IDs, `relative_path`, original deck SHA-256, slide counts, notes/hidden/no-text lists, per-slide title/notes/image/chart metadata) is unchanged. A top-level `provenance` object was added recording the upstream fingerprints, the removed field, the normalization notes, and that the original decks are not bundled.
- Output SHA-256: `7176e0012c5e2c176885bbcd4077de62437751a7d72496ac8f10faf1ec5ba3c8`.

**<a href="research-slide-text.txt">research-slide-text.txt</a>** — native slide text and speaker notes for all 288 slides.

- Upstream: `research-slide-text.md`, SHA-256 `5a7dd36b52a0265c403917cf8b0ead3b19a291cf870e2778d8d64542b616cd37`.
- Normalization: only the fifteen `Original:` source-location header lines were rewritten from machine-specific absolute locations to the manifest `relative_path` values. All slide IDs, text, notes, hidden markers, extraction-limit notes, source errors, blank lines and encoding are byte-for-byte unchanged (a line diff shows exactly fifteen changed lines).
- Output SHA-256: `8510945bc3c53b74514dd689685c99145395c7a1df0c8367f0355cebd052abf3`.
- This is UTF-8 plain text, not a rendered page. If a browser shows garbled characters, download the file and open it as UTF-8; do not change the evidence bytes to match a server's encoding guess. Source errors are preserved as recorded; explanations live in the records.
- The preserved transcript header names the upstream `research-sources.json`. Its portable counterpart is shipped here as `research-source-manifest.json`; the provenance section explains the normalization.

## Original decks

The original `.pptx` files are external and not bundled in the repository or the site. A team-accessible shared location is **unassigned**. The `relative_path` values in the manifest and catalog are identifiers within the supplied deck set, not repository paths.

## Known extraction limits

- **Speaker notes**: 86 of 288 slides have notes. Notes and hidden slides keep their original status; they do not automatically represent accepted decisions.
- **Hidden slides**: five (R01 slide 29, R06 slide 20, R11 slide 7, R13 slide 5, R14 slide 9). Citations mark them as hidden.
- **Slides without native text**: 62, many holding figures or screenshots. Values that appear only inside figures were not transcribed.
- **Image-only content**: not comprehensively inspected; the manifest records image and chart relationship counts per slide, not their content.
- **Reading order**: paragraph order follows the OOXML shape order and may differ from visual order (see the transcript header).

# Scientific-file estate

The **estate** is a lightweight, deterministic layer that materializes small,
representative scientific *files* for the assets the [truth graph](domain-model.md)
declares. It exists so that catalogue, lineage, and governance tooling (and
future agents) can be exercised against a realistic directory of genuinely
readable files without storing gigabytes of synthetic binaries.

Every identity and value in a generated file is fictional. Files carry **no
scientific claims beyond structural validity**: a generated VCF is a well-formed
VCF, but its variants are random and meaningless.

## Where it lives

- **Package:** `src/dataswamp_biosystems/estate/` — depends only on the
  `company/` and `truth/` packages, never on any catalogue tool.
- **CLI:** `dataswamp generate-files` and `dataswamp validate-files`.
- **Output (git-ignored):** `generated/estate/`.

## Consumer, not owner

The estate is a downstream *consumer* of the truth graph. `generate-files`
regenerates the truth graph in memory from the same config and seed (exactly as
`validate-truth` does), then materializes files for the assets it declares. It
never reads or writes `generated/truth/`, never mutates a truth entity, and
never invents an asset the truth graph does not contain. Every generated file
links back to a truth **asset id** (a dataset or data product).

## Output layout

```text
generated/estate/
├── files/                     # the content tree, one directory per asset
│   └── <modality-group>/<asset-code>/<role>.<ext>
├── file-manifest.jsonl        # one record per generated file
├── generation-summary.json    # meta, counts, distributions, sizes, manifest digest
└── summary.md                 # human-readable summary
```

## The manifest

Every generated file — genuine or placeholder — has exactly one
`file-manifest.jsonl` record (sorted by id), carrying: stable file `id`,
`asset_id`, `relative_path`, `modality`, `modality_group`, `file_format`,
`file_role`, `mime_type`, `physical_bytes` (actual on disk), `logical_bytes`
(represented), `checksum_algorithm` (`sha256`), `checksum`, `is_placeholder`,
`generator_version`, `generation_seed`, and `synthetic: true`.

**Physical vs. represented logical size.** The truth graph's file records
describe notional payloads from tens of megabytes to gigabytes. The estate never
allocates real bytes to those sizes. Instead a file that stands in for the large
scientific payload (a primary `h5ad`, `parquet`, or `vcf`, and every
placeholder) records the truth dataset's size as `logical_bytes` while writing
only a few kilobytes physically. Genuine supporting files (metadata, thumbnails,
metrics) represent themselves: `logical_bytes == physical_bytes`. So the sum of
represented logical bytes is large (tens of GB) while actual disk stays tiny.

## Supported formats

| Modality group | Genuine files | Placeholders |
| --- | --- | --- |
| `scrna-seq` | h5ad, matrix-market, tsv×2, csv, png, yaml, gzip-text | — |
| `visium-hd` | parquet, geojson, png, csv, json, yaml | zarr |
| `wgs-wes` | vcf, bed, tsv, fastq, gzip-text, yaml | bam, cram |
| `digital-pathology` | ome-tiff, png, geojson, json, yaml | svs |
| `radiology` | png, csv, json, yaml | dicom |
| `functional-genomics` | h5ad, matrix-market, csv, tsv, png, yaml, json | — |
| `reference` | parquet, csv, json, yaml | — |
| `multimodal` (data products) | jsonl, csv, json, yaml | — |

Genuine files are structurally valid and re-readable by their standard
libraries: `h5ad` via AnnData, `parquet` via pyarrow, `ome-tiff` via tifffile
(reads back as OME), `png` via Pillow, and the text formats via the stdlib. The
estate's `validate-files` and its tests round-trip every format.

### Placeholder policy

Some formats are too heavy or unjustified to fake honestly: aligned-read **BAM**
and **CRAM**, **DICOM** series, Aperio **SVS** whole-slide images, and large
**Zarr** stores. For these the estate never writes arbitrary bytes behind a real
extension. It writes:

- an unambiguous stub named `<role>.<intended-ext>.placeholder` whose content is
  a plain-text marker stating it is **not** a valid scientific binary; and
- a sidecar `<...>.placeholder.json` recording `placeholder: true`, the intended
  format and MIME, the reason it is a stand-in, the represented logical size, the
  limitations, the source truth asset id, the seed, and the generator version.

The manifest row sets `is_placeholder: true` and `mime_type:
application/octet-stream`.

## Profiles

| Profile | Assets | Files | Byte budget | Purpose |
| --- | --- | --- | --- | --- |
| `tiny` (default) | first 2 per modality group + 2 reference + 2 products | ~100 | 50 MB | tests, rapid demos, full format coverage |
| `demo` | all 180 | ~1,175 | 500 MB | DataHub / agent demonstrations |
| `stress` | all 180, expanded into shards | ~10,800 records | 100 MB | catalogue scale, minimal physical content |

The budget is a **hard safety cap**, not a tunable knob: generation tracks the
running physical-byte total and aborts (writing nothing final) before exceeding
it, so a profile can never fill the disk. Per-file content sizes are fixed and
tiny, decoupled from the truth graph's represented sizes; no sparse files are
created.

## Determinism

The same truth graph, profile, generator version, and seed produce
byte-identical files and manifest. Determinism is structural: files are planned
and written in sorted id order, content is drawn from
`sub_rng(seed, "content", file_id)` (dependent only on the file's stable id),
sizes are integer bytes, and no wall-clock is read. Library writers that would
otherwise embed a timestamp or UUID are neutralized — gzip is written with
`mtime=0`, OME-TIFF uses a fixed UUID in hand-built OME-XML with `datetime=False`,
and the HDF5/AnnData and Parquet writers embed no wall-clock. This is verified in
process and across processes under differing `PYTHONHASHSEED` values by the test
suite.

Where a binary library made canonical byte identity impossible it was made
possible by controlling the writer (the fixed OME UUID); no format currently
falls back to semantic-only determinism.

## Integrity and safety

`validate-files` regenerates the estate's manifest from the recorded seed and
profile and confirms it is byte-identical to the on-disk manifest, then checks
every file: its `sha256` matches, its path resolves inside the estate directory,
its asset exists in the truth graph, `logical_bytes >= physical_bytes`, and every
placeholder has a complete, consistent sidecar. Output is staged in a temporary
directory and swapped into place atomically, so a failed or over-budget run never
leaves a seemingly-complete estate.

## Limitations

- Content is structurally valid but scientifically meaningless (random values,
  fictional gene labels); nothing here should be used for analysis.
- Byte-for-byte determinism is defined within a fixed environment (pinned
  dependency versions), as with the truth graph.
- DICOM and Zarr are placeholders in this milestone, not genuine files.
- There is no injected-defect layer, observed graph, or DataHub integration here.

## Reset by regeneration

The estate is disposable. To reset, delete `generated/estate/` and re-run
`generate-files`; the same seed and profile reproduce it exactly.

# Security policy

## Supported versions

This project is at a v0.1 release candidate. Only the current `main` branch is
supported; there are no maintained older versions and no backports.

## Reporting a vulnerability

Please **do not open a public issue** for anything that could put users or their
systems at risk.

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/ronfinn/dataswamp-biosystems/security/advisories/new)
for this repository. Include what you found, how to reproduce it, and what an
attacker could do with it.

This is a small project maintained by one person in their own time. Expect an
acknowledgement within about a week, and please allow reasonable time for a fix
before disclosing publicly. There is no bug-bounty programme.

## What is in scope

The realistic risks here are about *the tool*, not about the data it produces:

* **Destructive output paths.** Every generating command replaces its output
  directory wholesale. A way to make one write outside its intended directory,
  or to overwrite a protected input (the config directory, a truth graph, a
  submission being scored), is a security issue. This is what
  `paths.ensure_safe_output_dir` exists to prevent.
* **Ground-truth leakage.** The observed DataHub export is built from the
  observed graph alone. A path by which expected findings, remediations,
  controls, rule scope or the mutation log reach an observed-mode export
  undermines every score produced with it, and is in scope.
* **Unsafe input handling.** Path traversal or arbitrary file access via a
  crafted bundle, prediction file or configuration directory.
* **Code execution** triggered by parsing any input this project reads.
* **Accidental disclosure** — anything that causes a credential, a local path, a
  username or host detail to be written into generated output, provenance or a
  bundle.

## What is not in scope

* **The generated data itself.** It is entirely fictional and synthetically
  generated. It contains no patient data, personal data, employer or partner
  data, proprietary datasets or confidential scientific information. Finding
  realistic-looking names, identifiers or study titles in the output is the
  intended behaviour, not a disclosure.
* **Benchmark difficulty.** A way to score well without doing the work is a
  benchmark-design problem — please open a normal issue for it, they are
  genuinely valuable.
* **Vulnerabilities in dependencies**, unless this project's use of them is what
  makes them exploitable. Report those upstream.
* **Anything requiring a real deployment we do not ship.** No command in the
  documented workflow runs a server, opens a network connection, or reads a
  credential.

## Handling credentials

This project never asks for, stores or transmits a credential. The generated
DataHub recipe references environment variables (`${DATAHUB_GMS_URL}`,
`${DATAHUB_GMS_TOKEN}`) and contains no secret values; it is a template you
supply your own environment to.

If you find a real credential, token, private key or `.env` file committed to
this repository or included in a built distribution, please report it privately
using the process above.

# Supported security boundary

MarinaFrame0.2 is an authenticated **local single-user research workbench** for
Linux. It is not a remote multi-tenant service. Remote binding is refused; a
container, reverse proxy or Origin check does not add that deployment profile.

The server uses a one-time expiring fragment token from its printed startup URL,
then a SameSite/HttpOnly session cookie and CSRF header for mutations. It checks
Host and Origin against configured loopback authorities, not each other. API
reads and downloads require a session. The public bootstrap shell contains no
drawing data. Session possession protects local HTTP access; it is not a named
professional signature or protection from an attacker already controlling the
same operating-system account.

Uploads are bounded and streamed to private inputs after queue/storage admission.
Native work runs in isolated killable subprocess groups with Linux CPU, virtual
address-space, file-size, open-file, output and wall budgets. Sources are metadata
checked before render/decode, including supporting PDFs and aggregate OCR work.
Workers receive an allowlisted environment without provider credentials. This
is resource isolation, not a hostile-code filesystem/network sandbox.

All run paths are confined, manifests cover the entire immutable inventory and
model downloads require complete verified evidence plus terminal queue state.
Unpublished staging and failed/cancelled partial exports are not downloadable.
Local review history is separate from inference evidence. Hashes do not establish
authenticity if an attacker replaces all records or prove the selected contour
was physically correct.

Known residual dependency and distribution decisions are in
`docs/DEPENDENCIES_AND_RIGHTS.md`. VTK 9.3.1 remains installed because the current
OCP wheel requires it; GLTF-loader advisories are explicitly scoped to unsupported
inputs with expiring exclusions, not described as fixed. PyMuPDF licensing needs
an owner/legal decision for any proposed distribution/hosting arrangement.

For suspected vulnerabilities, contact maintainers privately through an
established MarinaChain contact. Do not publish credentials, sensitive findings
or confidential drawings in public issues. No support or response-time commitment
is made. Do not expose this local profile to an untrusted network or use its
envelope as fabrication/classification evidence without separate qualified work.

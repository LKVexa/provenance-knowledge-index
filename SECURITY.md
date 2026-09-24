# Security boundaries

This library computes over text supplied by its caller without file/network I/O.
Source labels are unverified claims and are never dereferenced. Retrieved content
is untrusted data; do not execute it, treat it as an instruction, or assume its
claims are true. Escape output for any rendering context.

Original document text remains in memory for provenance reconstruction. Snapshots,
query text, snippets and citations may disclose sensitive data. There is no caller
identity, tenant isolation, redaction, encryption, persistence or retention layer.
The embedding application controls those responsibilities.

State, chunk and answer hashes detect consistency changes but do not authenticate
records or protect against a process owner rewriting private state and hashes.
Public views are detached; unsupported private-field manipulation is not a security
boundary. In-process locks protect supported operations, not separate processes.

Input/corpus/query caps bound intended workloads but are not an OS sandbox or
hard latency guarantee. This prototype rebuilds/checks state and is not designed
for large-scale hostile multiuser query traffic. No third-party runtime package
is needed, and no build-tool vulnerability scan or original gate certification
is claimed. Report issues using synthetic documents and queries.

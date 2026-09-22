# Security

Docstate lets anyone with publish rights put HTML with scripts on the site, so
the sandbox is the product. If you find a way for a document to read the
reader's session, call the site's API directly, reach another document's
state, or escape the iframe, please report it privately.

- Open a [private security advisory](https://github.com/qiaob/docs-site/security/advisories/new) on GitHub.
- Include the document (or a minimal reproduction) and the browser you used.

We will acknowledge within a few days and coordinate a fix and disclosure.
The threat model and the boundaries we defend are written up in
[docs/security.md](docs/security.md).

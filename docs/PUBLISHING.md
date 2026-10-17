# Release maintenance

The public repository is [hybrid-symbolic-llm-name-address-parsing](https://github.com/MohdMuzakkiruddinAhmed/hybrid-symbolic-llm-name-address-parsing). The study snapshot is tagged `v0.5.0`; its [release page](https://github.com/MohdMuzakkiruddinAhmed/hybrid-symbolic-llm-name-address-parsing/releases/tag/v0.5.0) hosts the larger LLM results archive, source distribution and archive checksums. The corpus archive is already tracked in `artifacts/`.

For later releases:

1. Keep the frozen v0.5.0 implementation and artifacts available under their original tag. Record changed methods under a new protocol and version.
2. Run the core tests, restore the corpus and verify all registered checksums. For changed evaluation or analysis, also run the relevant saved-response reproduction.
3. Refresh the publication file manifest and source archive from the exact files being released. Record SHA-256 digests for each archive.
4. Commit the reviewed publication files, push a new tag and create its release using that version's notes. Attach the corresponding saved-results archive and checksums.
5. Verify public visibility, the detected MIT code license, downloadable assets and GitHub Actions results. Keep third-party data notices and annotation provenance with the release.

Source and result archives omit credentials, private session identifiers and local authentication metadata. Predictive implementation and scientific records retain the preservation checks described in [publication provenance](PUBLICATION.md).

# I51 protected SDK-pin delta review

**Disposition: GO_PIN_DELTA_ONLY.** The public `protected_simnow.py` diff replaces exactly the three supplied hashes: the `bt_api_base` RECORD, the `bt_api_ctp` wheel, and the `bt_api_ctp` RECORD. Distribution versions, wheel filenames, and the remaining artifact fields are unchanged. The file is 8,556 bytes with SHA-256 `c4269bb9b78e40fd60843e32af5616dece5052d621258add12ba82f9696c1982`.

The supplied public installed-verification receipt reports `PASS_INSTALLED_WRAPPER_AND_PUBLIC_ARTIFACT_GATE_ONLY`, matches the installed Store source and protected-helper pins, records 667 payload files and 676 hashed RECORD entries, and says the wrapper was created with no SDK clients, private configuration read, native API, or provider call. Its exact pin is 1,332 bytes / `c7eb5f8971d4f6a14d698821ea2730bed18935bbf6b165139d7880c1f16ab7a9`. The receipt does not enumerate the CTP wheel and RECORD digests as separate result fields, so this review treats the declared gate status plus the source diff as the available evidence for those updated pins.

I inspected only the named public helper diff and the supplied public receipt. No SDK code was imported or executed; no private reader/configuration was accessed. This is installed artifact and wrapper-provenance evidence, not provider/account or formal acceptance.

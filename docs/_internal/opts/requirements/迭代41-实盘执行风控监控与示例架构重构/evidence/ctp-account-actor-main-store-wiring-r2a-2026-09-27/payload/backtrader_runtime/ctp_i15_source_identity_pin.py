"""Code-owned root for the I15 source manifest.

This pin is excluded from both I15 and I13 package manifests to avoid a
cross-candidate digest cycle. It remains an explicit trust root that requires
independent review; an unset value keeps all I15 supervision fail closed.
"""

I15_REVIEWED_SOURCE_MANIFEST_SHA256 = None

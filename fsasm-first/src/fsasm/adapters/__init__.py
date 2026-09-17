"""FS-ASM local inference adapters (T19+).

Adapters translate only transport and format between the provider-neutral
:class:`fsasm.gateway.ModelBackend` contract and a concrete local inference
server. They hold no domain rules (no retry, no PASS, no scope/routing policy).
"""

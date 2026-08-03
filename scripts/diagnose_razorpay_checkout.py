#!/usr/bin/env python3
"""Print Razorpay checkout diagnosis checklist (keys, contact format, OTP flows)."""

from __future__ import annotations

import sys

from app.config import reload_settings
from app.payments.razorpay_client import clear_client_cache, probe_credentials


def main() -> int:
    reload_settings()
    clear_client_cache()
    s = reload_settings()
    kid = s.razorpay_key_id or ""
    test_mode = kid.startswith("rzp_test_")
    config_id = (s.razorpay_checkout_config_id or "").strip()

    print("=== Razorpay checkout diagnosis ===\n")
    print(f"RAZORPAY_ENABLED:              {s.razorpay_enabled}")
    print(f"Key ID prefix:                 {kid[:16]}…" if len(kid) > 16 else f"Key ID:                        {kid or '(unset)'}")
    print(f"Test mode:                     {test_mode}")
    print(
        f"RAZORPAY_CHECKOUT_CONFIG_ID:   {config_id or '(unset — UPI may be missing; see Dashboard steps below)'}"
    )

    if s.razorpay_key_id and s.razorpay_key_secret:
        ok, msg = probe_credentials()
        print(f"API probe:                     {'PASS' if ok else 'FAIL — ' + msg}")
    else:
        ok = False
        print("API probe:                     SKIP (keys missing)")

    print("\n--- Dashboard Payment Configuration (required for UPI) ---")
    print("1. Account & Settings → Checkout Features → turn OFF Flash checkout")
    print("2. Account & Settings → Payment Configuration (Standard Payment Options)")
    print("   Enable UPI (Apps/Intent), UPI QR Code, Cards, Netbanking — UPI first")
    print("3. Save as Default and copy Configuration ID (config_…)")
    print("4. Add to backend/.env: RAZORPAY_CHECKOUT_CONFIG_ID=config_xxxxxxxx")
    print("5. Full backend restart after .env change")
    if config_id:
        print(f"\nConfigured config ID will be sent on order.create and to checkout JS.")

    print("\n--- Card OTP (save-card vs payment OTP) ---")
    print(
        "Screen: 'Securely saving your card' = SAVE-CARD tokenization OTP (real SMS).\n"
        "It is NOT the test payment OTP. Random digits will fail with a misleading\n"
        "'Please enter a 6 digit OTP' message.\n"
    )
    print("Fix in checkout UI:")
    print("  1. Uncheck 'Save this card as per RBI guidelines' before Pay")
    print("  2. Or click 'Skip OTP' on the save-card screen")
    print("  3. Payment OTP (after Pay): any 4–10 digits in test mode")
    print("\nBandForge code sets remember_customer=false (no save-card prompt from our side).")

    print("\n--- Contact prefill ---")
    print("Backend sends contact as E.164 (+91XXXXXXXXXX) for card OTP SMS routing.")

    print("\n--- Domestic vs international cards ---")
    print("Indian merchants reject international cards by default.")
    print("Visa 4111 often fails as 'international' when that method is off.")
    print("Prefer:")
    print("  Netbanking → any bank → Success   (fastest / most reliable)")
    print("  Mastercard domestic: 5267 3181 8797 5449 (Add new card; any CVV)")
    print("Optional Visa domestic: 4111 1111 1111 1111 (may still fail)")
    print("Do NOT use international test cards (5555 5555 5555 4444) or real foreign cards.")

    print("\n--- India test matrix ---")
    print("  Netbanking → Success     (fastest)")
    print("  Desktop UPI              scan QR with PhonePe/GPay/Paytm")
    print("  Mobile UPI               pick UPI app (Intent)")
    print("  Domestic Mastercard      5267… with Add new card")
    print("Note: success@razorpay VPA only on iOS mobile web; desktop uses QR (2026+ NPCI rules).")

    print("\n--- Dev environment ---")
    print("Run one frontend on port 3000 only (backend CORS is localhost:3000).")
    print("Do not rm -rf .next while npm run dev is running.")

    return 0 if (not s.razorpay_enabled or ok) else 1


if __name__ == "__main__":
    sys.exit(main())

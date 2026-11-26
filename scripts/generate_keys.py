"""
scripts/generate_keys.py — Generate cryptographic keys for SecureSearch Cloud

Run this ONCE before starting the application:
    python scripts/generate_keys.py

The script outputs .env variable assignments. Copy them into your .env file.

WARNING:
  - Keys are 256-bit values generated with a cryptographically secure RNG.
  - If you re-run this script, NEW keys are generated.
  - Existing encrypted data CANNOT be decrypted with new keys.
  - Back up your keys securely BEFORE running this in production.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.key_manager import generate_new_keys


def main():
    keys = generate_new_keys()

    print()
    print("=" * 70)
    print("  SecureSearch Cloud — Generated Cryptographic Keys")
    print("=" * 70)
    print()
    print("Add the following lines to your .env file:")
    print("(Replace any existing key values — but only if you have no stored data)")
    print()
    for name, value in keys.items():
        print(f"{name}={value}")
    print()
    print("=" * 70)
    print("IMPORTANT: Back up these values securely.")
    print("           If you lose your ENCRYPTION_KEY, all stored records")
    print("           become permanently unreadable.")
    print("           If you lose your SEARCH_KEY, all stored search indexes")
    print("           become permanently unsearchable.")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()

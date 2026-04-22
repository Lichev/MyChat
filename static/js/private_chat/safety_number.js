/**
 * safety_number.js — Signal-inspired 60-digit fingerprint.
 *
 * IMPORTANT: This is NOT bit-for-bit compatible with libsignal's
 * NumericFingerprintGenerator. Divergences from Signal v2:
 *   - This implementation hashes with SHA-256; Signal v2 uses SHA-512.
 *   - Each iteration is `h = SHA-256(h)`; Signal v2 re-injects the pubkey
 *     every round as `h = SHA-512(h || pubKey)`.
 * The iteration count (5200 per participant) and canonical sort-order
 * match Signal v2, but the digest and loop body do not. Users who
 * verify the 60-digit number against a libsignal-derived value will
 * see a mismatch — this is internal to MyChat, not interoperable.
 *
 * Algorithm:
 * - For each participant: input = IK_pub_ed25519_bytes + user_id_decimal_utf8_bytes.
 * - Sort participants by IK_pub_ed25519 (ascending byte comparison).
 * - For each sorted participant independently: iterate SHA-256 5200 times
 *   starting from that participant's input (no pubkey re-injection).
 * - Extract 30 decimal digits from each participant's final hash
 *   as 6 groups of 5 digits (big-endian uint40 mod 100000 per 5 bytes).
 * - Final result: 60 digits total — 30 from participant 1 + 30 from participant 2.
 * - Format: 12 groups of 5 digits, space-separated, newline after first 6.
 *
 * compute(selfIk, selfUid, peerIk, peerUid) → 60-digit string
 * format(digits)                             → formatted string (spaces + midline break)
 *
 * Computed entirely client-side from server-fetched public keys.
 * The server NEVER computes or transmits a safety number suggestion.
 */

'use strict';

(function (global) {

  /**
   * Per-participant fingerprint:
   * 5200 iterations of SHA-256 (h = SHA-256(h)) over the participant's
   * input, yielding 30 decimal digits. NOTE: This is NOT the same as
   * Signal v2's per-participant fingerprint, which uses SHA-512 and
   * re-injects the pubkey on each iteration. See file header.
   */
  async function _fingerprintForParticipant(ikPubEd25519Bytes, userIdStr) {
    const userIdBytes = new TextEncoder().encode(userIdStr);
    // Combine: IK_pub_ed25519 bytes + userId bytes
    const combined = new Uint8Array(ikPubEd25519Bytes.length + userIdBytes.length);
    combined.set(ikPubEd25519Bytes, 0);
    combined.set(userIdBytes, ikPubEd25519Bytes.length);

    // 5200 iterations of SHA-256.
    let current = combined;
    for (let i = 0; i < 5200; i++) {
      const hashBuf = await crypto.subtle.digest('SHA-256', current);
      current = new Uint8Array(hashBuf);
    }

    // Extract 30 decimal digits using Signal's chunk method.
    // Process 5 chunks of 5 bytes each (25 bytes used, 7 bytes ignored from 32-byte hash).
    // Each 5-byte chunk yields 1 group of 5 digits via big-endian uint40 mod 100000.
    let digits = '';
    for (let chunk = 0; chunk < 6; chunk++) {
      const offset = chunk * 5;
      // Read 5 bytes as big-endian uint40.
      let val = 0;
      for (let b = 0; b < 5; b++) {
        val = val * 256 + current[offset + b];
      }
      const group = String(val % 100000).padStart(5, '0');
      digits += group;
    }
    return digits; // 30 digits
  }

  /**
   * Compute the 60-digit safety number for a conversation.
   *
   * selfIk, peerIk: base64-encoded Ed25519 identity key public bytes.
   * selfUid, peerUid: user IDs as numbers or strings.
   *
   * Returns a 60-character string of decimal digits.
   */
  async function compute(selfIk, selfUid, peerIk, peerUid) {
    if (!selfIk || typeof selfIk !== 'string') {
      throw new Error('invalid input: self identity key is missing or not a string');
    }
    if (!peerIk || typeof peerIk !== 'string') {
      throw new Error('invalid input: peer identity key is missing or not a string');
    }

    await global.PM_CRYPTO_READY;
    const sodium = global.sodium;

    // Olm emits identity keys as standard base64 without padding
    // (alphabet +/, not the URL-safe -_ that libsodium-js defaults to),
    // so we must decode with ORIGINAL_NO_PADDING or ~73% of keys fail.
    const olmVariant = sodium.base64_variants.ORIGINAL_NO_PADDING;
    let selfIkBytes, peerIkBytes;
    try {
      selfIkBytes = sodium.from_base64(selfIk, olmVariant);
    } catch (e) {
      throw new Error('invalid input: self identity key is not valid base64');
    }
    try {
      peerIkBytes = sodium.from_base64(peerIk, olmVariant);
    } catch (e) {
      throw new Error('invalid input: peer identity key is not valid base64');
    }

    // Sort participants by IK bytes for canonical ordering.
    let firstIk, firstUid, secondIk, secondUid;
    let cmp = 0;
    for (let i = 0; i < Math.min(selfIkBytes.length, peerIkBytes.length); i++) {
      if (selfIkBytes[i] !== peerIkBytes[i]) {
        cmp = selfIkBytes[i] - peerIkBytes[i];
        break;
      }
    }
    if (cmp <= 0) {
      firstIk  = selfIkBytes; firstUid  = String(selfUid);
      secondIk = peerIkBytes; secondUid = String(peerUid);
    } else {
      firstIk  = peerIkBytes; firstUid  = String(peerUid);
      secondIk = selfIkBytes; secondUid = String(selfUid);
    }

    const firstDigits  = await _fingerprintForParticipant(firstIk,  firstUid);
    const secondDigits = await _fingerprintForParticipant(secondIk, secondUid);

    return firstDigits + secondDigits; // 60 digits total
  }

  /**
   * Format 60 digits as 12 groups of 5 with spaces, and a line break
   * after the 6th group (30 digits = first participant's contribution).
   *
   * Example output:
   *   "12345 67890 12345 67890 12345 67890\n12345 67890 12345 67890 12345 67890"
   */
  function format(digits) {
    if (!digits || digits.length !== 60) {
      return digits || '';
    }
    const groups = [];
    for (let i = 0; i < 12; i++) {
      groups.push(digits.slice(i * 5, i * 5 + 5));
    }
    const line1 = groups.slice(0,  6).join(' ');
    const line2 = groups.slice(6, 12).join(' ');
    return line1 + '\n' + line2;
  }

  global.PM_SAFETY_NUMBER = { compute, format };
})(window);

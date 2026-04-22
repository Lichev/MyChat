/**
 * safety_number.js — Signal v2 safety number derivation.
 *
 * Algorithm (blueprint § "Safety number (60-digit)"):
 * - For each participant: input = IK_pub_ed25519_bytes + user_id_decimal_utf8_bytes
 * - Sort participants by IK_pub_ed25519 (ascending byte comparison).
 * - Concatenate the two sorted inputs: combined = input_a + input_b
 * - Iterate SHA-256 5200 times starting with combined.
 * - Extract 30 decimal digits from each participant's iteration result,
 *   using Signal's iterative extraction: 6 groups of 5 digits.
 * - Final result: 60 digits total — 6 groups from participant 1 + 6 from participant 2.
 * - Format: 12 groups of 5 digits, space-separated, newline after first 6.
 *
 * compute(selfIk, selfUid, peerIk, peerUid) → 60-digit string
 * format(digits)                             → formatted string (spaces + midline break)
 *
 * This is computed entirely client-side from server-fetched public keys.
 * The server NEVER computes or transmits a safety number suggestion.
 */

'use strict';

(function (global) {

  /**
   * Signal v2 fingerprint for one participant:
   * 5200 iterations of SHA-256 over iterated hash, yielding 30 decimal digits.
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

    let selfIkBytes, peerIkBytes;
    try {
      selfIkBytes = sodium.from_base64(selfIk);
    } catch (e) {
      throw new Error('invalid input: self identity key is not valid base64');
    }
    try {
      peerIkBytes = sodium.from_base64(peerIk);
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

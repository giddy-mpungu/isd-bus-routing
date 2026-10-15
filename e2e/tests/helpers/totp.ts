import { createHmac } from 'node:crypto'

/**
 * The 6-digit code an authenticator app shows (RFC 6238: 30-second steps,
 * HMAC-SHA1), computed from the setup key the app is given. The API
 * accepts each code once, so `nextCode` waits for a fresh step when the
 * current one was already used.
 */

function base32(secret: string): Buffer {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  const clean = secret.replace(/[\s=]/g, '').toUpperCase()
  let bits = ''
  for (const char of clean) {
    const value = alphabet.indexOf(char)
    if (value < 0) throw new Error(`Not base32: ${char}`)
    bits += value.toString(2).padStart(5, '0')
  }
  const bytes: number[] = []
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2))
  return Buffer.from(bytes)
}

export function totp(secret: string, at: number = Date.now()): string {
  const step = Math.floor(at / 1000 / 30)
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(step))
  const hmac = createHmac('sha1', base32(secret)).update(counter).digest()
  const offset = hmac[hmac.length - 1] & 0x0f
  const value = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000
  return String(value).padStart(6, '0')
}

const lastUsed = new Map<string, number>()

/** A code from a time step this run hasn't used for this secret yet. */
export async function nextCode(secret: string): Promise<string> {
  let step = Math.floor(Date.now() / 30_000)
  while (lastUsed.get(secret) === step) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
    step = Math.floor(Date.now() / 30_000)
  }
  lastUsed.set(secret, step)
  return totp(secret)
}

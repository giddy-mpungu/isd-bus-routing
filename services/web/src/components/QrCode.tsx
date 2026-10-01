import { useEffect, useState } from 'react'

const QUIET_ZONE = 4 // modules of white border scanners expect

/**
 * Draws `value` as a QR code in SVG (Phase 5.3: authenticator setup). The
 * encoder is loaded only when this is shown, so it isn't in the main
 * bundle, and the SVG is built here, with no image URLs for the CSP to
 * allow.
 */
export function QrCode({
  value,
  label,
  size = 200,
}: {
  value: string
  label: string
  size?: number
}) {
  const [shape, setShape] = useState<{ path: string; count: number } | null>(null)

  useEffect(() => {
    let current = true
    void import('qrcode-generator').then(({ default: qrcode }) => {
      const qr = qrcode(0, 'M')
      qr.addData(value)
      qr.make()
      const count = qr.getModuleCount()
      let path = ''
      for (let row = 0; row < count; row++) {
        for (let col = 0; col < count; col++) {
          if (qr.isDark(row, col)) path += `M${col + QUIET_ZONE},${row + QUIET_ZONE}h1v1h-1z`
        }
      }
      if (current) setShape({ path, count })
    })
    return () => {
      current = false
    }
  }, [value])

  if (shape === null) {
    return <p className="status">Drawing the QR code…</p>
  }
  const side = shape.count + QUIET_ZONE * 2
  return (
    <svg
      className="qr-code"
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`0 0 ${side} ${side}`}
      shapeRendering="crispEdges"
    >
      <rect width={side} height={side} fill="#fff" />
      <path d={shape.path} fill="#000" />
    </svg>
  )
}

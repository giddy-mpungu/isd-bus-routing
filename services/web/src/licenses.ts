import type { LicenseClass } from './api/types'

// Spec section 15's classes, tiered: CDL A > CDL B > Class C (non-CDL).
export const LICENSE_CLASSES: LicenseClass[] = ['cdl_a', 'cdl_b', 'class_c']

export const LICENSE_LABELS: Record<LicenseClass, string> = {
  cdl_a: 'CDL A',
  cdl_b: 'CDL B',
  class_c: 'Class C (non-CDL)',
}

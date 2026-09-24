import { useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabItem {
  id: string
  label: string
  // Optional at-a-glance record count shown as a pill beside the label.
  count?: number
}

function tabId(idPrefix: string, id: string): string {
  return `${idPrefix}-tab-${id}`
}

function tabPanelId(idPrefix: string, id: string): string {
  return `${idPrefix}-panel-${id}`
}

// WAI-ARIA "tabs" pattern: one tab stop for the whole list (roving
// tabIndex), arrow keys / Home / End move between tabs and activate
// them (automatic activation -- every panel is already mounted, so
// switching is instant and there's no fetch to defer).
export function TabList({
  items,
  activeId,
  onSelect,
  idPrefix,
  label,
}: {
  items: TabItem[]
  activeId: string
  onSelect: (id: string) => void
  idPrefix: string
  label: string
}) {
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map())

  function focusAndSelect(index: number) {
    const item = items[(index + items.length) % items.length]
    onSelect(item.id)
    tabRefs.current.get(item.id)?.focus()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === 'ArrowRight') focusAndSelect(index + 1)
    else if (event.key === 'ArrowLeft') focusAndSelect(index - 1)
    else if (event.key === 'Home') focusAndSelect(0)
    else if (event.key === 'End') focusAndSelect(items.length - 1)
    else return
    event.preventDefault()
  }

  return (
    <div role="tablist" aria-label={label} className="tab-list">
      {items.map((item, index) => {
        const selected = item.id === activeId
        return (
          <button
            key={item.id}
            ref={(el) => {
              if (el) tabRefs.current.set(item.id, el)
              else tabRefs.current.delete(item.id)
            }}
            type="button"
            role="tab"
            id={tabId(idPrefix, item.id)}
            aria-selected={selected}
            aria-controls={tabPanelId(idPrefix, item.id)}
            tabIndex={selected ? 0 : -1}
            className="tab"
            onClick={() => onSelect(item.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {item.label}
            {item.count != null && <span className="tab-count">{item.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

// Inactive panels stay mounted (just `hidden`), so switching tabs never
// throws away a half-filled form or re-fetches a section's own data.
export function TabPanel({
  id,
  activeId,
  idPrefix,
  children,
}: {
  id: string
  activeId: string
  idPrefix: string
  children: ReactNode
}) {
  return (
    <div
      role="tabpanel"
      id={tabPanelId(idPrefix, id)}
      aria-labelledby={tabId(idPrefix, id)}
      hidden={id !== activeId}
      tabIndex={0}
      className="tab-panel"
    >
      {children}
    </div>
  )
}

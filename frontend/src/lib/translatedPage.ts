/**
 * Uebersetzt der Browser die Seite (Chrome, Edge, Erweiterungen), ersetzt er Textknoten durch eigene Elemente.
 * React haelt die alten Knoten fest und stuerzt beim naechsten Einfuegen oder Entfernen mit „insertBefore“ oder
 * „removeChild“ ab, die ganze Seite ist dann weg. Hier geben beide nach: ein schon fortgenommener Knoten wird
 * nicht noch einmal entfernt, und was vor einen fortgenommenen Knoten soll, kommt vor dessen Stellvertreter,
 * sonst ans Ende.
 */
export function bearTranslatedPages(): void {
  if (typeof Node !== 'function') return
  const proto = Node.prototype
  if ((proto as { nexbeatBears?: boolean }).nexbeatBears) return
  ;(proto as { nexbeatBears?: boolean }).nexbeatBears = true

  const removeChild = proto.removeChild
  proto.removeChild = function <T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) return child
    return removeChild.call(this, child) as T
  }

  const insertBefore = proto.insertBefore
  proto.insertBefore = function <T extends Node>(this: Node, node: T, before: Node | null): T {
    if (before !== null && before.parentNode !== this) {
      return insertBefore.call(this, node, childHolding(this, before)) as T
    }
    return insertBefore.call(this, node, before) as T
  }
}

/** Das Kind von `parent`, in dem `node` heute steckt; null, wenn es dort nicht mehr steckt. */
function childHolding(parent: Node, node: Node): Node | null {
  let current: Node | null = node
  while (current !== null && current.parentNode !== parent) current = current.parentNode
  return current
}
